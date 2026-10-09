import os
import csv
import subprocess
from qgis.PyQt.QtWidgets import QDialog, QFileDialog, QMessageBox
from .model_run import run_gated_model, begin_run_console, closes_run_console
from qgis.core import QgsProject
from qgis.utils import iface
from qgis.PyQt import uic  # For loading .ui dynamically
from .tsm_settings import Config

from .Skimmy_ui import Ui_Dialog_Skimmy

SETTINGS_FILENAME = "skimmy_settings.txt"
TRACE_SETTINGS_FILENAME = "skimmy_trace_settings.txt"

# Column mapping from the netPrep link/node schema to the positional CSV that
# PathSkim reads (links: from,to,ftype,distance,speed,toll ; nodes: N,zone,signal).
LINK_MAP = [("from", ["A", "from"]),
            ("to", ["B", "to"]),
            ("ftype", ["FTYPE", "FACTYPE", "ftype"]),
            ("distance", ["DISTANCE", "DIST", "distance"]),
            ("speed", ["SPEED", "speed"]),
            ("toll", ["TOLL", "toll"])]

# Default link fields for the Distance / Time / Toll dropdowns (first match wins).
DEFAULT_DIST_FIELDS = ["DISTANCE", "DIST", "distance"]
DEFAULT_TIME_FIELDS = ["SPEED", "speed"]
DEFAULT_TOLL_FIELDS = ["TOLL", "toll"]
NO_TOLL = "(none)"
TIME_UNITS = [("Speed (mph)", "speed"), ("Travel time (min)", "minutes")]


class FLSkim(QDialog, Ui_Dialog_Skimmy):
    def __init__(self):
        super().__init__()

        settings = Config()
        plugin_dir = settings.get("plugin_dir")
        ui_file = os.path.join(plugin_dir, "ui/Skimmy.ui")
        print(f"UI file found at: {ui_file}")
        if not os.path.exists(ui_file):
            print(f"UI file not found at: {ui_file}")
            return
        uic.loadUi(ui_file, self)

        self.populate_layer_combobox(self.comboBox_Linklayer, "LineString")
        self.populate_layer_combobox(self.comboBox_Nodelayer, "Point")

        self.comboBox_Format.addItems(["omx", "csv", "tiled_omx"])
        self.comboBox_Format.setCurrentText("omx")
        for label, code in TIME_UNITS:
            self.comboBox_timeUnits.addItem(label, code)

        # Default threads from General Configuration
        self.lineEdit_Threads.setText(str(settings.get("num_processors") or "0"))

        # Connections
        self.browse_skimFile.clicked.connect(lambda: self.select_file(self.lineEdit_OutSkimFile, "save", "OMX (*.omx);; CSV (*.csv)"))
        self.browse_debugFile.clicked.connect(lambda: self.select_file(self.lineEdit_debugOut, "save", "CSV (*.csv)"))
        self.browse_disconnected.clicked.connect(lambda: self.select_file(self.lineEdit_disconnected, "save", "CSV (*.csv)"))
        self.browse_tileGeo.clicked.connect(lambda: self.select_file(self.lineEdit_tileGeo, "open", "CSV (*.csv)"))
        self.browse_tileDir.clicked.connect(self._pick_tile_dir)
        self.browse_tileIndex.clicked.connect(lambda: self.select_file(self.lineEdit_tileIndex, "save", "JSON (*.json)"))
        self.button_run_Skimmy.clicked.connect(lambda: self.run_Skimmy(show_message=True))
        self.button_traceOnly.clicked.connect(lambda: self.run_trace())
        self.comboBox_Linklayer.currentIndexChanged.connect(lambda _: self.populate_field_combos())
        self.button_SaveCancel.accepted.connect(self.update_settings)
        self.button_SaveCancel.rejected.connect(self.cancel_action)
        self.comboBox_Format.currentTextChanged.connect(self.toggle_tiled_fields)

        # Prefill layer names from Config (fallback)
        if settings.get("link_layer_name"):
            self._select_combo_text(self.comboBox_Linklayer, settings.get("link_layer_name"))
        if settings.get("node_layer_name"):
            self._select_combo_text(self.comboBox_Nodelayer, settings.get("node_layer_name"))

        # Start from the legacy settings file, then overlay the saved project
        # settings (Config / settings.json) which the Save button writes -- Config
        # wins where it has a value -- then sync the tiled-field enabled state.
        self.load_from_settings_file()
        if settings.get("output_format"):
            self.comboBox_Format.setCurrentText(settings.get("output_format"))
        if settings.get("skim_file"):
            self.lineEdit_OutSkimFile.setText(settings.get("skim_file"))
        if settings.get("cost_coeff"):
            self.lineEdit_costCoeff.setText(str(settings.get("cost_coeff")))
        if settings.get("dist_coeff"):
            self.lineEdit_distCoeff.setText(str(settings.get("dist_coeff")))
        if settings.get("time_coeff"):
            self.lineEdit_timeCoeff.setText(str(settings.get("time_coeff")))
        for key, edit in (("tile_geo_file", self.lineEdit_tileGeo),
                          ("tile_dir", self.lineEdit_tileDir),
                          ("tile_index_file", self.lineEdit_tileIndex),
                          ("disconnected_file", self.lineEdit_disconnected),
                          ("skim_trace_origin", self.lineEdit_DebugStart),
                          ("skim_trace_dest", self.lineEdit_DebugEnd),
                          ("skim_trace_path", self.lineEdit_debugOut)):
            if settings.get(key):
                edit.setText(str(settings.get(key)))
        if settings.get("skim_trace_enabled") is not None:
            self.path_traceGB.setChecked(self._str2bool(settings.get("skim_trace_enabled")))
        self.populate_field_combos()
        self._fields_ready = True   # from here on a layer change keeps the user's picks
        self.toggle_tiled_fields()

    def _pick_tile_dir(self):
        """Pick the tile output directory; default the index to <dir>/tile_index.json
        when it's empty (the index normally lives inside the tile directory)."""
        directory = QFileDialog.getExistingDirectory(self, "Select Tile Directory")
        if not directory:
            return
        self.lineEdit_tileDir.setText(directory)
        if not self.lineEdit_tileIndex.text().strip():
            self.lineEdit_tileIndex.setText(os.path.join(directory, "tile_index.json").replace("\\", "/"))

    # ------------------------------------------------------------------
    # Settings-file helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _str2bool(value):
        return str(value).strip().lower() in ("true", "t", "1", "yes", "y")

    @staticmethod
    def _parse_settings_file(file_path):
        cfg = {}
        with open(file_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                cfg[key.strip()] = value.strip()
        return cfg

    def _select_combo_text(self, combo, text):
        if text and text in [combo.itemText(i) for i in range(combo.count())]:
            combo.setCurrentText(text)

    def load_from_settings_file(self):
        settings = Config()
        self._saved_fields = {k: settings.get("skim_" + k) for k in
                              ("dist_field", "time_field", "time_units", "toll_field")
                              if settings.get("skim_" + k)}
        out_dir = Config().get("scenarioDir")
        if not out_dir:
            return
        sfile = os.path.join(out_dir, SETTINGS_FILENAME)
        if not os.path.exists(sfile):
            print(f"No skim settings file at: {sfile}")
            return
        cfg = self._parse_settings_file(sfile)
        print(f"Loading skim settings from: {sfile}")

        if cfg.get("output_format"):
            self.comboBox_Format.setCurrentText(cfg["output_format"])
        if cfg.get("skim_file"):
            self.lineEdit_OutSkimFile.setText(cfg["skim_file"])
        if cfg.get("cost_coefficient"):
            self.lineEdit_costCoeff.setText(cfg["cost_coefficient"])
        if cfg.get("distance_coefficient"):
            self.lineEdit_distCoeff.setText(cfg["distance_coefficient"])
        if cfg.get("time_coefficient"):
            self.lineEdit_timeCoeff.setText(cfg["time_coefficient"])
        if cfg.get("use_threads"):
            self.lineEdit_Threads.setText(cfg["use_threads"])
        if cfg.get("disconnected_file"):
            self.lineEdit_disconnected.setText(cfg["disconnected_file"])
        if cfg.get("tile_geo_file"):
            self.lineEdit_tileGeo.setText(cfg["tile_geo_file"])
        if cfg.get("tile_dir"):
            self.lineEdit_tileDir.setText(cfg["tile_dir"])
        if cfg.get("tile_index_file"):
            self.lineEdit_tileIndex.setText(cfg["tile_index_file"])
        if "debug" in cfg:
            self.path_traceGB.setChecked(self._str2bool(cfg["debug"]))
        if cfg.get("debug_start"):
            self.lineEdit_DebugStart.setText(cfg["debug_start"])
        if cfg.get("debug_end"):
            self.lineEdit_DebugEnd.setText(cfg["debug_end"])
        if cfg.get("debug_path"):
            self.lineEdit_debugOut.setText(cfg["debug_path"])
        # Link-field choices (ignored by PathSkim; read back here only). Saved
        # project settings win, matching the rest of the dialog.
        for key in ("dist_field", "time_field", "time_units", "toll_field"):
            if cfg.get(key):
                self._saved_fields.setdefault(key, cfg[key])

    # ------------------------------------------------------------------
    # UI behaviour
    # ------------------------------------------------------------------
    def toggle_tiled_fields(self):
        is_tiled = self.comboBox_Format.currentText() == "tiled_omx"
        self.tiledGB.setEnabled(is_tiled)

    def update_settings(self):
        settings = Config()
        settings.set("link_layer_name", self.comboBox_Linklayer.currentText())
        settings.set("node_layer_name", self.comboBox_Nodelayer.currentText())
        self._save_field_settings(settings)
        settings.set("output_format", self.comboBox_Format.currentText())
        settings.set("time_coeff", self.lineEdit_timeCoeff.text())
        settings.set("cost_coeff", self.lineEdit_costCoeff.text())
        settings.set("dist_coeff", self.lineEdit_distCoeff.text())
        settings.set("skim_file", self.lineEdit_OutSkimFile.text())
        # Tiled-OMX + disconnected fields (previously only written to skimmy_settings.txt
        # on Run, so Save lost them and View Settings never showed them).
        settings.set("tile_geo_file", self.lineEdit_tileGeo.text())
        settings.set("tile_dir", self.lineEdit_tileDir.text())
        settings.set("tile_index_file", self.lineEdit_tileIndex.text())
        settings.set("disconnected_file", self.lineEdit_disconnected.text())
        # Path Trace (debug) fields -- previously not persisted, so they vanished on reload.
        settings.set("skim_trace_enabled", self.path_traceGB.isChecked())
        settings.set("skim_trace_origin", self.lineEdit_DebugStart.text())
        settings.set("skim_trace_dest", self.lineEdit_DebugEnd.text())
        settings.set("skim_trace_path", self.lineEdit_debugOut.text())
        self._save_field_settings(settings)
        settings.check_and_save_to_file("scenario_settings_file")
        QMessageBox.information(self, "Settings Updated", "Skim settings have been updated.")

    def cancel_action(self):
        self.reject()

    def select_file(self, line_edit, mode, file_filter="All Files (*)"):
        if mode == "open":
            file_path, _ = QFileDialog.getOpenFileName(self, "Select File", "", file_filter)
        else:
            file_path, _ = QFileDialog.getSaveFileName(self, "Select File", "", file_filter)
        if file_path:
            line_edit.setText(file_path)

    def select_directory(self, line_edit):
        directory = QFileDialog.getExistingDirectory(self, "Select Directory")
        if directory:
            line_edit.setText(directory)

    def populate_layer_combobox(self, combobox, geom_type):
        combobox.clear()
        combobox.addItem("Select a layer", None)
        layers = QgsProject.instance().mapLayers().values()
        for layer in [l for l in layers if hasattr(l, "geometryType")]:
            if layer.geometryType() == {"Point": 0, "LineString": 1, "Polygon": 2}[geom_type]:
                combobox.addItem(layer.name(), layer)

    def get_layer_path(self, layer):
        if layer is None:
            return None
        return layer.dataProvider().dataSourceUri().split("|")[0]

    # ------------------------------------------------------------------
    # Link-field dropdowns (Distance / Time / Toll)
    # ------------------------------------------------------------------
    def populate_field_combos(self):
        """Fill the field dropdowns with the link layer's numeric fields. Keeps the
        current pick, else the saved one, else the netPrep default (DISTANCE/SPEED/TOLL)."""
        # Until the dialog is set up, the saved choices win over whatever an early
        # layer-change signal put in the combos.
        ready = getattr(self, "_fields_ready", False)
        saved = getattr(self, "_saved_fields", {})
        layer = self.comboBox_Linklayer.currentData()
        names = [f.name() for f in layer.fields() if f.isNumeric()] if layer else []

        def fill(combo, defaults, key, extra=()):
            # Keep the user's pick only if the combo already listed layer fields
            # (not just the "(none)" placeholder from before a layer was picked).
            had_fields = combo.count() > len(extra)
            want = combo.currentText() if ready and had_fields else saved.get(key, "")
            combo.clear()
            combo.addItems(list(extra) + names)
            items = [combo.itemText(i) for i in range(combo.count())]
            lower = {t.lower(): t for t in items}
            for cand in [want] + defaults:
                if cand and cand.lower() in lower:
                    combo.setCurrentText(lower[cand.lower()])
                    return

        fill(self.comboBox_distField, DEFAULT_DIST_FIELDS, "dist_field")
        fill(self.comboBox_timeField, DEFAULT_TIME_FIELDS, "time_field")
        fill(self.comboBox_tollField, DEFAULT_TOLL_FIELDS, "toll_field", extra=[NO_TOLL])
        if not ready and saved.get("time_units"):
            idx = self.comboBox_timeUnits.findData(saved["time_units"])
            if idx >= 0:
                self.comboBox_timeUnits.setCurrentIndex(idx)

    def _field_spec(self):
        """(dist_field, time_field, time_units, toll_field). An empty dropdown (no
        layer picked, e.g. a full run off the consolidator outputs) means the default
        candidates; toll_field None means no tolls."""
        dist = self.comboBox_distField.currentText()
        time_f = self.comboBox_timeField.currentText()
        toll = self.comboBox_tollField.currentText()
        return (dist or None, time_f or None,
                self.comboBox_timeUnits.currentData() or "speed",
                None if toll == NO_TOLL else (toll or ""))

    def _save_field_settings(self, settings):
        dist, time_f, units, toll = self._field_spec()
        settings.set("skim_dist_field", dist or "")
        settings.set("skim_time_field", time_f or "")
        settings.set("skim_time_units", units)
        settings.set("skim_toll_field", NO_TOLL if toll is None else toll)

    # ------------------------------------------------------------------
    # gpkg -> PathSkim CSV transforms
    # ------------------------------------------------------------------
    @staticmethod
    def _ci_get(row, candidates):
        """Case-insensitive lookup of the first matching column."""
        lower = {k.lower(): v for k, v in row.items()}
        for c in candidates:
            if c.lower() in lower:
                return lower[c.lower()]
        return ""

    def _gpkg_to_full_csv(self, gpkgcsv_exe, gpkg_path, out_csv, log_path=None, append=False):
        r = Config().run_app([gpkgcsv_exe, "to-csv", gpkg_path, out_csv, "--drop-geom"],
                             log_path=log_path, console=bool(log_path), append=append)
        return r.returncode == 0 and os.path.exists(out_csv)

    def _transform_links(self, full_csv, out_csv):
        """Write PathSkim's positional link CSV using the Distance/Time/Toll fields
        picked in the dialog. A travel-time field (minutes) is passed to PathSkim as
        the equivalent speed, 60 * distance / time, so the engine's time is unchanged."""
        dist_f, time_f, units, toll_f = self._field_spec()
        cols = dict(LINK_MAP)
        if dist_f:
            cols["distance"] = [dist_f]
        if time_f:
            cols["speed"] = [time_f]
        if toll_f:
            cols["toll"] = [toll_f]
        with open(full_csv, newline="") as fi, open(out_csv, "w", newline="") as fo:
            reader = csv.DictReader(fi)
            header = {h.lower() for h in (reader.fieldnames or [])}
            # A missing default TOLL column still means toll 0 (PathSkim's behavior).
            for key in ("from", "to", "distance", "speed") + (("toll",) if toll_f else ()):
                if not any(c.lower() in header for c in cols[key]):
                    raise ValueError(f"link field for '{key}' not found (looked for {cols[key]})")
            writer = csv.writer(fo)
            writer.writerow([k for k, _ in LINK_MAP])
            for row in reader:
                vals = {k: self._ci_get(row, cands) for k, cands in cols.items()}
                if toll_f is None:
                    vals["toll"] = "0"
                if units == "minutes":
                    try:
                        t = float(vals["speed"])
                        vals["speed"] = repr(60.0 * float(vals["distance"]) / t) if t > 0 else ""
                    except ValueError:
                        vals["speed"] = ""   # PathSkim skips the link and logs it
                writer.writerow([vals[k] for k, _ in LINK_MAP])

    def _transform_nodes(self, full_csv, out_csv):
        # X,Y let the path trace locate the break between disconnected pieces.
        with open(full_csv, newline="") as fi, open(out_csv, "w", newline="") as fo:
            reader = csv.DictReader(fi)
            writer = csv.writer(fo)
            writer.writerow(["N", "zone", "signal", "X", "Y"])
            for row in reader:
                nid = self._ci_get(row, ["N", "NODE_ID", "id"])
                dta = str(self._ci_get(row, ["DTA_Type", "dta_type"])).strip()
                zone = "true" if dta in ("99", "99.0") else ""
                signal = "true" if str(self._ci_get(row, ["signal", "NSignals"])).strip() in ("1", "true", "True") else ""
                writer.writerow([nid, zone, signal,
                                 self._ci_get(row, ["X", "x"]), self._ci_get(row, ["Y", "y"])])

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------
    def _resolve_network(self):
        """(link_path, node_path) from the dropdowns, or the Link Consolidator
        outputs in a full run / when nothing is picked. Shows an error if missing."""
        link_layer = self.comboBox_Linklayer.currentData()
        node_layer = self.comboBox_Nodelayer.currentData()
        sel_link = self.get_layer_path(link_layer) if link_layer else ""
        sel_node = self.get_layer_path(node_layer) if node_layer else ""
        link_path, node_path = Config().resolve_network_paths(sel_link, sel_node)
        if not link_path or not node_path:
            QMessageBox.critical(self, "Error",
                "No link/node network found. Pick the layers here, or run Link Consolidation first.")
            return None, None
        return link_path, node_path

    def _check_coefficients(self):
        for coeff, label in ((self.lineEdit_costCoeff, "cost"),
                             (self.lineEdit_distCoeff, "distance"),
                             (self.lineEdit_timeCoeff, "time")):
            if not coeff.text().strip():
                QMessageBox.critical(self, "Error", f"Please enter the {label} coefficient.")
                return False
        return True

    def _resolve_apps(self):
        # Resolve apps from the plugin's own Apps/ folder (not tsm_location), so
        # all code runs from the plugin directory.
        settings = Config()
        pathskim_exe = settings.app_exe("skimmy/PathSkim.exe")
        gpkgcsv_exe = settings.app_exe("utilities/gpkgcsv.exe")
        for path, label in ((pathskim_exe, "PathSkim.exe"), (gpkgcsv_exe, "gpkgcsv.exe")):
            if not os.path.exists(path):
                QMessageBox.critical(self, "Error", f"{label} not found at: {path}")
                return None, None
        return pathskim_exe, gpkgcsv_exe

    def _prepare_network(self, gpkgcsv_exe, link_path, node_path, output_dir):
        """Dump gpkg attributes, then transform to PathSkim's positional schema.
        Returns (link_csv, node_csv, temp_files) or None after showing an error."""
        link_full = os.path.join(output_dir, "_link_full.csv")
        node_full = os.path.join(output_dir, "_node_full.csv")
        link_csv = os.path.join(output_dir, "Link_skim.csv")
        node_csv = os.path.join(output_dir, "Node_skim.csv")
        convert_log = os.path.join(output_dir, "Skimmy_convert.log")
        try:
            if not self._gpkg_to_full_csv(gpkgcsv_exe, link_path, link_full, convert_log):
                QMessageBox.critical(self, "Error", "Failed to export link layer to CSV.")
                return None
            if not self._gpkg_to_full_csv(gpkgcsv_exe, node_path, node_full, convert_log, append=True):
                QMessageBox.critical(self, "Error", "Failed to export node layer to CSV.")
                return None
            self._transform_links(link_full, link_csv)
            self._transform_nodes(node_full, node_csv)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error preparing link/node CSVs: {e}")
            return None
        return link_csv, node_csv, (link_full, node_full, link_csv, node_csv)

    def _write_common_settings(self, f, node_csv, link_csv):
        f.write(f"node_file            = {node_csv}\n")
        f.write(f"link_file            = {link_csv}\n")
        f.write(f"cost_coefficient     = {self.lineEdit_costCoeff.text().strip()}\n")
        f.write(f"distance_coefficient = {self.lineEdit_distCoeff.text().strip()}\n")
        f.write(f"time_coefficient     = {self.lineEdit_timeCoeff.text().strip()}\n")
        # Link-field choices: informational for PathSkim (it ignores these keys),
        # read back by load_from_settings_file.
        dist_f, time_f, units, toll_f = self._field_spec()
        f.write(f"dist_field           = {dist_f or ''}\n")
        f.write(f"time_field           = {time_f or ''}\n")
        f.write(f"time_units           = {units}\n")
        f.write(f"toll_field           = {NO_TOLL if toll_f is None else toll_f}\n")

    @staticmethod
    def _remove_files(paths):
        for tmp in paths:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass

    @closes_run_console
    def run_Skimmy(self, show_message=False):
        # Network input: dialog dropdown when standalone; in a full run (or when
        # nothing is picked) chain off the Link Consolidator outputs.
        link_path, node_path = self._resolve_network()
        if not link_path:
            return False
        skim_file = self.lineEdit_OutSkimFile.text().strip()
        if not skim_file:
            QMessageBox.critical(self, "Error", "Please select an output skim file.")
            return False
        # One live-tail window for the whole Skimmy run (no per-step black windows).
        begin_run_console(os.path.join(os.path.dirname(skim_file) or ".", "Skimmy.log"),
                          "Skimmy - run log")
        if not self._check_coefficients():
            return False

        output_format = self.comboBox_Format.currentText()
        if output_format == "tiled_omx" and not (self.lineEdit_tileGeo.text().strip()
                                                  and self.lineEdit_tileDir.text().strip()
                                                  and self.lineEdit_tileIndex.text().strip()):
            QMessageBox.critical(self, "Error", "tiled_omx output needs the tile geo file, tile directory, and tile index file.")
            return False

        pathskim_exe, gpkgcsv_exe = self._resolve_apps()
        if not pathskim_exe:
            return False

        output_dir = os.path.dirname(skim_file)

        # 1) gpkg -> PathSkim CSVs
        prepared = self._prepare_network(gpkgcsv_exe, link_path, node_path, output_dir)
        if not prepared:
            return False
        link_csv, node_csv, temp_files = prepared

        # 2) Write skimmy_settings.txt
        threads = self.lineEdit_Threads.text().strip() or "0"
        debug = self.path_traceGB.isChecked()
        settings_file = os.path.join(output_dir, SETTINGS_FILENAME)
        try:
            with open(settings_file, "w") as f:
                self._write_common_settings(f, node_csv, link_csv)
                f.write(f"output_format        = {output_format}\n")
                f.write(f"skim_file            = {skim_file}\n")
                f.write(f"use_threads          = {threads}\n")
                if self.lineEdit_disconnected.text().strip():
                    f.write(f"disconnected_file = {self.lineEdit_disconnected.text().strip()}\n")
                if output_format == "tiled_omx":
                    f.write(f"tile_geo_file   = {self.lineEdit_tileGeo.text().strip()}\n")
                    f.write(f"tile_dir        = {self.lineEdit_tileDir.text().strip()}\n")
                    f.write(f"tile_index_file = {self.lineEdit_tileIndex.text().strip()}\n")
                f.write(f"debug        = {debug}\n")
                if debug:
                    f.write(f"debug_start  = {self.lineEdit_DebugStart.text().strip()}\n")
                    f.write(f"debug_end    = {self.lineEdit_DebugEnd.text().strip()}\n")
                    f.write(f"debug_path   = {self.lineEdit_debugOut.text().strip()}\n")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error writing skim settings: {e}")
            return False

        # 3) Run PathSkim via the shared gated runner. Output streams live to a log
        #    next to the skim output (the QGIS GUI has no console); failures still
        #    report the real reason (token/offline/PathSkim error) in a message box.
        log_path = os.path.join(output_dir, "Skimmy.log")
        print(f"Skimmy: log -> {log_path}")
        if not run_gated_model(self, [pathskim_exe, settings_file], "Skimmy",
                               log_path=log_path, console=True):
            return False

        # Clean up the intermediate CSVs: the raw gpkg dumps and the transformed
        # PathSkim positional inputs (consumed by the run; not user outputs).
        self._remove_files(temp_files)

        self.update_settings_silent()
        print("Path skim completed successfully.")
        if show_message:
            QMessageBox.information(self, "Success", f"Path skim completed.\n\nSkim: {skim_file}")
        return True

    @closes_run_console
    def run_trace(self):
        """Trace one O-D pair without skimming: PathSkim runs a single shortest-path
        search from the trace origin (debug_only mode), writes the link-level trace
        CSV + <trace>_summary.txt, and the path is selected on the link layer."""
        origin = self.lineEdit_DebugStart.text().strip()
        dest = self.lineEdit_DebugEnd.text().strip()
        if not (origin.isdigit() and dest.isdigit()):
            QMessageBox.critical(self, "Error", "Trace Origin and Trace Destination must be node numbers.")
            return False
        if not self._check_coefficients():
            return False
        link_path, node_path = self._resolve_network()
        if not link_path:
            return False
        pathskim_exe, gpkgcsv_exe = self._resolve_apps()
        if not pathskim_exe:
            return False

        # Outputs go next to the skim (or the scenario folder if no skim is set).
        skim_file = self.lineEdit_OutSkimFile.text().strip()
        output_dir = os.path.dirname(skim_file) if skim_file else (Config().get("scenarioDir") or "")
        if not output_dir or not os.path.isdir(output_dir):
            QMessageBox.critical(self, "Error", "Set the Output Skim (its folder holds the trace outputs).")
            return False
        trace_path = self.lineEdit_debugOut.text().strip()
        if not trace_path:
            trace_path = os.path.join(output_dir, f"trace_{origin}-{dest}.csv").replace("\\", "/")
            self.lineEdit_debugOut.setText(trace_path)

        begin_run_console(os.path.join(output_dir, "Skimmy_trace.log"), "Skimmy - path trace")
        prepared = self._prepare_network(gpkgcsv_exe, link_path, node_path, output_dir)
        if not prepared:
            return False
        link_csv, node_csv, temp_files = prepared

        # Separate control file so the skim's skimmy_settings.txt is left alone.
        settings_file = os.path.join(output_dir, TRACE_SETTINGS_FILENAME)
        try:
            with open(settings_file, "w") as f:
                self._write_common_settings(f, node_csv, link_csv)
                f.write("debug_only   = true\n")
                f.write(f"debug_start  = {origin}\n")
                f.write(f"debug_end    = {dest}\n")
                f.write(f"debug_path   = {trace_path}\n")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error writing trace settings: {e}")
            return False

        log_path = os.path.join(output_dir, "Skimmy_trace.log")
        ok = run_gated_model(self, [pathskim_exe, settings_file], "Skimmy path trace",
                             log_path=log_path, console=True)
        self._remove_files(temp_files)
        if not ok:
            return False

        summary_path = os.path.splitext(trace_path)[0] + "_summary.txt"
        try:
            with open(summary_path) as f:
                summary = f.read()
        except OSError:
            summary = f"Trace written to {trace_path} (no summary file found)."
        self._select_trace_on_map(trace_path)
        QMessageBox.information(self, "Path Trace", summary)
        return True

    def _select_trace_on_map(self, trace_path):
        """Select the traced links (and the two GAP nodes) on the picked layers and
        zoom to them. Best effort: silently skipped if no layer is picked."""
        try:
            with open(trace_path, newline="") as f:
                rows = list(csv.DictReader(f))
        except OSError:
            return
        link_layer = self.comboBox_Linklayer.currentData()
        node_layer = self.comboBox_Nodelayer.currentData()
        pairs = [(r["from_node"], r["to_node"]) for r in rows if r["segment"] != "GAP"]
        gap_nodes = [n for r in rows if r["segment"] == "GAP" for n in (r["from_node"], r["to_node"])]

        def field(layer, cands):
            names = {f.name().lower(): f.name() for f in layer.fields()}
            return next((names[c.lower()] for c in cands if c.lower() in names), None)

        canvas = iface.mapCanvas() if iface else None
        if link_layer and pairs:
            a, b = field(link_layer, ["A", "from"]), field(link_layer, ["B", "to"])
            if a and b:
                expr = " OR ".join(f'("{a}" = {x} AND "{b}" = {y})' for x, y in pairs)
                link_layer.selectByExpression(expr)
                if canvas:
                    canvas.zoomToSelected(link_layer)
        if node_layer and gap_nodes:
            n = field(node_layer, ["N", "NODE_ID", "id"])
            if n:
                node_layer.selectByExpression(f'"{n}" IN ({",".join(gap_nodes)})')
                if canvas and not pairs:
                    canvas.zoomToSelected(node_layer)
        if canvas:
            canvas.refresh()

    def update_settings_silent(self):
        settings = Config()
        settings.set("output_format", self.comboBox_Format.currentText())
        settings.set("skim_file", self.lineEdit_OutSkimFile.text())
        settings.set("link_layer_name", self.comboBox_Linklayer.currentText())
        settings.set("node_layer_name", self.comboBox_Nodelayer.currentText())
        self._save_field_settings(settings)
