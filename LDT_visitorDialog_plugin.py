import os, shutil, subprocess, time
from PyQt5.QtWidgets import QDialog, QFileDialog, QDockWidget, QMessageBox, QApplication, QTableWidget, QTableWidgetItem, QHeaderView
from qgis.core import QgsProject, QgsVectorLayer
from PyQt5 import uic  # For loading .ui dynamically
from .tsm_settings import Config
# from .helper_functions import HelperFun 
from PyQt5.QtCore import Qt, QSettings
from PyQt5.QtGui import QColor

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
        
        self.table = self.findChild(QTableWidget, "table_ExtStn_Counts")
        # External-station overwrite table: col0 = Ext Zone ID, col1 = Base Count
        # (2024), col2 = Future Target or Growth %. Persisted per interstate in
        # Config as <name>_Zone / <name>_Count / <name>_Future.
        ext_defaults = {"I-75": ("", "55000", "1.0%"),
                        "I-10": ("", "30000", "1.0%"),
                        "I-95": ("", "75000", "1.0%")}
        for row in range(self.table.rowCount()):
            name = self.table.verticalHeaderItem(row).text()
            dz, dc, df = ext_defaults.get(name, ("", "", "1.0%"))
            zone = settings.get(f"{name}_Zone")
            count = settings.get(f"{name}_Count")
            future = settings.get(f"{name}_Future")
            self.table.setItem(row, 0, QTableWidgetItem(zone if zone is not None else dz))
            self.table.setItem(row, 1, QTableWidgetItem(count if count else dc))
            self.table.setItem(row, 2, QTableWidgetItem(future if future else df))
        # Stretch the three columns to fill the table width.
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        
        # Save these values to config file
        # row_names = []
        # row_keys = []
        # row_values = []
        # # Get existing values from the table
        # for row in range(self.table.rowCount()):
        #     item = self.table .verticalHeaderItem(row)
        #     row_name = item.text() if item else ""
        #     row_key = self.table .item(row, 1).text() if self.table .item(row, 1) else ""
        #     row_value = self.table .item(row, 2).text() if self.table .item(row, 2) else ""
        #     print(f"Row {row}: Name: {row_name}, Count: {row_key}, CAGR: {row_value}")
        #     row_names.append(row_name)
        #     row_keys.append(row_key)
        #     row_values.append(row_value)
        # print(row_names) 
        # print(row_keys)
        # print(row_keys)

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

    def _persist_external_targets(self):
        """Write the external-station overwrite table to a CSV for the downstream
        external-overwrite step (interstate, ext zone id, base count, future)."""
        settings = Config()
        out = os.path.join(settings.get("scenarioDir"), "ldt_external_targets.csv")
        try:
            with open(out, "w", newline="") as f:
                f.write("interstate,ext_zone_id,base_count_2024,future_target_or_growth\n")
                for row in range(self.table.rowCount()):
                    name = self.table.verticalHeaderItem(row).text()
                    zone = self.table.item(row, 0).text() if self.table.item(row, 0) else ""
                    count = self.table.item(row, 1).text() if self.table.item(row, 1) else ""
                    future = self.table.item(row, 2).text() if self.table.item(row, 2) else ""
                    f.write(f"{name},{zone},{count},{future}\n")
            print(f"Wrote external targets: {out}")
        except Exception as e:
            print(f"Could not write external targets: {e}")

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

        # Save the external-station overwrite table (zone / base count / future)
        for row in range(self.table.rowCount()):
            name = self.table.verticalHeaderItem(row).text()
            settings.set(f"{name}_Zone", self.table.item(row, 0).text() if self.table.item(row, 0) else "")
            settings.set(f"{name}_Count", self.table.item(row, 1).text() if self.table.item(row, 1) else "")
            settings.set(f"{name}_Future", self.table.item(row, 2).text() if self.table.item(row, 2) else "")

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
        QApplication.setOverrideCursor(Qt.WaitCursor)
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
        #------------------------------------------------------------------------------------
        # Generate updated landuse data file
        landuse_layer = self.comboBox_LU.currentData()
        if not landuse_layer:
            QMessageBox.critical(self, "Error", "Please select a landuse layer.")
            return False
        landuse_layer_path = self.get_layer_path(landuse_layer)
        settings.set("landuse_layer_path", landuse_layer_path) 
        r_script_path = os.path.join(settings.get("plugin_dir"), "Rscripts/Update_LDT_Landuse_from_SDT.R")
        r_exe_path = settings.get("r_exe_path")

        us_lu_file = settings.get("scenarioYear") + "_landuse.dat"
        ldt_resident_default = os.path.join(settings.get("tsm_location"), "Inputs/LDT_Skims_LU_SynHH", us_lu_file).replace("\\","/")
        ldt_resident_updated = os.path.join(settings.get("scenarioDir"), "LDT_Landuse.dat").replace("\\","/")
        settings.set("LDT_resident_Landuse_updated", ldt_resident_updated)
        print(f"Updated Landuse file: {ldt_resident_updated}")
        print(f"Default Landuse file: {ldt_resident_default}")
        print(f"Landuse layer path: {landuse_layer_path}")
        print(f"R script path: {r_script_path}")
        print(f"R executable path: {r_exe_path}")
        try:
            result1 = subprocess.run([r_exe_path, r_script_path, landuse_layer_path, ldt_resident_default, ldt_resident_updated])
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
        ref_year = settings.get("LDTExtCountYear")
        out_ldt_syn_hh = os.path.join(settings.get("scenarioDir"), "LDT_visitor_SynHH.dat").replace("/", "\\")
        settings.set("LDT_visitor_SynHH_updated", out_ldt_syn_hh)

        r_script_path = os.path.join(settings.get("plugin_dir"), "Rscripts",  "Create_Incremental_LDT_Syn_HH.R").replace("/", "\\")
        print(f"R script path: {r_script_path}")
        print(f"R executable path: {r_exe_path}")
        print(f"US HH all years: {US_ldt_syn_hh}")
        print(f"Scenario Year: {scenYear}")
        print(f"LDT reference year: {ref_year}")
        print(f"LDT HH updated: {out_ldt_syn_hh}")

        if ref_year is None:
            ref_year = "2023"  # Default reference year if not provided

        try:
            result2 = subprocess.run([r_exe_path, r_script_path, US_ldt_syn_hh, scenYear, ref_year, out_ldt_syn_hh])
            if result2.returncode != 0:
                QMessageBox.critical(self, "Error", "LDT HH from Scenario failed.")
                return False
        except Exception as e:
            print(f"Running LDT Syn HH update: {e}")
            return False

        self.check_nHH(settings.get("LDT_visitor_SynHH_updated")) # Update number of households in settings

        #------------------------------------------------------------------------------------
        LDT_Parameters = os.path.join(settings.get("tsm_location"), "config", "ldt_coefficients_toml").replace("\\", "/")

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

        # Persist the external-station overwrite targets for the downstream step.
        self._persist_external_targets()

        ldt_exe = os.path.join(settings.get("tsm_location"), "Apps", "ldt", "ldt-run.exe")
        if not os.path.exists(ldt_exe):
            QMessageBox.critical(self, "Error", f"ldt-run.exe not found at: {ldt_exe}")
            return False

        # Run the LDT-visitor model (ldt-run.exe)
        try:
            result3 = subprocess.run([ldt_exe, properties_file], cwd = settings.get("scenarioDir"))
            if result3.returncode != 0:
                return False
            # if show_message:
                # QMessageBox.information(self, "Success", "LDT Visitor Model run successfully.")
        except Exception as e:
            print(f"Running LDT-visitor model failed: {e}")
            return
        
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

        r_exe_path = settings.get("r_exe_path")
        r_script_path = os.path.join(settings.get("plugin_dir"), "Rscripts", "Append_Incremental_LDT_Syn_HH.R")
        scenYear = settings.get("scenarioYear")
        scenarioDir = settings.get("scenarioDir")
        tsm_location = settings.get("tsm_location")
        incremental_output = os.path.join(scenarioDir, "OS_LD_increment_tour_out.csv")
    
        try:
            result4 = subprocess.run([r_exe_path, r_script_path, incremental_output, checkBox_userRef_str, prev_out_file, tsm_location,  scenarioDir, scenYear])
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