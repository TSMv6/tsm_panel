import os
import csv
import subprocess
from PyQt5.QtWidgets import QDialog, QFileDialog, QMessageBox
from .model_run import run_gated_model
from qgis.core import QgsProject
from PyQt5 import uic  # For loading .ui dynamically
from .tsm_settings import Config

from .Skimmy_ui import Ui_Dialog_Skimmy

SETTINGS_FILENAME = "skimmy_settings.txt"

# Column mapping from the netPrep link/node schema to the positional CSV that
# PathSkim reads (links: from,to,ftype,distance,speed,toll ; nodes: N,zone,signal).
LINK_MAP = [("from", ["A", "from"]),
            ("to", ["B", "to"]),
            ("ftype", ["FTYPE", "FACTYPE", "ftype"]),
            ("distance", ["DISTANCE", "DIST", "distance"]),
            ("speed", ["SPEED", "speed"]),
            ("toll", ["TOLL", "toll"])]


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

        # Default threads from General Configuration
        self.lineEdit_Threads.setText(str(settings.get("num_processors") or "0"))

        # Connections
        self.browse_skimFile.clicked.connect(lambda: self.select_file(self.lineEdit_OutSkimFile, "save", "OMX (*.omx);; CSV (*.csv)"))
        self.browse_debugFile.clicked.connect(lambda: self.select_file(self.lineEdit_debugOut, "save", "CSV (*.csv)"))
        self.browse_disconnected.clicked.connect(lambda: self.select_file(self.lineEdit_disconnected, "save", "CSV (*.csv)"))
        self.browse_tileGeo.clicked.connect(lambda: self.select_file(self.lineEdit_tileGeo, "open", "CSV (*.csv)"))
        self.browse_tileDir.clicked.connect(lambda: self.select_directory(self.lineEdit_tileDir))
        self.browse_tileIndex.clicked.connect(lambda: self.select_file(self.lineEdit_tileIndex, "save", "JSON (*.json)"))
        self.button_run_Skimmy.clicked.connect(lambda: self.run_Skimmy(show_message=True))
        self.button_SaveCancel.accepted.connect(self.update_settings)
        self.button_SaveCancel.rejected.connect(self.cancel_action)
        self.comboBox_Format.currentTextChanged.connect(self.toggle_tiled_fields)

        # Prefill layer names from Config (fallback)
        if settings.get("link_layer_name"):
            self._select_combo_text(self.comboBox_Linklayer, settings.get("link_layer_name"))
        if settings.get("node_layer_name"):
            self._select_combo_text(self.comboBox_Nodelayer, settings.get("node_layer_name"))

        # Start from the settings file, then sync the tiled-field enabled state.
        self.load_from_settings_file()
        self.toggle_tiled_fields()

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
        settings.set("output_format", self.comboBox_Format.currentText())
        settings.set("time_coeff", self.lineEdit_timeCoeff.text())
        settings.set("cost_coeff", self.lineEdit_costCoeff.text())
        settings.set("dist_coeff", self.lineEdit_distCoeff.text())
        settings.set("skim_file", self.lineEdit_OutSkimFile.text())
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

    def _gpkg_to_full_csv(self, gpkgcsv_exe, gpkg_path, out_csv):
        r = subprocess.run([gpkgcsv_exe, "to-csv", gpkg_path, out_csv, "--drop-geom"],
                           env=Config().app_env(gpkgcsv_exe))
        return r.returncode == 0 and os.path.exists(out_csv)

    def _transform_links(self, full_csv, out_csv):
        with open(full_csv, newline="") as fi, open(out_csv, "w", newline="") as fo:
            reader = csv.DictReader(fi)
            writer = csv.writer(fo)
            writer.writerow([k for k, _ in LINK_MAP])
            for row in reader:
                writer.writerow([self._ci_get(row, cands) for _, cands in LINK_MAP])

    def _transform_nodes(self, full_csv, out_csv):
        with open(full_csv, newline="") as fi, open(out_csv, "w", newline="") as fo:
            reader = csv.DictReader(fi)
            writer = csv.writer(fo)
            writer.writerow(["N", "zone", "signal"])
            for row in reader:
                nid = self._ci_get(row, ["N", "NODE_ID", "id"])
                dta = str(self._ci_get(row, ["DTA_Type", "dta_type"])).strip()
                zone = "true" if dta in ("99", "99.0") else ""
                signal = "true" if str(self._ci_get(row, ["signal", "NSignals"])).strip() in ("1", "true", "True") else ""
                writer.writerow([nid, zone, signal])

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------
    def run_Skimmy(self, show_message=False):
        settings = Config()

        link_layer = self.comboBox_Linklayer.currentData()
        node_layer = self.comboBox_Nodelayer.currentData()
        if not link_layer or not node_layer:
            QMessageBox.critical(self, "Error", "Please select both a link and a node layer.")
            return False
        skim_file = self.lineEdit_OutSkimFile.text().strip()
        if not skim_file:
            QMessageBox.critical(self, "Error", "Please select an output skim file.")
            return False
        for coeff, label in ((self.lineEdit_costCoeff, "cost"),
                             (self.lineEdit_distCoeff, "distance"),
                             (self.lineEdit_timeCoeff, "time")):
            if not coeff.text().strip():
                QMessageBox.critical(self, "Error", f"Please enter the {label} coefficient.")
                return False

        output_format = self.comboBox_Format.currentText()
        if output_format == "tiled_omx" and not (self.lineEdit_tileGeo.text().strip()
                                                  and self.lineEdit_tileDir.text().strip()
                                                  and self.lineEdit_tileIndex.text().strip()):
            QMessageBox.critical(self, "Error", "tiled_omx output needs the tile geo file, tile directory, and tile index file.")
            return False

        # Resolve apps from the plugin's own Apps/ folder (not tsm_location), so
        # all code runs from the plugin directory.
        pathskim_exe = settings.app_exe("skimmy/PathSkim.exe")
        gpkgcsv_exe = settings.app_exe("utilities/gpkgcsv.exe")
        for path, label in ((pathskim_exe, "PathSkim.exe"), (gpkgcsv_exe, "gpkgcsv.exe")):
            if not os.path.exists(path):
                QMessageBox.critical(self, "Error", f"{label} not found at: {path}")
                return False

        output_dir = os.path.dirname(skim_file)
        link_path = self.get_layer_path(link_layer)
        node_path = self.get_layer_path(node_layer)

        # 1) Dump gpkg attributes, then transform to PathSkim's positional schema.
        link_full = os.path.join(output_dir, "_link_full.csv")
        node_full = os.path.join(output_dir, "_node_full.csv")
        link_csv = os.path.join(output_dir, "Link_skim.csv")
        node_csv = os.path.join(output_dir, "Node_skim.csv")
        try:
            if not self._gpkg_to_full_csv(gpkgcsv_exe, link_path, link_full):
                QMessageBox.critical(self, "Error", "Failed to export link layer to CSV.")
                return False
            if not self._gpkg_to_full_csv(gpkgcsv_exe, node_path, node_full):
                QMessageBox.critical(self, "Error", "Failed to export node layer to CSV.")
                return False
            self._transform_links(link_full, link_csv)
            self._transform_nodes(node_full, node_csv)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error preparing link/node CSVs: {e}")
            return False

        # 2) Write skimmy_settings.txt
        threads = self.lineEdit_Threads.text().strip() or "0"
        debug = self.path_traceGB.isChecked()
        settings_file = os.path.join(output_dir, SETTINGS_FILENAME)
        try:
            with open(settings_file, "w") as f:
                f.write(f"node_file            = {node_csv}\n")
                f.write(f"link_file            = {link_csv}\n")
                f.write(f"output_format        = {output_format}\n")
                f.write(f"skim_file            = {skim_file}\n")
                f.write(f"cost_coefficient     = {self.lineEdit_costCoeff.text().strip()}\n")
                f.write(f"distance_coefficient = {self.lineEdit_distCoeff.text().strip()}\n")
                f.write(f"time_coefficient     = {self.lineEdit_timeCoeff.text().strip()}\n")
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

        # 3) Run PathSkim via the shared gated runner (captures output and reports the
        #    real reason — token missing/invalid/expired/revoked, offline, or a
        #    PathSkim error — in a message box).
        if not run_gated_model(self, [pathskim_exe, settings_file], "Skimmy"):
            return False

        self.update_settings_silent()
        print("Path skim completed successfully.")
        if show_message:
            QMessageBox.information(self, "Success", f"Path skim completed.\n\nSkim: {skim_file}")
        return True

    def update_settings_silent(self):
        settings = Config()
        settings.set("output_format", self.comboBox_Format.currentText())
        settings.set("skim_file", self.lineEdit_OutSkimFile.text())
        settings.set("link_layer_name", self.comboBox_Linklayer.currentText())
        settings.set("node_layer_name", self.comboBox_Nodelayer.currentText())
