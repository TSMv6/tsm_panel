import os, shutil, subprocess, time
from qgis.PyQt.QtWidgets import (QDialog, QFileDialog, QDockWidget, QMessageBox,
                                 QApplication, QCheckBox, QGridLayout, QGroupBox,
                                 QVBoxLayout, QHBoxLayout, QLabel, QWidget)
from qgis.core import QgsProject, QgsVectorLayer
from qgis.PyQt import uic  # For loading .ui dynamically
from .tsm_settings import Config
from .model_run import run_gated_model, begin_run_console, closes_run_console
# from .helper_functions import HelperFun 
from qgis.PyQt.QtCore import Qt, QSettings
from qgis.PyQt.QtGui import QColor

from .LDT_outOfState_ui import Ui_Dialog_LDTos

class LDTVisitorModel(QDialog, Ui_Dialog_LDTos):
    def __init__(self):
        super().__init__()
        # self.setupUi(self)

        # Verify the UI file path
        # plugin_dir = os.path.dirname(__file__).replace("\\", "/")
        settings = Config()
        plugin_dir = settings.get("plugin_dir")
        ui_file = os.path.join(plugin_dir, "ui/LDT_OS.ui")
        print(f"UI file found at: {ui_file}")

        # Check if the UI file exists
        if not os.path.exists(ui_file):
            print(f"UI file not found at: {ui_file}")
            return  # If the file doesn't exist, stop further execution
        
        # Load the UI dynamically if the file exists
        uic.loadUi(ui_file, self)

        self.textBrowser.setOpenExternalLinks(True)
        self._load_help_doc(os.path.join(plugin_dir, "docs", "LDT_OS.md"))

        # Update Settings ("Main Panel -> Load Settings -> Config()")
        settings = Config()

        # Connect buttons to browse function
        self.browse_InputDir.clicked.connect(lambda: self.select_directory(self.lineEdit_InputDir))
        omx_filter = "OMX skim (*.omx);; All Files (*)"
        self.browse_RoadSkim.clicked.connect(lambda: self.select_file(self.lineEdit_RoadSkim, "open", omx_filter))
        self.browse_RailSkim.clicked.connect(lambda: self.select_file(self.lineEdit_RailSkim, "open", omx_filter))
        self.browse_AirSkim.clicked.connect(lambda: self.select_file(self.lineEdit_AirSkim, "open", omx_filter))
        # self.browse_LDTLanduse.clicked.connect(lambda: self.select_file(self.lineEdit_LanduseDAT, "open"))
        self.populate_layer_combobox(self.comboBox_LU,"Polygon")
        self.browse_LDTSynHH.clicked.connect(lambda: self.select_file(self.lineEdit_LDTSynHH, "open"))
        self.browse_OutputDir.clicked.connect(lambda: self.select_directory(self.lineEdit_OutDir))
        # self.pushButton_nHH.clicked.connect(self.check_nHH)
        self.checkBox_userRef.stateChanged.connect(self.check_userRef)
        self.check_userRef()
        
        # Connect the "save" button to the corresponding function
        self.button_SaveCancel.accepted.connect(self.update_settings)
        self.button_SaveCancel.rejected.connect(self.cancel_action)
        self.run_LDTOS.clicked.connect(lambda: self.run_LDT_visitor(show_message=True))
        self.lineEdit_NumHH.setText("enter number of households")
        # self.lineEdit_LDTRefYear.setText("2023")
        
        # The external-station calibration block (table, on/off, base-vs-growth)
        # used to live here. It moved to the agentPlans / Trip List dialog, which is
        # the step that actually reads ldt_external_targets.csv: writing it from
        # here meant a scenario that did not re-run LDT Visitor never got the file
        # and agentPlans logged "external target scaling skipped (not found: ...)"
        # while apply_external_targets was still true.

        # LDT-visitor incremental/absolute toggle. OFF = incremental: run only the
        # households added between the reference year and the scenario year
        # (ref < Year <= scen), then append back to the previous year's output. ON =
        # absolute: all Year <= scen, no reference, no append. read in
        # run_LDT_visitor() to pick ldtprep's ref arg (ref==scen=absolute).
        # Checked = INCREMENTAL. It used to read "Absolute run", i.e. the box
        # meant the opposite of the thing that is normally wanted, and the
        # future-year default (incremental) showed as an unticked "Absolute"
        # box. Labelled for what it does now; every read below is inverted to
        # match.
        self.checkBox_incremental = QCheckBox(
            "Run incremental (only HH added since the reference year, then append)")
        # (The old "Pre-sort syn-HH by hhnuma" checkbox lived here. It was dead:
        # its whole run-time block is commented out because ldt_synhh_prep.py
        # sorts and filters in a single pandas pass, so no separate one-time sort
        # is needed. Removed rather than left on screen doing nothing.)
        # Columns 1 and 4 of the main form grid are empty spacers that pushed the
        # fields far to the right, leaving a wide dead band beside the labels.
        # Set in code rather than the .ui: uic maps a "columnstretch" property to
        # setColumnstretch(), which does not exist, and refuses to load the file.
        _g2 = self.findChild(QGridLayout, "gridLayout_2")
        if _g2 is not None:
            for _c, _st in ((0, 0), (1, 0), (2, 1), (3, 0), (4, 0), (5, 0)):
                _g2.setColumnStretch(_c, _st)
                _g2.setColumnMinimumWidth(_c, 0)

        # ---- Group the bottom half: "Run mode and reference run" ---------------
        # absolute/incremental plus the reference year + reference tour file an
        # incremental run needs. gridLayout starts out as an item of
        # horizontalLayout, so it must be DETACHED first -- re-adding it without
        # removing left the original in place and produced a second column.
        # (The external-station calibration group that used to sit beside it now
        # lives in the agentPlans / Trip List dialog.)
        hbox = self.findChild(QHBoxLayout, "horizontalLayout")
        ref_grid = self.findChild(QGridLayout, "gridLayout")
        label_11 = self.findChild(QLabel, "label_11")
        if hbox is not None and ref_grid is not None:
            hbox.removeItem(ref_grid)

            self.grp_runmode = QGroupBox("Run mode and reference run")
            _lv = QVBoxLayout(self.grp_runmode)
            _lv.addWidget(self.checkBox_incremental)
            _lv.addLayout(ref_grid)
            _lv.addStretch(1)

            hbox.addWidget(self.grp_runmode, 1)
            if label_11 is not None:
                label_11.setVisible(False)

        # "Num of HHs (US - FL)" is derived internally by check_nHH(); it is not a
        # user input, so it is not shown.
        for _n in ("label_9", "lineEdit_NumHH", "pushButton_nHH"):
            _w = self.findChild(QWidget, _n)
            if _w is not None:
                _w.setVisible(False)

        # Absolute run drives whether a reference run is meaningful at all:
        # absolute => no reference, so grey the whole reference block; incremental
        # => hand control back to check_userRef().
        def _sync_runmode():
            inc = self.checkBox_incremental.isChecked()
            self.checkBox_userRef.setEnabled(inc)
            if inc:
                # An incremental run is meaningless without a reference run to
                # increment from, so turning it on implies the reference block.
                if not self.checkBox_userRef.isChecked():
                    self.checkBox_userRef.setChecked(True)
                self.check_userRef()
            else:
                self.lineEdit_LDTRefYear.setEnabled(False)
                self.pushButton.setEnabled(False)
                self.lineEdit_prevOut.setEnabled(False)
        self._sync_runmode = _sync_runmode
        self.checkBox_incremental.toggled.connect(lambda _: _sync_runmode())

        # Base year (2024) has NO prior-year output to increment from, so it MUST run
        # absolute -- force it on and grey it out. Future years (> base) may be either
        # incremental (default) or absolute, so the box is enabled for the user.
        BASE_YEAR = 2024
        try:
            _yr = int(settings.get("scenarioYear") or settings.get("networkYear") or BASE_YEAR)
        except (TypeError, ValueError):
            _yr = BASE_YEAR
        if _yr <= BASE_YEAR:
            self.checkBox_incremental.setChecked(False)
            self.checkBox_incremental.setToolTip(
                f"Base year ({BASE_YEAR}) has no prior-year LDT output to increment from, "
                "so it always runs absolute (all US HH ≤ scenario year). Locked for the base year.")
        else:
            # Future years default to INCREMENTAL. The old code restored
            # LDT_visitor_absolute, but that flag gets written as True by every
            # base-year run (where the box is force-checked and disabled), so a
            # future-year scenario inheriting a base-year json came up Absolute.
            # A separate key is used that only an enabled -- i.e. genuinely
            # user-chosen -- checkbox ever writes.
            self.checkBox_incremental.setChecked(
                str(settings.get("LDT_visitor_absolute_future")).lower()
                not in ("true", "1", "yes"))
            self.checkBox_incremental.setToolTip(
                "Off (default): incremental - run only households added between the reference "
                "year and the scenario year, then append back to the previous output.\n"
                "On: run every US household with Year ≤ scenario year; no reference, no append.")
        
        if settings.get("LDT_resident_InputDir"):
            self.lineEdit_InputDir.setText(settings.get("LDT_resident_InputDir"))
        if settings.get("LDT_resident_RoadSkim"):
            self.lineEdit_RoadSkim.setText(settings.get("LDT_resident_RoadSkim"))
        if settings.get("LDT_resident_RailSkim"):
            self.lineEdit_RailSkim.setText(settings.get("LDT_resident_RailSkim"))
        if settings.get("LDT_resident_AirSkim"):
            self.lineEdit_AirSkim.setText(settings.get("LDT_resident_AirSkim"))
        # if settings.get("LDT_visitor_Landuse"):
        #     self.lineEdit_LanduseDAT.setText(settings.get("LDT_visitor_Landuse"))
        if settings.get("landuse_layer"):
            landuse_layer_name = settings.get("landuse_layer")
            if landuse_layer_name in [self.comboBox_LU.itemText(i) for i in range(self.comboBox_LU.count())]:
                print("Landuse layer already in combo box")
                self.comboBox_LU.setCurrentText(landuse_layer_name)
        if settings.get("LDT_visitor_SynHH"):
            self.lineEdit_LDTSynHH.setText(settings.get("LDT_visitor_SynHH"))
        if settings.get("scenarioDir"):
            self.lineEdit_OutDir.setText(settings.get("scenarioDir"))
        if settings.get("LDT_visitor_nHH") :
            self.lineEdit_NumHH.setText("enter number of households")
        else:
            self.lineEdit_NumHH.setText(str(settings.get("LDT_visitor_nHH")))
        # if settings.get("LDTExtCountYear"):
        #     self.lineEdit_LDTRefYear.setText(settings.get("LDTExtCountYear"))
        if settings.get("LDT_visitor_nHH"):
            self.lineEdit_NumHH.setText(str(settings.get("LDT_visitor_nHH")))
        if settings.get("LDT_visitor_userRef"):
            self.checkBox_userRef.setChecked(settings.get("LDT_visitor_userRef"))
            self.pushButton.setEnabled(settings.get("LDT_visitor_userRef"))
            self.lineEdit_LDTRefYear.setText(settings.get("LDTExtCountYear"))
            # self.pushButton.clicked.connect(lambda: self.select_file(self.lineEdit_prevOut, "open"))
            self.lineEdit_prevOut.setEnabled(settings.get("LDT_visitor_userRef"))
            settings.set("LDT_visitor_userRef_filepath",  self.lineEdit_prevOut.text())

        # Base year (and prior) always runs absolute, so the reference-file
        # calibration block (User Reference File / Reference Year / Reference Tour
        # File) does not apply -- disable the whole grid. The external-counts table
        # beside it is a sibling layout and stays usable. Done last so it overrides
        # the userRef restore above.
        if _yr <= BASE_YEAR:
            self.checkBox_userRef.setChecked(False)
            ref_grid = self.findChild(QGridLayout, "gridLayout")
            if ref_grid is not None:
                for i in range(ref_grid.count()):
                    w = ref_grid.itemAt(i).widget()
                    if w is not None:
                        w.setEnabled(False)
        else:
            # Future year: the reference run is the normal way to work, so turn
            # the block on and pre-fill it. Reference Year is a free input, not
            # locked to the base year -- that is what lets runs chain
            # (2024 absolute -> 2030 ref 2024 -> 2035 ref 2030). It drives BOTH
            # the syn-HH delta (ref < Year <= scen) and which output the
            # increment is appended to.
            if self.checkBox_incremental.isChecked():
                self.checkBox_userRef.setChecked(True)
            # check_userRef() repopulates the reference-file field from settings,
            # so it has to run BEFORE the prefill or it overwrites it.
            self.check_userRef()
            # The .ui ships "2023" as placeholder text in the year field, so an
            # "is it empty" test never fires. Prefer a saved value; otherwise use
            # the base year, and treat the stale placeholder as unset.
            _saved_ref = (settings.get("LDTExtCountYear") or "").strip()
            _cur = (self.lineEdit_LDTRefYear.text() or "").strip()
            if _saved_ref:
                self.lineEdit_LDTRefYear.setText(_saved_ref)
            elif not _cur or _cur == "2023":
                self.lineEdit_LDTRefYear.setText(str(BASE_YEAR))
            self.lineEdit_LDTRefYear.setToolTip(
                "Year of the run being incremented FROM. Drives the syn-HH delta "
                "(ref < Year <= scenario year) and pairs with the Reference Tour "
                "File that the increment is appended onto.")

        # The run-mode group must show its real state on open, not only after
        # the first click.
        self._sync_runmode()

        # Suggest the reference tour file LAST. check_userRef() clears the stored
        # path on its second call, so a prefill written earlier does not survive
        # the sync above. Future-year scenarios sit as a subfolder of the run they
        # increment from, so the parent's tour output is the natural reference.
        if _yr > BASE_YEAR and self.checkBox_incremental.isChecked():
            _cur = (self.lineEdit_prevOut.text() or "").strip().lower()
            if _cur in ("", "none", "null"):
                _pref = os.path.join(
                    os.path.dirname(os.path.normpath(settings.get("scenarioDir") or "")),
                    "OS_LD_tour_out.csv")
                if os.path.exists(_pref):
                    _pref = _pref.replace(chr(92), "/")
                    self.lineEdit_prevOut.setText(_pref)
                    settings.set("LDT_visitor_userRef_filepath", _pref)

    def check_userRef(self):
        settings = Config()
        """Enable or disable the previous output directory based on the checkbox state."""
        if self.checkBox_userRef.isChecked():
            self.lineEdit_LDTRefYear.setEnabled(True)
            self.pushButton.setEnabled(True)
            self.lineEdit_prevOut.setEnabled(True)
            try:
                self.pushButton.clicked.disconnect()
                self.lineEdit_prevOut.setText("none")
                settings.set("LDT_visitor_userRef_filepath", None)
            except TypeError:
                pass
            self.pushButton.clicked.connect(lambda: self.select_file(self.lineEdit_prevOut, "open"))
            self.lineEdit_prevOut.setText(settings.get("LDT_visitor_userRef_filepath"))
        else:
            self.lineEdit_LDTRefYear.setEnabled(False)
            self.pushButton.setEnabled(False)
            self.lineEdit_prevOut.setEnabled(False)

    def populate_layer_combobox(self, combobox, geom_type):
        """Populate the dropdown with layers of the specified geometry type."""
        combobox.clear()
        combobox.addItem("Select a layer", None)  # Default option

        # Get all layers in QGIS
        layers = QgsProject.instance().mapLayers().values()
        vector_layers = [layer for layer in layers if hasattr(layer, "geometryType")]
        for layer in vector_layers:
            # if isinstance(layer, QgsVectorLayer) and 
            if layer.geometryType() == {"Point": 0, "LineString": 1, "Polygon": 2}[geom_type]:
                combobox.addItem(layer.name(), layer)           

    def _load_help_doc(self, md_path):
        try:
            with open(md_path, "r", encoding="utf-8") as f:
                md = f.read()
        except Exception as e:
            print(f"Could not read help doc {md_path}: {e}")
            return
        if hasattr(self.textBrowser, "setMarkdown"):
            self.textBrowser.setMarkdown(md)
        else:
            self.textBrowser.setPlainText(md)

    def update_settings(self):
        settings = Config()
        settings.set("LDT_resident_InputDir", self.lineEdit_InputDir.text())
        settings.set("LDT_resident_RoadSkim", self.lineEdit_RoadSkim.text())
        settings.set("LDT_resident_RailSkim", self.lineEdit_RailSkim.text())
        settings.set("LDT_resident_AirSkim", self.lineEdit_AirSkim.text())
        # settings.set("LDT_visitor_Landuse", self.lineEdit_LanduseDAT.text())
        landuse_layer = self.comboBox_LU.currentData()
        settings.set("landuse_layer", landuse_layer.name())  
        settings.set("LDT_visitor_SynHH", self.lineEdit_LDTSynHH.text())
        settings.set("scenarioDir", self.lineEdit_OutDir.text())

        # ldt_ext_calibrate / ldt_ext_mode and the station table are written by
        # the agentPlans / Trip List dialog, which owns the calibration now.

        # settings.set("LDTFutureYear", self.lineEdit_futYear.text())
        if settings.get("LDT_visitor_nHH") != self.lineEdit_NumHH.text():
            settings.set("LDT_visitor_nHH", self.lineEdit_NumHH.text())
        # if settings.get("scenarioYear") != self.lineEdit_futYear.text():
        #     settings.set("scenarioYear", self.lineEdit_futYear.text())
        # self.close()
        if self.checkBox_userRef.isChecked():
            settings.set("LDTExtCountYear", self.lineEdit_LDTRefYear.text())
            settings.set("LDT_visitor_userRef", True)
            settings.set("LDT_visitor_userRef_filepath", self.lineEdit_prevOut.text())
        else:
            settings.set("LDTExtCountYear", None)
            settings.set("LDT_visitor_userRef", False)
            settings.set("LDT_visitor_userRef_filepath", None)
        settings.set("LDT_visitor_absolute", not self.checkBox_incremental.isChecked())
        # Only record a *chosen* absolute/incremental preference. For the base
        # year the box is forced on and disabled, so writing it would poison the
        # next future-year scenario that inherits this json.
        settings.set("LDT_visitor_absolute_future",
                     not self.checkBox_incremental.isChecked())
        settings.check_and_save_to_file("scenario_settings_file")
        QMessageBox.information(self, "Settings Updated", "Project Specific settings have been updated.")
            
    def cancel_action(self):
        print("Action canceled. Closing dialog.")
        self.reject()  # Closes the dialog without executing any code

    def select_file(self, line_edit, type, file_filter="All Files (*)"):
        if type == "open":
            file_path, _ = QFileDialog.getOpenFileName(self, "Select File", "", file_filter)
        elif type == "save":
            file_path, _ = QFileDialog.getSaveFileName(self, "Select File", "", file_filter)
        if file_path:
            line_edit.setText(file_path)

    def select_directory(self, line_edit):
        directory = QFileDialog.getExistingDirectory(self, "Select Directory", )
        if directory:
            line_edit.setText(directory)

    # Create a copy of the template file
    def template_keys_update(self, template, replacements, properties_file):
        with open(template, "r") as file:
            content = file.read()

        # Replace keys with scenario-specific values
        for key, value in replacements.items():
            content = content.replace(f"{{{key}}}", value)

        # Write the modified content to the output file
        with open(properties_file, "w") as file:
            file.write(content)
        print(f"Scenario-specific file created: {properties_file}")  

    def check_nHH(self, file_path):
        settings = Config()
        if not os.path.exists(file_path):
            QMessageBox.critical(self, "Error", "Please select a synthetic household file.")
            return
        self.lineEdit_NumHH.setText("Calculating...")
        QApplication.processEvents()
        # file_path = settings.get("LDT_visitor_SynHH")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        total_lines = self.count_lines(file_path)
        self.lineEdit_NumHH.setText(str(total_lines))
        settings.set("LDT_visitor_nHH", total_lines)
        QApplication.restoreOverrideCursor()
        print(f"Total number of households: {total_lines}")


    def count_lines(self, filename):
        count = -1 # don't count header row
        with open(filename, 'rb') as f:
            for chunk in iter(lambda: f.raw.read(1024 * 1024), b''):
                count += chunk.count(b'\n')
        return count
    
    def get_layer_path(self, layer):
        """Retrieve the data source path of a layer."""
        if layer:
            provider = layer.dataProvider()
            return provider.dataSourceUri().split("|")[0]  # Remove extra filter params
        return None
    
    @closes_run_console
    def run_LDT_visitor(self, show_message=False):
        # Check if all required fields are filled
        if not self.lineEdit_InputDir.text():
            QMessageBox.critical(self, "Error", "Please select an input directory.")
            return False
        if not self.lineEdit_RoadSkim.text():
            QMessageBox.critical(self, "Error", "Please select a road skim file.")
            return False
        if not self.lineEdit_RailSkim.text():
            QMessageBox.critical(self, "Error", "Please select a rail skim file.")
            return False
        if not self.lineEdit_AirSkim.text():
            QMessageBox.critical(self, "Error", "Please select an air skim file.")
            return False
        if not self.lineEdit_LDTSynHH.text():
            QMessageBox.critical(self, "Error", "Please select a synthetic household file.")
            return False
        if not self.lineEdit_OutDir.text():
            QMessageBox.critical(self, "Error", "Please select an output directory.")
            return False

        settings = Config()
        # One live-tail window for the whole LDT-visitor run (no per-step black windows).
        begin_run_console(os.path.join(settings.get("scenarioDir"), "LDT_visitor.log"),
                          "LDT Visitor - run log")
        #------------------------------------------------------------------------------------
        # Generate updated landuse data file
        landuse_layer = self.comboBox_LU.currentData()
        if not landuse_layer:
            QMessageBox.critical(self, "Error", "Please select a landuse layer.")
            return False
        landuse_layer_path = self.get_layer_path(landuse_layer)
        settings.set("landuse_layer_path", landuse_layer_path)
        # ldtprep replaces Update_LDT_Landuse_from_SDT.R, Create_Incremental_*, Append_Incremental_*
        ldtprep_exe = settings.app_exe("utilities/ldtprep.exe")
        if not os.path.exists(ldtprep_exe):
            QMessageBox.critical(self, "Error", f"Utility not found: {ldtprep_exe}")
            return False

        us_lu_file = settings.get("scenarioYear") + "_landuse.dat"
        # LDT reference inputs (landuse, vehicle_type_alts, ...) all live in the
        # user-selected LDT Input Directory (panel field -> LDT_resident_InputDir,
        # e.g. {tsm_location}/Inputs/LDT_Skims_LU_SynHH). NOT a hardcoded folder.
        ldt_resident_default = os.path.join(settings.get("LDT_resident_InputDir"), us_lu_file).replace("\\","/")
        ldt_resident_updated = os.path.join(settings.get("scenarioDir"), "LDT_Landuse.dat").replace("\\","/")
        settings.set("LDT_resident_Landuse_updated", ldt_resident_updated)
        print(f"Updated Landuse file: {ldt_resident_updated}")
        print(f"Default Landuse file: {ldt_resident_default}")
        print(f"Landuse layer path: {landuse_layer_path}")
        print(f"ldtprep exe: {ldtprep_exe}")
        ldt_log = os.path.join(settings.get("scenarioDir"), "LDT_visitor.log")
        try:
            result1 = Config().run_app([ldtprep_exe, "landuse", landuse_layer_path, ldt_resident_default, ldt_resident_updated],
                                       log_path=ldt_log, console=True)
            if result1.returncode != 0:
                QMessageBox.critical(self, "Error", "LDT Landuse update failed.")
                return False
        except Exception as e:
            print(f"Error running LDT Landuse update: {e}")
            return False

        #------------------------------------------------------------------------------------
        # Generate incremental synthetic household data file
        US_ldt_syn_hh = settings.get("LDT_visitor_SynHH")
        scenYear = settings.get("scenarioYear")
        # NOTE: the one-time C++ sort-synhh pre-sort is no longer needed -- the Python
        # prep below does sort+filter in ONE pass (pandas sorts 134M rows in ~8s), so
        # the sort checkbox is now a no-op. ldtprep sort-synhh kept, commented out:
        # if self.checkBox_sortSynHH.isChecked():
        #     _stem = US_ldt_syn_hh
        #     for _ext in (".csv.gz", ".gz", ".csv", ".dat"):
        #         if _stem.lower().endswith(_ext):
        #             _stem = _stem[:-len(_ext)]; break
        #     sorted_hh = (_stem + "_sorted.csv.gz").replace("\\", "/")
        #     result_sort = Config().run_app([ldtprep_exe, "sort-synhh", US_ldt_syn_hh, sorted_hh],
        #                                    log_path=ldt_log, console=True, append=True)
        #     if result_sort.returncode != 0:
        #         QMessageBox.critical(self, "Error", "Syn-HH one-time sort failed."); return False
        #     US_ldt_syn_hh = sorted_hh; settings.set("LDT_visitor_SynHH", sorted_hh)
        #     self.lineEdit_LDTSynHH.setText(sorted_hh); self.checkBox_sortSynHH.setChecked(False)
        # LDT is run incrementally by design. Default = INCREMENTAL: pass the
        # reference year so ldtprep keeps only ref < Year <= scen (the households
        # added since the reference run), which are appended back below to rebuild
        # the complete set. ABSOLUTE (testing checkbox) = pass ref == scen so
        # ldtprep keeps ALL Year <= scen, and the append step is skipped.
        absolute = not self.checkBox_incremental.isChecked()
        if absolute:
            ref_year = str(scenYear)
        else:
            ref_year = settings.get("LDTExtCountYear")
            if not ref_year:
                # Was silently defaulting to 2023, which is not this model's base
                # year (2024) and would build the wrong syn-HH delta. The
                # reference year is required for an incremental run: it defines
                # both the delta (ref < Year <= scen) and the run whose output is
                # being appended to.
                QMessageBox.critical(
                    self, "Error",
                    "Incremental run needs a Reference Year. Tick 'User Reference File' "
                    "and set the Reference Year to the year of the run you are "
                    "incrementing from (e.g. 2024 when running 2030), plus its "
                    "Reference Tour File.")
                return False
        out_ldt_syn_hh = os.path.join(settings.get("scenarioDir"), "LDT_visitor_SynHH.dat").replace("/", "\\")
        settings.set("LDT_visitor_SynHH_updated", out_ldt_syn_hh)

        print(f"ldtprep exe: {ldtprep_exe}")
        print(f"US HH all years: {US_ldt_syn_hh}")
        print(f"Scenario Year: {scenYear}")
        print(f"LDT mode: {'ABSOLUTE (Year <= scen, no append)' if absolute else f'INCREMENTAL (ref {ref_year} < Year <= scen)'}")
        print(f"LDT HH updated: {out_ldt_syn_hh}")

        # --- syn-HH prep via Python (pandas): combined filter+sort in ONE pass ------
        # Replaces the C++ two-step (sort-synhh + synhh-incremental). pandas sorts
        # 134M rows in ~8s and does sort+filter together, dropping the intermediate
        # sorted-gz read/write. QGIS ships pandas, so no extra install for the user.
        import sys as _sys
        qgis_py = os.path.join(_sys.exec_prefix, "python.exe")
        if not os.path.exists(qgis_py):
            qgis_py = _sys.executable
        prep_script = os.path.join(settings.get("plugin_dir"), "ldt_synhh_prep.py")
        try:
            result2 = Config().run_app([qgis_py, prep_script, "visitor", US_ldt_syn_hh, str(scenYear), str(ref_year), out_ldt_syn_hh],
                                       log_path=ldt_log, console=True, append=True)
            if result2.returncode != 0:
                QMessageBox.critical(self, "Error", "LDT HH from Scenario failed.")
                return False
        except Exception as e:
            print(f"Running LDT Syn HH update: {e}")
            return False
        # --- C++ ldtprep path (commented out per the python switch; kept for fallback) ---
        # try:
        #     result2 = Config().run_app([ldtprep_exe, "synhh-incremental", US_ldt_syn_hh, str(scenYear), str(ref_year), out_ldt_syn_hh],
        #                                log_path=ldt_log, console=True, append=True)
        #     if result2.returncode != 0:
        #         QMessageBox.critical(self, "Error", "LDT HH from Scenario failed."); return False
        # except Exception as e:
        #     print(f"Running LDT Syn HH update: {e}"); return False

        self.check_nHH(settings.get("LDT_visitor_SynHH_updated")) # Update number of households in settings

        #------------------------------------------------------------------------------------
        LDT_Parameters = os.path.join(settings.get("plugin_dir"), "config", "ldt_coefficients_toml").replace("\\", "/")

        check_railSkim = os.path.join(settings.get("scenarioDir"), os.path.basename(settings.get("LDT_resident_RailSkim")))
        check_roadSkim = os.path.join(settings.get("scenarioDir"), os.path.basename(settings.get("LDT_resident_RoadSkim")))
        check_airSkim = os.path.join(settings.get("scenarioDir"), os.path.basename(settings.get("LDT_resident_AirSkim")))

        if not os.path.exists(check_roadSkim):
            QMessageBox.critical(self, "Error", "LDT resident Road Skim file not found, Either run LDT Resident Model or copy the skim to scenario directory.")
            return False
        if not os.path.exists(check_railSkim):
            QMessageBox.critical(self, "Error", "LDT resident Rail Skim file not found, Either run LDT Resident Model or copy the skim to scenario directory.")
            return False
        if not os.path.exists(check_airSkim):
            QMessageBox.critical(self, "Error", "LDT resident Air Skim file not found, Either run LDT Resident Model or copy the skim to scenario directory.")
            return False

        # Create LDT-visitor properties file
        ldt_vis_template = os.path.join(settings.get("plugin_dir"), "templates", "LDT_visitor_control_template.txt")
        properties_file = os.path.join(settings.get("scenarioDir"), "LDT_visitor.txt").replace("/", "\\")

        replacements = {
            "OUTPUT_DIR" : settings.get("scenarioDir").replace("/", "\\"),
            "INPUT_DIR" : settings.get("scenarioDir").replace("/", "\\"),
            "ROAD_SKIM" : os.path.basename(settings.get("LDT_resident_RoadSkim")),
            "RAIL_SKIM" : os.path.basename(settings.get("LDT_resident_RailSkim")),
            "AIR_SKIM" : os.path.basename(settings.get("LDT_resident_AirSkim")),
            "LAND_USE" : os.path.basename(settings.get("LDT_resident_Landuse_updated")),
            "SYN_HH" : os.path.basename(settings.get("LDT_visitor_SynHH_updated")),
            "NUM_HH" : str(settings.get("LDT_visitor_nHH")),
            "COEFF_TOML_DIR" : LDT_Parameters
        }
        self.template_keys_update(ldt_vis_template, replacements, properties_file)

        ldt_exe = settings.app_exe("ldt/ldt-run.exe")
        if not os.path.exists(ldt_exe):
            QMessageBox.critical(self, "Error", f"ldt-run.exe not found at: {ldt_exe}")
            return False

        # Run the LDT-visitor model (ldt-run.exe) via the shared gated runner
        # (captures output, reports token/offline/model errors in a message box).
        if not run_gated_model(self, [ldt_exe, properties_file], "LDT-visitor model",
                               cwd=settings.get("scenarioDir"),
                               log_path=os.path.join(settings.get("scenarioDir"), "LDT_visitor_run.log"),
                               console=True):
            return False

        # Absolute (testing) run: ldtprep already emitted the full Year <= scen set,
        # so there is nothing to append back. Done.
        if absolute:
            if show_message:
                QMessageBox.information(self, "Success",
                                       "LDT Visitor Model run successfully (absolute run - all HH <= scenario year, no append).")
            return True

        #------------------------------------------------------------------------------------
        # Check and append if incremental
        if self.checkBox_userRef.isChecked():
            # Check if the previous output file exists
            prev_out_file = settings.get("LDT_visitor_userRef_filepath")
            checkBox_userRef_str = "True"
            if os.path.exists(prev_out_file):
                print(f"Previous output file found: {prev_out_file}")
            else:
                print(f"Previous output file not found: {prev_out_file}")
                QMessageBox.critical(self, "Error", "Previous output file not found.")
                return
        else:
            prev_out_file = "none"
            checkBox_userRef_str = "False"

        ldtprep_exe = settings.app_exe("utilities/ldtprep.exe")
        if not os.path.exists(ldtprep_exe):
            QMessageBox.critical(self, "Error", f"Utility not found: {ldtprep_exe}")
            return False
        scenYear = settings.get("scenarioYear")
        scenarioDir = settings.get("scenarioDir")
        tsm_location = settings.get("tsm_location")
        incremental_output = os.path.join(scenarioDir, "OS_LD_increment_tour_out.csv")

        try:
            result4 = Config().run_app([ldtprep_exe, "synhh-append", incremental_output, checkBox_userRef_str, prev_out_file, tsm_location,  scenarioDir, scenYear],
                                       log_path=ldt_log, console=True, append=True)
            if result4.returncode == 0:
                print(f"Appended LDT incremental results with previous years: OS_LD_tour_out.csv")
                # QMessageBox.information(self, "Success", "Appended LDT incremental results with previous years: OS_LD_tour_out.csv")
                if show_message:
                    QMessageBox.information(self, "Success", "LDT Visitor Model run successfully.")        
                return True
            else:
                print(f"Appending LDT incremental results with previous years failed: {result4}")
                QMessageBox.critical(self, "Error", "Appending LDT incremental results with previous years failed.")
                return False
        except Exception as e:
            print(f"Appending LDT incremental results with previous years failed: {e}")
            return False
        #------------------------------------------------------------------------------------
        self.close()