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

    def app_exe(self, rel):
        """Resolve a bundled executable shipped inside the plugin's Apps/ folder.

        The Apps/ tree (model engines + data utilities + their GDAL DLLs) lives
        beside the plugin so users install nothing separately. `rel` is the path
        under Apps/, e.g. "utilities/gpkgcsv.exe" or "ldt/ldt-run.exe".
        """
        return os.path.join(self.get("plugin_dir"), "Apps", rel).replace("\\", "/")

    def app_env(self, exe_path):
        """Environment for launching a bundled GDAL-linked exe.

        The utilities/netPrep exes ship their own self-contained GDAL beside them.
        Pass this env to subprocess so the shipped gdal.dll uses ITS OWN driver
        path (the exe's folder, which has no GDAL plugins) instead of inheriting
        QGIS's GDAL_DRIVER_PATH -- otherwise the version-mismatched QGIS plugins
        fail to load and spam "Can't load requested DLL ... 127" errors. Also
        points GDAL_DATA/PROJ_LIB at the shipped data when present (needed to read
        CRS / write GeoPackages).
        """
        app_dir = os.path.dirname(exe_path)
        env = dict(os.environ)
        env["PATH"] = app_dir + os.pathsep + env.get("PATH", "")
        env["GDAL_DRIVER_PATH"] = app_dir          # no GDAL plugins here -> none loaded
        gdata = os.path.join(app_dir, "gdal-data")
        projd = os.path.join(app_dir, "proj")
        if os.path.isdir(gdata):
            env["GDAL_DATA"] = gdata
        if os.path.isdir(projd):
            env["PROJ_LIB"] = projd
        return env

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