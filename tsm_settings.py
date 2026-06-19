import json, os
from PyQt5.QtWidgets import QDialog, QFileDialog

class Config:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
            cls._instance.settings = {}  # Initialize settings dictionary
        return cls._instance

    def set(self, key, value):
        self.settings[key] = value

    def get(self, key):
        return self.settings.get(key)
    
    def remove(self, key):
        if key in self.settings:
            del self.settings[key]

    def get_all(self):
        return self.settings.copy()
    
    def save_to_file(self, file_path):
            """Save the configuration settings to a JSON file."""
            try:
                with open(file_path, 'w') as f:
                    json.dump(self.settings, f, indent=4)
                print(f"Settings saved to {file_path}")
            except Exception as e:
                print(f"Failed to save settings: {e}")

    def load_from_file(self, file_path):
            """Load the configuration settings from a JSON file."""
            try:
                with open(file_path, 'r') as f:
                    self.settings = json.load(f)
                print(f"Settings loaded from {file_path}")
            except Exception as e:
                print(f"Failed to read settings file: {e}")

    def check_and_save_to_file(self, file_path_key):
        """Save the configuration settings to a JSON file."""
        try:
            file_path = self.get(file_path_key)
        except Exception as e:
            print(f"Error getting file path for key '{file_path_key}': {e}")
            file_path = None

        if not file_path or not os.path.exists(file_path):
            file_path, _ = QFileDialog.getSaveFileName(
                None, "Save Settings", "", "JSON Files (*.json);;All Files (*)"
            )
            if not file_path:
                print("No file selected. Settings not saved.")
                return
            self.set(file_path_key, file_path)
            print(f"Settings file path set to {file_path}")

        try:
            with open(file_path, 'w') as f:
                json.dump(self.settings, f, indent=4)
            print(f"Settings saved to {file_path}")
        except Exception as e:
            print(f"Failed to save settings: {e}")