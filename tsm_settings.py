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
        # Windows stores it as "Path" (mixed case); find the real key so we PREPEND
        # app_dir instead of replacing PATH (which would drop System32 etc.).
        path_key = next((k for k in env if k.upper() == "PATH"), "PATH")
        env[path_key] = app_dir + os.pathsep + env.get(path_key, "")
        env["GDAL_DRIVER_PATH"] = app_dir          # no GDAL plugins here -> none loaded
        gdata = os.path.join(app_dir, "gdal-data")
        projd = os.path.join(app_dir, "proj")
        if os.path.isdir(gdata):
            env["GDAL_DATA"] = gdata
        if os.path.isdir(projd):
            env["PROJ_LIB"] = projd
        return env

    def run_app(self, args, log_path=None, console=False, append=False, **kw):
        """subprocess.run a bundled converter/utility exe (args[0]) with its GDAL env.
        Returns the CompletedProcess (check .returncode).

        console=True: run in its OWN console window (live output, interruptible) and,
          with log_path, tee that output to the log file (PowerShell Tee-Object); the
          exe's real exit code is propagated. append=True tees with -Append.
        console=False + log_path: stream output to the log file with NO window;
          append=True appends instead of truncating, so several steps + a live-tail
          window (model_run.open_log_console) share one log shown in one window.
          (Utilities set unbuffered stdout, so the tail shows it live.)
        console=False, no log_path: no window (CREATE_NO_WINDOW), output not shown."""
        import subprocess
        # One-window run active: redirect this console step into the shared run log
        # (streamed, windowless) instead of its own console window.
        if console:
            try:
                from . import model_run as _mr
                if getattr(_mr, "_RUN_LOG", None):
                    console, log_path, append = False, _mr._RUN_LOG, True
            except Exception:
                pass
        env = kw.pop("env", self.app_env(args[0]))
        no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        # Run heavy utilities at HIGH priority so Windows Thread Director schedules them
        # on P-cores at turbo clock instead of parking them on E-cores at base clock
        # (observed ~5x slowdown on the i9-13950HX P/E hybrid). Child exes inherit the
        # parent's priority class, so this also covers the PowerShell-launched console path.
        high = getattr(subprocess, "HIGH_PRIORITY_CLASS", 0)
        if console:
            q = lambda s: "'" + str(s).replace("'", "''") + "'"
            inner = "& " + " ".join(q(a) for a in args)
            if log_path:
                inner += " 2>&1 | Tee-Object -FilePath " + q(log_path) + (" -Append" if append else "")
            inner += "; exit $LASTEXITCODE"
            pwsh = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                                "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
            cmd = [pwsh, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", inner]
            return subprocess.run(cmd, creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0) | high,
                                  env=env, **kw)
        if log_path:
            import time as _time
            # Timestamp every line so the log reads as an activity log with a clock.
            with open(log_path, "a" if append else "w", encoding="utf-8", errors="replace") as lf:
                lf.write("\n[%s] $ %s\n" % (_time.strftime("%H:%M:%S"), " ".join(args))); lf.flush()
                p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     creationflags=no_window | high, env=env, text=True, **kw)
                for line in p.stdout:
                    lf.write("[%s] %s" % (_time.strftime("%H:%M:%S"), line)); lf.flush()
                p.wait()
            return subprocess.CompletedProcess(args, p.returncode)
        kw.setdefault("creationflags", no_window | high)
        return subprocess.run(args, env=env, **kw)

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