import os
import subprocess
from qgis.PyQt.QtWidgets import QDialog, QFileDialog, QMessageBox
from qgis.core import QgsProject
from qgis.PyQt import uic  # For loading .ui dynamically
from .tsm_settings import Config
from .model_run import run_gated_model, begin_run_console, closes_run_console

from .hydra_ui import Ui_DialogHydra

# Default meso extent: the full limited-access system (freeways 11/12, ramps
# 71-79, toll roads 91-94, express lanes 96-98) runs mesoscopic so flow
# conserves across it.
MESO_LIMITED_ACCESS = "11,12,71,72,75,76,79,91,92,93,94,96,97,98"

# Run-mode preset -> (MACRO_MODEL, default Meso FTYPEs, signals on).
#   PointQueue + BPR = point queue with BPR/VDF running time below capacity (hybrid)
#   Node-conserving loaders (NodeDnl): N_out == N_in at every interior node.
#   NodePQ = inflow-capacity receiving, NodeLTM = spatial storage/spillback.
#   Default = Node + Spatial/LTM with meso on the limited-access system.
MACRO_PRESETS = {
    "PointQueue + BPR":              ("DTA_PointQueue", "", False),
    "Node + PointQueue (nodeDNL)":   ("DTA_NodePQ", MESO_LIMITED_ACCESS, False),
    "Node + Spatial/LTM (nodeDNL)":  ("DTA_NodeLTM", MESO_LIMITED_ACCESS, False),
}
_DEFAULT_PRESET = ("DTA_NodeLTM", MESO_LIMITED_ACCESS, False)

# Per-iteration node-DNL refresh stride (NODE_SCHEDULE). Maps the GUI label to the
# control-file value; "hybrid" is expanded to an iteration ramp at write time
# (cheap per_iter through the sampling stages, a short per_chunk polish at the end).
NODE_SCHEDULES = {
    "Per iteration (fast - statewide)": "per_iter",
    "Per chunk (tight - county)":       "per_chunk",
    "Hybrid (per-iter -> per-chunk)":   "hybrid",
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

        # Default output location; the Output directory field (blank = scenario
        # directory) overrides it at run time via _resolve_out_dir.
        self._out_dir = (settings.get("scenarioDir") or "").replace("\\", "/")
        if settings.get("link_layer_name"):
            self._select_combo(self.comboBox_LinkLayer, settings.get("link_layer_name"))
        if settings.get("node_layer_name"):
            self._select_combo(self.comboBox_NodeLayer, settings.get("node_layer_name"))

        # Connections
        self.browse_TripFile.clicked.connect(lambda: self.select_file(self.lineEdit_TripFile, "Trip list (*.csv.gz *.csv)"))
        self.browse_OutDir.clicked.connect(self._browse_out_dir)
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
        if settings.get("hydra_node_schedule"):
            self._select_node_schedule(settings.get("hydra_node_schedule"))
        if settings.get("hydra_trip_file"):
            self.lineEdit_TripFile.setText(settings.get("hydra_trip_file"))
        if settings.get("hydra_out_dir"):
            self.lineEdit_OutDir.setText(settings.get("hydra_out_dir"))
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
        # Both agent artifacts default ON; only an explicit saved "false" unchecks.
        def _b_on(key):
            v = settings.get(key)
            return True if v in (None, "") else str(v).lower() in ("true", "1", "yes")
        self.checkBox_AgentPlans.setChecked(_b_on("hydra_agent_plans"))
        self.checkBox_AgentPaths.setChecked(_b_on("hydra_agent_paths"))

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
        _, meso, _ = MACRO_PRESETS.get(name, _DEFAULT_PRESET)
        self.lineEdit_MesoFtypes.setText(meso)

    def _select_node_schedule(self, value):
        """Select the node-schedule combo from a saved control value (per_iter /
        per_chunk / hybrid)."""
        for text, val in NODE_SCHEDULES.items():
            if val == value:
                self._select_combo(self.comboBox_NodeSchedule, text)
                return

    def _node_schedule_value(self):
        """NODE_SCHEDULE control value from the combo. 'hybrid' expands to an
        iteration ramp: cheap per_iter for most iterations, a short per_chunk
        polish at the end (last ~15%, min 3) to restore the AM/PM peaks."""
        val = NODE_SCHEDULES.get(self.comboBox_NodeSchedule.currentText(), "per_iter")
        if val != "hybrid":
            return val
        try:
            iters = int(float(self.lineEdit_Iters.text().strip() or "10"))
        except ValueError:
            iters = 10
        split = max(1, iters - max(3, round(iters * 0.15)))
        return "per_chunk" if split >= iters else f"1-{split}:iter, {split+1}-{iters}:chunk"

    def toggle_micro(self, on):
        self.lineEdit_MicroFtypes.setEnabled(on)
        self.comboBox_Coupling.setEnabled(on)
        self.comboBox_MicroChoice.setEnabled(on)

    def select_file(self, line_edit, file_filter):
        path, _ = QFileDialog.getOpenFileName(self, "Select File", "", file_filter + ";; All Files (*)")
        if path:
            line_edit.setText(path)

    def _browse_out_dir(self):
        settings = Config()
        start = self.lineEdit_OutDir.text().strip() or settings.get("scenarioDir") or ""
        path = QFileDialog.getExistingDirectory(self, "Select HyDRA output directory", start)
        if path:
            self.lineEdit_OutDir.setText(path)

    def _resolve_out_dir(self, settings):
        """User's output directory, defaulting to the scenario directory when
        blank (the panel-wide convention). Created if it does not exist."""
        out_dir = (self.lineEdit_OutDir.text().strip()
                   or settings.get("scenarioDir") or "").replace("\\", "/")
        if out_dir and not os.path.isdir(out_dir):
            try:
                os.makedirs(out_dir, exist_ok=True)
            except OSError:
                pass
        return out_dir

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
        settings.set("hydra_node_schedule",
                     NODE_SCHEDULES.get(self.comboBox_NodeSchedule.currentText(), "per_iter"))
        # Threads are NOT persisted here -- they come from General Configuration.
        # Inputs / outputs (blank output dir = scenario directory at run time)
        settings.set("hydra_trip_file", self.lineEdit_TripFile.text())
        settings.set("hydra_out_dir", self.lineEdit_OutDir.text().strip())
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
        settings.check_and_save_to_file("scenario_settings_file")
        QMessageBox.information(self, "Settings Updated", "HyDRA settings have been updated.")

    # ------------------------------------------------------------------
    @closes_run_console
    def run_hydra(self, show_message=False):
        settings = Config()
        tsm_location = settings.get("tsm_location")

        link_layer = self.comboBox_LinkLayer.currentData()
        node_layer = self.comboBox_NodeLayer.currentData()
        # Network input: dialog dropdown when standalone; in a full run (or when
        # nothing is picked) chain off the Link Consolidator outputs.
        sel_link = self.get_layer_path(link_layer) if link_layer else ""
        sel_node = self.get_layer_path(node_layer) if node_layer else ""
        link_path, node_path = settings.resolve_network_paths(sel_link, sel_node)
        trip_file = self.lineEdit_TripFile.text().strip()
        out_dir = self._resolve_out_dir(settings)
        if not (link_path and node_path and trip_file and out_dir):
            QMessageBox.critical(self, "Error", "Need a Link network, Node network, and Trip list. Pick the layers here, or run Link Consolidation first (output goes to the scenario directory).")
            return False
        # One live-tail window for the whole Hydra run (no per-step black windows).
        begin_run_console(os.path.join(out_dir, "Hydra.log"), "AgentFlow / Hydra - run log")

        macro = self.comboBox_Macro.currentText()
        macro_model, _, signals = MACRO_PRESETS.get(macro, _DEFAULT_PRESET)
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
            for i, (src, dst, label) in enumerate(((link_path, link_csv, "link"), (node_path, node_csv, "node"))):
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
                f.write(f"MAX_ITERATIONS        {self.lineEdit_Iters.text().strip() or '10'}\n")
                f.write(f"RELATIVE_GAP          {self.lineEdit_Gap.text().strip() or '0.01'}\n")
                f.write(f"ROUTE_CHUNKS          {self.lineEdit_Chunks.text().strip() or '10'}\n")
                # Node-DNL refresh stride (per_iter / per_chunk / hybrid ramp).
                # Only the DTA_Node* loaders run the node sim, but the key is
                # harmless for the others.
                f.write(f"NODE_SCHEDULE         {self._node_schedule_value()}\n")
                f.write(f"THREADS               {self.lineEdit_Threads.text().strip() or '0'}\n")
                # Per-purpose volume columns in every link_performance_
                # <Macro|Meso|Micro>DTA.csv (vol_<purpose> sums to volume).
                f.write("LINK_VOLUME_BREAKDOWN Purpose\n")
                if meso:
                    f.write(f"MESO_FTYPE            {meso}\n")
                    # Anti-gridlock breaker -- MESO ONLY, so these keys are
                    # written inside the `if meso` block and never appear in a
                    # macro-only control file.
                    #
                    # The engine defaults are meso_breaker_rate=0 ("legacy") and
                    # meso_max_spillback_min=20, which together drain a
                    # deadlocked movement at ONE packet (<=3 veh) per 20 min =
                    # ~9 veh/hour. That cannot dissolve interchange rings: meso
                    # gridlocked by ~11am, reported 0.0-0.4% of daily volume per
                    # hour for the rest of the day, held 18.2% of freeway demand
                    # out of the network entirely, and diverted the rest onto
                    # arterials -- limited access scored ratio 0.588 / R2 0.060.
                    #
                    # Rate mode drains a timed-out movement at rate*capacity per
                    # step; cap_credit still gates every release so the forced
                    # rate can NEVER exceed link capacity (values >1.0 buy
                    # nothing). With rate 1.0 + a 5-minute timeout, measured on
                    # New_landuse: backlog 18.2% -> 5.1%, limited access
                    # 0.588/0.060 -> 0.862/0.253, tolls 0.617 -> 1.160, ramps
                    # 0.796 -> 1.106, statewide R2 0.353 -> 0.544, rel_gap
                    # 0.1038 -> 0.0827.
                    brk = (settings.get("hydra_meso_breaker_rate") or "1.0").strip()
                    spb = (settings.get("hydra_meso_spillback_min") or "5").strip()
                    if brk.lower() != "off":
                        f.write(f"MESO_BREAKER_RATE     {brk}\n")
                    if spb.lower() != "off":
                        f.write(f"MESO_MAX_SPILLBACK_MIN {spb}\n")
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
                # Discharge calibration: QLOS planning capacities (LOS-E service
                # volumes) under-state physical discharge in a hard-capacity DNL;
                # the calibrated per-FTYPE scale-ups from the assignment of record
                # are written by DEFAULT (omitting them collapses freeway loading
                # -- limited-access ratio 0.58 vs 1.06 calibrated). Override via
                # the hydra_discharge_factors setting ("ft:factor,ft:factor,...";
                # "off" suppresses the block entirely).
                df_setting = (settings.get("hydra_discharge_factors") or "").strip()
                if df_setting.lower() != "off":
                    factors = df_setting or ("11:1.15,21:1.15,31:1.15,41:1.15,"
                                             "45:1.15,48:1.15,71:1.2,91:1.15,"
                                             "93:1.15,94:1.15")
                    for pair in factors.split(","):
                        ft, _, val = pair.partition(":")
                        if ft.strip() and val.strip():
                            f.write(f"DISCHARGE_FACTOR_{ft.strip()}  {val.strip()}\n")
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
                # Two independent agent artifacts, both default ON:
                #   Agent plans -> agentPlans_out.csv (light per-agent summary)
                #   Agent paths -> agentPaths.duckdb (heavy: full key paths;
                #                  feeds agentAnalysis select-link/trace/tiers)
                f.write(f"WRITE_AGENT_PLANS     {'YES' if self.checkBox_AgentPlans.isChecked() else 'NO'}\n")
                f.write(f"WRITE_AGENT_PATHS     {'YES' if self.checkBox_AgentPaths.isChecked() else 'NO'}\n")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error writing hydra_run.ctl: {e}")
            return False

        # A new run rewrites agentPaths.duckdb, so any existing sidecar link
        # index (agentPaths_index.duckdb) would describe the OLD paths. Delete
        # it here -- the authoritative place to know the pairing is broken (a
        # timestamp check can't: the index may legitimately be built later).
        # Agent Analysis offers to rebuild it on demand, so nothing is lost.
        if self.checkBox_AgentPaths.isChecked():
            stale_idx = os.path.join(out_dir, "agentPaths_index.duckdb")
            if os.path.exists(stale_idx):
                try:
                    os.remove(stale_idx)
                    print(f"removed stale link index (new run rewrites agentPaths.duckdb): {stale_idx}")
                except OSError as e:
                    QMessageBox.warning(self, "Stale link index",
                                        "Could not delete the old agentPaths_index.duckdb "
                                        "(in use?). Delete it before running Agent Analysis "
                                        "on the new results:\n%s" % e)

        hydra_log = os.path.join(out_dir, "Hydra.log")
        print(f"afdta   : {afdta}")
        print(f"control : {ctl}")
        print(f"log     : {hydra_log}")
        if not run_gated_model(self, [afdta, "--control", ctl], "HyDRA (AgentFlow-DTA)",
                               log_path=hydra_log, console=True):
            return False

        # Loaded network: run summarize.exe on the link-performance outputs so
        # every HyDRA run ends with loaded_network.gpkg/_daily.csv ready to map.
        loaded_note = ""
        try:
            gp = self._auto_summarize(out_dir, link_path)
            loaded_note = f"\nLoaded network: {gp}" if gp else \
                          "\n(loaded-network summary failed - see summarize_hydra_run.log)"
        except Exception as e:
            loaded_note = f"\n(loaded-network summary failed: {e})"

        if show_message:
            QMessageBox.information(self, "Success",
                                    f"HyDRA (AgentFlow-DTA) completed.\n\nOutputs in: {out_dir}{loaded_note}")
        return True

    def _auto_summarize(self, out_dir, link_path):
        """Post-run loaded network: summarize.exe (hydra mode) over the macro /
        meso / micro link-performance CSVs joined to the run's link layer ->
        loaded_network.gpkg (+ _daily.csv), loaded into QGIS with the standard
        symbology. Returns the gpkg path, or None."""
        from .summarize_runner import run_summary
        macro_csv = os.path.join(out_dir, "link_performance_macroDTA.csv")
        if not os.path.exists(macro_csv):
            return None
        meso_csv = os.path.join(out_dir, "link_performance_mesoDTA.csv")
        micro_csv = os.path.join(out_dir, "link_performance_microDTA.csv")
        out_gpkg = os.path.join(out_dir, "loaded_network.gpkg").replace("\\", "/")
        # Release QGIS's handle if the previous run's loaded network is open --
        # otherwise the GeoPackage rewrite fails ("already exists" lock).
        proj = QgsProject.instance()
        target = os.path.normcase(os.path.abspath(out_gpkg))
        removed = 0
        for lyr in list(proj.mapLayers().values()):
            try:
                src = lyr.source().split("|")[0]
                if os.path.normcase(os.path.abspath(src)) == target:
                    proj.removeMapLayer(lyr.id())
                    removed += 1
            except Exception:
                continue
        if removed:
            try:
                import gc
                from qgis.PyQt.QtWidgets import QApplication
                gc.collect(); QApplication.processEvents(); gc.collect()
            except Exception:
                pass
        r = run_summary("summarize_hydra.toml", link_path, macro_csv, out_gpkg,
                        subarea=False,
                        vol2=meso_csv if os.path.exists(meso_csv) else None,
                        vol3=micro_csv if os.path.exists(micro_csv) else None)
        if r.returncode != 0 or not os.path.exists(out_gpkg):
            return None
        try:
            from qgis.core import QgsVectorLayer
            lyr = QgsVectorLayer(out_gpkg, "LoadedNetwork", "ogr")
            if lyr.isValid():
                qml = os.path.join(Config().get("plugin_dir") or "",
                                   "qgis_styles/TSM_Loaded_Symbology.qml")
                if os.path.exists(qml):
                    lyr.loadNamedStyle(qml)
                QgsProject.instance().addMapLayer(lyr)
        except Exception:
            pass
        return out_gpkg
