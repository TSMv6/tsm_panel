import os, shutil, subprocess, time
from PyQt5.QtWidgets import QDialog, QFileDialog, QDockWidget, QMessageBox, QApplication
from qgis.core import QgsProject, QgsVectorLayer
from PyQt5 import uic  # For loading .ui dynamically
from .tsm_settings import Config
# from .helper_functions import HelperFun 

from .trip_list2table_ui import Ui_Dialog_Triptable

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
        self.pushButton_ScenDir.clicked.connect(lambda: self.select_directory(self.lineEdit_SCENLoc))
        self.browse_TripTable.clicked.connect(lambda: self.select_file(self.lineEdit_triptable, "save"))

        self.pushButton_RunTT.clicked.connect(lambda: self.run_trip_table(show_message=True))
        self.pushButton_ELToDTable.clicked.connect(self.run_eltod_table)
        self.button_SaveCancel.accepted.connect(self.update_settings)
        self.button_SaveCancel.rejected.connect(self.cancel_action)

        self.comboBox_Year.addItems(["2023", "2024", "2025", "2030", "2035", "2040", "2045", "2050", "2055", "2060"])
        self.comboBox_Year.setCurrentIndex(0)
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
        if settings.get("scenarioDir"):
            self.lineEdit_SCENLoc.setText(settings.get("scenarioDir"))
        if settings.get("scenarioYear"):
            self.comboBox_Year.setCurrentText(settings.get("scenarioYear"))
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

    # ------------------------------------------------------------------
    # Editable input-file list (one browseable row per agentPlans input)
    # ------------------------------------------------------------------
    def _default_inputs(self):
        """Ordered (key, label, default_path) for the per-scenario agentPlans
        INPUTS only: SDT/LDT demand, the distance skim and the synthetic
        households. Distribution/lookup files are configs, not inputs -- see
        _config_distributions(). The key matches the agentPlans control key."""
        scen = self.lineEdit_SCENLoc.text().replace("\\", "/")
        loop = self.comboBox_Feedback.currentText() or "1"
        syn_hh = (Config().get("synHH_file") or "").replace("\\", "/")

        def sc(rel):
            return (scen + "/" + rel) if scen else ""

        return [
            ("sdt_res_trips", "SDT resident trips",       sc(f"trips_{loop}.csv")),
            ("sdt_vis_trips", "SDT visitor trips",        sc("visitorTrips.csv")),
            ("fl_ldt_tours",  "FL LDT tours",             sc("FL_LD_tour_out.csv")),
            ("os_ldt_tours",  "OS LDT tours",             sc("OS_LD_tour_out.csv")),
            ("distance_skim", "Distance skim",            sc("Skim_distbased.csv")),
            ("sdt_syn_hh",    "SDT synthetic households", syn_hh),
        ]

    def _config_distributions(self):
        """Fixed distribution/lookup configs (not per-scenario inputs). Bundled
        with the plugin under config/agentPlan/; keyed by agentPlans control key."""
        cfg = os.path.join(Config().get("plugin_dir"), "config", "agentPlan").replace("\\", "/")
        return {
            "truck_odme":           cfg + "/TSMv5_Truck_ODME_TT.csv",
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
        from PyQt5.QtWidgets import QLabel, QLineEdit, QPushButton
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
<li><b>Distance guard:</b> air access/egress legs longer than 25 miles are flagged
(<code>LDT_Air_AccEgr25M</code>) since travellers rarely lodge far from the airport.</li>
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
        settings.set("scenarioDir", self.lineEdit_SCENLoc.text())
        settings.set("scenarioYear", self.comboBox_Year.currentText())
        settings.set("feedback", self.comboBox_Feedback.currentText())
        settings.set("output_resolution", self.comboBox_Resolution.currentText())
        # settings.set("ldtIncremental", self.checkBox_LDTIcrement.isChecked())
        # settings.set("FLOS", self.checkBox_FLOS.isChecked())
        settings.set("triptable_file", self.lineEdit_triptable.text())
        settings.set("msr_subarea", self.lineEdit_MSRSubarea.text())
        settings.set("msr_lookup", self.lineEdit_MSRLookup.text())
        settings.set("run_msr", self.groupBox_MSR.isChecked())
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
        ok = self.run_trip_table(show_message=False)
        if ok:
            scen = (Config().get("scenarioDir") or "").replace("\\", "/")
            QMessageBox.information(
                self, "ELToD trip table",
                "ELToD (quasi-DTA) trip table built (hourly):\n"
                f"{scen}/ELTOD_tt_HourClock.csv")

    def _run_msr_if_enabled(self, modelDir, scenarioDir):
        """MSR multi-spatial-resolution disaggregation, folded into this step.
        Takes the TSM-resolution trip list and disaggregates it to the MSR subarea
        zones. msr.exe is a future component -- guarded until it exists."""
        if not self.groupBox_MSR.isChecked():
            return
        msr_exe = os.path.join(modelDir, "Apps", "msr", "msr.exe")
        if not os.path.exists(msr_exe):
            QMessageBox.information(
                self, "MSR",
                "MSR disaggregation was requested, but msr.exe is not built yet.\n\n"
                "The trip list was produced at TSM resolution; MSR disaggregation "
                "will run automatically here once msr.exe is available.")
            return
        subarea = self.lineEdit_MSRSubarea.text().strip()
        lookup = self.lineEdit_MSRLookup.text().strip()
        try:
            r = subprocess.run([msr_exe, scenarioDir, subarea, lookup], env=Config().app_env(msr_exe))
            if r.returncode != 0:
                QMessageBox.critical(self, "Error", "MSR disaggregation failed. Check console for details.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error running MSR: {e}")

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

    def run_trip_table(self, show_message=False):
        settings = Config()
        settings.set("output_resolution", self.comboBox_Resolution.currentText())
        modelDir = settings.get("tsm_location").replace("\\", "/")
        scenarioDir = settings.get("scenarioDir").replace("\\", "/")
        year = settings.get("scenarioYear")
        feedback_loop = settings.get("feedback")
        trip_table_out = settings.get("triptable_file")
        plugin_dir = settings.get("plugin_dir")

        # agentPlans.exe (C++ port of 2_Create_LDT_TripTable + 3_get_ELTOD_TripTable)
        # is the only path; the legacy R scripts are retired.
        agentplans_exe = os.path.join(modelDir, "Apps", "TripList_to_TripTable", "agentPlans.exe")
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

        # Output is the trip list at the selected resolution (no ELToD branding).
        trip_out = os.path.join(scenarioDir, f"tripList_{output_resolution}min.csv.gz").replace("\\", "/")

        mapping = {
            "catalog_dir": modelDir,
            "scenario_dir": scenarioDir,
            "year": year,
            "feedback_loop": feedback_loop,
            "output_resolution": output_resolution,
            "trip_table_out": trip_out,
            # External-station target calibration. ext_station_* must match the
            # ext_zone_id values in ldt_external_targets.csv (written by the GUI).
            "ldt_external_targets": os.path.join(scenarioDir, "ldt_external_targets.csv").replace("\\", "/"),
            "external_base_year": settings.get("external_base_year") or "2024",
            "ext_station_i10": settings.get("ext_station_i10") or "11504",
            "ext_station_i75": settings.get("ext_station_i75") or "11548",
            "ext_station_i95": settings.get("ext_station_i95") or "11560",
        }
        mapping.update(self._config_distributions())  # fixed configs (plugin/config/agentPlan)
        mapping.update(inputs)  # per-scenario inputs

        control_path = os.path.join(modelDir, "config", "agentplans", "agentplans_settings.txt")
        try:
            self._generate_control(template, control_path, mapping)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error writing agentPlans control file: {e}")
            return False

        CREATE_NEW_CONSOLE = subprocess.CREATE_NEW_CONSOLE
        try:
            result = subprocess.run([agentplans_exe, control_path], creationflags=CREATE_NEW_CONSOLE)
        except Exception as e:
            print(f"Error running agentPlans: {e}")
            QMessageBox.critical(self, "Error", f"Error running agentPlans: {e}")
            return False

        if result.returncode == 0:
            print(f"agentPlans trip list created: {trip_out}")
            self._run_msr_if_enabled(modelDir, scenarioDir)
            if show_message:
                QMessageBox.information(
                    self, "Success",
                    f"Trip list generated successfully (agentPlans).\n\n"
                    f"Trip list ({output_resolution}-min): {trip_out}")
            return True
        print("agentPlans run failed")
        QMessageBox.critical(self, "Error", "agentPlans run failed. Check console for details.")
        return False