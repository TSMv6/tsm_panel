import os
import subprocess
from qgis.PyQt.QtWidgets import QDialog, QFileDialog, QMessageBox
from qgis.core import QgsProject
from qgis.PyQt import uic  # For loading .ui dynamically
from .tsm_settings import Config
from .model_run import run_gated_model, begin_run_console, closes_run_console, end_run_console

from .popsyn_ui import Ui_Dialog_PopSyn


class PopSynDialog(QDialog, Ui_Dialog_PopSyn):
    def __init__(self):
        super().__init__()

        settings = Config()
        plugin_dir = settings.get("plugin_dir")
        ui_file = os.path.join(plugin_dir, "ui/popsyn.ui")
        print(f"UI file found at: {ui_file}")
        if not os.path.exists(ui_file):
            print(f"UI file not found at: {ui_file}")
            return
        uic.loadUi(ui_file, self)
        self.setWindowTitle("PopSyn")  # display name: Population Synthesis (was PopSim)

        self.textBrowser.setOpenExternalLinks(True)
        self._load_help_doc(os.path.join(plugin_dir, "docs", "POPSYN.md"))

        # Land-use layer dropdowns (polygons)
        self.populate_layer_combobox(self.comboBox_LUlayer, "Polygon")
        self.populate_layer_combobox(self.comboBox_RefLUlayer, "Polygon")

        # Prefill from Config
        if settings.get("landuse_layer"):
            name = settings.get("landuse_layer")
            if name in [self.comboBox_LUlayer.itemText(i) for i in range(self.comboBox_LUlayer.count())]:
                self.comboBox_LUlayer.setCurrentText(name)
        if settings.get("synHH_file"):
            self.lineEdit_SynHH.setText(settings.get("synHH_file"))
        if settings.get("synPer_file"):
            self.lineEdit_SynPer.setText(settings.get("synPer_file"))
        if settings.get("GQ_in_POP"):
            self.checkBox_GQ.setChecked(settings.get("GQ_in_POP") is True)
        if settings.get("runPopsim_incrementally"):
            self.checkBox_Increment.setChecked(settings.get("runPopsim_incrementally") is True)
            if settings.get("refSynHH_file"):
                self.lineEdit_RefSynHH.setText(settings.get("refSynHH_file"))
            if settings.get("refSynPer_file"):
                self.lineEdit_RefSynPer.setText(settings.get("refSynPer_file"))
            if settings.get("ref_landuse_layer"):
                rname = settings.get("ref_landuse_layer")
                if rname in [self.comboBox_RefLUlayer.itemText(i) for i in range(self.comboBox_RefLUlayer.count())]:
                    self.comboBox_RefLUlayer.setCurrentText(rname)

        # Connections
        self.browse_SynHH.clicked.connect(lambda: self.select_file(self.lineEdit_SynHH, "save"))
        self.browse_SynPer.clicked.connect(lambda: self.select_file(self.lineEdit_SynPer, "save"))
        self.checkBox_Increment.clicked.connect(self.update_incremental_state)
        # Connect run/ok/cancel ONCE here. These must NOT live in
        # update_incremental_state(), which re-runs on every Increment toggle and
        # would stack duplicate connections -> the "settings saved" message (and a
        # run) firing multiple times.
        self.runPopSim.clicked.connect(lambda: self.run_popsim_script(show_message=True))
        self.okcancel_PopSIM.accepted.connect(self.update_settings)
        self.okcancel_PopSIM.rejected.connect(self.cancel_action)
        self.update_incremental_state()

    # ------------------------------------------------------------------
    # UI behaviour
    # ------------------------------------------------------------------
    def update_incremental_state(self):
        self.bool_run_incremental = self.checkBox_Increment.isChecked()
        self.increment_box.setEnabled(self.bool_run_incremental)

        if self.bool_run_incremental:
            self.browse_RefSynHH.setEnabled(True)
            self.browse_RefSynPer.setEnabled(True)
            self.populate_layer_combobox(self.comboBox_RefLUlayer, "Polygon")
            try:
                self.browse_RefSynHH.clicked.disconnect()
                self.browse_RefSynPer.clicked.disconnect()
            except TypeError:
                pass
            settings = Config()
            if settings.get("ref_landuse_layer"):
                self.comboBox_RefLUlayer.setCurrentText(settings.get("ref_landuse_layer"))
            self.browse_RefSynHH.clicked.connect(lambda: self.select_file(self.lineEdit_RefSynHH, "open"))
            self.browse_RefSynPer.clicked.connect(lambda: self.select_file(self.lineEdit_RefSynPer, "open"))
        else:
            self.browse_RefSynHH.setEnabled(False)
            self.browse_RefSynPer.setEnabled(False)

    def cancel_action(self):
        print("Action canceled. Closing dialog.")
        self.reject()

    def select_file(self, line_edit, type):
        if type == "open":
            file_path, _ = QFileDialog.getOpenFileName(self, "Select File", "", "csv (*.csv) ;; All Files (*)")
        else:
            file_path, _ = QFileDialog.getSaveFileName(self, "Select File", "", "csv (*.csv) ;; All Files (*)")
        if file_path:
            line_edit.setText(file_path)

    def populate_layer_combobox(self, combobox, geom_type):
        combobox.clear()
        combobox.addItem("Select a layer", None)
        layers = QgsProject.instance().mapLayers().values()
        vector_layers = [layer for layer in layers if hasattr(layer, "geometryType")]
        for layer in vector_layers:
            if layer.geometryType() == {"Point": 0, "LineString": 1, "Polygon": 2}[geom_type]:
                combobox.addItem(layer.name(), layer)

    def get_layer_path(self, layer):
        if layer is None:
            return None
        if isinstance(layer, str):
            return layer
        return layer.dataProvider().dataSourceUri().split("|")[0]

    def update_settings(self):
        settings = Config()
        if self.lineEdit_SynHH.text():
            settings.set("synHH_file", self.lineEdit_SynHH.text())
        if self.lineEdit_SynPer.text():
            settings.set("synPer_file", self.lineEdit_SynPer.text())
        if self.comboBox_LUlayer.currentData():
            settings.set("landuse_layer", self.comboBox_LUlayer.currentData().name())
        settings.set("GQ_in_POP", self.checkBox_GQ.isChecked())
        settings.set("runPopsim_incrementally", self.checkBox_Increment.isChecked())
        if self.checkBox_Increment.isChecked():
            settings.set("refSynHH_file", self.lineEdit_RefSynHH.text())
            settings.set("refSynPer_file", self.lineEdit_RefSynPer.text())
            if self.comboBox_RefLUlayer.currentData():
                settings.set("ref_landuse_layer", self.comboBox_RefLUlayer.currentData().name())
        settings.check_and_save_to_file("scenario_settings_file")
        QMessageBox.information(self, "Settings Updated", "PopSyn settings have been updated.")

    # ------------------------------------------------------------------
    # Helpers
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

    @staticmethod
    def _ensure_np_column(se_data):
        """Add an 'NP' column (= ResPOP, resident population) to the se_data CSV for
        PopSim's res_pop control. No-op if NP already present. Writes LF endings."""
        import csv
        with open(se_data, newline="") as f:
            rows = list(csv.reader(f))
        if not rows:
            return
        header = rows[0]
        if "NP" in header:
            return
        if "ResPOP" not in header:
            raise ValueError("se_data has neither 'NP' nor 'ResPOP'")
        ri = header.index("ResPOP")
        header.append("NP")
        for r in rows[1:]:
            r.append(r[ri] if ri < len(r) else "")
        with open(se_data, "w", newline="") as f:
            csv.writer(f, lineterminator="\n").writerows(rows)
        print(f"Added NP column (= ResPOP) to {se_data}")

    @staticmethod
    def _generate_toml(template_path, out_path, scenario_dir, threads, tsm_location="", plugin_dir="",
                       se_data=""):
        """Fill {scenario_dir}, {se_data}, {threads}, {tsm_location} and {plugin_dir}
        in a template TOML. se_data + output stay per-scenario; the large
        seeds/crosswalk live under {tsm_location}/Inputs/popsim_seed; the popsim
        CONTROLS ship inside the plugin at {plugin_dir}/config/popsim."""
        with open(template_path, "r", encoding="utf-8") as f:
            text = f.read()
        text = text.replace("{se_data}", str(se_data).replace("\\", "/"))
        text = text.replace("{scenario_dir}", scenario_dir.replace("\\", "/"))
        text = text.replace("{tsm_location}", str(tsm_location).replace("\\", "/").rstrip("/"))
        text = text.replace("{plugin_dir}", str(plugin_dir).replace("\\", "/").rstrip("/"))
        text = text.replace("{threads}", str(threads))
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"Wrote TOML: {out_path}")

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------
    @closes_run_console
    def run_popsim_script(self, show_message=False):
        settings = Config()
        scenario_dir = settings.get("scenarioDir")
        # Resolve to the v6 default if the General Configuration was never opened
        # this session (in-memory setting), and seed it back so every downstream
        # step (se_aggregate, popsim TOML) gets an absolute TSM root, not a path
        # relative to the process cwd.
        tsm_location = settings.tsm_root()
        settings.set("tsm_location", tsm_location)
        plugin_dir = settings.get("plugin_dir")
        threads = settings.get("num_processors") or "0"

        if not scenario_dir:
            QMessageBox.warning(self, "Warning", "Please set a scenario directory in Project Settings.")
            return False

        # One live-tail window for the whole PopSyn run (no per-step black windows).
        begin_run_console(os.path.join(scenario_dir, "PopSyn.log"), "PopSyn - run log")

        landuse_layer = self.comboBox_LUlayer.currentData()
        if not landuse_layer:
            QMessageBox.warning(self, "Warning", "Please select a land-use layer.")
            return False

        # Incremental: PopSyn is synthesized on the land-use DELTA
        # (scenario - reference), then merged into the reference synthetic
        # population (add growth, remove shrink) keeping household ids consistent.
        # NOTE: the delta is for PopSyn only -- SDT and LDT use the full
        # user-supplied land use (handled in their own dialogs).
        incremental = self.checkBox_Increment.isChecked()
        ref_landuse_path = ref_synhh = ref_synper = None
        if incremental:
            ref_layer = self.comboBox_RefLUlayer.currentData()
            if not ref_layer:
                QMessageBox.warning(self, "Warning", "Incremental: select a reference (base) land-use layer.")
                return False
            ref_landuse_path = self.get_layer_path(ref_layer)
            ref_synhh = self.lineEdit_RefSynHH.text().strip()
            ref_synper = self.lineEdit_RefSynPer.text().strip()
            if not (ref_synhh and ref_synper and os.path.exists(ref_synhh) and os.path.exists(ref_synper)):
                QMessageBox.warning(self, "Warning",
                    "Incremental: select existing reference synthetic Households and Persons files.")
                return False

        # Resolve apps
        popsim_exe = settings.app_exe("popsim/popsim-run.exe")
        se_agg_exe = settings.app_exe("utilities/se_aggregate.exe")
        popsimprep_exe = settings.app_exe("utilities/popsimprep.exe")  # HH+GQ combine (C++) + incremental append
        for path, label in ((popsim_exe, "popsim-run.exe"),
                            (se_agg_exe, "se_aggregate.exe"),
                            (popsimprep_exe, "popsimprep.exe")):
            if not os.path.exists(path):
                QMessageBox.critical(self, "Error", f"{label} not found at: {path}")
                return False

        # Utilities for the incremental path (delta land use + reference append).
        ldelta_exe = settings.app_exe("utilities/landuse_delta.exe")
        if incremental:
            for path, label in ((ldelta_exe, "landuse_delta.exe"), (popsimprep_exe, "popsimprep.exe")):
                if not os.path.exists(path):
                    QMessageBox.critical(self, "Error", f"{label} not found at: {path}")
                    return False

        # 1) Build the PopSim control land use (se_data). The level follows
        # Project Settings > Model Resolution: MSR, or Standard TSM with "PopSyn
        # at RPM level statewide", synthesizes in the land use's own zones
        # (PopSyn_Index: the 26k land use, or model_zones_landuse.gpkg, whose TSM
        # rows carry PopSyn_Index = TSM_NG); Standard TSM otherwise aggregates to
        # TSM_NG, whichever layer is picked. Both write popsyn_landuse.csv, and the
        # combine step gives every household TAZ = its TSM zone (demand models)
        # plus PopSyn_Index = the zone it was synthesized in (= TAZ at TSM level).
        # A land use without PopSyn_Index aggregates to TSM_NG as before
        # (tsm_landuse.csv joined to {tsm_location}/Inputs/landuse/tsm_landuse_default.csv).
        landuse_path = self.get_layer_path(landuse_layer)
        has_index = landuse_layer.fields().indexOf("PopSyn_Index") >= 0
        rpm_level = (settings.get("model_structure") == "MSR" or
                     str(settings.get("popsyn_rpm_statewide")) in ("True", "true", "1"))
        by_index = has_index and rpm_level
        print(f"PopSyn level: {'land-use zones (PopSyn_Index)' if by_index else 'TSM zones (TSM_NG)'}")
        if incremental and by_index and \
                self.comboBox_RefLUlayer.currentData().fields().indexOf("PopSyn_Index") < 0:
            QMessageBox.warning(self, "Warning",
                "Incremental: the land use has PopSyn_Index but the reference land use does not; "
                "pick a reference with the same zone fields.")
            return False
        if by_index:
            # Every zone needs its id: a model_zones_landuse.gpkg built before
            # TSM rows carried PopSyn_Index has them empty, and those zones
            # would not be synthesized at all.
            from qgis.core import QgsFeatureRequest
            req = QgsFeatureRequest().setFilterExpression(
                '"PopSyn_Index" IS NULL OR "PopSyn_Index" <= 0')
            req.setFlags(QgsFeatureRequest.Flag.NoGeometry)
            n_missing = sum(1 for _ in landuse_layer.getFeatures(req))
            if n_missing:
                QMessageBox.warning(self, "Warning",
                    f"{n_missing:,} zones of '{landuse_layer.name()}' have no PopSyn_Index, so "
                    "they would not be synthesized.\n\nIf this is model_zones_landuse.gpkg, "
                    "rebuild it: open Project Settings and Save.")
                return False
        key_args = ["--src-key", "PopSyn_Index"] if by_index else []
        se_data = os.path.join(scenario_dir, "popsyn_landuse.csv" if has_index
                               else "tsm_landuse.csv").replace("\\", "/")
        lu_default = "-" if has_index else os.path.join(
            tsm_location, "Inputs", "landuse", "tsm_landuse_default.csv").replace("\\", "/")
        prep_log = os.path.join(scenario_dir, "PopSyn_landuse.log")
        try:
            if incremental:
                # Aggregate BOTH scenario and reference to TSM level, then delta at
                # TSM (key TAZ), growth floored at 0 (PopSim synthesizes only the
                # increment; shrink is handled at the append step). PopSim-only --
                # SDT/LDT use the full user land use.
                scen_tsm = os.path.join(scenario_dir, "scenario_tsm_landuse.csv").replace("\\", "/")
                ref_tsm = os.path.join(scenario_dir, "reference_tsm_landuse.csv").replace("\\", "/")
                ra = settings.run_app([se_agg_exe, landuse_path, scen_tsm, lu_default] + key_args,
                                      log_path=prep_log, console=True)
                rb = settings.run_app([se_agg_exe, ref_landuse_path, ref_tsm, lu_default] + key_args,
                                      log_path=prep_log, console=True, append=True)
                if ra.returncode != 0 or rb.returncode != 0 or not (os.path.exists(scen_tsm) and os.path.exists(ref_tsm)):
                    QMessageBox.critical(self, "Error", "Failed to aggregate scenario/reference land use to TSM (se_aggregate).")
                    return False
                r = settings.run_app([ldelta_exe, ref_tsm, scen_tsm, se_data,
                                      "--key", "TAZ", "--keep-zero", "--floor0"], log_path=prep_log, console=True, append=True)
                err = "Failed to build TSM-level delta land-use (landuse_delta)."
            else:
                r = settings.run_app([se_agg_exe, landuse_path, se_data, lu_default] + key_args,
                                     log_path=prep_log, console=True)
                err = "Failed to aggregate land use to TSM (se_aggregate)."
            if r.returncode != 0 or not os.path.exists(se_data):
                QMessageBox.critical(self, "Error", err)
                return False
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error building PopSim land-use: {e}")
            return False

        # 1b) The res_pop control_field is 'NP' -- popsim needs it in BOTH the se_data
        # marginal AND the seed (the NP-aware swap corrector reads it from the seed,
        # where NP is the PUMS household size). The seed already has NP; se_aggregate
        # emits resident population as 'ResPOP', so alias NP = ResPOP in the se_data.
        try:
            self._ensure_np_column(se_data)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not add NP column to land use: {e}")
            return False

        # 1c) PopSim silently skips a land-use zone that is not in the
        # crosswalk, so check coverage first (zones with households or GQ).
        try:
            import csv
            xw_path = os.path.join(tsm_location, "Inputs", "popsim_seed", "PopSyn_geo_Crosswalk.csv")
            with open(xw_path, newline="") as f:
                xw = {int(float(r["TAZ"])) for r in csv.DictReader(f)}
            missing = []
            with open(se_data, newline="") as f:
                for r in csv.DictReader(f):
                    if float(r.get("TotHH") or 0) > 0 or float(r.get("GQ") or 0) > 0:
                        z = int(float(r["TAZ"]))
                        if z not in xw:
                            missing.append(z)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not check the PopSim crosswalk: {e}")
            return False
        if missing:
            QMessageBox.critical(self, "Error",
                f"{len(missing):,} land-use zones with households or GQ are not in "
                f"{xw_path}, so PopSim would skip them (first: "
                f"{', '.join(map(str, sorted(missing)[:10]))}).")
            return False

        # 2) Generate the HH + GQ TOMLs into the config folder
        config_popsim = os.path.join(plugin_dir, "config", "popsim")
        hh_toml = os.path.join(config_popsim, "popsim_run_HH.toml")
        gq_toml = os.path.join(config_popsim, "popsim_run_GQ.toml")
        tmpl_hh = os.path.join(plugin_dir, "templates", "popsim_run_HH_template.toml")
        tmpl_gq = os.path.join(plugin_dir, "templates", "popsim_run_GQ_template.toml")
        try:
            self._generate_toml(tmpl_hh, hh_toml, scenario_dir, threads, tsm_location, plugin_dir, se_data)
            self._generate_toml(tmpl_gq, gq_toml, scenario_dir, threads, tsm_location, plugin_dir, se_data)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error writing PopSim TOML configs: {e}")
            return False

        # 3) Run popsim-run.exe for HH then GQ via the shared gated runner. Output is
        #    streamed live to a log next to the user's outputs (scenario dir) so it's
        #    visible/tailable -- the QGIS GUI has no console.
        for toml_path, label in ((hh_toml, "HH"), (gq_toml, "GQ")):
            log_path = os.path.join(scenario_dir, f"PopSyn_{label}.log")
            print(f"PopSyn {label}: log -> {log_path}")
            if not run_gated_model(self, [popsim_exe, toml_path], f"PopSyn ({label})",
                                   log_path=log_path, console=True):
                return False

        # 4) Resolve the user's output files (synHH/synPer) and combine HH + GQ
        # (C++ popsimprep -- fast streaming). Non-incremental writes the combined
        # population STRAIGHT to synHH/synPer (no intermediate "Combined" dir).
        synHH = self.lineEdit_SynHH.text().strip()
        synPer = self.lineEdit_SynPer.text().strip()
        if not synHH or synHH == "synthetic_hh.csv":
            synHH = os.path.join(scenario_dir, "synthetic_hh.csv")
        if not synPer or synPer == "synthetic_per.csv":
            synPer = os.path.join(scenario_dir, "synthetic_per.csv")

        # Incremental combines the delta synthesis to a scratch dir (read by the
        # append step); non-incremental combines directly to the final outputs.
        combined_dir = os.path.join(scenario_dir, "Combined")
        if incremental:
            comb_hh = os.path.join(combined_dir, "synthetic_households.csv")
            comb_per = os.path.join(combined_dir, "synthetic_persons.csv")
        else:
            comb_hh, comb_per = synHH, synPer
        try:
            # PopSim writes HH_* and GQ_* files into the scenario folder. With
            # PopSyn_Index zones, --zone-map (the se_data, which carries TSM_NG;
            # incremental: the full scenario land use, not the delta) rewrites
            # the households' TAZ to the parent TSM zone and appends PopSyn_Index.
            zone_map = (scen_tsm if incremental else se_data) if has_index else None
            r = settings.run_app([popsimprep_exe, "combine", scenario_dir, scenario_dir, comb_hh, comb_per,
                                  "--hh-prefix", "HH_", "--gq-prefix", "GQ_"] +
                                 (["--zone-map", zone_map] if zone_map else []),
                                 log_path=os.path.join(scenario_dir, "PopSyn_combine.log"), console=True)
            if r.returncode != 0 or not os.path.exists(comb_hh):
                QMessageBox.critical(self, "Error", "Combining HH + GQ outputs failed.")
                return False
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error combining HH + GQ outputs: {e}")
            return False

        # 5) Incremental only: merge the combined delta synthesis onto the reference
        # population (add growth / remove shrink, consistent ids) -> synHH/synPer.
        if incremental:
            settings_popsim = os.path.join(scenario_dir, "settings_PopSim.txt").replace("\\", "/")
            gq_flag = "T" if self.checkBox_GQ.isChecked() else "F"
            try:
                with open(settings_popsim, "w") as f:
                    f.write(f"tsm_location = {tsm_location}\n")
                    f.write(f"combined_dir = {combined_dir}\n".replace("\\", "/"))
                    f.write("str_bool_run_incremental = T\n")
                    f.write(f"str_bool_GQ_in_POP = {gq_flag}\n")
                    f.write(f"landuse_layer_path = {landuse_path}\n")
                    f.write(f"ref_landuse_layer_path = {ref_landuse_path}\n")
                    f.write(f"synHH_path = {synHH}\n".replace("\\", "/"))
                    f.write(f"synPer_path = {synPer}\n".replace("\\", "/"))
                    f.write(f"refSynHH_path = {ref_synhh}\n")
                    f.write(f"refSynPer_path = {ref_synper}\n")
                r = settings.run_app([popsimprep_exe, "append-incremental", settings_popsim],
                                     log_path=os.path.join(scenario_dir, "PopSyn_append.log"), console=True)
                if r.returncode != 0 or not os.path.exists(synHH):
                    QMessageBox.critical(self, "Error", "Incremental append (popsimprep) failed.")
                    return False
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Error in incremental append: {e}")
                return False
        settings.set("synHH_file", synHH)
        settings.set("synPer_file", synPer)

        print("PopSyn completed successfully.")
        # Close the live run-log window first, so the success message is not
        # left behind it (the decorator's close is then a no-op).
        end_run_console()
        if show_message:
            QMessageBox.information(
                self, "Success",
                f"PopSyn completed.\n\nHouseholds: {synHH}\nPersons: {synPer}")
        return True
