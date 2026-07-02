import json
import os
from qgis.PyQt.QtWidgets import QDialog, QFileDialog, QPushButton, QLineEdit
from qgis.PyQt import uic  # For loading .ui dynamically

class SettingsDialog(QDialog):
    """Dynamically loads a .ui file and connects actions to widgets."""
    def __init__(self, tool_name, parent=None):
        super().__init__(parent)
        self.tool_name = tool_name
        self.setWindowTitle(f"Settings for {tool_name}")

        # Determine UI file based on tool_name
        ui_file = os.path.join(os.path.dirname(__file__), f"ui/{tool_name}.ui")

        # Load UI dynamically
        uic.loadUi(ui_file, self)

        # Locate widgets dynamically
        self.input_line = self.findChild(QLineEdit, "inputPathLineEdit")
        self.browse_button = self.findChild(QPushButton, "browseButton")
        self.apply_button = self.findChild(QPushButton, "applyButton")

        # Connect actions
        if self.browse_button:
            self.browse_button.clicked.connect(self.select_file)
        if self.apply_button:
            self.apply_button.clicked.connect(self.save_settings)

        # Load existing settings
        self.settings_file = os.path.join(os.path.dirname(__file__),"settings.json")
        self.load_settings()

    def select_file(self):
        """Open file dialog to select an input file."""
        file_name, _ = QFileDialog.getOpenFileName(self, "Select File", "", "All Files (*);;CSV Files (*.csv);;Shapefiles (*.shp)")
        if file_name and self.input_line:
            self.input_line.setText(file_name)

    def save_settings(self):
        """Save settings to a JSON file."""
        settings_data = {}

        # Store input path
        if self.input_line:
            settings_data["input_path"] = self.input_line.text()

        # Load existing settings file
        if os.path.exists(self.settings_file):
            with open(self.settings_file, "r") as f:
                all_settings = json.load(f)
        else:
            all_settings = {}

        # Update settings for this tool
        all_settings[self.tool_name] = settings_data

        # Save to JSON file
        with open(self.settings_file, "w") as f:
            json.dump(all_settings, f, indent=4)

    def load_settings(self):
        """Load existing settings from JSON."""
        if os.path.exists(self.settings_file):
            with open(self.settings_file, "r") as f:
                all_settings = json.load(f)

            if self.tool_name in all_settings:
                if self.input_line:
                    self.input_line.setText(all_settings[self.tool_name].get("input_path", ""))
