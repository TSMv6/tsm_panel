import os
import subprocess
from PyQt5.QtWidgets import QDialog, QFileDialog, QMessageBox
from qgis.core import QgsProject
from PyQt5 import uic  # For loading .ui dynamically
from .tsm_settings import Config

from .hydra_ui import Ui_DialogHydra

# Run-mode preset -> (MACRO_MODEL, default Meso FTYPEs, signals on).
#   PointQueue           = point queue, free-flow below capacity
#   PointQueue + BPR     = point queue with BPR/VDF running time below capacity (hybrid)
#   LTM                  = Link Transmission Model (spillback)
#   LTM + Meso           = LTM + selected FTYPEs run mesoscopic
#   LTM + Meso + Signals = + signal-delay model at signalized nodes
MACRO_PRESETS = {
    "PointQueue":           ("DTA_PointQueue", "", False),
    "PointQueue + BPR":     ("DTA_PointQueue", "", False),
    "LTM":                  ("DTA_LTM", "", False),
    "LTM + Meso":           ("DTA_LTM", "11,91,93,94", False),
    "LTM + Meso + Signals": ("DTA_LTM", "11,91,93,94", True),
}


class HydraAssignModel(QDialog, Ui_DialogHydra):
    def __init__(self):
        super().__init__()

        settings = Config()
        plugin_dir = settings.get("plugin_dir")
        ui_file = os.path.join(plugin_dir, "ui/hydra.ui")
        if not os.path.exists(ui_file):
            print(f"UI file not found at: {ui_file}")
            return
        uic.loadUi(ui_file, self)

        self.textBrowser.setOpenExternalLinks(True)
        self._load_help_doc(os.path.join(plugin_dir, "docs", "HYDRA.md"))

        # Threads default from General Configuration
        self.lineEdit_Threads.setText(str(settings.get("num_processors") or "0"))

        # Link/Node are GeoPackage layers loaded in QGIS; converted to CSV at run
        # time via gpkgcsv.exe.
        self.populate_layer_combobox(self.comboBox_LinkLayer, "LineString")
        self.populate_layer_combobox(self.comboBox_NodeLayer, "Point")

        scen = settings.get("scenarioDir")
        if scen:
            self.lineEdit_OutDir.setText(scen)
        if settings.get("link_layer_name"):
            self._select_combo(self.comboBox_LinkLayer, settings.get("link_layer_name"))
        if settings.get("node_layer_name"):
            self._select_combo(self.comboBox_NodeLayer, settings.get("node_layer_name"))

        # Connections
        self.browse_TripFile.clicked.connect(lambda: self.select_file(self.lineEdit_TripFile, "Trip list (*.csv.gz *.csv)"))
        self.browse_TollPolicy.clicked.connect(lambda: self.select_file(self.lineEdit_TollPolicy, "CSV (*.csv)"))
        self.browse_OutDir.clicked.connect(self.select_out_dir)
        self.comboBox_Macro.currentTextChanged.connect(self.apply_macro_preset)
        self.checkBox_Micro.toggled.connect(self.toggle_micro)
        self.run_Hydra.clicked.connect(lambda: self.run_hydra(show_message=True))
        self.buttonBox.accepted.connect(self.update_settings)
        self.buttonBox.rejected.connect(self.reject)

        self.apply_macro_preset(self.comboBox_Macro.currentText())
        self.toggle_micro(self.checkBox_Micro.isChecked())

    # ------------------------------------------------------------------
    def _load_help_doc(self, md_path):
        try:
            with open(md_path, "r", encoding="utf-8") as f:
                md = f.read()
        except Exception as e:
            print(f"Could not read help doc {md_path}: {e}")
            return
        if hasattr(self.textBrowser, "setMarkdown"):
            self.textBrowser.setMarkdown(md)
        else:
            self.textBrowser.setPlainText(md)

    def apply_macro_preset(self, name):
        _, meso, _ = MACRO_PRESETS.get(name, ("DTA_PointQueue", "", False))
        self.lineEdit_MesoFtypes.setText(meso)

    def toggle_micro(self, on):
        self.lineEdit_MicroFtypes.setEnabled(on)
        self.comboBox_Coupling.setEnabled(on)
        self.comboBox_MicroChoice.setEnabled(on)

    def select_file(self, line_edit, file_filter):
        path, _ = QFileDialog.getOpenFileName(self, "Select File", "", file_filter + ";; All Files (*)")
        if path:
            line_edit.setText(path)

    def select_out_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if d:
            self.lineEdit_OutDir.setText(d)

    def populate_layer_combobox(self, combobox, geom_type):
        combobox.clear()
        combobox.addItem("Select a layer", None)
        for layer in [l for l in QgsProject.instance().mapLayers().values() if hasattr(l, "geometryType")]:
            if layer.geometryType() == {"Point": 0, "LineString": 1, "Polygon": 2}[geom_type]:
                combobox.addItem(layer.name(), layer)

    def get_layer_path(self, layer):
        if layer is None:
            return None
        return layer.dataProvider().dataSourceUri().split("|")[0]

    def _select_combo(self, combo, text):
        if text and text in [combo.itemText(i) for i in range(combo.count())]:
            combo.setCurrentText(text)

    def update_settings(self):
        settings = Config()
        settings.set("hydra_macro", self.comboBox_Macro.currentText())
        settings.set("hydra_iters", self.lineEdit_Iters.text())
        settings.set("hydra_gap", self.lineEdit_Gap.text())
        settings.set("link_layer_name", self.comboBox_LinkLayer.currentText())
        settings.set("node_layer_name", self.comboBox_NodeLayer.currentText())
        settings.check_and_save_to_file("scenario_settings_file")
        QMessageBox.information(self, "Settings Updated", "HyDRA settings have been updated.")

    # ------------------------------------------------------------------
    def run_hydra(self, show_message=False):
        settings = Config()
        tsm_location = settings.get("tsm_location")

        link_layer = self.comboBox_LinkLayer.currentData()
        node_layer = self.comboBox_NodeLayer.currentData()
        trip_file = self.lineEdit_TripFile.text().strip()
        out_dir = self.lineEdit_OutDir.text().strip()
        if not (link_layer and node_layer and trip_file and out_dir):
            QMessageBox.critical(self, "Error", "Please select the Link layer, Node layer, Trip list, and Output directory.")
            return False

        macro = self.comboBox_Macro.currentText()
        macro_model, _, signals = MACRO_PRESETS.get(macro, ("DTA_PointQueue", "", False))
        meso = self.lineEdit_MesoFtypes.text().strip()
        toll_policy = self.lineEdit_TollPolicy.text().strip()

        afdta = os.path.join(tsm_location, "Apps", "Hydra", "afdta.exe")
        if not os.path.exists(afdta):
            QMessageBox.critical(self, "Error", f"afdta.exe not found at: {afdta}")
            return False

        # Convert the GeoPackage link/node layers to CSV (gpkgcsv.exe), then run.
        gpkgcsv = os.path.join(tsm_location, "Apps", "LinkConsolidator", "gpkgcsv.exe")
        if not os.path.exists(gpkgcsv):
            QMessageBox.critical(self, "Error", f"gpkgcsv.exe not found at: {gpkgcsv}")
            return False
        link_csv = os.path.join(out_dir, "Link_hydra.csv")
        node_csv = os.path.join(out_dir, "Node_hydra.csv")
        try:
            for src_layer, dst, label in ((link_layer, link_csv, "link"), (node_layer, node_csv, "node")):
                src = self.get_layer_path(src_layer)
                r = subprocess.run([gpkgcsv, "to-csv", src, dst, "--drop-geom"],
                                   env=Config().app_env(gpkgcsv))
                if r.returncode != 0 or not os.path.exists(dst):
                    QMessageBox.critical(self, "Error", f"Failed to convert {label} layer to CSV.")
                    return False
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error converting layers to CSV: {e}")
            return False

        ctl = os.path.join(out_dir, "hydra_run.ctl")
        try:
            with open(ctl, "w") as f:
                f.write("# AgentFlow DTA control - generated by the HyDRA dialog\n")
                f.write(f"NODE_FILE              {node_csv}\n")
                f.write(f"LINK_FILE              {link_csv}\n")
                f.write(f"TRIP_FILE             {trip_file}\n")
                f.write(f"OUTPUT_DIRECTORY      {out_dir}\n")
                f.write(f"MACRO_MODEL           {macro_model}\n")
                f.write(f"MAX_ITERATIONS        {self.lineEdit_Iters.text().strip() or '30'}\n")
                f.write(f"RELATIVE_GAP          {self.lineEdit_Gap.text().strip() or '0.01'}\n")
                f.write(f"ROUTE_CHUNKS          {self.lineEdit_Chunks.text().strip() or '10'}\n")
                f.write(f"THREADS               {self.lineEdit_Threads.text().strip() or '0'}\n")
                if meso:
                    f.write(f"MESO_FTYPE            {meso}\n")
                if signals:
                    f.write("SIGNAL_MODEL          YES\n")
                if toll_policy:
                    f.write(f"TOLL_POLICY_FILE      {toll_policy}\n")
                if self.checkBox_Micro.isChecked():
                    micro_ft = self.lineEdit_MicroFtypes.text().strip()
                    f.write("MICRO_CORRIDOR        YES\n")
                    if micro_ft:
                        f.write(f"MICRO_FTYPE           {micro_ft}\n")
                    f.write(f"MICRO_COUPLING        {self.comboBox_Coupling.currentText()}\n")
                    # EL/GP choice inside the micro corridor: meso logit vs micro
                    # time-differential converted by each agent's VOT.
                    if self.comboBox_MicroChoice.currentText().startswith("Meso"):
                        f.write("MICRO_CHOICE          MODEA\n")
                    else:
                        f.write("MICRO_CHOICE          ENDOGENOUS\n")
                # Link performance (macro/meso/micro) is always written by the engine.
                # Agent plans/paths are optional and can be heavy.
                write_agents = self.checkBox_AgentPlans.isChecked() or self.checkBox_AgentPaths.isChecked()
                if write_agents:
                    f.write(f"WRITE_AGENT_RESULTS   {'DUCKDB' if self.checkBox_DuckDB.isChecked() else 'CSV'}\n")
                else:
                    f.write("WRITE_AGENT_RESULTS   NO\n")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error writing hydra_run.ctl: {e}")
            return False

        print(f"afdta   : {afdta}")
        print(f"control : {ctl}")
        try:
            result = subprocess.run([afdta, "--control", ctl])
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error running afdta: {e}")
            return False
        if result.returncode != 0:
            QMessageBox.critical(self, "Error", "AgentFlow DTA run failed. Check console for details.")
            return False

        if show_message:
            QMessageBox.information(self, "Success", f"HyDRA (AgentFlow-DTA) completed.\n\nOutputs in: {out_dir}")
        return True
