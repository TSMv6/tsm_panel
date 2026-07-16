import json, os
from qgis.PyQt.QtWidgets import QDialog, QFileDialog
from qgis.PyQt.QtCore import QSettings

DEFAULT_TSM_LOCATION = "C:/TSM_NextGen_v6"
# Keys mirrored to disk (QSettings) so they survive a QGIS restart instead of
# living only in the in-memory singleton. Namespaced under "tsm_panel/".
_PERSIST_KEYS = {"tsm_location", "hydra_segment_params"}
_QS_PREFIX = "tsm_panel/"

class Config:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
            cls._instance.settings = {}  # Initialize settings dictionary
        return cls._instance

    def set(self, key, value):
        self.settings[key] = value
        # Mirror persisted keys to disk so a change here (e.g. the user editing
        # TSM Location in General Configuration) is remembered next session.
        if key in _PERSIST_KEYS:
            QSettings().setValue(_QS_PREFIX + key, value)

    def get(self, key):
        v = self.settings.get(key)
        # Persisted keys: hydrate from disk when not set this session, so tools
        # that need them (e.g. segment params for PCE) work before the dialog
        # that owns the field has been opened.
        if v in (None, "") and key in _PERSIST_KEYS:
            v = QSettings().value(_QS_PREFIX + key)
            if v:
                self.settings[key] = v
        return v
    
    def remove(self, key):
        if key in self.settings:
            del self.settings[key]

    def get_all(self):
        return self.settings.copy()

    def tsm_root(self):
        """TSM install root (all model inputs live under here). Resolution order:
        in-memory setting -> value persisted to disk in a prior session -> the v6
        default. This guarantees an ABSOLUTE root even before the General
        Configuration dialog is opened this session (the in-memory setting would
        otherwise be None and build paths RELATIVE to the process cwd, e.g.
        C:/Program Files/Java/...). The disk value is hydrated into memory but
        NOT re-persisted, so a bare default is never written over an unset key."""
        loc = self.get("tsm_location")
        if not loc:
            loc = QSettings().value(_QS_PREFIX + "tsm_location") or DEFAULT_TSM_LOCATION
            self.settings["tsm_location"] = loc  # hydrate only; don't persist a default
        return loc

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
            # Set BOTH PROJ_DATA (PROJ 9.1+) and PROJ_LIB (legacy) to the bundled
            # proj.db. QGIS injects its OWN PROJ_DATA into our environment, and the
            # bundled proj is NEWER than QGIS's -- if we leave QGIS's PROJ_DATA in
            # place the exe loads that older proj.db and rejects it ("PROJ: no
            # database context specified ... DATABASE.LAYOUT.VERSION ... from another
            # PROJ installation"), which breaks CRS lookups. Overriding both makes
            # every bundled GDAL exe use its own matching proj.db.
            env["PROJ_DATA"] = projd
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
            if log_path:
                # Merge stderr into stdout at the CMD level (one-line batch)
                # BEFORE PowerShell sees it. A native "2>&1" inside PowerShell
                # wraps every stderr line in a NativeCommandError record, so
                # ordinary progress messages (the engines print progress to
                # stderr to keep stdout clean CSV) showed up as big red error
                # blocks even on successful exit-0 runs.
                import tempfile
                bf = tempfile.NamedTemporaryFile("w", suffix=".cmd", prefix="tsm_run_",
                                                 delete=False)
                bf.write("@" + " ".join('"%s"' % a for a in args) + " 2>&1\n")
                bf.close()
                inner = ("& " + q(bf.name) + " | Tee-Object -FilePath " + q(log_path) +
                         (" -Append" if append else ""))
            else:
                inner = "& " + " ".join(q(a) for a in args)
            inner += "; exit $LASTEXITCODE"
            pwsh = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                                "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
            cmd = [pwsh, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", inner]
            return subprocess.run(cmd, creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0) | high,
                                  env=env, **kw)
        if log_path:
            import time as _time
            import threading as _threading
            # Kill switch: closing the live-tail run-log window cancels the run.
            # The window (model_run._RUN_CONSOLE) and the worker exe are unrelated
            # processes, so a watchdog thread inside QGIS bridges them: when the
            # user closes the window while the exe runs, kill the exe TREE.
            try:
                from . import model_run as _mr
                _console_closed = _mr.run_console_closed
            except Exception:
                _console_closed = lambda: False
            if _console_closed():
                # Window already closed (user cancelled an earlier step): don't
                # even launch the next exe -- fail fast so the chain stops.
                with open(log_path, "a", encoding="utf-8", errors="replace") as lf:
                    lf.write("\n[%s] RUN CANCELLED -- log window closed; skipping: %s\n"
                             % (_time.strftime("%H:%M:%S"), " ".join(args)))
                return subprocess.CompletedProcess(args, 1)
            # Timestamp every line so the log reads as an activity log with a clock.
            with open(log_path, "a" if append else "w", encoding="utf-8", errors="replace") as lf:
                lf.write("\n[%s] $ %s\n" % (_time.strftime("%H:%M:%S"), " ".join(args))); lf.flush()
                p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     creationflags=no_window | high, env=env, text=True, **kw)
                cancelled = []
                def _watchdog():
                    while p.poll() is None:
                        if _console_closed():
                            cancelled.append(True)
                            # Kill the whole tree (children too), windowless.
                            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"],
                                           creationflags=no_window,
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                            return
                        _time.sleep(0.5)
                wd = _threading.Thread(target=_watchdog, daemon=True)
                wd.start()
                for line in p.stdout:
                    lf.write("[%s] %s" % (_time.strftime("%H:%M:%S"), line)); lf.flush()
                p.wait()
                wd.join(timeout=2)
                rc = p.returncode
                if cancelled:
                    lf.write("[%s] RUN CANCELLED -- log window closed; %s terminated\n"
                             % (_time.strftime("%H:%M:%S"), os.path.basename(args[0])))
                    if rc == 0:
                        rc = 1  # a cancelled run must never read as success
            return subprocess.CompletedProcess(args, rc)
        kw.setdefault("creationflags", no_window | high)
        return subprocess.run(args, env=env, **kw)

    # ---- network-input chaining -------------------------------------------
    # Link Consolidation (step 1) writes the canonical scenario network to
    # TSM_Link_File / TSM_Node_File and auto-loads them as the TSM_Link /
    # TSM_Node layers. Downstream steps (Skimmy, ELToD, HyDRA) should chain off
    # those during a full run -- where the dialogs aren't touched and the layers
    # may not even be loaded -- while a standalone run honors the layer the user
    # picked. A class-level flag marks a full run in progress (never persisted).
    _full_run_active = False

    @classmethod
    def set_full_run(cls, active):
        """Mark a full-model run in progress (set by the panel's Run TSM)."""
        Config._full_run_active = bool(active)

    @classmethod
    def full_run_active(cls):
        return Config._full_run_active

    def resolve_network_paths(self, link_sel="", node_sel=""):
        """Resolve (link_path, node_path) for a downstream step. A standalone run
        uses the dialog's picked layer paths (link_sel/node_sel); in a full run,
        or when a selection is empty, fall back to the Link Consolidator outputs
        (TSM_Link_File / TSM_Node_File) so the chain works even with no layers
        loaded. Returns file paths (possibly empty strings)."""
        link = (link_sel or "").strip()
        node = (node_sel or "").strip()
        if Config._full_run_active or not link:
            link = (self.get("TSM_Link_File") or link or "").strip()
        if Config._full_run_active or not node:
            node = (self.get("TSM_Node_File") or node or "").strip()
        return link, node

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