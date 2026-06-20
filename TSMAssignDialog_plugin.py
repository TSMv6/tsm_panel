import os, re
import subprocess
from PyQt5.QtWidgets import QDialog, QFileDialog, QDockWidget, QMessageBox
from qgis.core import QgsProject, QgsVectorLayer
from PyQt5 import uic  # For loading .ui dynamically
from .tsm_settings import Config
# from .helper_functions import HelperFun 

import processing

from .TSM_Assignment_ui import Ui_DialogTSMAssign

class TSMAssignDialog(QDialog, Ui_DialogTSMAssign):
    def __init__(self):
        super().__init__()
        # self.setupUi(self)

        # Verify the UI file path
        # plugin_dir = os.path.dirname(__file__).replace("\\", "/")
        settings = Config()
        plugin_dir = settings.get("plugin_dir")
        ui_file = os.path.join(plugin_dir, "ui/TSM_Assignment.ui")
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
        settings = Config()

        # Load Standard TSM Assigment settings
        if settings.get("link_layer_name") != "":
            link_layer_name = settings.get("link_layer_name")
            if link_layer_name in [self.comboBox_linkLayer.itemText(i) for i in range(self.comboBox_linkLayer.count())]:
                self.comboBox_linkLayer.setCurrentText(link_layer_name)
        if settings.get("node_layer_name") != "":
            node_layer_name = settings.get("node_layer_name")
            if node_layer_name in [self.comboBox_nodeLayer.itemText(i) for i in range(self.comboBox_nodeLayer.count())]:
                self.comboBox_nodeLayer.setCurrentText(node_layer_name)
        if settings.get("triptable_file"):
            self.lineEdit_triptable.setText(settings.get("triptable_file"))
        if settings.get("volume_file"):
            self.lineEdit_volume.setText(settings.get("volume_file"))
        if settings.get("max_iterations"):
            self.lineEdit_literations.setText(settings.get("max_iterations"))
        
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
            if settings.get("SL_AB1"):
                self.lineEdit_SL_TT_AB1.setText(settings.get("SL_TT_AB1"))
            if settings.get("SL_AB2"):
                self.lineEdit_SL_TT_AB2.setText(settings.get("SL_TT_AB2"))
            if settings.get("OutSL_TT"):
                self.lineEdit_OutSL_TT.setText(settings.get("OutSL_TT"))
        else:
            settings.set("runSelectLinkTT", False)

        # Load Subarea Extraction settings
        if settings.get("runSubExtTT"):
            self.groupBox_SubExt_TT.setChecked(settings.get("runSubExtTT"))
            if settings.get("Subarea_boundaryList"):
                self.lineEdit_boundaryList.setText(settings.get("Subarea_boundaryList"))
            if settings.get("Subarea_maxZones"):
                self.lineEdit_Sub_maxZones.setText(str(settings.get("Subarea_maxZones")))
            if settings.get("Subarea_TT_out"):
                self.lineEdit_OutSubareaTT.setText(settings.get("Subarea_TT_out"))
        else:
            settings.set("runSubExtTT", False)

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
        # max_iterations = self.lineEdit_Sub_maxZones.text()

        self.browse_selectLinkOut.clicked.connect(lambda: self.select_directory(self.lineEdit_SLOuputDir))

        self.browse_outputDir.clicked.connect(lambda: self.select_directory(self.lineEdit_OutSL_TT))

        self.browse_boundaryList.clicked.connect(lambda: self.select_file(self.lineEdit_boundaryList, "open"))
        self.browse_getSubZones.clicked.connect(lambda:self.get_max_subarea_zones(self.lineEdit_boundaryList.text()))
        self.browse_output_SubTT.clicked.connect(lambda: self.select_file(self.lineEdit_OutSubareaTT, "save"))
        
        self.browse_TurnMove_NodeList.clicked.connect(lambda: self.select_file(self.lineEdit_TurnMove_NodeList, "open"))
        self.browse_outputDir_TurnMove.clicked.connect(lambda: self.select_file(self.lineEdit_TurnMove_OutDir, "save"))

        # Example usage:
        # max_number = get_max_from_csv('data.csv')
        # print(max_number)
      
        # settings.set("SLOuputDir", self.lineEdit_OutSL_TT.text())
        # settings.set("OutSL_TT", self.lineEdit_OutSL_TT.text())     

        # settings.set("runSubExtTT", self.groupBox_SubExt_TT.isChecked())
        
        # self.populate_layer_combobox(self.comboBox_linkLayer, "LineString")
        # self.populate_layer_combobox(self.comboBox_nodeLayer, "Point")
        
        # Connect the "save" button to the corresponding function
        self.saveAssign_settings.accepted.connect(self.update_settings)
        self.saveAssign_settings.rejected.connect(self.cancel_action)
        
        self.runAssignment.clicked.connect(lambda: self.run_TSM_assignment(show_message=True))

        # Connect the checkbox state change to the function
        self.groupBox_SL.clicked.connect(self.update_SelectLink_state)
        self.groupBox_SL_TT.clicked.connect(self.update_SelectLink_TT_state)
        self.groupBox_SubExt_TT.clicked.connect(self.update_Subarea_state)
        self.groupBox_TurnMove.clicked.connect(self.update_TurnMove_state)

        # Call once to initialize state correctly when the UI loads
        self.update_SelectLink_state()
        self.update_SelectLink_TT_state()
        self.update_Subarea_state()
        self.update_TurnMove_state()

    def cancel_action(self):
        """Handles the Cancel button."""
        print("Action canceled. Closing dialog.")
        self.reject()  # Closes the dialog without executing any code

    def select_file(self, line_edit, type):
        if type == "open":
            file_path, _ = QFileDialog.getOpenFileName(self, "Select File", "", "triptable (*.csv);; linklist (*.csv);; nodelist (*.csv);; All Files (*)")
        elif type == "save":
            file_path, _ = QFileDialog.getSaveFileName(self, "Select File", "", "volume (*.csv);;  sub_triptable (*.csv);;  turn_moves (*.csv);; All Files (*)")
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
    
    def get_max_subarea_zones(self, csv_file):
        """
        Reads a CSV file using PyQGIS, finds the maximum number from columns NEWA and NEWB,
        returns the max number only if it is less than 11560.

        Parameters:
            csv_file (str): Path to the CSV file.

        Returns:
            float or None: The maximum number if less than 11560, otherwise None.
        """
        csv_file = csv_file.replace("\\", "/")  # Ensure forward slashes for file path
        # Check if the file exists
        if not os.path.exists(csv_file):
            print(f"File not found: {csv_file}")
            QDialog.critical(self, "Error", f"File not found: {csv_file}")
        print(csv_file, "exists")
        # Create a temporary layer from the CSV file
        uri = f"file:///{csv_file}?delimiter=,&geometryType=none"
        layer = QgsVectorLayer(uri, "temp_layer", "delimitedtext")
        print("layer:", layer)
        if not layer.isValid():
            raise ValueError("Invalid layer. Please check the CSV file path.")
        values = [int(f[col]) for f in layer.getFeatures() for col in ['NEW_A', 'NEW_B'] if int(f[col]) < 11560]
        # max_val = max(max(int(f[col]) for col in ['NEW_A', 'NEW_B']) for f in layer.getFeatures())
        max_val = max(values) if values else None
        print("max_val:", max_val)
        if max_val is None:
            print("No valid values found in the specified columns.")
            QDialog.critical(self, "Error", "No valid values found in the specified columns.")
            return None
        else:
            print("Maximum value found:", max_val)
            settings = Config()
            settings.set("Subarea_maxZones", max_val)
            self.lineEdit_Sub_maxZones.setText(str(max_val))
        return 

    def update_settings(self):
        settings = Config()
        if self.comboBox_linkLayer.currentData():
            link_layer = self.comboBox_linkLayer.currentData()
            settings.set("link_layer_name", link_layer.name())  
        if self.comboBox_nodeLayer.currentData():
            node_layer = self.comboBox_nodeLayer.currentData()
            settings.set("node_layer_name", node_layer.name())
        if self.lineEdit_triptable.text():
            settings.set("triptable_file", self.lineEdit_triptable.text())
        if self.lineEdit_volume.text():
            settings.set("volume_file", self.lineEdit_volume.text())
        if self.lineEdit_literations.text():
            settings.set("max_iterations", self.lineEdit_literations.text())
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
        # Subarea Extraction settings
        if self.groupBox_SubExt_TT.isChecked():
            settings.set("runSubExtTT", self.groupBox_SubExt_TT.isChecked())
            if self.lineEdit_boundaryList.text():
                settings.set("Subarea_boundaryList", self.lineEdit_boundaryList.text())
            if self.lineEdit_Sub_maxZones.text():
                settings.set("Subarea_maxZones", self.lineEdit_Sub_maxZones.text())
            if self.lineEdit_OutSubareaTT.text():
                settings.set("Subarea_TT_out", self.lineEdit_OutSubareaTT.text())
        else:
            settings.set("runSubExtTT", False)
            settings.set("Subarea_boundaryList", "")
            settings.set("Subarea_maxZones", "")
            settings.set("Subarea_TT_out", "")
        # Turn Movement settings
        if self.groupBox_TurnMove.isChecked():
            settings.set("runTurnMove", self.groupBox_TurnMove.isChecked())
            if self.lineEdit_TurnMove_NodeList.text():
                settings.set("TurnMove_NodeList", self.lineEdit_TurnMove_NodeList.text())
            if self.lineEdit_TurnMove_OutDir.text():
                settings.set("TurnMove_OutDir", self.lineEdit_TurnMove_OutDir.text())
        else:
            settings.set("runTurnMove", False)
            settings.set("TurnMove_NodeList", "")
            settings.set("TurnMove_OutDir", "")
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

    def run_TSM_assignment(self, show_message=False):        
        settings = Config()
        if not settings.get("link_layer_name") or not settings.get("node_layer_name"):
            QMessageBox.critical(self, "Error", "Please select both Link and Node layers.")
            return
        if not settings.get("triptable_file") or not settings.get("volume_file"):
            QMessageBox.critical(self, "Error", "Please select both Trip Table and Volume files.")
            return
        
        # create control file from the template
        plugin_dir = settings.get("plugin_dir")
        tsm_location = settings.get("tsm_location")
        scenario_dir = settings.get("scenarioDir")
        eltod_template = os.path.join(plugin_dir, "templates", "ELToD_template.ctl")
        etlod_temp_scenario = os.path.join(scenario_dir, "ELToD_temp.ctl")
        etlod_scenario = os.path.join(scenario_dir, "ELToD.ctl")
        self.generate_controls_from_template("{tsm_loc}", tsm_location, eltod_template, etlod_temp_scenario)
        self.generate_controls_from_template("{scenario_loc}", scenario_dir, etlod_temp_scenario, etlod_temp_scenario)

        # Export Link GPKG to Link.csv
        link_file = self.get_layer_path(self.comboBox_linkLayer.currentData()) + "|layername=" + settings.get("link_layer_name")
        print("link_file", link_file)
        link_csv_file = os.path.join(scenario_dir, "LINK.csv").replace("/","\\")
        settings.set("link_csv_file", link_csv_file)
        # self.export_GPKG_to_csv(link_file, link_csv_file) # Built-in option is slow
        
        # Export Node GPKG to Node.csv
        node_file = self.get_layer_path(self.comboBox_nodeLayer.currentData()) + "|layername=" + settings.get("node_layer_name")
        print("node_file", node_file)
        node_csv_file = os.path.join(scenario_dir, "NODE.csv").replace("/","\\")
        settings.set("node_csv_file", node_csv_file)
        # self.export_GPKG_to_csv(node_file, node_csv_file)  # Built-in option is slow

        # ""
        # Export the link/node GeoPackages to CSV with gpkgcsv.exe (C++ port of
        # the old Rscripts/gpkg_to_csv.R) -- attributes only, no column renames.
        gpkgcsv_exe = settings.app_exe("utilities/gpkgcsv.exe")
        if not os.path.exists(gpkgcsv_exe):
            QMessageBox.critical(self, "Error", f"gpkgcsv.exe not found at: {gpkgcsv_exe}")
            self.close()
            return

         # STEP 1: Generate PopulationSIM input files
        try:
            result1 = subprocess.run([gpkgcsv_exe, "to-csv", self.get_layer_path(self.comboBox_linkLayer.currentData()), os.path.join(scenario_dir, "LINK.csv"), "--drop-geom"])
            result2 = subprocess.run([gpkgcsv_exe, "to-csv", self.get_layer_path(self.comboBox_nodeLayer.currentData()), os.path.join(scenario_dir, "NODE.csv"), "--drop-geom"])
            if result1.returncode == 0 and result2.returncode == 0:  # Check if the conversion ran successfully
                    print("Link and node file are exported to csv")
            else:
                print("Link or node file are failed to export to csv.")
        except Exception as e:
            print("Error running PopulationSIM:", e)
            QMessageBox.critical(self, "Error", f"Error exporting GPKG to CSV format in STEP 1: {e}")
            self.close()
        
        # Run a subprocess to call R and convert network to Link or Node file (note user can update the file in GGIS and so export attrabuties)
        # keys to remove
        conditional_keys = ['SELECT_LINKS', 'NEW_SELECT_LINK_FILE', 'NEW_SELECT_LINK_FORMAT',                  
                            'SELECT_LINKS_1', 'NEW_SELECT_LINK_FILE_1', 'NEW_SELECT_LINK_FORMAT_1',                
                            'SELECT_LINKS_2', 'NEW_SELECT_LINK_FILE_2',  'NEW_SELECT_LINK_FORMAT_2',                
                            'NEW_SELECT_TRIP_FILE', 'NEW_SELECT_TRIP_FORMAT',
                            'COUNT_FILE', 'COUNT_FORMAT','MAXIMUM_PERCENT_CHANGE', 'TRIP_UPDATE_RATE', 'STORE_TRIPS_IN_MEMORY', 
                            'NEW_TRIP_FILE', 'NEW_TRIP_FORMAT', 'DUMP_COUNT_STATUS',
                            'SUBAREA_LINK_MAP_FILE', 'NEW_SUBAREA_FILE', 'NEW_SUBAREA_FORMAT', 'MAXIMUM_SUBAREA_ZONE',
                            'SELECT_TURN_NODE_FILE', 'SELECT_TURN_PERIODS', 'SELECT_TURN_INCREMENT', 'SAVE_ALL_VOLUME_RECORDS', 
                            'NEW_TURN_MOVEMENT_FILE', 'NEW_TURN_MOVEMENT_FORMAT']

        # Keys to replace
        update_keys = {
                    'LINK_FILE'      : settings.get("link_csv_file").replace("/", "\\"),     # link_csv_name                 
                    'NODE_FILE'      : settings.get("node_csv_file").replace("/", "\\"),     # node_csv_name
                    'TRIP_FILE'      : settings.get("triptable_file").replace("/", "\\") ,          
                    'NEW_VOLUME_FILE': settings.get("volume_file").replace("/", "\\"),
                    'MAXIMUM_ITERATIONS' : settings.get("max_iterations"),
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
           update_keys["SELECT_LINKS"] = settings.get("SL_AB1")
           update_keys["NEW_SELECT_TRIP_FILE"] = os.path.join(settings.get("OutSL_TT"), "Select_Link_TripTable.csv").replace("/", "\\")
           update_keys["NEW_SELECT_TRIP_FORMAT"] = "COMMA_DELIMITED"
           keys_to_remove = list(set(keys_to_remove) - set(["SELECT_LINKS", "NEW_SELECT_TRIP_FILE", "NEW_SELECT_TRIP_FORMAT"]))

        # Subarea trip table extraction (only if other selections are set to false)
        if settings.get("runSubExtTT"):  #and not settings.get("runSelectLinkAnalysis") and not settings.get("runSelectLinkTT") and not settings.get("runTurnMove"):
           update_keys["SUBAREA_LINK_MAP_FILE"] = settings.get("Subarea_boundaryList").replace("/", "\\")
           update_keys["NEW_SUBAREA_FILE"] = settings.get("Subarea_TT_out").replace("/", "\\")
           update_keys["NEW_SUBAREA_FORMAT"] = "COMMA_DELIMITED"
           update_keys["MAXIMUM_SUBAREA_ZONE"] = settings.get("Subarea_maxZones")
           keys_to_remove = list(set(keys_to_remove) - set(["SUBAREA_LINK_MAP_FILE", "NEW_SUBAREA_FORMAT", 
                                                              "NEW_SUBAREA_FILE", "MAXIMUM_SUBAREA_ZONE"]))

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
           
        self.update_controls_by_selection(etlod_temp_scenario, etlod_scenario, update_keys, keys_to_remove)
        os.remove(etlod_temp_scenario)

        # Run ELToD 
        eltod_exe_path = os.path.join(tsm_location, "Apps", "ELToD", "ELToD5_14.exe") 
        etlod_scenario 

        try:
            result3 = subprocess.run([eltod_exe_path, etlod_scenario]) 
            if result3.returncode == 0:  # Check if the ELToD ran successfully
                    print("TSM Assignment ran successfully")
                    if show_message:
                        QMessageBox.information(self, "Success", "TSM Assignment ran successfully.")
                    return True
            else:
                print("TSM Assignment Failed to run.")
        except Exception as e:
            print("Error running TSM Assignment:", e)
            QMessageBox.critical(self, "Error", f"Error in TSM Assignment STEP 3: {e}") 
            return False
        
        # ====================================================================================
        # Loaded network -- C++ summarize.exe (port of Summarise_Loaded_Volumes.R)
        from summarize_runner import run_summary

        link_layer_path = self.get_layer_path(self.comboBox_linkLayer.currentData())
        volume_file = settings.get("volume_file")
        loadedOut_file = settings.get("volume_file").replace(".csv", ".gpkg")

        print("link_layer_path:", link_layer_path)
        print("volume_file:", volume_file)
        print("loadedOut_file:", loadedOut_file)
        loaded_qml_file = os.path.join(plugin_dir, "qgis_styles/TSM_Loaded_Symbology.qml").replace("\\","/")

        try:
            result4 = run_summary("summarize_loaded.toml", link_layer_path, volume_file, loadedOut_file, subarea=False)
      
            if result4.returncode == 0:  # Check if the R script ran successfully
                print("loaded network volumes script ran successfully.")
                # QMessageBox.information(self, "Success", "Loaded network volumes script ran successfully.")
                # if bool_LoadOutputs:
                self.load_output_layer(loadedOut_file, "LoadedNetwork")
                self.load_layer_symbology(loaded_qml_file, "LoadedNetwork")
                print("R script executed successfully. Loading output layers...")
                if settings.get("runSelectLinkAnalysis"):
                    if not settings.get("SL_AB2"):
                        sl_vol_file = os.path.join(settings.get("SLOuputDir"), "Select_Link_Volume.csv")
                        sl_loadedOut_file = os.path.join(settings.get("SLOuputDir"), "Select_Link_Volume.gpkg")
                        run_summary("summarize_selectlink.toml", link_layer_path, sl_vol_file, sl_loadedOut_file, subarea=False, include_speed_ff=False)
                    else:
                        sl_vol_file_1 = os.path.join(settings.get("SLOuputDir"), "Select_Link_1_Volume.csv")
                        sl_vol_file_2 = os.path.join(settings.get("SLOuputDir"), "Select_Link_2_Volume.csv")
                        sl_loadedOut_file = os.path.join(settings.get("SLOuputDir"), "Select_Link_Volume.gpkg")
                        run_summary("summarize_selectlink2.toml", link_layer_path, sl_vol_file_1, sl_loadedOut_file, subarea=False, vol2=sl_vol_file_2, include_speed_ff=False)
                return True
            else:
                print("error running loaded networks or validation.")
        except Exception as e:
            print("Error running loaded networks or validation:", e)
            QMessageBox.critical(self, "Error", f"Error running summary script: {e}") 
            return False
            # self.close()


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
            self.browse_outputDir.setEnabled(True)

            # Disconnect any previous connections to avoid duplicates
            try:
                self.browse_outputDir.clicked.disconnect()
                settings.set("SL_TT_AB1", "")
                settings.set("SL_TT_AB2", "")
            except TypeError:
                pass  # If nothing is connected, ignore error
            # Connect file selection function
            self.browse_outputDir.clicked.connect(lambda: self.select_directory(self.lineEdit_OutSL_TT))
            settings.set("OutSL_TT", self.lineEdit_OutSL_TT.text())
            settings.set("SL_TT_AB1", self.lineEdit_SL_TT_AB1.text())
            settings.set("SL_TT_AB2", self.lineEdit_SL_TT_AB2.text())
        else:
            # Disable buttons if checkbox is unchecked
            self.browse_outputDir.setEnabled(False)
    
    def update_Subarea_state(self):
        # Update the variable to reflect the checkbox state
        settings = Config()
        self.bool_run_SubExt = self.groupBox_SubExt_TT.isChecked()
        print("bool_run_SubExt:", self.bool_run_SubExt)
        if self.bool_run_SubExt:
            # Enable related UI components and set up interactions
            self.browse_boundaryList.setEnabled(True)

            # Disconnect any previous connections to avoid duplicates
            try:
                self.browse_boundaryList.clicked.disconnect()
                self.browse_output_SubTT.clicked.disconnect()
                settings.set("Subarea_boundaryList", "")
                settings.set("Subarea_maxZones", "")
            except TypeError:
                pass  # If nothing is connected, ignore error   
            # Connect file selection function
            self.browse_boundaryList.clicked.connect(lambda: self.select_file(self.lineEdit_boundaryList, "open"))
            self.browse_output_SubTT.clicked.connect(lambda: self.select_file(self.lineEdit_OutSubareaTT, "save"))
            settings.set("Subarea_boundaryList", self.lineEdit_boundaryList.text())
            settings.set("Subarea_maxZones", self.lineEdit_Sub_maxZones.text())
            settings.set("Subarea_TT_out", self.lineEdit_OutSubareaTT.text())
        else:
            # Disable buttons if checkbox is unchecked
            self.browse_boundaryList.setEnabled(False)
            # self.browse_output_SubTT.setEnabled(False)

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