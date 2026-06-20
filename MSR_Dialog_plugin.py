import os, shutil, subprocess, time
from PyQt5.QtWidgets import QDialog, QFileDialog, QDockWidget, QMessageBox
from qgis.core import QgsProject, QgsVectorLayer
from PyQt5 import uic  # For loading .ui dynamically
from .tsm_settings import Config
# from .helper_functions import HelperFun 

from .MSR_ui import Ui_Dialog_MSR

class MSR_Disaggregate(QDialog, Ui_Dialog_MSR):
    def __init__(self):
        super().__init__()
        # self.setupUi(self)

        # Verify the UI file path
        # plugin_dir = os.path.dirname(__file__).replace("\\", "/")
        settings = Config()
        plugin_dir = settings.get("plugin_dir")
        ui_file = os.path.join(plugin_dir, "ui/MSR.ui")
        print(f"UI file found at: {ui_file}")

        # Check if the UI file exists
        if not os.path.exists(ui_file):
            print(f"UI file not found at: {ui_file}")
            return  # If the file doesn't exist, stop further execution

        # Load the UI dynamically if the file exists
        uic.loadUi(ui_file, self)  # This will automatically load the UI and set it up

        # Populate the dropdowns with available land-use layers (polygons)
        self.populate_layer_combobox(self.comboBox_Landuse,"Polygon")

        # self.populate_layer_combobox(self.comboBox_RefLUlayer, "Polygon")
        # Connect buttons to browse function
        self.browse_SynHH.clicked.connect(lambda: self.select_file(self.lineEdit_SynHH, "open"))
        self.browse_SynPer.clicked.connect(lambda: self.select_file(self.lineEdit_SynPer, "open"))
        self.browse_Skim.clicked.connect(lambda: self.select_file(self.lineEdit_Skim, "open"))

        # Populate telework policies (7%, 10%, 15%, 20%, 25%)
        # Default = 15%, which is default zero in the floridaturnpike<scenario>.properties 
        # self.comboBox_TeleworkShare.addItems(["7%", "10%", "15%", "20%", "25%"])
        # self.comboBox_TeleworkShare.setCurrentText("15%")
        # self.browse_SDTOut.clicked.connect(lambda: self.select_directory(self.lineEdit_OutDir))

        # Connect the "save" button to the corresponding function
        self.button_OkCancel.accepted.connect(self.update_settings)
        self.button_OkCancel.rejected.connect(self.cancel_action)
        self.Run_MSR.clicked.connect(lambda: self.run_MSR(show_message=True))

        # Update Settings ("Main Panel -> Load Settings -> Config()")
        settings = Config()
        print("current landuse layer:", settings.get("landuse_layer"))
        if settings.get("landuse_layer"):
            landuse_layer_name = settings.get("landuse_layer")
            # print(landuse_layer_name)
            # if isinstance(layer, QgsVectorLayer):
            # landuse_layer = QgsProject.instance().mapLayersByName(landuse_layer_name)[0]
            if landuse_layer_name in [self.comboBox_Landuse.itemText(i) for i in range(self.comboBox_Landuse.count())]:
                print("Landuse layer already in combo box")
                # self.comboBox_LUlayer.addItem(landuse_layer_name) # Add to combo box if not already present
                self.comboBox_Landuse.setCurrentText(landuse_layer_name)
        if settings.get("synHH_file"):
            self.lineEdit_SynHH.setText(settings.get("synHH_file"))
        if settings.get("synPer_file"):
            self.lineEdit_SynPer.setText(settings.get("synPer_file"))
        if settings.get("skim_file"):
            self.lineEdit_Skim.setText(settings.get("skim_file"))
        if settings.get("telework_share"):
            self.comboBox_TeleworkShare.setCurrentText(settings.get("telework_share"))
        if settings.get("scenarioDir"):
                self.lineEdit_OutDir.setText(settings.get("scenarioDir"))

    def update_settings(self):
        settings = Config()
        if self.comboBox_Landuse.currentData():
            landuse_layer = self.comboBox_Landuse.currentData()
            settings.set("landuse_layer", landuse_layer.name())  
        if self.lineEdit_SynHH.text():
            settings.set("synHH_file", self.lineEdit_SynHH.text())
        if self.lineEdit_SynPer.text():
            settings.set("synPer_file", self.lineEdit_SynPer.text())
        if self.lineEdit_Skim.text():
            settings.set("skim_file", self.lineEdit_Skim.text())
        if self.comboBox_TeleworkShare.currentText():
            settings.set("telework_share", self.comboBox_TeleworkShare.currentText())   
        if self.lineEdit_OutDir.text():
            settings.set("scenarioDir", self.lineEdit_OutDir.text())
        # self.close()  # Closes the dialog and saves the settings
        settings.check_and_save_to_file("scenario_settings_file")
        QMessageBox.information(self, "Settings Updated", "Project Specific settings have been updated.")
        

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

    def run_MSR(self, show_message=False):
        # Check if all required fields are filled
        if not self.comboBox_Landuse.currentData():
            QMessageBox.critical(self, "Error", "Please select a land-use layer.")
            return False
        if not self.lineEdit_SynHH.text():
            QMessageBox.critical(self, "Error", "Please select a synthetic household file.")
            return False
        if not self.lineEdit_SynPer.text():
            QMessageBox.critical(self, "Error", "Please select a synthetic person file.")
            return False
        if not self.lineEdit_Skim.text():
            QMessageBox.critical(self, "Error", "Please select a skim file.")
            return False
        if not self.lineEdit_OutDir.text():
            QMessageBox.critical(self, "Error", "Please select an output directory.")
            return False

        # Run the R script to get Landuse data at TSM level from the regional level
        settings = Config()
        landuse_layer = self.comboBox_Landuse.currentData()
        landuse_layer_path = self.get_layer_path(landuse_layer)
        settings.set("landuse_layer_path", landuse_layer_path) 
        tsm_landuse_path = os.path.join(settings.get("scenarioDir"), "tsm_landuse.csv").replace("\\", "/")
        tsm_landuse_default = os.path.join(settings.get("plugin_dir"), "Rscripts/tsm_landuse_default.csv").replace("\\", "/")
        settings.set("tsm_landuse_path", tsm_landuse_path)

        # se_aggregate.exe replaces SDT_resident_LUPrep.R (aggregate MPO/SE polygons
        # to the TSM zone land use; args: gpkg, out, default).
        se_exe = settings.app_exe("utilities/se_aggregate.exe")
        if not os.path.exists(se_exe):
            QMessageBox.critical(self, "Error", f"Land-use prep utility not found: {se_exe}")
            return False
        try:
            print(f"Aggregating MPO landuse to TSM with {se_exe}: {landuse_layer_path} -> {tsm_landuse_path}")
            result1 = subprocess.run([se_exe, landuse_layer_path, tsm_landuse_path, tsm_landuse_default])
            if result1.returncode != 0 or not os.path.exists(tsm_landuse_path):
                print("Aggregating MPO landuse to TSM failed.")
                QMessageBox.critical(self, "Error", "Aggregating MPO landuse to TSM failed.")
                return False
            print(f"Aggregation of MPO landuse to TSM successful: {tsm_landuse_path}")
        except Exception as e:
            print(f"Aggregating MPO landuse to TSM failed: {e}")
            QMessageBox.critical(self, "Error", f"Aggregating MPO landuse to TSM failed: {e}")
            return False

        # Copy AM skim as MD until we decide to build MD skims or warm start skims
        source_file = settings.get("skim_file")
        extension = os.path.splitext(source_file)[1][1:]
        if extension != "omx":
            QMessageBox.critical(self, "Error", "Please select a valid skim file (.omx).")
            return False
        destination_file = os.path.join(settings.get("scenarioDir"), "MD_Skim.omx")
        try:
            if os.path.exists(destination_file):
                os.remove(destination_file)
            shutil.copyfile(source_file, destination_file)
            destination_file = os.path.join(settings.get("scenarioDir"), "AM_Skim.omx")
            if not os.path.exists(destination_file):
                shutil.copyfile(source_file, destination_file)
        except Exception as e:
            print(f"Error copying skim files: {e}")
            QMessageBox.critical(self, "Error", f"Error copying skim files: {e}")
            return False

        # Create SDT-resident properties file
        sdt_res_template = os.path.join(settings.get("plugin_dir"), "templates", "floridaturnpike_template.properties")
        tsm_location = settings.get("tsm_location")
        properties_file = os.path.join(settings.get("tsm_location"), "config", "floridaturnpike.properties")
        replacements = {
            "PROJECT_DIR": tsm_location.replace("\\", "/"),
            "SCENARIO_DIR": settings.get("scenarioDir").replace("\\", "/"),
            "SYN_HH": self.lineEdit_SynHH.text().replace("\\", "/"),
            "SYN_PER": self.lineEdit_SynPer.text().replace("\\", "/"),
            "SKIM_FILE": self.lineEdit_Skim.text().replace("\\", "/"),
            "LANDUSE_DATA": os.path.basename(tsm_landuse_path)
        }
        try:
            self.template_keys_update(sdt_res_template, replacements, properties_file)
        except Exception as e:
            print(f"Error creating properties file: {e}")
            QMessageBox.critical(self, "Error", f"Error creating properties file: {e}")
            return False

        # Run the SDT-resident model
        jdk_path = settings.get("jdk_path")
        jdk_path_update = jdk_path.replace("Program Files", "Progra~1")
        prj_drive, prj_dir = os.path.splitdrive(tsm_location)
        cmd_sdt_res_template = os.path.join(settings.get("plugin_dir"), "templates", "runSDModel_RES_template.cmd")
        cmd_file = os.path.join(settings.get("scenarioDir"), "runSDModel_RES.cmd")
        replacements = {
            "PRJ_DRIVE": prj_drive,
            "PRJ_DIR": prj_dir.replace("\\", "/"),
            "JDK_PATH": jdk_path_update.replace("\\", "/")
        }
        try:
            self.template_keys_update(cmd_sdt_res_template, replacements, cmd_file)
        except Exception as e:
            print(f"Error creating CMD file: {e}")
            QMessageBox.critical(self, "Error", f"Error creating CMD file: {e}")
            return False

        ps_command = f'start "" powershell.exe -Command "& \'{cmd_file}\'"'
        output_file1 = os.path.join(settings.get("scenarioDir"), "households_1.csv").replace("\\", "/")
        output_file2 = os.path.join(settings.get("scenarioDir"), "persons_1.csv").replace("\\", "/")
        try:
            if os.path.exists(output_file1):
                os.remove(output_file1)
            if os.path.exists(output_file2):
                os.remove(output_file2)
        except Exception as e:
            print(f"Error removing old output files: {e}")
            QMessageBox.critical(self, "Error", f"Error removing old output files: {e}")
            return False

        try:
            result2 = subprocess.Popen(ps_command, shell=True)
            if hasattr(result2, "returncode") and result2.returncode is not None and result2.returncode != 0:
                print("SDT Resident Model run failed.")
                QMessageBox.critical(self, "Error", "SDT Resident Model run failed.")
                return False
        except Exception as e:
            print(f"SDT Resident Model run failed: {e}")
            QMessageBox.critical(self, "Error", f"SDT Resident Model run failed: {e}")
            return False

        # Check for files
        try:
            check_exe = os.path.join(settings.get("plugin_dir"), "templates", "wait_for_files.exe").replace("\\", "/")
            print(f"wait for files: {check_exe}")
            print(f"Checking for files: {output_file1}, {output_file2}")
            watcher = subprocess.Popen([check_exe, "180", "18000", output_file1, output_file2])
            return_code = watcher.wait()
            if return_code == 0:
                print(f"SDT Resident Model run successful: {watcher.pid}")
                if show_message:
                    QMessageBox.information(self, "Success", "SDT Resident Model run successful. \n\nPlease check the output files in the selected directory.")
                return True
            else:
                print(f"SDT-Res file watcher process failed: {return_code}")
                QMessageBox.critical(self, "Error", "Watcher process failed.")
                return False
        except Exception as e:
           print(f"Error SDT-Res file watcher process: {e}")
           return False
        # Check if the output files exist


    def cancel_action(self):
        print("Action canceled. Closing dialog.")
        self.reject()  # Closes the dialog without executing any code

    def select_file(self, line_edit, type):
        if type == "open":
            file_path, _ = QFileDialog.getOpenFileName(self, "Select File",  "", "csv (*.csv) ;; skim (*.omx);; All Files (*)") 
        elif type == "save":
            file_path, _ = QFileDialog.getSaveFileName(self, "Select File",  "", "csv (*.csv) ;; All Files (*)")
        if file_path:
            line_edit.setText(file_path)

    def select_directory(self, line_edit):
        directory = QFileDialog.getExistingDirectory(self, "Select Directory", )
        if directory:
            line_edit.setText(directory)

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
    
    def get_layer_path(self, layer):
        """Retrieve the data source path of a layer."""
        if layer:
            provider = layer.dataProvider()
            return provider.dataSourceUri().split("|")[0]  # Remove extra filter params
        return None
    
