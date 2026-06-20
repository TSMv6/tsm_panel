import os, shutil, subprocess, time
from PyQt5.QtWidgets import QDialog, QFileDialog, QDockWidget, QMessageBox
from qgis.core import QgsProject, QgsVectorLayer
from PyQt5 import uic  # For loading .ui dynamically
from .tsm_settings import Config
# from .helper_functions import HelperFun 

from .LDT_resident_ui import Ui_Dialog_LDTRes

class LDTResidentModel(QDialog, Ui_Dialog_LDTRes):
    def __init__(self):
        super().__init__()
        # self.setupUi(self)

        # Verify the UI file path
        # plugin_dir = os.path.dirname(__file__).replace("\\", "/")
        settings = Config()
        plugin_dir = settings.get("plugin_dir")
        ui_file = os.path.join(plugin_dir, "ui/LDT_Res.ui")
        print(f"UI file found at: {ui_file}")

        # Check if the UI file exists
        if not os.path.exists(ui_file):
            print(f"UI file not found at: {ui_file}")
            return  # If the file doesn't exist, stop further execution
        
        # Load the UI dynamically if the file exists
        uic.loadUi(ui_file, self)

        self.textBrowser.setOpenExternalLinks(True)
        self._load_help_doc(os.path.join(plugin_dir, "docs", "LDT_RES.md"))

        # Connect buttons to browse function
        self.browse_LDTInputDir.clicked.connect(lambda: self.select_directory(self.lineEdit_InputDir))
        omx_filter = "OMX skim (*.omx);; All Files (*)"
        self.browse_RoadSkim.clicked.connect(lambda: self.select_file(self.lineEdit_RoadSkim, "open", omx_filter))
        self.browse_RailSkim.clicked.connect(lambda: self.select_file(self.lineEdit_RailSkim, "open", omx_filter))
        self.browse_AirSkim.clicked.connect(lambda: self.select_file(self.lineEdit_AirSkim, "open", omx_filter))
        # self.browse_LDTLanduse.clicked.connect(lambda: self.select_file(self.lineEdit_LanduseDAT, "open"))
        self.populate_layer_combobox(self.comboBox_LU,"Polygon")
        self.browse_LDT_SynHH.clicked.connect(lambda: self.select_file(self.lineEdit_LDTSynHH, "open"))
        self.browse_LDTOutputDir.clicked.connect(lambda: self.select_directory(self.lineEdit_OutDir))
        # self.checkBox_nHH.stateChanged.connect(self.check_nHH)

        # Connect the "save" button to the corresponding function
        self.button_SaveCancel.accepted.connect(self.update_settings)
        self.button_SaveCancel.rejected.connect(self.cancel_action)
        self.run_LDTRes.clicked.connect(lambda: self.run_LDT_resident(show_message=True))

        # Update Settings ("Main Panel -> Load Settings -> Config()")
        if settings.get("LDT_resident_InputDir"):
            self.lineEdit_InputDir.setText(settings.get("LDT_resident_InputDir"))
        if settings.get("LDT_resident_RoadSkim"):
            self.lineEdit_RoadSkim.setText(settings.get("LDT_resident_RoadSkim"))
        if settings.get("LDT_resident_RailSkim"):
            self.lineEdit_RailSkim.setText(settings.get("LDT_resident_RailSkim"))   
        if settings.get("LDT_resident_AirSkim"):
            self.lineEdit_AirSkim.setText(settings.get("LDT_resident_AirSkim"))
        if settings.get("landuse_layer"):
            landuse_layer_name = settings.get("landuse_layer")
            if landuse_layer_name in [self.comboBox_LU.itemText(i) for i in range(self.comboBox_LU.count())]:
                print("Landuse layer already in combo box")
                self.comboBox_LU.setCurrentText(landuse_layer_name)
        if settings.get("synHH_file"):
            self.lineEdit_LDTSynHH.setText(settings.get("synHH_file"))
        # if settings.get("LDT_resident_SynHH"):
        #     self.lineEdit_LDTSynHH.setText(settings.get("LDT_resident_SynHH"))
        if settings.get("scenarioDir"):
            self.lineEdit_OutDir.setText(settings.get("scenarioDir"))
        if settings.get("LDT_resident_nHH"):
            self.checkBox_nHH.setChecked(True)
            self.lineEdit_NumHH.setText(str(settings.get("LDT_resident_nHH")))

    def update_settings(self):
        settings = Config()
        settings.set("LDT_resident_InputDir", self.lineEdit_InputDir.text())
        settings.set("LDT_resident_RoadSkim", self.lineEdit_RoadSkim.text())
        settings.set("LDT_resident_RailSkim", self.lineEdit_RailSkim.text())
        settings.set("LDT_resident_AirSkim", self.lineEdit_AirSkim.text())
        # if self.lineEdit_LanduseDAT.text():
        #     settings.set("LDT_resident_Landuse", self.lineEdit_LanduseDAT.text())
        landuse_layer = self.comboBox_LU.currentData()
        settings.set("landuse_layer", landuse_layer.name())  
        settings.set("synHH_file", self.lineEdit_LDTSynHH.text())
        settings.set("scenarioDir", self.lineEdit_OutDir.text())
        # if self.checkBox_nHH.isChecked() and 
        self.lineEdit_NumHH.setText(str(settings.get("LDT_resident_nHH")))
        # self.close()
        QMessageBox.information(self, "Success", "Settings updated successfully.")
        settings.check_and_save_to_file("scenario_settings_file")

    def cancel_action(self):
        print("Action canceled. Closing dialog.")
        self.reject()  # Closes the dialog without executing any code

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

    def select_file(self, line_edit, type, file_filter="Syn HH (*.csv) ;; skim (*.omx) ;; All Files (*)"):
        if type == "open":
            file_path, _ = QFileDialog.getOpenFileName(self, "Select File", "", file_filter)
        elif type == "save":
            file_path, _ = QFileDialog.getSaveFileName(self, "Select File", "", "All Files (*)")
        if file_path:
            line_edit.setText(file_path)

    def select_directory(self, line_edit):
        directory = QFileDialog.getExistingDirectory(self, "Select Directory", )
        if directory:
            line_edit.setText(directory)

    def check_nHH(self):
        # if self.checkBox_nHH.isChecked():
        settings = Config()
        self.lineEdit_NumHH.setEnabled(True)
        file_path = settings.get("synHH_file")
        if not file_path:
            QMessageBox.critical(self, "Error", "Please select a synthetic household file.")
            return
        if not os.path.exists(file_path):
            QMessageBox.critical(self, "Error", "The selected synthetic household file does not exist.")
            return
        total_lines = self.count_lines(file_path)
        settings.set("LDT_resident_nHH", total_lines)
        self.lineEdit_NumHH.setText(str(total_lines))
        # else:
        #     self.lineEdit_NumHH.setEnabled(False)

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
    
    def run_LDT_resident(self, show_message=False):
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
        # compute number of households (updates LDT_resident_SynHH)
        self.check_nHH()

        #------------------------------------------------------------------------------------
        # Generate updated landuse data file
        landuse_layer = self.comboBox_LU.currentData()
        if not landuse_layer:
            QMessageBox.critical(self, "Error", "Please select a landuse layer.")
            return False
        landuse_layer_path = self.get_layer_path(landuse_layer)
        settings.set("landuse_layer_path", landuse_layer_path)
        # ldtprep replaces Update_LDT_Landuse_from_SDT.R + convert_SDT_SynHH_to_LDT_format.R
        ldtprep_exe = settings.app_exe("utilities/ldtprep.exe")
        if not os.path.exists(ldtprep_exe):
            QMessageBox.critical(self, "Error", f"Utility not found: {ldtprep_exe}")
            return False

        us_lu_file = settings.get("scenarioYear") + "_landuse.dat"
        ldt_resident_default = os.path.join(settings.get("tsm_location"), "Inputs/LDT_Skims_LU_SynHH", us_lu_file).replace("\\","/")
        ldt_resident_updated = os.path.join(settings.get("scenarioDir"), "LDT_Landuse.dat").replace("\\","/")
        settings.set("LDT_resident_Landuse_updated", ldt_resident_updated)
        print(f"Updated Landuse file: {ldt_resident_updated}")
        print(f"Default Landuse file: {ldt_resident_default}")
        print(f"Landuse layer path: {landuse_layer_path}")
        print(f"ldtprep exe: {ldtprep_exe}")
        try:
            result1 = subprocess.run([ldtprep_exe, "landuse", landuse_layer_path, ldt_resident_default, ldt_resident_updated])
            if result1.returncode == 0:
                print(f"Running LDT Landuse updated successful: {ldt_resident_updated}")
            else:
                print(f"Running LDT Landuse update failed: {result1}")
                QMessageBox.critical(self, "Error", "LDT Landuse update failed.")
                return False
        except Exception as e:
            print(f"Error running LDT Landuse update: {e}")
            return False
        #------------------------------------------------------------------------------------

        # Generate updated synthetic household data file
        sdt_syn_hh = settings.get("synHH_file")
        sdt_syn_auto = os.path.join(settings.get("scenarioDir"), "households_1.csv").replace("/", "\\")
        if not os.path.exists(sdt_syn_auto):
            QMessageBox.critical(self, "Error", "Please run the SDT Resident model first for households_1.csv which contains Auto Ownership results for FL residents.")
            return False
        LDT_households_template = os.path.join(settings.get("plugin_dir"), "templates", "ldt_syn_hh_template.dat")
        LDT_households_updated_basefile = "LDT_FL_Syn_hh.dat"
        LDT_households_updated = os.path.join(settings.get("scenarioDir"), LDT_households_updated_basefile).replace("/", "\\")

        print(f"ldtprep exe: {ldtprep_exe}")
        print(f"SDT Syn HH: {sdt_syn_hh}")
        print(f"SDT Syn Auto: {sdt_syn_auto}")
        print(f"LDT HH template: {LDT_households_template}")
        print(f"LDT HH updated: {LDT_households_updated}")
        try:
            result2 = subprocess.run([ldtprep_exe, "synhh-convert", sdt_syn_hh, sdt_syn_auto, LDT_households_template, LDT_households_updated])
            if result2.returncode == 0:
                print(f"Running LDT HH from SDT successful: {LDT_households_updated}")
            else:
                print(f"Running LDT HH from SDT failed: {result2}")
                QMessageBox.critical(self, "Error", "LDT HH from SDT update failed.")
                return False
        except Exception as e:
            print(f"Running LDT Syn HH update: {e}")
            return False
        #------------------------------------------------------------------------------------

        LDT_Parameters = os.path.join(settings.get("tsm_location"), "config", "ldt_coefficients_toml").replace("\\", "/")

        # Create LDT-resident properties file
        ldt_res_template = os.path.join(settings.get("plugin_dir"), "templates", "LDT_resident_control_template.txt")
        properties_file = os.path.join(settings.get("scenarioDir"), "LDT_resident.txt").replace("/", "\\")

        # Copy files to scenario directory
        try:
            if settings.get("LDT_resident_RoadSkim"):
                shutil.copy(settings.get("LDT_resident_RoadSkim"), os.path.join(settings.get("scenarioDir"), os.path.basename(settings.get("LDT_resident_RoadSkim"))))
            if settings.get("LDT_resident_RailSkim"):
                shutil.copy(settings.get("LDT_resident_RailSkim"), os.path.join(settings.get("scenarioDir"), os.path.basename(settings.get("LDT_resident_RailSkim"))))
            if settings.get("LDT_resident_AirSkim"):
                shutil.copy(settings.get("LDT_resident_AirSkim"), os.path.join(settings.get("scenarioDir"), os.path.basename(settings.get("LDT_resident_AirSkim"))))
            shutil.copy(os.path.join(settings.get("tsm_location"), "Inputs/LDT_Skims_LU_SynHH/vehicle_type_alts.csv"),
                        os.path.join(settings.get("scenarioDir"),"vehicle_type_alts.csv"))
        except Exception as e:
            print(f"Error copying input files: {e}")
            QMessageBox.critical(self, "Error", f"Error copying input files: {e}")
            return False

        replacements = {
            "OUTPUT_DIR" : settings.get("scenarioDir").replace("/", "\\"),
            "INPUT_DIR" : settings.get("scenarioDir").replace("/", "\\"),
            "ROAD_SKIM" : os.path.basename(settings.get("LDT_resident_RoadSkim")),
            "RAIL_SKIM" : os.path.basename(settings.get("LDT_resident_RailSkim")),
            "AIR_SKIM" : os.path.basename(settings.get("LDT_resident_AirSkim")),
            "LAND_USE" : os.path.basename(settings.get("LDT_resident_Landuse_updated")),
            "SYN_HH" : LDT_households_updated_basefile,
            "NUM_HH" : str(settings.get("LDT_resident_nHH")),
            "COEFF_TOML_DIR" : LDT_Parameters
        }
        print(replacements)

        self.template_keys_update(ldt_res_template, replacements, properties_file)

        ldt_exe = os.path.join(settings.get("tsm_location"), "Apps", "ldt", "ldt-run.exe")
        if not os.path.exists(ldt_exe):
            QMessageBox.critical(self, "Error", f"ldt-run.exe not found at: {ldt_exe}")
            return False

        # Run the LDT-resident model (ldt-run.exe)
        try:
            result1 = subprocess.run([ldt_exe, properties_file], cwd = settings.get("scenarioDir"))
            if result1.returncode == 0:
                print(f"Running LDT-resident model successful: {properties_file}")
                if show_message:
                    QMessageBox.information(self, "Success", "LDT-resident model run successfully.")
                return True
            else:
                print(f"Running LDT-resident model failed: {result1}")
                return False
        except Exception as e:
            print(f"Running LDT-resident model failed: {e}")
            return False
