import os
import shutil
import subprocess
import importlib.util
from PyQt5.QtWidgets import QDialog, QFileDialog, QMessageBox
from qgis.core import QgsProject
from PyQt5 import uic  # For loading .ui dynamically
from .tsm_settings import Config

from .PopulationSIM_ui import Ui_Dialog_PopulationSIM


class PopulatioSIMDialog(QDialog, Ui_Dialog_PopulationSIM):
    def __init__(self):
        super().__init__()

        settings = Config()
        plugin_dir = settings.get("plugin_dir")
        ui_file = os.path.join(plugin_dir, "ui/PopulationSIM.ui")
        print(f"UI file found at: {ui_file}")
        if not os.path.exists(ui_file):
            print(f"UI file not found at: {ui_file}")
            return
        uic.loadUi(ui_file, self)

        self.textBrowser.setOpenExternalLinks(True)
        self._load_help_doc(os.path.join(plugin_dir, "docs", "POPULATIONSIM.md"))

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
        QMessageBox.information(self, "Settings Updated", "PopulationSIM settings have been updated.")

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
    def _generate_toml(template_path, out_path, scenario_dir, threads):
        """Fill {scenario_dir} and {threads} in a template TOML and write it out."""
        with open(template_path, "r", encoding="utf-8") as f:
            text = f.read()
        text = text.replace("{scenario_dir}", scenario_dir.replace("\\", "/"))
        text = text.replace("{threads}", str(threads))
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"Wrote TOML: {out_path}")

    @staticmethod
    def _run_combine(combine_script, hh_dir, gq_dir, out_dir):
        """Import combine_synpop.py (stdlib-only) and merge HH + GQ outputs."""
        spec = importlib.util.spec_from_file_location("combine_synpop", combine_script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.combine(hh_dir, gq_dir, out_dir)

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------
    def run_popsim_script(self, show_message=False):
        settings = Config()
        scenario_dir = settings.get("scenarioDir")
        tsm_location = settings.get("tsm_location")
        plugin_dir = settings.get("plugin_dir")
        threads = settings.get("num_processors") or "0"

        if not scenario_dir:
            QMessageBox.warning(self, "Warning", "Please set a scenario directory in Project Settings.")
            return False

        landuse_layer = self.comboBox_LUlayer.currentData()
        if not landuse_layer:
            QMessageBox.warning(self, "Warning", "Please select a land-use layer.")
            return False

        # Incremental: PopulationSIM is synthesized on the land-use DELTA
        # (scenario - reference), then merged into the reference synthetic
        # population (add growth, remove shrink) keeping household ids consistent.
        # NOTE: the delta is for PopulationSIM only -- SDT and LDT use the full
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
        popsim_exe = os.path.join(tsm_location, "Apps", "popsim", "popsim-run.exe")
        combine_script = os.path.join(tsm_location, "Apps", "popsim", "combine_synpop.py")
        gpkgcsv_exe = os.path.join(tsm_location, "Apps", "LinkConsolidator", "gpkgcsv.exe")
        for path, label in ((popsim_exe, "popsim-run.exe"),
                            (combine_script, "combine_synpop.py"),
                            (gpkgcsv_exe, "gpkgcsv.exe")):
            if not os.path.exists(path):
                QMessageBox.critical(self, "Error", f"{label} not found at: {path}")
                return False

        # Utilities for the incremental path (delta land use + reference append).
        ldelta_exe = settings.app_exe("utilities/landuse_delta.exe")
        popsimprep_exe = settings.app_exe("utilities/popsimprep.exe")
        if incremental:
            for path, label in ((ldelta_exe, "landuse_delta.exe"), (popsimprep_exe, "popsimprep.exe")):
                if not os.path.exists(path):
                    QMessageBox.critical(self, "Error", f"{label} not found at: {path}")
                    return False

        # 1) Build the PopSim control land use (se_data) -> tsm_landuse.csv
        landuse_path = self.get_layer_path(landuse_layer)
        se_data = os.path.join(scenario_dir, "tsm_landuse.csv").replace("\\", "/")
        try:
            if incremental:
                # delta = scenario - reference, keyed on the unique MSR subzone index
                # (MSR_Index, formerly PopSyn_Index). TSM_NG (parent TAZ) and TAZ_REG
                # (subzone, both non-unique) ride along. Growth floored at 0 (PopSim
                # synthesizes only the increment; shrink is handled at the append step).
                try:
                    field_names = [f.name() for f in landuse_layer.fields()]
                except Exception:
                    field_names = []
                msr_key = "MSR_Index" if "MSR_Index" in field_names else "PopSyn_Index"
                r = subprocess.run([ldelta_exe, ref_landuse_path, landuse_path, se_data,
                                    "--key", msr_key, "--keep-zero", "--floor0"],
                                   env=settings.app_env(ldelta_exe))
                err = f"Failed to build delta land-use (landuse_delta, key={msr_key})."
            else:
                r = subprocess.run([gpkgcsv_exe, "to-csv", landuse_path, se_data, "--drop-geom"],
                                   env=settings.app_env(gpkgcsv_exe))
                err = "Failed to export land-use layer to tsm_landuse.csv."
            if r.returncode != 0 or not os.path.exists(se_data):
                QMessageBox.critical(self, "Error", err)
                return False
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error building PopSim land-use: {e}")
            return False

        # 2) Generate the HH + GQ TOMLs into the config folder
        config_popsim = os.path.join(tsm_location, "config", "popsim")
        hh_toml = os.path.join(config_popsim, "popsim_run_HH.toml")
        gq_toml = os.path.join(config_popsim, "popsim_run_GQ.toml")
        tmpl_hh = os.path.join(plugin_dir, "templates", "popsim_run_HH_template.toml")
        tmpl_gq = os.path.join(plugin_dir, "templates", "popsim_run_GQ_template.toml")
        try:
            self._generate_toml(tmpl_hh, hh_toml, scenario_dir, threads)
            self._generate_toml(tmpl_gq, gq_toml, scenario_dir, threads)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error writing PopSim TOML configs: {e}")
            return False

        # 3) Run popsim-run.exe for HH then GQ
        for toml_path, label in ((hh_toml, "HH"), (gq_toml, "GQ")):
            try:
                r = subprocess.run([popsim_exe, toml_path])
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Error running PopulationSIM ({label}): {e}")
                return False
            if r.returncode != 0:
                QMessageBox.critical(self, "Error", f"PopulationSIM {label} run failed. Check console for details.")
                return False

        # 4) Combine HH + GQ
        hh_dir = os.path.join(scenario_dir, "HH")
        gq_dir = os.path.join(scenario_dir, "GQ")
        combined_dir = os.path.join(scenario_dir, "Combined")
        try:
            self._run_combine(combine_script, hh_dir, gq_dir, combined_dir)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error combining HH + GQ outputs: {e}")
            return False

        # 5) Copy the combined outputs to the user's output files
        synHH = self.lineEdit_SynHH.text().strip()
        synPer = self.lineEdit_SynPer.text().strip()
        if not synHH or synHH == "synthetic_hh.csv":
            synHH = os.path.join(scenario_dir, "synthetic_hh.csv")
        if not synPer or synPer == "synthetic_per.csv":
            synPer = os.path.join(scenario_dir, "synthetic_per.csv")
        if incremental:
            # Merge the delta synthesis into the reference population: add the new
            # (growth) households with ids continued above the reference max, and
            # remove reference households for shrink zones. popsimprep writes the
            # final synHH/synPer directly.
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
                r = subprocess.run([popsimprep_exe, "append-incremental", settings_popsim],
                                   env=settings.app_env(popsimprep_exe))
                if r.returncode != 0 or not os.path.exists(synHH):
                    QMessageBox.critical(self, "Error", "Incremental append (popsimprep) failed.")
                    return False
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Error in incremental append: {e}")
                return False
        else:
            try:
                shutil.copy(os.path.join(combined_dir, "synthetic_households.csv"), synHH)
                shutil.copy(os.path.join(combined_dir, "synthetic_persons.csv"), synPer)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Combine finished but copying outputs failed: {e}")
                return False
        settings.set("synHH_file", synHH)
        settings.set("synPer_file", synPer)

        print("PopulationSIM completed successfully.")
        if show_message:
            QMessageBox.information(
                self, "Success",
                f"PopulationSIM completed.\n\nHouseholds: {synHH}\nPersons: {synPer}")
        return True
