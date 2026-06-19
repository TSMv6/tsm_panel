import os
import subprocess
from PyQt5.QtWidgets import QDialog, QFileDialog, QMessageBox
from qgis.core import QgsProject, QgsVectorLayer
from PyQt5 import uic  # For loading .ui dynamically
from .tsm_settings import Config

from .Project_Settings_ui import Ui_Dialog_ProjectSettings

class ProjectSpecsDialog(QDialog, Ui_Dialog_ProjectSettings):
    def __init__(self):
        super().__init__()
        # self.setupUi(self)
 
         # Verify the UI file path
        # plugin_dir = os.path.dirname(__file__).replace("\\", "/")
        settings = Config()
        plugin_dir = settings.get("plugin_dir")
        ui_file = os.path.join(plugin_dir, "ui/Project_Settings.ui")
        print(f"UI file found at: {ui_file}")

        # Check if the UI file exists
        if not os.path.exists(ui_file):
            print(f"UI file not found at: {ui_file}")
            return  # If the file doesn't exist, stop further execution

        # Load the UI dynamically if the file exists
        uic.loadUi(ui_file, self)  # This will automatically load the UI and set it up

        # Populate the dropdowns with available layers
        self.populate_layer_combobox(self.lineLayerCombo, "LineString")
        self.populate_layer_combobox(self.nodeLayerCombo, "Point")
        self.populate_layer_combobox(self.landuseLayerCombo, "Polygon")

         # Populate Year specific list in dropdown
        self.comboBox_ScenYear.addItems(["2023", "2024", "2025", "2030", "2035", "2040", "2045", "2050", "2055", "2060"])
        self.comboBox_NetYear.addItems(["2023",  "2024", "2025", "2030", "2035", "2050"])
        
        # Update Settings ("Main Panel -> Load Settings -> Config()")
        if settings.get("scenarioName"):
            self.lineEdit_ScenarioName.setText(settings.get("scenarioName"))
        if settings.get("scenarioYear"):
            userYear = settings.get("scenarioYear")
            # if userYear not in [self.comboBox_ScenYear.itemText(i) for i in range(self.comboBox_ScenYear.count())]:
            #     self.comboBox_ScenYear.addItem(userYear)  # Add the new text if it's not already present
            self.comboBox_ScenYear.setCurrentText(userYear)
        if settings.get("networkYear"):
            userNetYear = settings.get("networkYear")
            # Set the new text in the combo box
            self.comboBox_NetYear.setCurrentText(userNetYear)

        if(settings.get("scenarioDescription")):
            self.textEdit_ScenarioDescription.setPlainText(settings.get("scenarioDescription"))
        if settings.get("scenarioDir"):
            self.scenario_directory.setText(settings.get("scenarioDir"))
        if settings.get("GM_line_layer") != "":
            line_layer_name = settings.get("GM_line_layer")
            if line_layer_name in [self.lineLayerCombo.itemText(i) for i in range(self.lineLayerCombo.count())]:
                    self.lineLayerCombo.setCurrentText(line_layer_name)
        if settings.get("GM_node_layer") != "":
            node_layer_name = settings.get("GM_node_layer")
            if node_layer_name in [self.nodeLayerCombo.itemText(i) for i in range(self.nodeLayerCombo.count())]:
                    self.nodeLayerCombo.setCurrentText(node_layer_name)
        if settings.get("landuse_layer") != "":
            landuse_layer_name = settings.get("landuse_layer")
            if landuse_layer_name in [self.landuseLayerCombo.itemText(i) for i in range(self.landuseLayerCombo.count())]:
                    self.landuseLayerCombo.setCurrentText(landuse_layer_name)

        # Connect buttons to browse function
        self.browse_Scendir.clicked.connect(lambda: self.select_directory(self.scenario_directory))

        # self.pushButton_Browse_TSMPath.clicked.connect(lambda: self.select_directory(self.lineEdit_ModelPath))
        # self.pushButton_Browse_TSMPath.clicked.connect(lambda: self.select_file(self.lineEdit_SettingsFile))

        # selected_year = self.comboBox_ScenYear.currentText()
        # scenarioName = self.lineEdit_ScenarioName.text()
        # scenarioDir = self.scenario_directory.text()
   


        # Run the script when the "Run" button is clicked
        # self.buttonBox_Run.clicked.connect(self.run_r_script)
        self.buttonBox_Run.accepted.connect(self.update_settings)
        self.buttonBox_Run.rejected.connect(self.cancel_action)

    def cancel_action(self):
        """Handles the Cancel button."""
        print("Action canceled. Closing dialog.")
        self.reject()  # Closes the dialog without executing any code

    def select_directory(self, scenario_directory):
        directory = QFileDialog.getExistingDirectory(self, "Select Directory")
        if directory:
            self.scenario_directory.setText(directory)

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
        settings = Config()
        if self.lineEdit_ScenarioName.text():
            settings.set("scenarioName", self.lineEdit_ScenarioName.text())
        if self.comboBox_ScenYear.currentText():
            settings.set("scenarioYear", self.comboBox_ScenYear.currentText())
        if self.comboBox_NetYear.currentText():
            settings.set("networkYear", self.comboBox_NetYear.currentText())
        if self.scenario_directory.text():
            settings.set("scenarioDir", self.scenario_directory.text())
        if self.textEdit_ScenarioDescription.toPlainText():
            settings.set("scenarioDescription", self.textEdit_ScenarioDescription.toPlainText())
        if self.lineLayerCombo.currentData():
            line_layer = self.lineLayerCombo.currentData()
            settings.set("GM_line_layer", line_layer.name())
        if self.nodeLayerCombo.currentData():
            node_layer = self.nodeLayerCombo.currentData()
            settings.set("GM_node_layer", node_layer.name())
        if self.landuseLayerCombo.currentData():
            landuse_layer = self.landuseLayerCombo.currentData()
            settings.set("landuse_layer", landuse_layer.name())
        settings.check_and_save_to_file("scenario_settings_file")
        QMessageBox.information(self, "Settings Updated", "Project Specific settings have been updated.")
        # self.close() 
        

