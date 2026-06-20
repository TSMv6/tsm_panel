import os, re
import subprocess
from PyQt5.QtWidgets import QDialog, QFileDialog, QDockWidget, QMessageBox
from qgis.core import QgsProject, QgsVectorLayer
from PyQt5 import uic  # For loading .ui dynamically
from .tsm_settings import Config
# from .helper_functions import HelperFun 

import processing

from .summary_loadedNetwork_ui import Ui_QDailog_LoadedNetwork

class Summary_Dialog(QDialog, Ui_QDailog_LoadedNetwork):
    def __init__(self):
        super().__init__()
        # self.setupUi(self)

        settings = Config()
        plugin_dir = settings.get("plugin_dir")
        ui_file = os.path.join(plugin_dir, "ui/summary_loadedNetwork.ui")
        print(f"UI file found at: {ui_file}")

        # Check if the UI file exists
        if not os.path.exists(ui_file):
            print(f"UI file not found at: {ui_file}")
            return  # If the file doesn't exist, stop further execution

        # Load the UI dynamically if the file exists
        uic.loadUi(ui_file, self)  # This will automatically load the UI and set it up

        # Populate the dropdowns with available land-use layers (polygons)
        self.populate_layer_combobox(self.comboBox_linkLayer, "LineString")

        # Update Settings ("Main Panel -> Load Settings -> Config()")
        settings = Config()

        # Load Standard TSM Assigment settings
        if settings.get("link_layer_name") != "":
            link_layer_name = settings.get("link_layer_name")
            if link_layer_name in [self.comboBox_linkLayer.itemText(i) for i in range(self.comboBox_linkLayer.count())]:
                self.comboBox_linkLayer.setCurrentText(link_layer_name)
        if settings.get("volume_file"):
            self.lineEdit_volume.setText(settings.get("volume_file"))
        if settings.get("loadedOut_file"):
            self.lineEdit_loadedOut.setText(settings.get("loadedOut_file"))
        if settings.get("isSubareaLevel"):
            self.checkBox_isSubarea.setChecked(settings.get("isSubareaLevel"))
        if settings.get("validationStats_file"):
            self.lineEdit_validationStats.setText(settings.get("validationStats_file"))
        if settings.get("validationStats"):
            self.checkBox_ValidationStats.setChecked(settings.get("validationStats"))
        
        self.browse_volume.clicked.connect(lambda: self.select_file(self.lineEdit_volume, "open"))
        self.browse_loadedOut.clicked.connect(lambda: self.select_file(self.lineEdit_loadedOut, "save"))
        self.checkBox_isSubarea.stateChanged.connect(self.toggle_TSM_or_subarea)

        self.browse_ValidationStats.clicked.connect(lambda: self.select_file_xlsx(self.lineEdit_validationStats, "save"))
        self.browse_ValidationStats.setEnabled(False)
        self.checkBox_ValidationStats.stateChanged.connect(self.toggle_validation_stats)

        self.buttonBox_OkCancel.accepted.disconnect()  # Disconnect the default behavior
        self.buttonBox_OkCancel.accepted.connect(self.update_settings)  # Connect to custom method
        self.buttonBox_OkCancel.rejected.connect(self.cancel_action)
        
        self.pushButton_Run.clicked.connect(self.run_summary)
       
        self.toggle_validation_stats()
        self.toggle_TSM_or_subarea()

    def toggle_TSM_or_subarea(self):
        """Enable or disable the TSM or subarea button based on the checkbox state."""
        settings = Config()
        if self.checkBox_isSubarea.isChecked():
            settings.set("isSubareaLevel", True)
        else:
            settings.set("isSubareaLevel", False)

    def toggle_validation_stats(self):
        """Enable or disable the validation stats button based on the checkbox state."""
        settings = Config()
        if self.checkBox_ValidationStats.isChecked():
            self.browse_ValidationStats.setEnabled(True)
            self.lineEdit_validationStats.setEnabled(True)
            settings.set("validationStats", True)
        else:
            self.browse_ValidationStats.setEnabled(False)
            self.lineEdit_validationStats.setEnabled(False)
            self.lineEdit_validationStats.clear()
            settings.set("validationStats", False)

    def cancel_action(self):
        """Handles the Cancel button."""
        print("Action canceled. Closing dialog.")
        self.reject()  # Closes the dialog without executing any code

    def select_file(self, line_edit, type):
        if type == "open":
            file_path, _ = QFileDialog.getOpenFileName(self, "Select File", "", "All Files (*)") #"", "JSON Files (*.json);;All Files (*)")
        elif type == "save":
            file_path, _ = QFileDialog.getSaveFileName(self, "Select File", "", "GeoPackage (*.gpkg);; Shapefiles (*.shp)") 
            
        if file_path:
            line_edit.setText(file_path)

    def select_file_xlsx(self, line_edit, type):
        if type == "open":
            file_path, _ = QFileDialog.getOpenFileName(self, "Select File", "", "Excel File (*xlsx)") #"", "JSON Files (*.json);;All Files (*)")
        elif type == "save":
            file_path, _ = QFileDialog.getSaveFileName(self, "Select File", "", "Excel File (*xlsx);; All Files (*)") 
            
        if file_path:
            line_edit.setText(file_path)

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
    
    def update_settings(self):
        """Update settings without closing the dialog."""
        settings = Config()
        if self.comboBox_linkLayer.currentData():
            link_layer = self.comboBox_linkLayer.currentData()
            settings.set("link_layer_name", link_layer.name())  
        if self.lineEdit_volume.text():
            settings.set("volume_file", self.lineEdit_volume.text())
        if self.lineEdit_loadedOut.text():
            settings.set("loadedOut_file", self.lineEdit_loadedOut.text())
        if self.lineEdit_validationStats.text():
            settings.set("validationStats_file", self.lineEdit_validationStats.text())
        if self.checkBox_ValidationStats.isChecked():
            settings.set("validationStats", True)
        else:
            settings.set("validationStats", False)
        if self.checkBox_isSubarea.isChecked():
            settings.set("isSubareaLevel", True)
        else:
            settings.set("isSubareaLevel", False)
            
        settings.check_and_save_to_file("scenario_settings_file")
        QMessageBox.information(self, "Settings Updated", "Project Specific settings have been updated.")
           # Keep the dialog open
        # self.show()
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
                
    def run_summary(self):
        settings = Config()
        plugin_dir = settings.get("plugin_dir")
        link_layer = self.comboBox_linkLayer.currentData()
        volume_file = self.lineEdit_volume.text()
        loadedOut_file = self.lineEdit_loadedOut.text()
        if not link_layer:
            QMessageBox.warning(self, "Warning", "Please select a link layer.")
            return
        if not volume_file:
            QMessageBox.warning(self, "Warning", "Please select a volume file.")
            return
        
        validationStats = settings.get("validationStats")
        if validationStats:
            bool_validation_stats = "TRUE"
            validationStats_file = self.lineEdit_validationStats.text()
        else:
            bool_validation_stats = "FALSE"
            validationStats_file = "None"
        
        if validationStats and not self.lineEdit_validationStats.text():
            QMessageBox.warning(self, "Warning", "Please select a validation stats file.")
            return

        # Get the path of the link layer
        link_layer_path = self.get_layer_path(link_layer)
        if not link_layer_path:
            QMessageBox.warning(self, "Warning", "Link layer path not found.")
            return
        
        from summarize_runner import run_summary
        is_subarea = bool(settings.get("isSubareaLevel"))

        print("link_layer_path:", link_layer_path)
        print("volume_file:", volume_file)
        print("loadedOut_file:", loadedOut_file)
        print("is_subarea:", is_subarea)

        loaded_qml_file = os.path.join(plugin_dir, "qgis_styles/TSM_Loaded_Symbology.qml").replace("\\","/")

        try:
            # C++ summarize.exe (port of Summarise_Loaded_Volumes.R)
            result1 = run_summary("summarize_loaded.toml", link_layer_path, volume_file, loadedOut_file, subarea=is_subarea)
      
            if result1.returncode == 0:  # Check if the R script ran successfully
                print("loaded entwork volumes script ran successfully.")
                
                self.load_output_layer(loadedOut_file, "LoadedNetwork")
                self.load_layer_symbology(loaded_qml_file, "LoadedNetwork")
                QMessageBox.information(self, "Success", "Loaded network volumes script ran successfully.")
            else:
                print("error running loaded networks or validation.")
        except Exception as e:
            print("Error running loaded networks or validation:", e)
            QMessageBox.critical(self, "Error", f"Error running summary script: {e}") 
            # self.close()
        # QMessageBox.information(self, "Success", "Loaded network volumes script ran successfully.")

