import os, shutil, subprocess, time
from qgis.PyQt.QtWidgets import (QDialog, QFileDialog, QDockWidget, QMessageBox,
                                 QApplication, QTableWidgetItem, QHeaderView,
                                 QButtonGroup)
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsProject, QgsVectorLayer
from qgis.PyQt import uic  # For loading .ui dynamically
from .tsm_settings import Config
from .model_run import begin_run_console, closes_run_console
from . import msr_run
# from .helper_functions import HelperFun

from .trip_list2table_ui import Ui_Dialog_Triptable

# External-station calibration lives HERE, not in the LDT Visitor dialog, because
# agentPlans is what reads ldt_external_targets.csv (stage_eltod.cpp). Writing it
# from the LDT step meant a scenario that reused an existing LDT tour file never
# got the targets file, and the engine logged
#   [eltod] external target scaling skipped (not found: <scen>/ldt_external_targets.csv)
# while apply_external_targets was still true -- the calibration silently did not
# run. The file is now written by the step that consumes it, immediately before
# the run.

# Ext Zone ID is NOT user data: it must equal the external-station zone the engine
# keys on (agentPlans settings.h ext_station_i10/i75/i95). A blank id is mapped to
# zone 0 by load_ext_targets(), which collapses every row onto one key and disables
# external scaling, so the column is populated from the canonical ids and read-only.
EXT_ZONE_ID = {"I-10": "11504", "I-75": "11548", "I-95": "11560"}

# Calibrated external targets behind the 74.83M-trip revised trip list (externals
# matched exactly), not the older round placeholders (30,000 / 55,000 / 75,000).
EXT_DEFAULTS = {"I-75": ("48054", "1.0%"),
                "I-10": ("36000", "1.0%"),
                "I-95": ("75636", "1.0%")}

# Catalog copy of the curated all-station targets file, used to seed a scenario
# that has none. The production file covers ~60 crossings; without a seed only the
# three interstate rows would be written and the other ~57 stations would silently
# lose their calibration.
EXT_MASTER_REL = "Inputs/external_counts/ldt_external_targets.csv"


class ConvertTripListtoTable(QDialog, Ui_Dialog_Triptable):
    def __init__(self):
        super().__init__()
        # self.setupUi(self)

        # Verify the UI file path
        # plugin_dir = os.path.dirname(__file__).replace("\\", "/")
        settings = Config()
        plugin_dir = settings.get("plugin_dir")
        ui_file = os.path.join(plugin_dir, "ui/trip_list2table.ui")
        print(f"UI file found at: {ui_file}")

        # Check if the UI file exists
        if not os.path.exists(ui_file):
            print(f"UI file not found at: {ui_file}")
            return  # If the file doesn't exist, stop further execution
        
        # Load the UI dynamically if the file exists
        uic.loadUi(ui_file, self)
 
        # Connect the buttons to the functions
        self.pushButton_ModelDir.clicked.connect(lambda: self.select_directory(self.lineEdit_TSMLoc))
        self.browse_TripTable.clicked.connect(lambda: self.select_file(self.lineEdit_triptable, "save"))

        self.pushButton_RunTT.clicked.connect(lambda: self.run_trip_table(show_message=True))
        self.pushButton_ELToDTable.clicked.connect(self.run_eltod_table)
        self.button_SaveCancel.accepted.connect(self.update_settings)
        self.button_SaveCancel.rejected.connect(self.cancel_action)

        # Scenario directory and scenario year are NOT edited here: Project /
        # Scenario Settings owns both, and the run already reads them from
        # Config. Having a second copy on this dialog meant the value the run
        # used could differ from the value on screen.
        self.comboBox_Feedback.addItems(["1", "2", "3"])
        self.comboBox_Feedback.setCurrentIndex(0)
        # Output (temporal) resolution of the trip list, per agentPlans (15 or 30 min).
        self.comboBox_Resolution.addItems(["30", "15"])
        self.comboBox_Resolution.setCurrentText("30")

        # bool_ldtIcremental = self.checkBox_LDTIcrement.isChecked()
        # bool_FLOS = self.checkBox_FLOS.isChecked()

        # Update Settings ("Main Panel -> Load Settings -> Config()")
        settings = Config()
        if settings.get("tsm_location"):
            self.lineEdit_TSMLoc.setText(settings.get("tsm_location"))
        if settings.get("feedback"):
            self.comboBox_Feedback.setCurrentText(settings.get("feedback"))
        if settings.get("output_resolution"):
            self.comboBox_Resolution.setCurrentText(str(settings.get("output_resolution")))
        # if settings.get("ldtIncremental"):
        #     self.checkBox_LDTIcrement.setChecked(settings.get("ldtIncremental"))
        # if settings.get("FLOS"):
        #     self.checkBox_FLOS.setChecked(settings.get("FLOS"))
        if settings.get("triptable_file"):
            self.lineEdit_triptable.setText(settings.get("triptable_file"))

        # Right-side help panel + editable per-file input list.
        self._input_edits = {}   # key -> QLineEdit
        self._input_marks = {}   # key -> QLabel (present/missing marker)
        self.pushButton_ResetInputs.clicked.connect(self._reset_inputs)
        self._populate_help()
        self._build_input_rows()

        # MSR disaggregation (folded into agentPlans). msr.exe is a future
        # component; the run is guarded until it exists.
        self.browse_MSRSubarea.clicked.connect(lambda: self.select_file(self.lineEdit_MSRSubarea, "open"))
        self.browse_MSRLookup.clicked.connect(lambda: self.select_file(self.lineEdit_MSRLookup, "open"))
        if settings.get("msr_subarea"):
            self.lineEdit_MSRSubarea.setText(settings.get("msr_subarea"))
        if settings.get("msr_lookup"):
            self.lineEdit_MSRLookup.setText(settings.get("msr_lookup"))
        if settings.get("run_msr"):
            self.groupBox_MSR.setChecked(settings.get("run_msr") is True)

        # External-station calibration (moved here from the LDT Visitor dialog).
        self._build_ext_calibration()

        # A QTabWidget reserves the height of its TALLEST page, so the short
        # tabs (MSR, ELToD) sat in a frame sized for External stations with a
        # band of dead space underneath. Give every hidden page an Ignored
        # vertical policy so the frame follows the page actually on screen.
        self.tabWidget_Options.currentChanged.connect(self._fit_tab_height)
        self._fit_tab_height(self.tabWidget_Options.currentIndex())

        # ELToD hourly OD table. The template used to hardcode
        # write_hourly_table=true, so EVERY run wrote ELTOD_tt_HourClock.csv
        # whether or not anything downstream wanted it. It is opt-in now; the
        # "Build trip table (hourly)" button still forces it for one run.
        self.checkBox_ELToD.setChecked(
            str(settings.get("write_hourly_table")).lower() in ("true", "1", "yes"))
        self._force_hourly = False

    def _fit_tab_height(self, index):
        """Size the tab frame to the visible page, not to the tallest one.

        A QTabWidget reserves the height of its TALLEST page, so MSR (120px) and
        ELToD (147px) sat in a frame sized for External stations (293px) with a
        band of dead space underneath. The usual fix -- giving hidden pages an
        Ignored size policy -- does nothing here: QStackedLayout::sizeHint takes
        the max over every page without consulting their policies. Capping the
        frame's maximum height to the page on screen is what actually shrinks it.
        """
        tabs = self.tabWidget_Options
        page = tabs.widget(index)
        if page is None:
            return
        tabs.setMaximumHeight(page.sizeHint().height()
                              + tabs.tabBar().sizeHint().height() + 12)

    # ------------------------------------------------------------------
    # External-station target calibration
    # ------------------------------------------------------------------
    def _build_ext_calibration(self):
        """Populate and wire the external-station calibration group."""
        settings = Config()
        self.table = self.table_ExtStn_Counts

        for row in range(self.table.rowCount()):
            name = self.table.verticalHeaderItem(row).text()
            dc, df = EXT_DEFAULTS.get(name, ("", "1.0%"))
            count = settings.get(f"{name}_Count")
            future = settings.get(f"{name}_Future")
            zone_item = QTableWidgetItem(EXT_ZONE_ID.get(name, ""))
            zone_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            zone_item.setToolTip("Fixed external-station zone id; must match "
                                 "ext_station_* in the agentPlans control file.")
            self.table.setItem(row, 0, zone_item)
            self.table.setItem(row, 1, QTableWidgetItem(count if count else dc))
            self.table.setItem(row, 2, QTableWidgetItem(future if future else df))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        self._ext_mode_group = QButtonGroup(self)
        self._ext_mode_group.addButton(self.radio_extBase)
        self._ext_mode_group.addButton(self.radio_extGrow)

        self.browse_ExtMaster.clicked.connect(
            lambda: self.select_file(self.lineEdit_ExtMaster, "open"))
        self.lineEdit_ExtMaster.textChanged.connect(lambda _: self._sync_ext_enabled())
        self.checkBox_extCalib.toggled.connect(lambda _: self._sync_ext_enabled())
        self.radio_extBase.toggled.connect(lambda _: self._sync_ext_enabled())

        # Restore saved state. Absent setting => OFF (opt-in), so an existing
        # scenario does not silently start scaling externals on the next run.
        self.checkBox_extCalib.setChecked(
            str(settings.get("ldt_ext_calibrate")).lower() in ("true", "1", "yes"))
        if str(settings.get("ldt_ext_mode") or "base").lower() == "grow":
            self.radio_extGrow.setChecked(True)
        else:
            self.radio_extBase.setChecked(True)
        self.lineEdit_ExtMaster.setText(
            (settings.get("ldt_ext_master") or self._default_ext_master()).replace("\\", "/"))
        self._sync_ext_enabled()

    @staticmethod
    def _scen_dir():
        """Scenario directory for this run, from Project / Scenario Settings.

        The dialog used to carry its own Scenario Dir field; the run read
        Config either way, so an edit here that was not saved produced a control
        file pointing somewhere else. One source now.
        """
        return (Config().get("scenarioDir") or "").replace("\\", "/")

    @staticmethod
    def _default_ext_master():
        """Catalog master targets file, or "" when it is not installed."""
        loc = (Config().get("tsm_location") or "").replace("\\", "/")
        p = (loc.rstrip("/") + "/" + EXT_MASTER_REL) if loc else ""
        return p if p and os.path.exists(p) else ""

    def _ext_target_path(self, scen=None):
        """Where this run's targets file goes.

        The run passes the SAME scenarioDir that goes into the control file's
        ldt_external_targets key, so the file is always written where the engine
        is told to look for it. The UI preview (scen=None) falls back to the
        dialog's own field, which is what Save will store.
        """
        scen = (scen if scen is not None else self._scen_dir()).strip().replace("\\", "/")
        return (scen.rstrip("/") + "/ldt_external_targets.csv") if scen else ""

    def _sync_ext_enabled(self):
        on = self.checkBox_extCalib.isChecked()
        for w in (self.radio_extBase, self.radio_extGrow, self.table,
                  self.lineEdit_ExtMaster, self.browse_ExtMaster,
                  self.label_ExtMaster):
            w.setEnabled(on)
        # The growth column only means anything in growth mode.
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 2)
            if it is None:
                continue
            f = it.flags()
            if on and self.radio_extGrow.isChecked():
                it.setFlags(f | Qt.ItemFlag.ItemIsEditable)
            else:
                it.setFlags(f & ~Qt.ItemFlag.ItemIsEditable)
        # Say plainly which file the run will write, and whether it exists yet.
        out = self._ext_target_path()
        if not on:
            self.label_ExtTargetPath.setText(
                "Off - apply_external_targets=false; no targets file is written.")
            self.label_ExtTargetPath.setStyleSheet("color:#666;")
        elif not out:
            self.label_ExtTargetPath.setText("Set the scenario directory first.")
            self.label_ExtTargetPath.setStyleSheet("color:#c0392b;")
        else:
            state = "will be updated" if os.path.exists(out) else "will be created"
            msg = "Writes %s (%s) at run time." % (out, state)
            master = self.lineEdit_ExtMaster.text().strip()
            if master and os.path.exists(master):
                msg += "  Every other station comes from the master file."
                self.label_ExtTargetPath.setStyleSheet("color:#157f1f;")
            elif os.path.exists(out):
                msg += ("  No master file - the scenario's existing file supplies "
                        "the other stations.")
                self.label_ExtTargetPath.setStyleSheet("color:#b9770e;")
            else:
                # Nothing to supply the other ~57 crossings: they lose calibration.
                msg += ("  No master file - ONLY the three interstates below will "
                        "be calibrated.")
                self.label_ExtTargetPath.setStyleSheet("color:#b9770e;")
            self.label_ExtTargetPath.setText(msg)
        # That label wraps, so its height can change; re-fit the tab frame.
        if hasattr(self, "_fit_tab_height"):
            self._fit_tab_height(self.tabWidget_Options.currentIndex())

    def _persist_external_targets(self, scen=None):
        """Write <scenarioDir>/ldt_external_targets.csv for this run.

        MERGES rather than overwrites. The production targets file covers ~60
        crossings with filled zone ids and absolute counts; this table only knows
        the big three interstates, so a blind rewrite silently discarded ~57
        stations. When a targets file already exists in the scenario (or a master
        is configured to seed one) its header, row order and every other station
        are preserved, and only rows matching this table's ext_zone_id are updated.

        Returns True when the file is on disk and agentPlans can use it.
        """
        import csv
        out = self._ext_target_path(scen)

        if not self.checkBox_extCalib.isChecked():
            print("External targets: calibration is OFF - file left untouched "
                  "(apply_external_targets=false)")
            return True
        if not out:
            print("External targets: no scenario directory - nothing written")
            return False

        mine = {}
        for row in range(self.table.rowCount()):
            name = self.table.verticalHeaderItem(row).text()
            it0, it1, it2 = (self.table.item(row, c) for c in (0, 1, 2))
            zone = it0.text().strip() if it0 else ""
            count = it1.text().strip() if it1 else ""
            future = it2.text().strip() if it2 else ""
            if not zone:
                print("External targets: row %s has no zone id - skipped" % name)
                continue
            # Spec is written explicitly from the selected mode, never inferred.
            # Base-year mode emits the absolute count (agentPlans returns it
            # verbatim); growth mode emits "<rate>%" (linear, applied over
            # scenario year - external_base_year).
            if self.radio_extGrow.isChecked():
                spec = future if future.endswith("%") else (future + "%" if future else "0%")
            else:
                spec = count
            mine[zone] = (name, count, spec)
        if not mine:
            print("External targets: nothing written (no row carries a zone id)")
            return False

        # The master is the BASE FOR EVERY RUN, not a one-off seed: it carries all
        # ~60 crossings and the GUI rows below are the only overrides on top of it
        # ("use the master for all externals except the ones specified here"). A
        # stale scenario copy -- e.g. a three-row file left by an older run, or one
        # merged against a superseded master -- therefore cannot quietly survive
        # and starve the other stations.
        #
        # Falling back to the scenario's own file when no master is configured
        # keeps a hand-curated per-scenario file working.
        master = self.lineEdit_ExtMaster.text().strip().replace("\\", "/")
        use_master = bool(master) and os.path.exists(master) and \
            os.path.abspath(master) != os.path.abspath(out)
        base = master if use_master else out

        try:
            header = None
            existing = []
            if os.path.exists(base):
                with open(base, newline="") as f:
                    rd = csv.reader(f)
                    header = next(rd, None)
                    for r in rd:
                        if r:
                            existing.append(r)

            if header and "ext_zone_id" in header:
                iz = header.index("ext_zone_id")
                ic = None
                for i, h in enumerate(header):
                    if h.strip().lower().startswith("base_count"):
                        ic = i
                        break
                isp = header.index("future_target_or_growth") if "future_target_or_growth" in header else None
                touched = 0
                for r in existing:
                    if iz >= len(r):
                        continue
                    hit = mine.get(r[iz].strip())
                    if not hit:
                        continue
                    count = hit[1]
                    future = hit[2]
                    if ic is not None and ic < len(r) and count:
                        r[ic] = count
                    if isp is not None and isp < len(r) and future:
                        r[isp] = future
                    touched += 1
                have = set()
                for r in existing:
                    if iz < len(r):
                        have.add(r[iz].strip())
                for zone in mine:
                    if zone in have:
                        continue
                    name, count, future = mine[zone]
                    new = [""] * len(header)
                    new[0] = name
                    new[iz] = zone
                    if ic is not None:
                        new[ic] = count
                    if isp is not None:
                        new[isp] = future
                    existing.append(new)
                    touched += 1
                os.makedirs(os.path.dirname(out), exist_ok=True)
                with open(out, "w", newline="") as f:
                    w = csv.writer(f)
                    w.writerow(header)
                    w.writerows(existing)
                print("External targets: %d GUI row(s) merged over %s, "
                      "%d stations total -> %s"
                      % (touched, ("master " + master) if use_master
                         else "the scenario's own file", len(existing), out))
            else:
                with open(out, "w", newline="") as f:
                    w = csv.writer(f)
                    w.writerow(["interstate", "ext_zone_id", "base_count_2024",
                                "future_target_or_growth"])
                    for zone in mine:
                        name, count, future = mine[zone]
                        w.writerow([name, zone, count, future])
                print("External targets: wrote %d row(s) -> %s  (NO master seed: only "
                      "these stations are calibrated)" % (len(mine), out))
        except Exception as e:
            print("Could not write external targets: %s" % e)
            return False
        return os.path.exists(out)

    # ------------------------------------------------------------------
    # Editable input-file list (one browseable row per agentPlans input)
    # ------------------------------------------------------------------
    def _default_inputs(self):
        """Ordered (key, label, default_path) for the per-scenario agentPlans
        INPUTS only: SDT/LDT demand and the synthetic households.
        Distribution/lookup files are configs, not inputs -- see
        _config_distributions(). The key matches the agentPlans control key."""
        scen = self._scen_dir()
        loop = self.comboBox_Feedback.currentText() or "1"
        syn_hh = (Config().get("synHH_file") or "").replace("\\", "/")

        def sc(rel):
            return (scen + "/" + rel) if scen else ""

        return [
            # SDT trip outputs are fixed by the SDT TOML: sdt_resident_trips_<loop>.csv,
            # sdt_visitor_trips_<loop>.csv (in the scenario dir).
            ("sdt_res_trips", "SDT resident trips",       sc(f"sdt_resident_trips_{loop}.csv")),
            ("sdt_vis_trips", "SDT visitor trips",        sc(f"sdt_visitor_trips_{loop}.csv")),
            ("fl_ldt_tours",  "FL LDT tours",             sc("FL_LD_tour_out.csv")),
            ("os_ldt_tours",  "OS LDT tours",             sc("OS_LD_tour_out.csv")),
            ("sdt_syn_hh",    "SDT synthetic households", syn_hh),
        ]

    def _config_distributions(self):
        """Fixed distribution/lookup configs (not per-scenario inputs). Bundled
        with the plugin under config/agentPlan/; keyed by agentPlans control key."""
        cfg = os.path.join(Config().get("plugin_dir"), "config", "agentPlan").replace("\\", "/")
        # truck_odme is a large (~15 MB) trip table -> lives under Inputs (file-size
        # policy: large inputs in Inputs, only small distribution CSVs in the plugin).
        trk = os.path.join(Config().get("tsm_location"), "Inputs", "trk_ODME",
                           "TSMv5_Truck_ODME_TT.csv").replace("\\", "/")
        return {
            "truck_odme":           trk,
            "tod_distributions":    cfg + "/tod_distributions.csv",
            "external_auto_shares": cfg + "/external_auto_shares.csv",
            "airport_shares":       cfg + "/airport_shares.csv",
            "canaveral_cruise":     cfg + "/canaveral_cruise.csv",
            "ga_al_destinations":   cfg + "/ga_al_ldt_destinations.csv",
            "cbm_external_lookup":  cfg + "/cbm_external_lookup.csv",
            "taz_dma":              cfg + "/Florida_Zones_appended_STL_TSMv4.csv",
        }

    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _build_input_rows(self, use_defaults=False):
        """(Re)build the editable input rows. Unless use_defaults is True, each row
        is prefilled with a saved override (Config 'tt_input_<key>') if present,
        else the computed default."""
        from qgis.PyQt.QtWidgets import QLabel, QLineEdit, QPushButton
        grid = self.gridLayout_Inputs
        self._clear_layout(grid)
        self._input_edits.clear()
        self._input_marks.clear()
        settings = Config()

        for i, (key, label, default) in enumerate(self._default_inputs()):
            value = default
            if not use_defaults:
                saved = settings.get(f"tt_input_{key}")
                if saved:
                    value = saved

            mark = QLabel()
            mark.setFixedWidth(16)
            name = QLabel(label)
            name.setMinimumWidth(150)
            name.setToolTip(f"agentPlans control key: {key}")
            edit = QLineEdit(value)
            edit.setToolTip(key)
            browse = QPushButton("...")
            browse.setFixedWidth(28)

            browse.clicked.connect(lambda _, e=edit: self._browse_input(e))
            edit.textChanged.connect(lambda _, k=key: self._update_mark(k))

            grid.addWidget(mark, i, 0)
            grid.addWidget(name, i, 1)
            grid.addWidget(edit, i, 2)
            grid.addWidget(browse, i, 3)
            self._input_edits[key] = edit
            self._input_marks[key] = mark
            self._update_mark(key)

        grid.setColumnStretch(2, 1)

    def _update_mark(self, key):
        edit = self._input_edits.get(key)
        mark = self._input_marks.get(key)
        if edit is None or mark is None:
            return
        path = edit.text().strip()
        ok = bool(path) and os.path.exists(path)
        mark.setText("✓" if ok else "✗")
        mark.setStyleSheet("color:#157f1f;" if ok else "color:#c0392b;")
        mark.setToolTip("found" if ok else ("missing: " + path if path else "not set"))

    def _browse_input(self, edit):
        start = edit.text().strip()
        start_dir = os.path.dirname(start) if start else ""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select input file", start_dir,
            "Data files (*.csv *.csv.gz *.gz *.omx) ;; All Files (*)")
        if file_path:
            edit.setText(file_path.replace("\\", "/"))

    def _reset_inputs(self):
        """Recompute every input path from the current dirs (discard overrides)."""
        self._build_input_rows(use_defaults=True)

    def _resolved_inputs(self):
        """Current path for every input key (override or default)."""
        return {key: edit.text().strip() for key, edit in self._input_edits.items()}

    def _populate_help(self):
        """Static explanation of what agentPlans does to build the trip list."""
        html = """
<html><body style='font-family:Segoe UI,Arial; font-size:9pt; line-height:1.35;'>
<h2 style='margin:0 0 6px 0;'>agentPlans &#8211; trip list / trip table builder</h2>
<p>agentPlans merges every demand market into one <b>trip list</b> at the selected
resolution (<code>tripList_&lt;res&gt;min.csv.gz</code>) that the assignment engine
(HyDRA/AgentFlow, or ELToD) reads. Each output row is one vehicle trip with origin (O),
destination (D), <code>depart_time</code> (HH:MM:SS), market segment and
value-of-time class.</p>

<h4>1. Person tours &#8594; vehicle trips</h4>
<ul>
<li><b>SDT (short-distance):</b> resident &amp; visitor person trips become vehicle
trips by dividing the expansion factor by auto occupancy (carpool modes 3/4 &#8594; 2,
5/6 &#8594; 3.2 persons/veh).</li>
<li><b>LDT (long-distance):</b> each <i>tour</i> is made by the whole
party travelling together, so one tour = one vehicle trip (no occupancy split).
Both directions are generated (outbound <i>tour_dir</i> + <i>return_dir</i>).</li>
</ul>

<h4>2. Long-distance AIR mode &#8211; airport access/egress (first/last mile)</h4>
<p>An air tour is not assignable end-to-end; only the ground (auto) legs to/from the
airport load on the network. agentPlans converts each air tour into the airport
access/egress ODs:</p>
<ul>
<li><b>Airport TAZ pick:</b> an airport zone is sampled by DMA share (e.g. OIA = 4657).
For a <b>visitor (EI)</b> arriving in FL, the airport is the trip <i>origin</i>
(egress / last mile to the destination); for a <b>resident (IE)</b> leaving FL it is
the trip <i>destination</i> (access / first mile from home).</li>
<li><b>Internal&#8211;internal (II) air:</b> two separate OD legs are emitted &#8211; an
access leg (home &#8594; origin airport) and an egress leg (destination airport &#8594;
destination).</li>
<li><b>Access/egress mode choice:</b> each ground leg gets a mode by share
(Auto 81.5%, DME 18.3%, Other 2%). DME (Disney Magical Express) is only valid at OIA
and only for Disney resort zones; otherwise it reverts to Auto.</li>
<li>If both tour ends fall in the same DMA, the &quot;air&quot; tour is treated as an
auto trip instead.</li>
</ul>

<h4>3. External stations (auto crossings)</h4>
<ul>
<li>EI/IE auto tours crossing the state line are assigned an <b>external station</b>
(I-10, I-75 or I-95) by origin state; the trip O or D is rewritten to that external
zone. North-FL &#8594; GA/AL crossborder trips use a TAZ&#8594;external lookup.</li>
<li><b>Target calibration:</b> OD trips serving each external zone are scaled so the
zone's modeled volume matches a target count or annual growth rate from
<code>ldt_external_targets.csv</code> (scale = target / modeled).</li>
</ul>

<h4>4. Other markets</h4>
<ul>
<li><b>Cruise:</b> Port Canaveral hotel-room &#8594; port-parking auto trips are added.</li>
<li><b>Trucks:</b> the ODME matrix is split into light/medium/heavy by axle-based
time-of-day, grown to the forecast year, and given a VOT distribution.</li>
</ul>

<h4>5. Time-of-day &amp; VOT</h4>
<ul>
<li>Daily sources (LDT, trucks) are timed to 15-min using the ToD shares; SDT 30-min
periods are split to 15-min; the output <code>depart_time</code> is then written at the
selected resolution (15 or 30 min).</li>
<li>Each trip is tagged with a market &amp; VOT class (Low/Med/High) used as the routing
segment (<code>marketVot</code>).</li>
</ul>

<h4>6. Output</h4>
<ul>
<li><b><code>tripList_&lt;res&gt;min.csv.gz</code></b> &#8211; the agent trip list at the
selected resolution (feeds HyDRA): <code>hh_id, person_id, tour_id, trip_id,
valueOfTime, purpose, depart_time, O, D, marketVot, vehTrips, occupancy, hhIncome,
market</code>. <b>15-min roughly doubles the trip count and memory vs 30-min.</b></li>
<li><b><code>ELTOD_tt_HourClock.csv</code></b> &#8211; the wide <b>ELToD trip table</b>
(hourly OD by market) for the ELToD (quasi-DTA) assignment. Build it with the
<b>ELToD &#8594; Build trip table (hourly)</b> button.</li>
</ul>
</body></html>
"""
        self.textBrowser_Help.setHtml(html)

    def cancel_action(self):
        """Handles the Cancel button."""
        print("Action canceled. Closing dialog.")
        self.reject()  # Closes the dialog without executing any code

    def update_settings(self):
        settings = Config()
        settings.set("tsm_location", self.lineEdit_TSMLoc.text())
        # scenarioDir / scenarioYear belong to Project / Scenario Settings.
        settings.set("feedback", self.comboBox_Feedback.currentText())
        settings.set("output_resolution", self.comboBox_Resolution.currentText())
        # settings.set("ldtIncremental", self.checkBox_LDTIcrement.isChecked())
        # settings.set("FLOS", self.checkBox_FLOS.isChecked())
        settings.set("triptable_file", self.lineEdit_triptable.text())
        settings.set("msr_subarea", self.lineEdit_MSRSubarea.text())
        settings.set("msr_lookup", self.lineEdit_MSRLookup.text())
        settings.set("run_msr", self.groupBox_MSR.isChecked())
        # External-station calibration: the flag, the basis and the station table,
        # so a reopened scenario shows what it will actually run.
        settings.set("ldt_ext_calibrate", self.checkBox_extCalib.isChecked())
        settings.set("ldt_ext_mode", "grow" if self.radio_extGrow.isChecked() else "base")
        settings.set("ldt_ext_master", self.lineEdit_ExtMaster.text().strip())
        settings.set("write_hourly_table", self.checkBox_ELToD.isChecked())
        for row in range(self.table.rowCount()):
            name = self.table.verticalHeaderItem(row).text()
            for col, key in ((0, "Zone"), (1, "Count"), (2, "Future")):
                it = self.table.item(row, col)
                settings.set(f"{name}_{key}", it.text() if it else "")
        # Persist per-file input overrides (key 'tt_input_<control_key>').
        for key, path in self._resolved_inputs().items():
            settings.set(f"tt_input_{key}", path)
        settings.check_and_save_to_file("scenario_settings_file")
        QMessageBox.information(self, "Settings Updated", "Project Specific settings have been updated.")
           

    def select_directory(self, line_edit):
        directory = QFileDialog.getExistingDirectory(self, "Select Directory")
        if directory:
            line_edit.setText(directory)
            
    def select_file(self, line_edit, type):
        if type == "open":
            file_path, _ = QFileDialog.getOpenFileName(self, "Select File", "",  "csv (*.csv) ;; All Files (*)")
        elif type == "save":
            file_path, _ = QFileDialog.getSaveFileName(self, "Select File", "", "csv (*.csv) ;; All Files (*)")
        if file_path:
            line_edit.setText(file_path)

    def run_eltod_table(self):
        """Build the ELToD (quasi-DTA) trip TABLE (hourly) using this same
        agentPlans tool. agentPlans always writes the hourly ELToD OD table
        (ELTOD_tt_HourClock.csv) on a run; the trip-list resolution above does
        not apply to it."""
        self._force_hourly = True
        try:
            ok = self.run_trip_table(show_message=False)
        finally:
            self._force_hourly = False
        if ok:
            scen = (Config().get("scenarioDir") or "").replace("\\", "/")
            QMessageBox.information(
                self, "ELToD trip table",
                "ELToD (quasi-DTA) trip table built (hourly):\n"
                f"{scen}/ELTOD_tt_HourClock.csv")

    def _run_msr_if_enabled(self, scenarioDir, trip_list_path):
        """MSR multi-spatial-resolution disaggregation, folded into this step.
        Delegates to the shared msr_run helper (same engine as the standalone MSR
        editor) so there is one source of truth for the msr.exe control + run.
        Returns True if OK / skipped."""
        if not self.groupBox_MSR.isChecked():
            return True
        ok, msg = msr_run.run(
            scenarioDir,
            trip_list_path,
            self.lineEdit_MSRSubarea.text().strip(),
            self.lineEdit_MSRLookup.text().strip(),
            export_sizeterms=False,
        )
        if not ok:
            QMessageBox.critical(self, "Error", msg)
            return False
        return True

    @staticmethod
    def _generate_control(template_path, out_path, mapping):
        """Fill {placeholders} in a agentPlans control template and write it out."""
        with open(template_path, "r", encoding="utf-8") as f:
            text = f.read()
        for key, val in mapping.items():
            text = text.replace("{" + key + "}", str(val).replace("\\", "/"))
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"Wrote agentPlans control: {out_path}")
        return out_path

    @closes_run_console
    def run_trip_table(self, show_message=False):
        settings = Config()
        settings.set("output_resolution", self.comboBox_Resolution.currentText())
        modelDir = settings.get("tsm_location").replace("\\", "/")
        scenarioDir = settings.get("scenarioDir").replace("\\", "/")
        year = settings.get("scenarioYear")
        feedback_loop = settings.get("feedback")
        trip_table_out = settings.get("triptable_file")
        plugin_dir = settings.get("plugin_dir")
        # One live-tail window for the whole Trip Table run (no per-step black windows).
        begin_run_console(os.path.join(scenarioDir, "TripTable.log"), "Trip Table - run log")

        # agentPlans.exe (C++ port of 2_Create_LDT_TripTable + 3_get_ELTOD_TripTable)
        # is the only path; the legacy R scripts are retired. Ships in the plugin's
        # Apps/ (the {tsm_location}/Apps tree was retired).
        agentplans_exe = settings.app_exe("TripList_to_TripTable/agentPlans.exe")
        if not os.path.exists(agentplans_exe):
            QMessageBox.critical(self, "Error", f"agentPlans.exe not found: {agentplans_exe}")
            return False
        return self._run_agentplans(settings, agentplans_exe, modelDir, scenarioDir,
                                     year, feedback_loop, plugin_dir, show_message)

    def _run_agentplans(self, settings, agentplans_exe, modelDir, scenarioDir,
                         year, feedback_loop, plugin_dir, show_message):
        """Generate a control file and run the agentPlans C++ trip-list pipeline.

        agentPlans replaces 2_Create_LDT_TripTable + 3_get_ELTOD_TripTable and
        writes the HyDRA trip list scenario_dir/ELTOD_tt_List_hourly.csv.gz
        (depart_time as HH:MM:SS) plus the ELToD OD table. Resolution of the
        output trip list is taken from the 'output_resolution' project setting
        (15 or 30 minutes; default 30)."""
        output_resolution = settings.get("output_resolution") or "30"
        inputs = self._resolved_inputs()  # the 6 per-scenario input paths

        if not all([modelDir, scenarioDir, year, inputs.get("sdt_syn_hh")]):
            QMessageBox.critical(self, "Error", "Missing required input for Trip List generation.")
            return False

        template = os.path.join(plugin_dir, "templates", "agentplans_settings_template.txt")
        if not os.path.exists(template):
            QMessageBox.critical(self, "Error", f"agentPlans template not found: {template}")
            return False

        # External-station targets: written HERE, into the same scenarioDir that
        # goes into the control file below, so the engine can never be pointed at
        # a targets file nothing produced. Previously the LDT Visitor dialog wrote
        # it, so any scenario that did not re-run LDT Visitor got
        #   [eltod] external target scaling skipped (not found: .../ldt_external_targets.csv)
        # with apply_external_targets still true -- calibration silently off.
        ext_on = self.checkBox_extCalib.isChecked()
        if not self._persist_external_targets(scenarioDir):
            QMessageBox.critical(
                self, "External targets",
                "External station calibration is ON but the targets file\n"
                f"{self._ext_target_path(scenarioDir)}\ncould not be written.\n\n"
                "Fix the scenario directory, or turn the calibration off, and run again.")
            return False

        # Output is the trip list at the selected resolution (no ELToD branding).
        trip_out = os.path.join(scenarioDir, f"tripList_{output_resolution}min.csv.gz").replace("\\", "/")

        mapping = {
            "catalog_dir": modelDir,
            "scenario_dir": scenarioDir,
            "year": year,
            "feedback_loop": feedback_loop,
            "output_resolution": output_resolution,
            "trip_table_out": trip_out,
            # Hourly ELToD OD table: opt-in on the ELToD tab, or forced for a
            # single run by the "Build trip table (hourly)" button.
            "write_hourly_table":
                "true" if (self.checkBox_ELToD.isChecked()
                           or getattr(self, "_force_hourly", False)) else "false",
            # External-station target calibration. ext_station_* must match the
            # ext_zone_id values in ldt_external_targets.csv, which the block above
            # just wrote. Read from the checkbox on THIS dialog rather than a
            # stored setting, so the flag and the file are always decided together
            # -- opt-in, so it never runs silently.
            "apply_external_targets": "true" if ext_on else "false",
            "ldt_external_targets": os.path.join(scenarioDir, "ldt_external_targets.csv").replace("\\", "/"),
            "external_base_year": settings.get("external_base_year") or "2024",
            "ext_station_i10": settings.get("ext_station_i10") or "11504",
            "ext_station_i75": settings.get("ext_station_i75") or "11548",
            "ext_station_i95": settings.get("ext_station_i95") or "11560",
        }
        mapping.update(self._config_distributions())  # fixed configs (plugin/config/agentPlan)
        mapping.update(inputs)  # per-scenario inputs

        # Generated per-run control -> scenario folder (with the run's outputs/logs),
        # not {tsm_location}/config.
        control_path = os.path.join(scenarioDir, "agentplans_settings.txt")
        try:
            self._generate_control(template, control_path, mapping)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error writing agentPlans control file: {e}")
            return False

        try:
            result = Config().run_app([agentplans_exe, control_path],
                                      log_path=os.path.join(scenarioDir, "agentPlans.log"), console=True)
        except Exception as e:
            print(f"Error running agentPlans: {e}")
            QMessageBox.critical(self, "Error", f"Error running agentPlans: {e}")
            return False

        if result.returncode == 0:
            print(f"agentPlans trip list created: {trip_out}")
            # MSR disaggregation runs on the trip list just produced (if enabled).
            if not self._run_msr_if_enabled(scenarioDir, trip_out):
                return False
            if show_message:
                msg = (f"Trip list generated successfully (agentPlans).\n\n"
                       f"Trip list ({output_resolution}-min): {trip_out}")
                if self.groupBox_MSR.isChecked():
                    msg += (f"\n\nMSR disaggregation:\n"
                            f"{scenarioDir}/subarea_msr_triplist.csv.gz\n"
                            f"{scenarioDir}/ELToD_MSR_Hourly_tt.csv")
                QMessageBox.information(self, "Success", msg)
            return True
        print("agentPlans run failed")
        QMessageBox.critical(self, "Error", "agentPlans run failed. Check console for details.")
        return False