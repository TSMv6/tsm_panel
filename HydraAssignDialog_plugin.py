import os
import subprocess
from PyQt5.QtWidgets import QDialog, QFileDialog, QMessageBox
from qgis.core import QgsProject
from PyQt5 import uic  # For loading .ui dynamically
from .tsm_settings import Config
from .model_run import run_gated_model, begin_run_console, closes_run_console

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

        # Threads default from General Configuration (num_processors) but stay editable
        # for a one-off run. Not persisted as a HyDRA setting -- it re-seeds from
        # General Configuration each time the dialog opens.
        self.lineEdit_Threads.setText(str(settings.get("num_processors") or "0"))
        self.lineEdit_Threads.setToolTip("Defaults from General Configuration (number of "
                                         "processors). Edit for this run only; not saved.")

        # Link/Node are GeoPackage layers loaded in QGIS; converted to CSV at run
        # time via gpkgcsv.exe.
        self.populate_layer_combobox(self.comboBox_LinkLayer, "LineString")
        self.populate_layer_combobox(self.comboBox_NodeLayer, "Point")

        # HyDRA always writes to the scenario directory (no separate output field).
        self._out_dir = (settings.get("scenarioDir") or "").replace("\\", "/")
        if settings.get("link_layer_name"):
            self._select_combo(self.comboBox_LinkLayer, settings.get("link_layer_name"))
        if settings.get("node_layer_name"):
            self._select_combo(self.comboBox_NodeLayer, settings.get("node_layer_name"))

        # Connections
        self.browse_TripFile.clicked.connect(lambda: self.select_file(self.lineEdit_TripFile, "Trip list (*.csv.gz *.csv)"))
        self.browse_TollPolicy.clicked.connect(lambda: self.select_file(self.lineEdit_TollPolicy, "CSV (*.csv)"))
        self.browse_SegParams.clicked.connect(lambda: self.select_file(self.lineEdit_SegParams, "CSV (*.csv)"))
        self.comboBox_Macro.currentTextChanged.connect(self.apply_macro_preset)
        self.checkBox_Micro.toggled.connect(self.toggle_micro)
        self.run_Hydra.clicked.connect(lambda: self.run_hydra(show_message=True))
        self.buttonBox.accepted.connect(self.update_settings)
        self.buttonBox.rejected.connect(self.reject)

        # Restore everything the Save button persists, so the dialog reopens with
        # the user's last HyDRA settings (not just the defaults).
        def _b(key):
            v = settings.get(key)
            return str(v).lower() in ("true", "1", "yes") if v is not None else False

        if settings.get("hydra_macro"):
            self._select_combo(self.comboBox_Macro, settings.get("hydra_macro"))
        if settings.get("hydra_iters"):
            self.lineEdit_Iters.setText(str(settings.get("hydra_iters")))
        if settings.get("hydra_gap"):
            self.lineEdit_Gap.setText(str(settings.get("hydra_gap")))
        if settings.get("hydra_chunks"):
            self.lineEdit_Chunks.setText(str(settings.get("hydra_chunks")))
        if settings.get("hydra_trip_file"):
            self.lineEdit_TripFile.setText(settings.get("hydra_trip_file"))
        if settings.get("hydra_toll_policy"):
            self.lineEdit_TollPolicy.setText(settings.get("hydra_toll_policy"))
        if settings.get("hydra_segment_params"):
            self.lineEdit_SegParams.setText(settings.get("hydra_segment_params"))
        # Advanced numeric keys (each falls back to the .ui default if unset).
        for key, edit in (("hydra_reroute_fraction", self.lineEdit_RerouteFraction),
                          ("hydra_reroute_threshold", self.lineEdit_RerouteThreshold),
                          ("hydra_ltm_spillback", self.lineEdit_LtmSpillback),
                          ("hydra_jam_density", self.lineEdit_JamDensity),
                          ("hydra_max_trips", self.lineEdit_MaxTrips),
                          ("hydra_sample_every", self.lineEdit_SampleEvery)):
            if settings.get(key) not in (None, ""):
                edit.setText(str(settings.get(key)))
        if settings.get("hydra_micro_ftypes"):
            self.lineEdit_MicroFtypes.setText(settings.get("hydra_micro_ftypes"))
        if settings.get("hydra_coupling"):
            self._select_combo(self.comboBox_Coupling, settings.get("hydra_coupling"))
        if settings.get("hydra_micro_choice"):
            self._select_combo(self.comboBox_MicroChoice, settings.get("hydra_micro_choice"))
        self.checkBox_Micro.setChecked(_b("hydra_micro_enabled"))
        self.checkBox_AgentPlans.setChecked(_b("hydra_agent_plans"))
        self.checkBox_AgentPaths.setChecked(_b("hydra_agent_paths"))
        self.checkBox_DuckDB.setChecked(_b("hydra_duckdb"))

        # apply_macro_preset() overwrites Meso FTYPEs from the preset, so restore the
        # saved override AFTER it; toggle_micro() applies the enable state.
        self.apply_macro_preset(self.comboBox_Macro.currentText())
        if settings.get("hydra_meso_ftypes"):
            self.lineEdit_MesoFtypes.setText(settings.get("hydra_meso_ftypes"))
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
        # Equilibrium / run mode
        settings.set("hydra_macro", self.comboBox_Macro.currentText())
        settings.set("hydra_iters", self.lineEdit_Iters.text())
        settings.set("hydra_gap", self.lineEdit_Gap.text())
        settings.set("hydra_chunks", self.lineEdit_Chunks.text())
        # Threads are NOT persisted here -- they come from General Configuration.
        # Inputs / outputs (output dir is always the scenario directory)
        settings.set("hydra_trip_file", self.lineEdit_TripFile.text())
        settings.set("link_layer_name", self.comboBox_LinkLayer.currentText())
        settings.set("node_layer_name", self.comboBox_NodeLayer.currentText())
        # Meso / Micro
        settings.set("hydra_meso_ftypes", self.lineEdit_MesoFtypes.text())
        settings.set("hydra_micro_enabled", self.checkBox_Micro.isChecked())
        settings.set("hydra_micro_ftypes", self.lineEdit_MicroFtypes.text())
        settings.set("hydra_coupling", self.comboBox_Coupling.currentText())
        settings.set("hydra_micro_choice", self.comboBox_MicroChoice.currentText())
        settings.set("hydra_toll_policy", self.lineEdit_TollPolicy.text())
        # Generalized cost + advanced (afdta) tuning
        settings.set("hydra_segment_params", self.lineEdit_SegParams.text())
        settings.set("hydra_reroute_fraction", self.lineEdit_RerouteFraction.text())
        settings.set("hydra_reroute_threshold", self.lineEdit_RerouteThreshold.text())
        settings.set("hydra_ltm_spillback", self.lineEdit_LtmSpillback.text())
        settings.set("hydra_jam_density", self.lineEdit_JamDensity.text())
        settings.set("hydra_max_trips", self.lineEdit_MaxTrips.text())
        settings.set("hydra_sample_every", self.lineEdit_SampleEvery.text())
        # Output toggles
        settings.set("hydra_agent_plans", self.checkBox_AgentPlans.isChecked())
        settings.set("hydra_agent_paths", self.checkBox_AgentPaths.isChecked())
        settings.set("hydra_duckdb", self.checkBox_DuckDB.isChecked())
        settings.check_and_save_to_file("scenario_settings_file")
        QMessageBox.information(self, "Settings Updated", "HyDRA settings have been updated.")

    # ------------------------------------------------------------------
    @closes_run_console
    def run_hydra(self, show_message=False):
        settings = Config()
        tsm_location = settings.get("tsm_location")

        link_layer = self.comboBox_LinkLayer.currentData()
        node_layer = self.comboBox_NodeLayer.currentData()
        trip_file = self.lineEdit_TripFile.text().strip()
        out_dir = (settings.get("scenarioDir") or "").replace("\\", "/")
        if not (link_layer and node_layer and trip_file and out_dir):
            QMessageBox.critical(self, "Error", "Please select the Link layer, Node layer, and Trip list (output goes to the scenario directory).")
            return False
        # One live-tail window for the whole Hydra run (no per-step black windows).
        begin_run_console(os.path.join(out_dir, "Hydra.log"), "AgentFlow / Hydra - run log")

        macro = self.comboBox_Macro.currentText()
        macro_model, _, signals = MACRO_PRESETS.get(macro, ("DTA_PointQueue", "", False))
        meso = self.lineEdit_MesoFtypes.text().strip()
        toll_policy = self.lineEdit_TollPolicy.text().strip()

        afdta = settings.app_exe("Hydra/afdta.exe")
        if not os.path.exists(afdta):
            QMessageBox.critical(self, "Error", f"afdta.exe not found at: {afdta}")
            return False

        # Convert the GeoPackage link/node layers to CSV (gpkgcsv.exe), then run.
        gpkgcsv = settings.app_exe("utilities/gpkgcsv.exe")
        if not os.path.exists(gpkgcsv):
            QMessageBox.critical(self, "Error", f"gpkgcsv.exe not found at: {gpkgcsv}")
            return False
        link_csv = os.path.join(out_dir, "Link_hydra.csv")
        node_csv = os.path.join(out_dir, "Node_hydra.csv")
        convert_log = os.path.join(out_dir, "Hydra_convert.log")
        try:
            for i, (src_layer, dst, label) in enumerate(((link_layer, link_csv, "link"), (node_layer, node_csv, "node"))):
                src = self.get_layer_path(src_layer)
                r = Config().run_app([gpkgcsv, "to-csv", src, dst, "--drop-geom"],
                                     log_path=convert_log, console=True, append=(i > 0))
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
                # Generalized-cost segment params (beta_time/beta_cost/distance per
                # market segment). Without it afdta falls back to time-only GC.
                seg_params = self.lineEdit_SegParams.text().strip()
                if seg_params:
                    f.write(f"SEGMENT_PARAM_FILE    {seg_params}\n")
                # Rerouting controls
                f.write(f"REROUTE_FRACTION_MIN  {self.lineEdit_RerouteFraction.text().strip() or '0.05'}\n")
                f.write(f"REROUTE_THRESHOLD_MIN {self.lineEdit_RerouteThreshold.text().strip() or '0.01'}\n")
                # LTM / spillback (used by the LTM macro models)
                f.write(f"LTM_MAX_SPILLBACK_MIN {self.lineEdit_LtmSpillback.text().strip() or '20'}\n")
                f.write(f"JAM_DENSITY           {self.lineEdit_JamDensity.text().strip() or '240'}\n")
                # Sampling / limits
                f.write(f"MAX_TRIPS             {self.lineEdit_MaxTrips.text().strip() or '0'}\n")
                f.write(f"SAMPLE_EVERY          {self.lineEdit_SampleEvery.text().strip() or '1'}\n")
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

        hydra_log = os.path.join(out_dir, "Hydra.log")
        print(f"afdta   : {afdta}")
        print(f"control : {ctl}")
        print(f"log     : {hydra_log}")
        if not run_gated_model(self, [afdta, "--control", ctl], "HyDRA (AgentFlow-DTA)",
                               log_path=hydra_log, console=True):
            return False

        if show_message:
            QMessageBox.information(self, "Success", f"HyDRA (AgentFlow-DTA) completed.\n\nOutputs in: {out_dir}")
        return True
