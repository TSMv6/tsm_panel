import os
import subprocess
from PyQt5.QtWidgets import QDialog, QFileDialog, QMessageBox,QTableWidget, QTableWidgetItem, QMainWindow
from qgis.core import QgsProject, QgsVectorLayer
from PyQt5 import uic  # For loading .ui dynamically
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor

from .tsm_settings import Config

from .configurationTable_ui import Ui_Form

class ViewSettings(QDialog, Ui_Form):
    def __init__(self):
        super().__init__()

        settings = Config()
        plugin_dir = settings.get("plugin_dir")
        ui_file = os.path.join(plugin_dir, "ui/configurationTable.ui")
        print(f"UI file found at: {ui_file}")

        # Check if the UI file exists
        if not os.path.exists(ui_file):
            print(f"UI file not found at: {ui_file}")
            return  # If the file doesn't exist, stop further execution

        # Load the UI dynamically if the file exists
        uic.loadUi(ui_file, self)  # This will automatically load the UI and set it up
        self.table = self.findChild(QTableWidget, "tableWidget")
        if self.table is None:
            print("❌ Could not find tableWidget in UI. Check objectName.")
            return
        # Set the table properties
        # self.table.setRowCount(0)  # Clear any existing rows
        # self.table.setColumnCount(2)
        # self.table.setHorizontalHeaderLabels(["Key", "Value"])
        # self.table.setSelectionBehavior(QTableWidget.SelectRows)

        saveSettings_button = getattr(self, "pushButton_Save", None)
        saveSettings_button.clicked.connect(lambda _, tool= "save":self.save_settings_to_file())
        loadSettings_button = getattr(self, "pushButton_Load", None)
        loadSettings_button.clicked.connect(lambda _, tool= "load":self.load_settings_from_file())

        self.load_settings()
        # self.load_settings_from_file()
        # self.save_settings_to_file()
        self.table.cellChanged.connect(self.on_cell_changed)  
        
    def load_settings(self):
        self.table.blockSignals(True)  # prevent triggering cellChanged while populating
        settings = Config().get_all()
        # print(settings)
        # self.table.setRowCount(len(settings))
        # self.table.setRowCount(75) # Fix number of rows in the tableWidget
        self.table.setColumnCount(3)
        self.table.setColumnHidden(1, True)
        self.table.setHorizontalHeaderLabels(["Label", "Key", "Value"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)

        self.table.setColumnWidth(0, 150)  # Set width of the first column
        self.table.setColumnWidth(1, 100)  # Set width of the second column
        self.table.setColumnWidth(2, 400)  # Set width of the second column
        
        for row in range(self.table.rowCount()):
            key_item = self.table.item(row, 1)
            # value_item = self.table.item(row, 2)

            if not key_item:
                continue

            key = key_item.text()

            if key in settings:
                new_value = settings[key]
                new_value_item = QTableWidgetItem(str(new_value))
                new_value_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
                self.table.setItem(row, 2, new_value_item)

        # keys = list(settings.keys())
        # # for row, (key, value) in enumerate(settings.items()):
        # for row, key in enumerate(keys):
        #     value = settings[key]
        #     key_item = QTableWidgetItem(str(key))
        #     print(f"Key: {key}, Value: {value}")
        #     # key_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        #     # self.table.setItem(row, 0, key_item)

        #     value_item = QTableWidgetItem(str(value))
        #     value_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
        #     self.table.setItem(row, 1, value_item)

        self.table.blockSignals(False)

    def on_cell_changed(self, row, column):
        if column != 2:
            return  # only handle edits to the value column
        key_item = self.table.item(row, 1)
        value_item = self.table.item(row, 2)
        key = key_item.text()
        value = value_item.text()
        original_value = str(Config().get(key))

        print(f"Value changed for key: {key}, Old Value: {original_value}, New Value: {value}")
        if value != original_value:
            # Check for only boolean keys
            if key in ["runTurnMove", "runSubExtTT", "runSelectLinkTT", "runSelectLinkAnalysis", "FLOS", "LDT_visitor_userRef"]:
                if value in ["False", "false", "F", "f"]:
                    value = False
                elif value in ["True", "true", "T", "t"]:
                    value = True
                else:
                    QMessageBox.warning(self, "Warning", f"Value for key '{key}' is not a boolean. Please enter a valid value False/F, True/T")

            # Highlight changed cell
            value_item.setBackground(QColor(255, 255, 150))  # light yellow
        else:
            # Clear highlight if change is undone
            value_item.setBackground(QColor(255, 255, 255))  # white

        # Optional: convert value to original type (int, bool, etc.)
        Config().set(key, value)

    def load_settings_from_file(self):
        """Triggered when the Load button is clicked."""
        settings = Config()
        file_path, _ = QFileDialog.getOpenFileName(self, "Open Settings", "", "JSON Files (*.json);;All Files (*)")
        print(file_path)
        if file_path:
            try:
            # Load the settings using Config
                settings.load_from_file(file_path)  # Load the settings from the selected file path
                plugin_dir = os.path.dirname(__file__).replace("\\", "/")
                settings.set("plugin_dir", plugin_dir)
                self.load_settings()
                # self.save_last_used_settings(file_path)  # Save the last used settings file path
                print("UI updated with loaded settings")
                QMessageBox.information(self, "Information", f"Read settings from file: {file_path}")
            # self.update_ui_with_settings(settings)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load settings: {e}")

    def save_settings_to_file(self):
        """Save the current settings to a JSON file."""
        settings = Config()
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Settings", "", "JSON Files (*.json);;All Files (*)")
        if file_path:
            try:
                # Save the settings as JSON
                settings.save_to_file(file_path) 
                QMessageBox.information(self, "Information", f"Save settings to file: {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save settings: {e}")
        else:
            print("No file selected.")
