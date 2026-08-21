import os, re
import subprocess
from qgis.PyQt.QtWidgets import QDialog, QFileDialog, QDockWidget, QMessageBox
from qgis.core import QgsProject, QgsVectorLayer
from qgis.PyQt import uic  # For loading .ui dynamically
from .tsm_settings import Config
from .model_run import run_gated_model, begin_run_console, closes_run_console
# from .helper_functions import HelperFun 

import processing

from .Subarea_Assignment_ui import Ui_DialogSubAssign

class Subarea_AssignDialog(QDialog, Ui_DialogSubAssign):
    def __init__(self):
        super().__init__()
        # self.setupUi(self)

        # Verify the UI file path
        # plugin_dir = os.path.dirname(__file__).replace("\\", "/")
        settings = Config()
        plugin_dir = settings.get("plugin_dir")
        ui_file = os.path.join(plugin_dir, "ui/Subarea_Assignment.ui")
        print(f"UI file found at: {ui_file}")

        # Check if the UI file exists
        if not os.path.exists(ui_file):
            print(f"UI file not found at: {ui_file}")
            return  # If the file doesn't exist, stop further execution

        # Load the UI dynamically if the file exists
        uic.loadUi(ui_file, self)  # This will automatically load the UI and set it up

        # Populate the dropdowns with available land-use layers (polygons)
        self.populate_layer_combobox(self.comboBox_linkLayer, "LineString")
        self.populate_layer_combobox(self.comboBox_nodeLayer, "Point")
 
        # Update Settings ("Main Panel -> Load Settings -> Config()")
        # settings = Config()

        # Load Subarea Assigment settings
        if settings.get("sub_link_layer_name") != "":
            sub_link_layer_name = settings.get("sub_link_layer_name")
            if sub_link_layer_name in [self.comboBox_linkLayer.itemText(i) for i in range(self.comboBox_linkLayer.count())]:
                self.comboBox_linkLayer.setCurrentText(sub_link_layer_name)
        if settings.get("sub_node_layer_name") != "":
            sub_node_layer_name = settings.get("sub_node_layer_name")
            if sub_node_layer_name in [self.comboBox_nodeLayer.itemText(i) for i in range(self.comboBox_nodeLayer.count())]:
                self.comboBox_nodeLayer.setCurrentText(sub_node_layer_name)
        if settings.get("sub_triptable_file"):
            self.lineEdit_triptable.setText(settings.get("sub_triptable_file"))
        if settings.get("sub_volume_file"):
            self.lineEdit_volume.setText(settings.get("sub_volume_file"))
        if settings.get("sub_max_iterations"):
            self.lineEdit_literations.setText(settings.get("sub_max_iterations"))
        
        # Load Select Link Analysis settings
        if settings.get("runSelectLinkAnalysis"):
            self.groupBox_SL.setChecked(settings.get("runSelectLinkAnalysis"))
            if settings.get("SL_AB1"):
                self.lineEdit_SL_AB1.setText(settings.get("SL_AB1"))
            if settings.get("SL_AB2"):
                self.lineEdit_SL_AB2.setText(settings.get("SL_AB2"))
            if settings.get("SLOuputDir"):
                self.lineEdit_SLOuputDir.setText(settings.get("SLOuputDir"))
        else:
            settings.set("runSelectLinkAnalysis", False)

        # Load Select Link Trip Table settings
        if settings.get("runSelectLinkTT"):
            self.groupBox_SL_TT.setChecked(settings.get("runSelectLinkTT"))
            if settings.get("SL_TT_AB1"):
                self.lineEdit_SL_TT_AB1.setText(settings.get("SL_TT_AB1"))
            if settings.get("SL_TT_AB2"):
                self.lineEdit_SL_TT_AB2.setText(settings.get("SL_TT_AB2"))
            if settings.get("OutSL_TT"):
                self.lineEdit_OutSL_TT.setText(settings.get("OutSL_TT"))
        else:
            settings.set("runSelectLinkTT", False)

        # Load Toll Choice settings
        if settings.get("runEnrouteTollChoice"):
            self.groupBox_TollChoice.setChecked(settings.get("runEnrouteTollChoice"))
            if settings.get("TollSegDef"):
                self.lineEdit_TollSegDef.setText(settings.get("TollSegDef"))
            if settings.get("TollSegConst"):
                self.lineEdit_TollSegConst.setText(settings.get("TollSegConst"))
            # if settings.get("Subarea_TT_out"):
            #     self.lineEdit_OutSubareaTT.setText(settings.get("Subarea_TT_out"))
        else:
            settings.set("runEnrouteTollChoice", False)

        # Load ODME settings
        if settings.get("runODME"):
            self.groupBox_ODME.setChecked(settings.get("runODME"))
            if settings.get("ODMECounts"):
                self.lineEdit_ODMECounts.setText(settings.get("ODMECounts"))
            if settings.get("ODMETT"):
                self.lineEdit_ODMETT.setText(settings.get("ODMETT"))
            if settings.get("ODME_Corrections"):
                self.lineEdit_ODME_Corrections.setText(settings.get("ODME_Corrections"))
            # if settings.get("ODME_VOL"):
            #     self.lineEdit_ODME_VOL.setText(settings.get("ODME_VOL"))
        else:
            settings.set("runODME", False)

        # Load Apply ODME Settings
        if settings.get("runApplyODME"):
            self.groupBox_ODME_Apply.setChecked(settings.get("runApplyODME"))
            if settings.get("ODME_Corrections_2"):
                self.lineEdit_ODME_IN_Correction_2.setText(settings.get("ODME_Corrections_2"))
            if settings.get("ODME_FUT_TT"):
                self.lineEdit_ODMETT_FUT_2.setText(settings.get("ODME_FUT_TT"))
            if settings.get("NodeReplacementFile"):
                self.lineEdit_NodeReplacements.setText(settings.get("NodeReplacementFile"))
        else:
            settings.set("runApplyODME", False)

        # Load Turn Movement settings
        if settings.get("runTurnMove"):
            self.groupBox_TurnMove.setChecked(settings.get("runTurnMove"))
            if settings.get("TurnMove_NodeList"):
                self.lineEdit_TurnMove_NodeList.setText(settings.get("TurnMove_NodeList"))
            if settings.get("TurnMove_OutDir"):
                self.lineEdit_TurnMove_OutDir.setText(settings.get("TurnMove_OutDir"))
        else:
            settings.set("runTurnMove", False)

        # Connect buttons to browse function
        self.browse_TripTable.clicked.connect(lambda: self.select_file(self.lineEdit_triptable, "open"))
        self.browse_volume.clicked.connect(lambda: self.select_file(self.lineEdit_volume, "save"))
 
        self.browse_selectLinkOut.clicked.connect(lambda: self.select_directory(self.lineEdit_SLOuputDir))

        self.browse_OutSL_TT.clicked.connect(lambda: self.select_directory(self.lineEdit_OutSL_TT))

        self.browse_TollSegDef.clicked.connect(lambda: self.select_file(self.lineEdit_TollSegDef, "open"))
        self.browse_TollSegConst.clicked.connect(lambda: self.select_file(self.lineEdit_TollSegConst, "open"))
        
        self.pushButton_GenTargets.clicked.connect(lambda:self.generate_count_targets())
        self.browse_ODMECounts.clicked.connect(lambda: self.select_file(self.lineEdit_ODMECounts, "open"))
        self.browse_ODMETT.clicked.connect(lambda: self.select_file(self.lineEdit_ODMETT, "save"))
        # self.browse_ODME_VOL.clicked.connect(lambda: self.select_file(self.lineEdit_ODME_VOL, "save"))

        self.pushButton_GenCorrections.clicked.connect(lambda:self.generate_count_corrections())
        self.browse_ODMETT_Corrections.clicked.connect(lambda: self.select_file(self.lineEdit_ODME_Corrections, "save")) #self.lineEdit_ODME_Corrections.text()) #self.lineEdit_ODME_Corrections.text()) #
        
    
        self.browse_ODME_IN_Corrections_2.clicked.connect(lambda: self.select_file(self.lineEdit_ODME_IN_Correction_2, "open"))
        self.browse_ODMETT_FUT_2.clicked.connect(lambda: self.select_file(self.lineEdit_ODMETT_FUT_2, "save"))
        self.browse_NodeReplacements.clicked.connect(lambda: self.select_file(self.lineEdit_NodeReplacements, "open"))

        self.browse_TurnMove_NodeList.clicked.connect(lambda: self.select_file(self.lineEdit_TurnMove_NodeList, "open"))
        self.browse_outputDir_TurnMove.clicked.connect(lambda: self.select_file(self.lineEdit_TurnMove_OutDir, "save"))

        # Connect the "save" button to the corresponding function
        self.saveAssign_settings.accepted.connect(self.update_settings)
        self.saveAssign_settings.rejected.connect(self.cancel_action)
        
        # lambda, not a direct connect: run_subarea_assignment is wrapped by
        # @closes_run_console, whose _wrap(*args, **kwargs) accepts anything, so
        # PyQt does not truncate clicked's bool and forwards it -- giving
        # "takes 1 positional argument but 2 were given". Every other dialog
        # already connects its run button through a lambda for this reason.
        self.runAssignment.clicked.connect(lambda: self.run_subarea_assignment())

        # Connect the checkbox state change to the function
        self.groupBox_SL.clicked.connect(self.update_SelectLink_state)
        self.groupBox_SL_TT.clicked.connect(self.update_SelectLink_TT_state)
        self.groupBox_TollChoice.clicked.connect(self.update_TollChoice_state)
        self.groupBox_ODME.clicked.connect(self.update_ODME_state)
        self.groupBox_ODME_Apply.clicked.connect(self.update_ODMEApply_state)
        self.groupBox_TurnMove.clicked.connect(self.update_TurnMove_state)

        # Call once to initialize state correctly when the UI loads
        self.update_SelectLink_state()
        self.update_SelectLink_TT_state()
        self.update_TollChoice_state()
        self.update_ODME_state()
        self.update_ODMEApply_state()
        self.update_TurnMove_state()

    def cancel_action(self):
        """Handles the Cancel button."""
        print("Action canceled. Closing dialog.")
        self.reject()  # Closes the dialog without executing any code

    def select_file(self, line_edit, type):
        if type == "open":
            file_path, _ = QFileDialog.getOpenFileName(self, "Select File", "", "(*.csv);;All Files (*)")
        elif type == "save":
            file_path, _ = QFileDialog.getSaveFileName(self, "Select File", "", "(*.csv);;All Files (*)")
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
    

    def load_output_layer(self, file_path, layer_name):
        """Load the output GPKG file into QGIS."""
        if os.path.exists(file_path):
            layer = QgsVectorLayer(file_path, layer_name, "ogr")
            if layer.isValid():
                QgsProject.instance().addMapLayer(layer)
                print(f"Loaded {layer_name} successfully.")
            else:
                print(f"Failed to load {layer_name}.")
        else:
            print(f"File not found: {file_path}")


    def load_layer_symbology(self, qml_file, layer_name):        
        # Apply a QML Style for the opened layer
        if qml_file and os.path.exists(qml_file):
            layer = QgsProject.instance().mapLayersByName(layer_name)[0]
            layer.loadNamedStyle(qml_file)
            layer.triggerRepaint()
            print(f"Success Loaded output layer: {layer_name}")
        else:
            print(f"Error Unable to Layer Symbology to: {layer_name}")


    def generate_count_targets(self):
        """Generate count targets."""
        # Check if the file exists
        # if not os.path.exists(count_file):
        #     QMessageBox.critical(self, "Error", f"File {count_file} does not exist.")
        #     return
        settings = Config()
        # Check if the layer exists in the project
        sub_link_layer_name = settings.get("sub_link_layer_name")
        layer = QgsProject.instance().mapLayersByName(sub_link_layer_name)
        if not layer:
            QMessageBox.critical(self, "Error", f"Layer {sub_link_layer_name} does not exist in the project.")
            return

        # Export Link GPKG to Link.csv
        # sub_link_file = self.get_layer_path(sub_link_layer_name) + #"|layername=" + sub_link_layer_name
        sub_link_file = self.get_layer_path(self.comboBox_linkLayer.currentData())
        print("subarea link file:", sub_link_file)
        odme_exe = settings.app_exe("utilities/odme.exe")
        count_file = os.path.join(settings.get("scenarioDir"), "ODME_Counts.csv").replace("\\","/")
        settings.set("ODMECounts", count_file)
        settings.set("sub_link_file", sub_link_file)

        self.lineEdit_ODMECounts.setText(count_file)
        if not os.path.exists(odme_exe):
            QMessageBox.critical(self, "Error", f"odme.exe not found at: {odme_exe}")
            return
        try:
            # odme counts (C++ port of Generate_ODME_Counts.R): subarea link gpkg -> ODME target counts
            result = Config().run_app([odme_exe, "counts", sub_link_file, count_file],
                                      log_path=os.path.splitext(count_file)[0] + ".log", console=True)
            if result.returncode == 0:
                print("ODME Target Counts file generated successfully")
            else:
                print("ODME Target Counts file generation failed.")
        except Exception as e:
            print("Error running odme.exe:", e)

    def generate_count_corrections(self):
        settings = Config()
        odme_correct_file = settings.get("ODME_Corrections")
        base_tt_file = settings.get("sub_triptable_file")
        odme_tt_file = settings.get("ODMETT")
        odme_exe = settings.app_exe("utilities/odme.exe")
        if not os.path.exists(odme_exe):
            QMessageBox.critical(self, "Error", f"odme.exe not found at: {odme_exe}")
            return
        try:
            # odme develop (C++ port of Develop_ODME_Correction_factors.R)
            result = Config().run_app([odme_exe, "develop", base_tt_file, odme_tt_file, odme_correct_file],
                                      log_path=os.path.splitext(odme_correct_file)[0] + ".log", console=True)
            if result.returncode == 0:
                print("Successfully computed ODME correction factors")
                QMessageBox.information(self, "Success", "Successfully computed ODME correction factors.")
            else:
                print("computing ODME correction factors failed.")
                QMessageBox.critical(self, "Error", "Error computing ODME correction factors") 
        except Exception as e:
            print("Error generating ODME correction factors:", e)
            QMessageBox.critical(self, "Error", f"Error computing ODME correction factors: {e}") 
            self.close()

    def get_layer_path(self, layer):
        """Retrieve the data source path of a layer."""
        if layer:
            provider = layer.dataProvider()
            return provider.dataSourceUri().split("|")[0]  # Remove extra filter params
        return None
    
    def update_settings(self):
        settings = Config()
        if self.comboBox_linkLayer.currentData():
            sub_link_layer = self.comboBox_linkLayer.currentData()
            settings.set("sub_link_layer_name", sub_link_layer.name())  
        if self.comboBox_nodeLayer.currentData():
            sub_node_layer = self.comboBox_nodeLayer.currentData()
            settings.set("sub_node_layer_name", sub_node_layer.name())
        if self.lineEdit_triptable.text():
            settings.set("sub_triptable_file", self.lineEdit_triptable.text())
        if self.lineEdit_volume.text():
            settings.set("sub_volume_file", self.lineEdit_volume.text())
        if self.lineEdit_literations.text():
            settings.set("sub_max_iterations", self.lineEdit_literations.text())
        # Select Link Analysis settings
        if self.groupBox_SL.isChecked():
            settings.set("runSelectLinkAnalysis", self.groupBox_SL.isChecked())
            if self.lineEdit_SL_AB1.text():
                settings.set("SL_AB1", self.lineEdit_SL_AB1.text())
            if self.lineEdit_SL_AB2.text():
                settings.set("SL_AB2", self.lineEdit_SL_AB2.text())
            if self.lineEdit_SLOuputDir.text():
                settings.set("SLOuputDir", self.lineEdit_SLOuputDir.text())
        else:
            settings.set("runSelectLinkAnalysis", False)  
            settings.set("SL_AB1", "")
            settings.set("SL_AB2", "")
            settings.set("SLOuputDir", "")

        # Select Link Trip Table settings
        if self.groupBox_SL_TT.isChecked():
            settings.set("runSelectLinkTT", self.groupBox_SL_TT.isChecked())
            if self.lineEdit_SL_AB1.text():
                settings.set("SL_TT_AB1", self.lineEdit_SL_TT_AB1.text())
            if self.lineEdit_SL_AB2.text():
                settings.set("SL_TT_AB2", self.lineEdit_SL_TT_AB2.text())
            if self.lineEdit_OutSL_TT.text():
                settings.set("OutSL_TT", self.lineEdit_OutSL_TT.text())
        else:
            settings.set("runSelectLinkTT", False)
            settings.set("SL_TT_AB1", "")
            settings.set("SL_TT_AB2", "")
            settings.set("OutSL_TT", "")

        # Toll Choice settings
        if self.groupBox_TollChoice.isChecked():
            settings.set("runEnrouteTollChoice", self.groupBox_TollChoice.isChecked())
            if self.lineEdit_TollSegDef.text():
                settings.set("TollSegDef", self.lineEdit_TollSegDef.text())
            if self.lineEdit_TollSegConst.text():
                settings.set("TollSegConst", self.lineEdit_TollSegConst.text())
        else:
            settings.set("runEnrouteTollChoice", False)
            settings.set("TollSegDef", "")
            settings.set("TollSegConst", "")

        # ODME settings 
        if self.groupBox_ODME.isChecked():
            settings.set("runODME", self.groupBox_ODME.isChecked())
            if self.lineEdit_ODMECounts.text():
                settings.set("ODMECounts", self.lineEdit_ODMECounts.text())
            if self.lineEdit_ODMETT.text():
                settings.set("ODMETT", self.lineEdit_ODMETT.text())
            # if self.lineEdit_ODME_VOL.text():
            #     settings.set("ODME_VOL", self.lineEdit_ODME_VOL.text())
            if self.lineEdit_ODME_Corrections.text():
                settings.set("ODME_Corrections", self.lineEdit_ODME_Corrections.text())
        else:
            settings.set("runODME", False)
        
        if self.groupBox_ODME_Apply.isChecked():
            settings.set("runApplyODME", self.groupBox_ODME_Apply.isChecked())
            if self.lineEdit_ODME_IN_Correction_2.text():
                settings.set("ODME_Corrections_2", self.lineEdit_ODME_IN_Correction_2.text())
            if self.lineEdit_ODMETT_FUT_2.text():
                settings.set("ODME_FUT_TT", self.lineEdit_ODMETT_FUT_2.text())
            if self.lineEdit_NodeReplacements.text():
                settings.set("NodeReplacementFile", self.lineEdit_NodeReplacements.text())
        else:
            settings.set("runApplyODME", False)

        # Turn Movement settings
        if self.groupBox_TurnMove.isChecked():
            settings.set("runTurnMove", self.groupBox_TurnMove.isChecked())
            if self.lineEdit_TurnMove_NodeList.text():
                settings.set("TurnMove_NodeList", self.lineEdit_TurnMove_NodeList.text())
            if self.lineEdit_TurnMove_OutDir.text():
                settings.set("TurnMove_OutDir", self.lineEdit_TurnMove_OutDir.text())
        # self.close()
        settings.check_and_save_to_file("scenario_settings_file")
        QMessageBox.information(self, "Settings Updated", "Project Specific settings have been updated.")
           
    def generate_controls_from_template(self, search_key, replace_key, template_path, output_path):
        with open(template_path, 'r') as f:
            template = f.read()

        # Escape backslashes in case user uses raw strings without r""
        replace_key = os.path.normpath(replace_key)

        # Replace {tsm_loc} in the template
        # filled = template.replace("{tsm_loc}", tsm_loc)
        filled = template.replace(search_key, replace_key)
        
        with open(output_path, 'w') as f:
            f.write(filled)
        print(f"Batch file created: {output_path}")

    # Read input file
    def update_controls_by_selection (self, template_file, template_out_file, update_keys, exclude_keys):
        with open(template_file, 'r') as file:
            lines = file.readlines()

        updated_lines = []
        for line in lines:
            # Use regex to split the line by multiple spaces (at least two spaces)
            parts = re.split(r'\s{2,}', line.strip())
            
            if len(parts) >= 2:
                key, value = parts[0], parts[1]
                
                # Skip keys that need to be removed
                if key in exclude_keys:
                    continue

                # Update key's value if in updates dict else add 
                if key in update_keys:
                    value = update_keys[key]
                # else:
                #     updated_lines.append(line)

                # Reconstruct line (using fixed 31-space padding)
                updated_line = f"{key:<31}{value}\n"
                updated_lines.append(updated_line)
            else:
                # Keep lines unchanged (if they don't match key-value pattern)
                updated_lines.append(line)

        # Write updated content back to a new file
        with open(template_out_file, 'w') as file:
            file.writelines(updated_lines)

        print("File updated successfully.")

    def export_GPKG_to_csv(self, gpkg_file, csv_file):
        # Define the input QPKG layer path and the output CSV file path
        # qpkg_path =  gpkg_file + '|layername=' + layer_name

        # Run QGIS algorithm to export attribute table to CSV directly
        processing.run("native:savefeatures", {
            'INPUT': gpkg_file,
            'OUTPUT': csv_file,
            'LAYER_OPTIONS': '',
            'DATASOURCE_OPTIONS': '',
            'SAVE_STYLES': False,
            'SAVE_METADATA': False,
            'SAVE_STYLES_METADATA': False
        })

    @closes_run_console
    def run_subarea_assignment(self):        
        settings = Config()
        if not settings.get("sub_link_layer_name") or not settings.get("sub_node_layer_name"):
            QMessageBox.critical(self, "Error", "Please select both Link and Node layers.")
            return
        if not settings.get("sub_triptable_file") or not settings.get("sub_volume_file"):
            QMessageBox.critical(self, "Error", "Please select both Trip Table and Volume files.")
            return
        
        # create control file from the template
        plugin_dir = settings.get("plugin_dir")
        tsm_location = settings.get("tsm_location")
        scenario_dir = settings.get("scenarioDir")
        # One live-tail window for the whole Subarea run (no per-step black windows).
        begin_run_console(os.path.join(scenario_dir, "Subarea.log"), "Subarea Assignment - run log")
        eltod_template = os.path.join(plugin_dir, "templates", "ELToD_template.ctl")
        etlod_temp_scenario = os.path.join(scenario_dir, "ELToD_temp.ctl")
        eltod_scenario = os.path.join(scenario_dir, "ELToD.ctl")
        
        print("Scenario directory:", scenario_dir)
        print("TSM location:", tsm_location)
        # if tsm_location == "":
        #     QMessageBox.info(self, "Information", "TSM location defaults to C:/TSM_NextGen_v5")
        #     tsm_location = settings.get("C:/TSM_NextGen_v5")

        self.generate_controls_from_template("{tsm_loc}", tsm_location, eltod_template, etlod_temp_scenario)
        self.generate_controls_from_template("{scenario_loc}", scenario_dir, etlod_temp_scenario, etlod_temp_scenario)
        # ELToD EL parameter files (toll/turn/closer) ship with the plugin, not under
        # tsm_location/Parameters: {config_loc} -> plugin_dir/config/eltod_el_parameters.
        eltod_param_dir = os.path.join(plugin_dir, "config", "eltod_el_parameters")
        self.generate_controls_from_template("{config_loc}", eltod_param_dir, etlod_temp_scenario, etlod_temp_scenario)

        # Export Link GPKG to Link.csv
        sub_link_file = self.get_layer_path(self.comboBox_linkLayer.currentData()) + "|layername=" + settings.get("sub_link_layer_name")
        print("subarea link file", sub_link_file)
        sub_link_csv_file = os.path.join(scenario_dir, "Subarea_LINK.csv").replace("/","\\")
        settings.set("sub_link_csv_file", sub_link_csv_file)
        # self.export_GPKG_to_csv(link_file, link_csv_file) # Built-in option is slow
        
        # Export Node GPKG to Node.csv
        sub_node_file = self.get_layer_path(self.comboBox_nodeLayer.currentData()) + "|layername=" + settings.get("sub_node_layer_name")
        print("subarea node file", sub_node_file)
        sub_node_csv_file = os.path.join(scenario_dir, "Subarea_NODE.csv").replace("/","\\")
        settings.set("sub_node_csv_file", sub_node_csv_file)
        # self.export_GPKG_to_csv(node_file, node_csv_file)  # Built-in option is slow

        # ""
        # Export the link/node GeoPackages to CSV with gpkgcsv.exe (C++ port of
        # the old Rscripts/gpkg_to_csv.R). For the subarea LINK the working node
        # ids live in Sub_A/Sub_B, so drop A/B and rename Sub_A/Sub_B -> A/B.
        gpkgcsv_exe = settings.app_exe("utilities/gpkgcsv.exe")
        if not os.path.exists(gpkgcsv_exe):
            QMessageBox.critical(self, "Error", f"gpkgcsv.exe not found at: {gpkgcsv_exe}")
            self.close()
            return

         # STEP 1: Generate PopSyn input files
        try:
            convert_log = os.path.join(scenario_dir, "Subarea_convert.log")
            result1 = settings.run_app([gpkgcsv_exe, "to-csv", self.get_layer_path(self.comboBox_linkLayer.currentData()), os.path.join(scenario_dir, "Subarea_LINK.csv"),
                                      "--drop-geom", "--drop", "A", "--drop", "B", "--rename", "Sub_A=A", "--rename", "Sub_B=B"],
                                     log_path=convert_log, console=True)
            result2 = settings.run_app([gpkgcsv_exe, "to-csv", self.get_layer_path(self.comboBox_nodeLayer.currentData()), os.path.join(scenario_dir, "Subarea_NODE.csv"),
                                      "--drop-geom"], log_path=convert_log, console=True, append=True)
            if result1.returncode == 0 and result2.returncode == 0:  # Check if the conversion ran successfully
                    print("Link and node file are exported to csv")
            else:
                print("Link or node file are failed to export to csv.")
        except Exception as e:
            print("Error running PopSyn:", e)
            QMessageBox.critical(self, "Error", f"Error exporting GPKG to CSV format in STEP 1: {e}")
            self.close()
        
        # Run a subprocess to call R and convert network to Link or Node file (note user can update the file in GGIS and so export attrabuties)
        # keys to remove
        conditional_keys = ['SELECT_LINKS', 'NEW_SELECT_LINK_FILE', 'NEW_SELECT_LINK_FORMAT',                  
                            'SELECT_LINKS_1', 'NEW_SELECT_LINK_FILE_1', 'NEW_SELECT_LINK_FORMAT_1',                
                            'SELECT_LINKS_2', 'NEW_SELECT_LINK_FILE_2',  'NEW_SELECT_LINK_FORMAT_2',                
                            'NEW_SELECT_TRIP_FILE', 'NEW_SELECT_TRIP_FORMAT',
                            "NEW_SELECT_TRIP_FILE_1", "NEW_SELECT_TRIP_FORMAT_1",
                            "NEW_SELECT_TRIP_FILE_2", "NEW_SELECT_TRIP_FORMAT_2",
                            'COUNT_FILE', 'COUNT_FORMAT','MAXIMUM_PERCENT_CHANGE', 'TRIP_UPDATE_RATE', 'STORE_TRIPS_IN_MEMORY', 
                            'NEW_TRIP_FILE', 'NEW_TRIP_FORMAT', 'DUMP_COUNT_STATUS',
                            'SUBAREA_LINK_MAP_FILE', 'NEW_SUBAREA_FILE', 'NEW_SUBAREA_FORMAT', 'MAXIMUM_SUBAREA_ZONE',
                            'SELECT_TURN_NODE_FILE', 'SELECT_TURN_PERIODS', 'SELECT_TURN_INCREMENT', 'SAVE_ALL_VOLUME_RECORDS', 
                            'NEW_TURN_MOVEMENT_FILE', 'NEW_TURN_MOVEMENT_FORMAT']

        # Keys to replace
        update_keys = {
                    'LINK_FILE'      : settings.get("sub_link_csv_file").replace("/", "\\"),     # link_csv_name                 
                    'NODE_FILE'      : settings.get("sub_node_csv_file").replace("/", "\\"),     # node_csv_name
                    'TRIP_FILE'      : settings.get("sub_triptable_file").replace("/", "\\") ,          
                    'NEW_VOLUME_FILE': settings.get("sub_volume_file").replace("/", "\\"),
                    'MAXIMUM_ITERATIONS' : settings.get("sub_max_iterations"),
                    'NUMBER_OF_THREADS' : settings.get("num_processors")
                  }
        
        # Remove all conditional keys if none of the selections are checked
        keys_to_remove = conditional_keys

        # runSelectLinkAnalysis, SL_TT_AB2, runSelectLinkTT, runSubExtTT, runTurnMove
        if settings.get("runSelectLinkAnalysis"): #and not settings.get("runSelectLinkTT") and not settings.get("runSubExtTT") and not settings.get("runTurnMove"):
            if not settings.get("SL_AB2"): 
                update_keys["SELECT_LINKS"] = settings.get("SL_AB1")
                update_keys["NEW_SELECT_LINK_FILE"] = os.path.join(settings.get("SLOuputDir"), "Select_Link_Volume.csv").replace("/", "\\")
                update_keys["NEW_SELECT_LINK_FORMAT"] = "COMMA_DELIMITED"
                keys_to_remove = list(set(keys_to_remove) - set(["SELECT_LINKS", "NEW_SELECT_LINK_FILE", "NEW_SELECT_LINK_FORMAT"]))
            if settings.get("SL_AB2"):
                update_keys["SELECT_LINKS_1"] = settings.get("SL_AB1")
                update_keys["NEW_SELECT_LINK_FILE_1"] = os.path.join(settings.get("SLOuputDir"), "Select_Link_1_Volume.csv").replace("/", "\\")
                update_keys["NEW_SELECT_LINK_FORMAT_1"] = "COMMA_DELIMITED"
                update_keys["SELECT_LINKS_2"] = settings.get("SL_AB2")
                update_keys["NEW_SELECT_LINK_FILE_2"] = os.path.join(settings.get("SLOuputDir"), "Select_Link_2_Volume.csv").replace("/", "\\")
                update_keys["NEW_SELECT_LINK_FORMAT_2"] = "COMMA_DELIMITED"
                keys_to_remove = list(set(keys_to_remove) - set(["SELECT_LINKS_1", "NEW_SELECT_LINK_FILE_1", "NEW_SELECT_LINK_FORMAT_1", 
                                                     "SELECT_LINKS_2", "NEW_SELECT_LINK_FILE_2", "NEW_SELECT_LINK_FORMAT_2"]))

        # Select trip tables (only if other selections are set to false)
        if settings.get("runSelectLinkTT"): #and not settings.get("runSelectLinkAnalysis") and not settings.get("runSubExtTT") and not settings.get("runTurnMove"):
            if not settings.get("SL_TT_AB2"): 
                update_keys["SELECT_LINKS"] = settings.get("SL_TT_AB1")
                update_keys["NEW_SELECT_TRIP_FILE"] = os.path.join(settings.get("OutSL_TT"), "Select_Link_TripTable.csv").replace("/", "\\")
                update_keys["NEW_SELECT_TRIP_FORMAT"] = "COMMA_DELIMITED"
                keys_to_remove = list(set(keys_to_remove) - set(["SELECT_LINKS", "NEW_SELECT_TRIP_FILE", "NEW_SELECT_TRIP_FORMAT"]))
            if settings.get("SL_TT_AB2"):  
                update_keys["SELECT_LINKS_1"] = settings.get("SL_TT_AB1")
                update_keys["NEW_SELECT_TRIP_FILE_1"] = os.path.join(settings.get("OutSL_TT"), "Select_Link_TripTable_1.csv").replace("/", "\\")
                print(update_keys["NEW_SELECT_TRIP_FILE_1"])
                update_keys["NEW_SELECT_TRIP_FORMAT_1"] = "COMMA_DELIMITED"
                update_keys["SELECT_LINKS_2"] = settings.get("SL_TT_AB2")
                update_keys["NEW_SELECT_TRIP_FILE_2"] = os.path.join(settings.get("OutSL_TT"), "Select_Link_TripTable_2.csv").replace("/", "\\")
                update_keys["NEW_SELECT_TRIP_FORMAT_2"] = "COMMA_DELIMITED"
                keys_to_remove = list(set(keys_to_remove) - set(["SELECT_LINKS_1", "NEW_SELECT_TRIP_FILE_1", "NEW_SELECT_TRIP_FORMAT_1",
                                                    "SELECT_LINKS_2", "NEW_SELECT_TRIP_FILE_2", "NEW_SELECT_TRIP_FORMAT_2"]))
                print("keys_to_remove", keys_to_remove)
        
        # Subarea trip table extraction (only if other selections are set to false)
        if settings.get("runODME"):  
           update_keys["COUNT_FILE"] = settings.get("ODMECounts").replace("/", "\\")
           update_keys["COUNT_FORMAT"] = "COMMA_DELIMITED"
           update_keys["MAXIMUM_PERCENT_CHANGE"] = 0 # settings.get("ODME_maxPercentChange")
           update_keys["TRIP_UPDATE_RATE"] = 5 # settings.get("ODME_tripUpdateRate")
           update_keys["STORE_TRIPS_IN_MEMORY"] = "TRUE" # settings.get("ODME_storeTripsInMemory")
           update_keys["NEW_TRIP_FILE"] = settings.get("ODMETT").replace("/", "\\")
           update_keys["NEW_TRIP_FORMAT"] = "COMMA_DELIMITED"
           update_keys["DUMP_COUNT_STATUS"] = "TRUE" # settings.get("ODME_dumpCountStatus")
          
           keys_to_remove = list(set(keys_to_remove) - set(["COUNT_FILE", "COUNT_FORMAT", "MAXIMUM_PERCENT_CHANGE", "TRIP_UPDATE_RATE",
                                                              "STORE_TRIPS_IN_MEMORY", "NEW_TRIP_FILE", "NEW_TRIP_FORMAT", "DUMP_COUNT_STATUS"]))

        # Turning Movement list (only if other selections are set to false)
        if settings.get("runTurnMove"): #and not settings.get("runSelectLinkAnalysis") and not settings.get("runSelectLinkTT") and not settings.get("runSubExtTT"):
           update_keys["SELECT_TURN_NODE_FILE"] = settings.get("TurnMove_NodeList").replace("/", "\\")
           update_keys["SELECT_TURN_PERIODS"] = '1:00..25:00'
           update_keys["SELECT_TURN_INCREMENT"] = '60 minutes'
           update_keys["SAVE_ALL_VOLUME_RECORDS"] = 'TRUE'
           update_keys["NEW_TURN_MOVEMENT_FILE"] = settings.get("TurnMove_OutDir").replace("/", "\\")
           update_keys["NEW_TURN_MOVEMENT_FORMAT"] = "COMMA_DELIMITED"     
           keys_to_remove = list(set(keys_to_remove) - set(["SELECT_TURN_NODE_FILE", "SELECT_TURN_PERIODS", "SELECT_TURN_INCREMENT",
                                                              "SAVE_ALL_VOLUME_RECORDS", "NEW_TURN_MOVEMENT_FILE", "NEW_TURN_MOVEMENT_FORMAT"]))

        if settings.get("runApplyODME"): 
            update_keys["TRIP_FILE"] = settings.get("ODME_FUT_TT").replace("/", "\\")
            keys_to_remove = list(set(keys_to_remove))
            
            # compute future ODME trip table file
            odme_corr_fac = settings.get("ODME_Corrections_2")
            fut_odme_file = settings.get("ODME_FUT_TT")
            fut_sub_file = settings.get("sub_triptable_file")
            node_replacement_file = settings.get("NodeReplacementFile")

            # odme apply (C++ port of Apply_ODME_Correction_factors.R). Node
            # replacement is optional -- pass it only when the file exists.
            odme_exe = settings.app_exe("utilities/odme.exe")
            apply_args = [odme_exe, "apply", fut_sub_file, fut_odme_file, odme_corr_fac]
            if node_replacement_file and os.path.exists(node_replacement_file):
                apply_args.append(node_replacement_file)
            result1 = settings.run_app(apply_args, log_path=os.path.join(scenario_dir, "ODME_apply.log"), console=True)
            if( result1.returncode == 0):
                print("Successfully applied ODME correction factors")
            else:
                print("Applying ODME correction factors failed.")
        
        # Update the control file based on user selections
        print("update_keys", update_keys)
        print("keys_to_remove", keys_to_remove)
        self.update_controls_by_selection(etlod_temp_scenario, eltod_scenario, update_keys, keys_to_remove)
        os.remove(etlod_temp_scenario)

        # Run ELToD  (shipped under the plugin's Apps/ELToD; was tsm_location/Apps)
        eltod_exe_path = Config().app_exe("ELToD/ELToD.exe")
        
        # Run ELToD via the shared gated runner (captures output; reports
        # token/offline/model errors in a message box instead of the console).
        if not run_gated_model(self, [eltod_exe_path, eltod_scenario], "ELToD assignment",
                               log_path=os.path.join(scenario_dir, "ELToD.log"), console=True):
            return
        print("Subarea Assignment ran successfully")

        # ====================================================================================
        # Loaded network -- C++ summarize.exe (port of Summarise_Loaded_Volumes.R)
        from .summarize_runner import run_summary

        sub_link_layer_path = self.get_layer_path(self.comboBox_linkLayer.currentData())
        sub_volume_file = settings.get("sub_volume_file")
        sub_loadedOut_file = settings.get("sub_volume_file").replace(".csv", ".gpkg")

        print("sub_link_layer_path:", sub_link_layer_path)
        print("sub_volume_file:", sub_volume_file)
        print("sub_loadedOut_file:", sub_loadedOut_file)

        try:
            result4 = run_summary("summarize_loaded.toml", sub_link_layer_path, sub_volume_file, sub_loadedOut_file, subarea=True)
            print("result4.returncode", result4.returncode)
            if result4.returncode == 0:  # Check if the R script ran successfully
                print("loaded network volumes script ran successfully.")
                if not settings.get("subarea_name"):
                    subarea_name = ""
                else:
                    subarea_name = settings.get("subarea_name")
                
                self.load_output_layer(sub_loadedOut_file, subarea_name + "_Loaded")
                if not settings.get("link_qml_file"):
                    link_qml_file = os.path.join(plugin_dir, "qgis_styles/Subarea_Link_Symbology.qml").replace("\\","/")
                else:
                    link_qml_file = settings.get("link_qml_file")
                self.load_layer_symbology(link_qml_file, subarea_name + "_Loaded")
                # QMessageBox.information(self, "Success", "Loaded network volumes script ran successfully.")

                if settings.get("runSelectLinkAnalysis"):
                    if not settings.get("SL_AB2"):
                        sl_vol_file = os.path.join(settings.get("SLOuputDir"), "Select_Link_Volume.csv")
                        sl_loadedOut_file = os.path.join(settings.get("SLOuputDir"), "Select_Link_Volume.gpkg")
                        run_summary("summarize_selectlink.toml", sub_link_layer_path, sl_vol_file, sl_loadedOut_file, subarea=True, include_speed_ff=False)
                    else:
                        sl_vol_file_1 = os.path.join(settings.get("SLOuputDir"), "Select_Link_1_Volume.csv")
                        sl_vol_file_2 = os.path.join(settings.get("SLOuputDir"), "Select_Link_2_Volume.csv")
                        sl_loadedOut_file = os.path.join(settings.get("SLOuputDir"), "Select_Link_Volume.gpkg")
                        run_summary("summarize_selectlink2.toml", sub_link_layer_path, sl_vol_file_1, sl_loadedOut_file, subarea=True, vol2=sl_vol_file_2, include_speed_ff=False)
                
                QMessageBox.information(self, "Success", "Subarea Assignment ran successfully.")

            else:
                print("error running loaded networks or validation.")
        except Exception as e:
            print("Error running loaded networks or validation:", e)
            QMessageBox.critical(self, "Error", f"Error running summary script: {e}") 
            self.close()

    
    def update_SelectLink_state(self):
        # Update the variable to reflect the checkbox state
        settings = Config()
        self.bool_run_SL = self.groupBox_SL.isChecked()
        print("bool_run_SL:", self.bool_run_SL)
        if self.bool_run_SL:
            # Enable related UI components and set up interactions
            self.browse_selectLinkOut.setEnabled(True)

            # Disconnect any previous connections to avoid duplicates
            try:
                self.browse_selectLinkOut.clicked.disconnect()
                settings.set("SL_AB1", "")
                settings.set("SL_AB2", "")
            except TypeError:
                pass  # If nothing is connected, ignore error
            # Connect file selection function
            self.browse_selectLinkOut.clicked.connect(lambda: self.select_directory(self.lineEdit_SLOuputDir))
            settings.set("SLOuputDir", self.lineEdit_SLOuputDir.text())
            settings.set("SL_AB1", self.lineEdit_SL_AB1.text())
            settings.set("SL_AB2", self.lineEdit_SL_AB2.text())
        else:
            # Disable buttons if checkbox is unchecked
            self.browse_selectLinkOut.setEnabled(False)

    def update_SelectLink_TT_state(self):
        # Update the variable to reflect the checkbox state
        settings = Config()
        self.bool_run_SL_TT = self.groupBox_SL_TT.isChecked()
        print("bool_run_SL_TT:", self.bool_run_SL_TT)
        if self.bool_run_SL_TT:
            # Enable related UI components and set up interactions
            self.browse_OutSL_TT.setEnabled(True)

            # Disconnect any previous connections to avoid duplicates
            try:
                self.browse_OutSL_TT.clicked.disconnect()
                settings.set("SL_TT_AB1", "")
                settings.set("SL_TT_AB2", "")
            except TypeError:
                pass  # If nothing is connected, ignore error
            # Connect file selection function
            self.browse_OutSL_TT.clicked.connect(lambda: self.select_directory(self.lineEdit_OutSL_TT))
            settings.set("OutSL_TT", self.lineEdit_OutSL_TT.text())
            settings.set("SL_TT_AB1", self.lineEdit_SL_TT_AB1.text())
            settings.set("SL_TT_AB2", self.lineEdit_SL_TT_AB2.text())
        else:
            # Disable buttons if checkbox is unchecked
            self.browse_OutSL_TT.setEnabled(False)
    
    def update_TollChoice_state(self):
        # Update the variable to reflect the checkbox state
        settings = Config()
        self.bool_run_TollChoice = self.groupBox_TollChoice.isChecked()
        print("bool_run_TollChoice:", self.bool_run_TollChoice)
        if self.bool_run_TollChoice:
            # Enable related UI components and set up interactions
            self.browse_TollSegDef.setEnabled(True)
            self.browse_TollSegConst.setEnabled(True)

            # Disconnect any previous connections to avoid duplicates
            try:
                self.browse_TollSegDef.clicked.disconnect()
                self.browse_TollSegConst.clicked.disconnect()
                settings.set("TollSegDef", "")
                settings.set("TollSegConst", "")
            except TypeError:
                pass
            # Connect file selection function
            self.browse_TollSegDef.clicked.connect(lambda: self.select_file(self.lineEdit_TollSegDef, "open"))
            self.browse_TollSegConst.clicked.connect(lambda: self.select_file(self.lineEdit_TollSegConst, "open"))
        else:
            # Disable buttons if checkbox is unchecked
            self.browse_TollSegDef.setEnabled(False)
            self.browse_TollSegConst.setEnabled(False)

    def update_ODME_state(self):
        # Update the variable to reflect the checkbox state
        settings = Config()
        self.bool_run_ODME = self.groupBox_ODME.isChecked()
        print("bool_run_ODME:", self.bool_run_ODME)
        if self.bool_run_ODME:
            # Enable related UI components and set up interactions
            self.browse_ODMECounts.setEnabled(True)
            self.browse_ODMETT.setEnabled(True)
            self.browse_ODMETT_Corrections.setEnabled(True)
            # Disconnect any previous connections to avoid duplicates
            try:
                self.browse_ODMECounts.clicked.disconnect()
                self.browse_ODMETT.clicked.disconnect()
                self.browse_ODMETT_Corrections.clicked.disconnect()
                settings.set("ODMECounts", "")
                settings.set("ODMETT", "")
                settings.set("ODME_Corrections", "")
            except TypeError:
                pass
            # Connect file selection function
            self.browse_ODMECounts.clicked.connect(lambda: self.select_file(self.lineEdit_ODMECounts, "open"))
            self.browse_ODMETT.clicked.connect(lambda: self.select_file(self.lineEdit_ODMETT, "save"))
            self.browse_ODMETT_Corrections.clicked.connect(lambda: self.select_file(self.lineEdit_ODME_Corrections, "save"))
            settings.set("ODMECounts", self.lineEdit_ODMECounts.text())
            settings.set("ODMETT", self.lineEdit_ODMETT.text())
            settings.set("ODME_Corrections", self.lineEdit_ODME_Corrections.text())
        else:   
            # Disable buttons if checkbox is unchecked
            self.browse_ODMECounts.setEnabled(False)
            self.browse_ODMETT.setEnabled(False)
            self.browse_ODMETT_Corrections.setEnabled(False)
            # Disconnect any previous connections to avoid duplicates

    def update_ODMEApply_state(self):
        # Update the variable to reflect the checkbox state
        settings = Config()
        self.bool_run_ODMEApply = self.groupBox_ODME_Apply.isChecked()
        print("bool_run_ODMEApply:", self.bool_run_ODMEApply)
        if self.bool_run_ODMEApply:
            # Enable related UI components and set up interactions
            self.browse_ODME_IN_Corrections_2.setEnabled(True)
            self.browse_ODMETT_FUT_2.setEnabled(True)

            # Disconnect any previous connections to avoid duplicates
            try:
                self.browse_ODME_IN_Corrections_2.clicked.disconnect()
                self.browse_ODMETT_FUT_2.clicked.disconnect()
                self.browse_NodeReplacements.clicked.disconnect()
                settings.set("ODME_Corrections", "")
                settings.set("ODME_FUT_TT", "")
                settings.set("NodeReplacementFile", "")
            except TypeError:
                pass   
            # Connect file selection function
            self.browse_ODME_IN_Corrections_2.clicked.connect(lambda: self.select_file(self.lineEdit_ODME_IN_Correction_2, "open"))
            self.browse_ODMETT_FUT_2.clicked.connect(lambda: self.select_file(self.lineEdit_ODMETT_FUT_2, "save"))
            self.browse_NodeReplacements.clicked.connect(lambda: self.select_file(self.lineEdit_NodeReplacements, "open"))
            settings.set("NodeReplacementFile", self.lineEdit_NodeReplacements.text())
            settings.set("ODME_Corrections", self.lineEdit_ODME_IN_Correction_2.text())
            settings.set("ODME_FUT_TT", self.lineEdit_ODMETT_FUT_2.text())

        else:
            # Disable buttons if checkbox is unchecked
            self.browse_ODME_IN_Corrections_2.setEnabled(False)
            self.browse_ODMETT_FUT_2.setEnabled(False)
            # self.browse_NodeReplacements.setEnabled(False)
            # Disconnect any previous connections to avoid duplicates


    def update_TurnMove_state(self):
        # Update the variable to reflect the checkbox state
        settings = Config()
        self.bool_run_TurnMove = self.groupBox_TurnMove.isChecked()
        print("bool_run_TurnMove:", self.bool_run_TurnMove)
        if self.bool_run_TurnMove:
            # Enable related UI components and set up interactions
            self.browse_TurnMove_NodeList.setEnabled(True)
            self.browse_outputDir_TurnMove.setEnabled(True)

            # Disconnect any previous connections to avoid duplicates
            try:
                self.browse_TurnMove_NodeList.clicked.disconnect()
                self.browse_outputDir_TurnMove.clicked.disconnect()
                settings.set("TurnMove_NodeList", "")
                settings.set("TurnMove_OutDir", "")
            except TypeError:
                pass  # If nothing is connected, ignore error
            # Connect file selection function
            self.browse_TurnMove_NodeList.clicked.connect(lambda: self.select_file(self.lineEdit_TurnMove_NodeList, "open"))
            self.browse_outputDir_TurnMove.clicked.connect(lambda: self.select_file(self.lineEdit_TurnMove_OutDir, "save"))
            settings.set("TurnMove_NodeList", self.lineEdit_TurnMove_NodeList.text())
            settings.set("TurnMove_OutDir", self.lineEdit_TurnMove_OutDir.text())
        else:
            # Disable buttons if checkbox is unchecked
            self.browse_TurnMove_NodeList.setEnabled(False)
            self.browse_outputDir_TurnMove.setEnabled(False)

           