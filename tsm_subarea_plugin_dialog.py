import os
import subprocess
from PyQt5.QtWidgets import QDialog, QFileDialog, QMessageBox
from qgis.core import QgsProject, QgsVectorLayer

from qgis import processing
from PyQt5 import uic  # For loading .ui dynamically

from .tsm_subarea_extractor_ui import Ui_Dialog
from .tsm_settings import Config

class TsmSubareaExtDialogX(QDialog, Ui_Dialog):
    def __init__(self):
        print("Initializing TsmSubareaExtDialog") 
        super().__init__()
        # self.setupUi(self)
        
       # Determine UI file based on tool_name
         # Verify the UI file path
        plugin_dir = os.path.dirname(__file__).replace("\\", "/")
        ui_file = os.path.join(plugin_dir, "ui/tsm_subarea_extractor.ui")
        print(f"UI file found at: {ui_file}")

        # Check if the UI file exists
        if not os.path.exists(ui_file):
            print(f"UI file not found at: {ui_file}")
            return  # If the file doesn't exist, stop further execution

        # Load the UI dynamically if the file exists
        uic.loadUi(ui_file, self)  # This will automatically load the UI and set it up
        
        print("UI Setup Complete")  # This should now print if the UI is loaded successfully

        # Populate the dropdowns with available layers
        self.populate_layer_combobox(self.lineLayerCombo, "LineString")
        self.populate_layer_combobox(self.nodeLayerCombo, "Point")
        self.populate_layer_combobox(self.subareaLayerCombo, "Polygon")
 
        # Connect buttons to browse function
        self.browse_Outdir.clicked.connect(self.select_directory)
        self.browse_SaveSettings.clicked.connect(lambda: self.select_file(self.lineEdit_SettingsFile, "save"))
        self.browse_SaveCW.clicked.connect(lambda: self.select_file(self.lineEdit_SaveCW, "save"))
        self.browse_OpenCW.clicked.connect(lambda: self.select_file(self.lineEdit_OpenCW, "open"))

        # Run the script when the "Run" button is clicked
        self.pushButton_Run.clicked.connect(self.run_r_script)
        self.buttonBox_Save.accepted.connect(self.update_settings)
        self.buttonBox_Save.rejected.connect(self.cancel_action)
        print("Buttons connected.")

        # Load settings from the config file
        settings = Config()
        plugin_dir = settings.get("plugin_dir")

        # # Load settings into the UI
        if settings.get("subarea_name"):
            self.lineEdit_SubareaName.setText(settings.get("subarea_name"))
        if settings.get("settings_file"):
            self.lineEdit_SettingsFile.setText(settings.get("settings_file"))
        if settings.get("subarea_output_dir"):
            self.output_directory.setText(settings.get("subarea_output_dir"))
        if settings.get("readCW_file"):
            self.lineEdit_OpenCW.setText(settings.get("readCW_file"))
        if settings.get("saveCW_file") != "":
            self.lineEdit_SaveCW.setText(settings.get("saveCW_file"))
        # if settings.get("bool_selectSubBoundary") != "":
        #     self.checkBox_SelectSubarea.setChecked(settings.get("bool_selectSubBoundary"))
        if settings.get("bool_ReadNodeCW") :
            self.checkBox_ReadNodeCW.setChecked(settings.get("bool_ReadNodeCW"))
        if settings.get("bool_SaveNodeCW"):
            self.checkBox_SaveNodeCW.setChecked(settings.get("bool_SaveNodeCW"))
        if settings.get("link_layer_name"):
            link_layer_name = settings.get("link_layer_name")
            if link_layer_name in [self.lineLayerCombo.itemText(i) for i in range(self.lineLayerCombo.count())]:
                    self.lineLayerCombo.setCurrentText(link_layer_name)
        if settings.get("node_layer_name"):
            node_layer_name = settings.get("node_layer_name")
            if node_layer_name in [self.nodeLayerCombo.itemText(i) for i in range(self.nodeLayerCombo.count())]:
                    self.nodeLayerCombo.setCurrentText(node_layer_name)
        if settings.get("subarea_boundary_layer"):
            boundary_layer_name = settings.get("subarea_boundary_layer")
            if boundary_layer_name in [self.subareaLayerCombo.itemText(i) for i in range(self.subareaLayerCombo.count())]:
                    self.subareaLayerCombo.setCurrentText(boundary_layer_name)

    def cancel_action(self):
        """Handles the Cancel button."""
        print("Action canceled. Closing dialog.")
        self.reject()  # Closes the dialog without executing any code

    def select_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Directory")
        if directory:
            self.output_directory.setText(directory)

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

    def select_file(self, line_edit, type):
        if type == "open":
            file_path, _ = QFileDialog.getOpenFileName(self, "Select File", "", "csv (*.csv);;All Files (*)")
        elif type == "save":
            file_path, _ = QFileDialog.getSaveFileName(self, "Select File", "", "csv (*.csv);;All Files (*)")
        if file_path:
            line_edit.setText(file_path)

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

    # First select links and extract subarea link file
    def selectSubareaLinks(self, link_layer, polygon_layer, output_file, bool_selectPolygon):
        # Remove existing file and layer
        subarea_name = self.lineEdit_SubareaName.text()
        subarea_layers =  [subarea_name + "_Links", subarea_name + "_Nodes"]
        for sub_layer in subarea_layers:
            # existing_layers = QgsProject.instance().mapLayersByName("Subarea_Link")
            existing_layers = QgsProject.instance().mapLayersByName(sub_layer)
            for layer in existing_layers:
                QgsProject.instance().removeMapLayer(layer)
            # delete file if exists
            if os.path.exists(output_file):
                os.remove(output_file)
        
        # if bool_selectPolygon : 
        #     # Filter polygon layer to use only selected features
        #     selected_features = polygon_layer.selectedFeatures()
        #     polygon_subset = QgsVectorLayer(polygon_layer.source(), "Selected Polygons", "ogr")
        #     polygon_subset.setSubsetString("fid IN ({})".format(
        #         ",".join(str(f.id()) for f in selected_features)))
        #     polygon_layer_to_use = polygon_subset
        # else:
            polygon_layer_to_use = polygon_layer

        # Run selection process
        processing.run("native:selectbylocation", {
            'INPUT': link_layer,
            'PREDICATE': [6,7],  # Intersects
            'INTERSECT': polygon_layer_to_use,
            'METHOD': 0
        })

        # Save selected features
        processing.run("native:saveselectedfeatures", {
            'INPUT': link_layer,
            'OUTPUT': output_file
        })
        print(f"Subarea links saved to {output_file}")
        # Deselect selected features
        link_layer.selectByIds([])


    def update_settings(self):
        """Update settings based on the current UI values."""
        settings = Config()
        settings.set("subarea_name", self.lineEdit_SubareaName.text())
        settings.set("settings_file", self.lineEdit_SettingsFile.text())
        settings.set("subarea_output_dir", self.output_directory.text())
        settings.set("readCW_file", self.lineEdit_OpenCW.text())
        settings.set("saveCW_file", self.lineEdit_SaveCW.text())
        # settings.set("bool_selectSubBoundary", self.checkBox_SelectSubarea.isChecked())
        settings.set("bool_ReadNodeCW", self.checkBox_ReadNodeCW.isChecked())
        settings.set("bool_SaveNodeCW", self.checkBox_SaveNodeCW.isChecked())

        link_path = self.get_layer_path(self.lineLayerCombo.currentData())
        node_path = self.get_layer_path(self.nodeLayerCombo.currentData())
        poly_path = self.get_layer_path(self.subareaLayerCombo.currentData())

        settings.set("link_path", link_path)
        settings.set("node_path", node_path)

        settings.set("link_layer_name",os.path.splitext(os.path.basename(link_path))[0])
        settings.set("node_layer_name",  os.path.splitext(os.path.basename(node_path))[0])
        settings.set("subarea_boundary_layer", os.path.splitext(os.path.basename(poly_path))[0])

        output_dir = self.output_directory.text().strip()
        subarea_name = self.lineEdit_SubareaName.text()
        plugin_dir = settings.get("plugin_dir")
        settings.set("subarea_linkfile", os.path.join(output_dir, subarea_name, "Subarea_Link.GPKG").replace("\\","/"))
        settings.set("subarea_nodefile", os.path.join(output_dir, subarea_name, "Subarea_Link.GPKG").replace("\\","/"))

        settings.set("link_qml_file",  os.path.join(plugin_dir, "qgis_styles/Subarea_Link_Symbology.qml").replace("\\","/"))
        settings.set("node_qml_file",  os.path.join(plugin_dir, "qgis_styles/Subarea_Node_Symbology.qml").replace("\\","/"))
        settings.check_and_save_to_file("scenario_settings_file")
        QMessageBox.information(self, "Settings Updated", "Project Specific settings have been updated.")
           

    def run_r_script(self):
        """Write selected layer paths to a settings file and run the R script."""

        # In another class, access the settings:
        settings = Config()
        subarea_name = settings.get("subarea_name")

        # Get file paths from the UI
        subarea_name = self.lineEdit_SubareaName.text()
        settings_file = self.lineEdit_SettingsFile.text()
        output_dir = self.output_directory.text().strip()
        readCW_file = self.lineEdit_OpenCW.text()
        saveCW_file = self.lineEdit_SaveCW.text()

        if settings_file in ['settings.txt', '']:
            settings_file =  os.path.join(output_dir, settings_file).replace("\\","/")

        # Get checkbox values
        # bool_SubNet = self.checkBox_SubareaNet.isChecked()
        # bool_SubTT = self.checkBox_ExtractSubTT.isChecked()
        bool_selectSubBoundary = "False"
        bool_ReadNodeCW = self.checkBox_ReadNodeCW.isChecked()
        bool_SaveNodeCW = self.checkBox_SaveNodeCW.isChecked()

        # if(bool_SubNet):
        self.label_Input_Linelayer.setText('TSM Link File')
        self.label_Input_Nodelayer.setText('TSM Node File')
        # else:
        #     self.label_Input_Linelayer.setText('Subarea Link File')
        #     self.label_Input_Linelayer.setText('Subarea Link File')

        # Get selected layers
        link_layer = self.lineLayerCombo.currentData()
        node_layer = self.nodeLayerCombo.currentData()
        polygon_layer = self.subareaLayerCombo.currentData()

        # Validate inputs
        if not (link_layer and node_layer and polygon_layer):
            print("Please select link, node and subarea files")
            return False

        # Get full file paths
        link_path = self.get_layer_path(link_layer)
        node_path = self.get_layer_path(node_layer)
        poly_path = self.get_layer_path(polygon_layer)

        if not link_path or not node_path or not poly_path:
            print("Could not retrieve file paths.")
            return False

        # Create Subarea directory if doesn't exist
        path = os.path.join(output_dir, subarea_name)

        try:
            os.mkdir(path)
            print(f"Directory '{path}' created successfully.")
        except FileExistsError:
            print(f"Directory '{path}' already exists.")
        except FileNotFoundError:
            print("Parent directory does not exist.")
            return False

        # Define output file paths (modify as needed)
        output_linkfile = os.path.join(output_dir, subarea_name, "Subarea_Link.GPKG").replace("\\","/")  # paste0(output_dir,paste0("/TSM_Link_",year ,".GPKG"))
        output_nodefile = os.path.join(output_dir, subarea_name, "Subarea_Node.GPKG").replace("\\","/")

        # Extract Subarea Network
        # if bool_SubNet:
        print([link_layer, polygon_layer, output_linkfile, bool_selectSubBoundary])
        result = self.selectSubareaLinks(link_layer, polygon_layer, output_linkfile, bool_selectSubBoundary)
        # try:
        #     result = self.selectSubareaLinks(link_layer, polygon_layer, output_linkfile, bool_selectSubBoundary)
        #     print("Error:", result.stderr)
        #     if result.returncode == 0:  # Check if selection ran ok
        #         print("Subarea links extracted successfully. Loading output layers...")
        #     else:
        #         print("Error in Subarea links extraction...")
        #         return False
        # except Exception as e:
        #         print("Error in selecting subarea links:", e)
        #         return False

        # Write settings to a text file
        # script_path = "C:/TSM_NextGen_v5/Base/TSMv5_2023/validation"
        # plugin_dir = os.path.dirname(__file__).replace("\\","/")
        # settings = Config()
        plugin_dir = settings.get("plugin_dir")
        # subarea.exe replaces Renumber_Subarea_Nodes.R (reads the same settings file).
        subarea_exe = settings.app_exe("utilities/subarea.exe")
        if not os.path.exists(subarea_exe):
            QMessageBox.critical(self, "Error", f"Utility not found: {subarea_exe}")
            return False

        link_qml_file = os.path.join(plugin_dir, "qgis_styles/Subarea_Link_Symbology.qml").replace("\\","/")
        node_qml_file = os.path.join(plugin_dir, "qgis_styles/Subarea_Node_Symbology.qml").replace("\\","/")

        # Call the R script with the settings file
        # r_exe = "C:/Program Files/R/R-4.3.2/bin/Rscript.exe"

        # For global access:
        config = Config()
        config.set("subarea_name", self.lineEdit_SubareaName.text())
        config.set("settings_file", self.lineEdit_SettingsFile.text())
        config.set("subarea_output_dir", self.output_directory.text())
        config.set("readCW_file", self.lineEdit_OpenCW.text())
        config.set("saveCW_file", self.lineEdit_SaveCW.text())

        config.set("bool_ReadNodeCW", self.checkBox_ReadNodeCW.isChecked())
        config.set("bool_SaveNodeCW", self.checkBox_SaveNodeCW.isChecked())

        config.set("link_path", link_path)
        config.set("node_path", node_path)

        config.set("link_layer_name",os.path.splitext(os.path.basename(link_path))[0])
        config.set("node_layer_name",  os.path.splitext(os.path.basename(node_path))[0])
        config.set("subarea_boundary_layer", os.path.splitext(os.path.basename(poly_path))[0])

        config.set("subarea_linkfile", os.path.join(output_dir, subarea_name, "Subarea_Link.GPKG").replace("\\","/"))
        config.set("subarea_nodefile", os.path.join(output_dir, subarea_name, "Subarea_Link.GPKG").replace("\\","/"))

        config.set("link_qml_file",  os.path.join(plugin_dir, "qgis_styles/Subarea_Link_Symbology.qml").replace("\\","/"))
        config.set("node_qml_file",  os.path.join(plugin_dir, "qgis_styles/Subarea_Node_Symbology.qml").replace("\\","/"))

        with open(settings_file, "w") as f:
            # f.write(f"{link_path}\n{node_path}\n{output1}\n{output2}\n")
            f.write(f"subarea_name = {subarea_name}\n")       
            f.write(f"link_layer = {link_path}\n")
            f.write(f"node_layer = {node_path}\n")

            f.write(f"output_dir = {output_dir}\n")

            f.write(f"output_linkfile = {output_linkfile}\n")
            f.write(f"output_nodefile = {output_nodefile}\n")

            f.write(f"Settings_File = {settings_file}\n") 

            f.write(f"check_readCW = {bool_ReadNodeCW}\n") 
            f.write(f"readCW_file = {readCW_file}\n") 
            
            f.write(f"check_saveCW = {bool_SaveNodeCW}\n")
            f.write(f"saveCW_file = {saveCW_file}\n") 

            f.write(f"plugin_dir = {plugin_dir}\n")

        try:
            result = subprocess.run([subarea_exe, "renumber", settings_file]) #capture_output=True, text=True)
            print("Output:", result.stdout)
            print("Error:", result.stderr)

            # If the script was successful, load the output layers
            if result.returncode == 0:  # Check if the R script ran successfully
                print("R script executed successfully. Loading output layers...")
                # if bool_LoadOutputs:
                self.load_output_layer(output_linkfile, subarea_name + "_Links")
                self.load_layer_symbology(link_qml_file, subarea_name + "_Links")

                self.load_output_layer(output_nodefile, subarea_name + "_Nodes")
                self.load_layer_symbology(node_qml_file, subarea_name + "_Nodes")
                QMessageBox.information(self, "Subarea Extracted", "Output layers loaded.")
                return True
            else:
                print("R script execution failed.")

        except Exception as e:
            print("Error running R script:", e)
            QMessageBox.information(self, "Subarea Extracted", "R script executed successfully. Output layers loaded.")
            return False
