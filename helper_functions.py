from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QLineEdit, QPushButton, QFileDialog

class HelperFun: 
    def select_file(self, line_edit, type):
            if type == "open":
                file_path, _ = QFileDialog.getOpenFileName(self, "Select File", "", "All Files (*)")
            elif type == "save":
                file_path, _ = QFileDialog.getSaveFileName(self, "Select File", "", "All Files (*)")
            if file_path:
                line_edit.setText(file_path)

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