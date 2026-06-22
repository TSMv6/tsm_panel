import os
from PyQt5.QtWidgets import QDialog, QFileDialog, QMessageBox
from qgis.core import QgsProject
from PyQt5 import uic  # For loading .ui dynamically
from .tsm_settings import Config
from .sdt_runner import run_sdt_models

from .SDT_resident_ui import Ui_Dialog_SDTRes


class SDTResidentModel(QDialog, Ui_Dialog_SDTRes):
    def __init__(self):
        super().__init__()

        settings = Config()
        plugin_dir = settings.get("plugin_dir")
        ui_file = os.path.join(plugin_dir, "ui/SDT_resident.ui")
        if not os.path.exists(ui_file):
            print(f"UI file not found at: {ui_file}")
            return
        uic.loadUi(ui_file, self)

        self.textBrowser.setOpenExternalLinks(True)
        self._load_help_doc(os.path.join(plugin_dir, "docs", "SDT_RESIDENT.md"))

        self.populate_layer_combobox(self.comboBox_Landuse, "Polygon")
        self.browse_SynHH.clicked.connect(lambda: self.select_file(self.lineEdit_SynHH, "open"))
        self.browse_SynPer.clicked.connect(lambda: self.select_file(self.lineEdit_SynPer, "open"))
        self.browse_Skim.clicked.connect(lambda: self.select_file(self.lineEdit_Skim, "open"))
        self.browse_SDTOut.clicked.connect(lambda: self.select_directory(self.lineEdit_OutDir))

        self.comboBox_TeleworkShare.addItems(["7%", "10%", "15%", "20%", "25%"])
        self.comboBox_TeleworkShare.setCurrentText("15%")

        self.button_OkCancel.accepted.connect(self.update_settings)
        self.button_OkCancel.rejected.connect(self.cancel_action)
        self.Run_SDTRes.clicked.connect(lambda: self.run_SDT_resident(show_message=True))

        # Resident phase checkboxes (greyed out while "Run all phases" is on).
        self.phase_checkboxes = [self.cb_wfh, self.cb_autoOwn, self.cb_vehType,
                                 self.cb_mandatory, self.cb_tour, self.cb_stop, self.cb_trip]
        self.cb_runAllPhases.toggled.connect(self.toggle_phases)
        self.cb_runResident.toggled.connect(self.toggle_phases)
        self.toggle_phases()

        # Prefill from Config
        if settings.get("landuse_layer"):
            name = settings.get("landuse_layer")
            if name in [self.comboBox_Landuse.itemText(i) for i in range(self.comboBox_Landuse.count())]:
                self.comboBox_Landuse.setCurrentText(name)
        if settings.get("synHH_file"):
            self.lineEdit_SynHH.setText(settings.get("synHH_file"))
        if settings.get("synPer_file"):
            self.lineEdit_SynPer.setText(settings.get("synPer_file"))
        if settings.get("skim_file"):
            self.lineEdit_Skim.setText(settings.get("skim_file"))
        if settings.get("telework_share"):
            self.comboBox_TeleworkShare.setCurrentText(settings.get("telework_share"))
        if settings.get("scenarioDir"):
            self.lineEdit_OutDir.setText(settings.get("scenarioDir"))

        # Model-selection + phase checkboxes (Resident, Visitor, Run-all, phases).
        # Persisted in Config so the dialog remembers them across open/close.
        self._cb_settings = {
            "sdt_run_resident":    self.cb_runResident,
            "sdt_run_visitor":     self.cb_runVisitor,
            "sdt_run_all_phases":  self.cb_runAllPhases,
            "sdt_phase_wfh":       self.cb_wfh,
            "sdt_phase_auto_own":  self.cb_autoOwn,
            "sdt_phase_veh_type":  self.cb_vehType,
            "sdt_phase_mandatory": self.cb_mandatory,
            "sdt_phase_tour":      self.cb_tour,
            "sdt_phase_stop":      self.cb_stop,
            "sdt_phase_trip":      self.cb_trip,
        }
        for key, cb in self._cb_settings.items():
            v = settings.get(key)
            if v is not None:
                cb.setChecked(bool(v))
        self.toggle_phases()  # reflect restored state in the enabled/disabled phases

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

    def toggle_phases(self):
        """Phases apply only to a resident run; individual phases are editable
        only when 'Run all phases' is off."""
        resident_on = self.cb_runResident.isChecked()
        self.phasesGB.setEnabled(resident_on)
        individual = resident_on and not self.cb_runAllPhases.isChecked()
        for cb in self.phase_checkboxes:
            cb.setEnabled(individual)

    def _model_flags(self):
        resident = self.cb_runResident.isChecked()
        run_all = self.cb_runAllPhases.isChecked()

        def phase(cb):
            return resident and (run_all or cb.isChecked())

        visitor = self.cb_runVisitor.isChecked()
        return {
            "resident": resident,
            "wfh": phase(self.cb_wfh),
            "auto_own": phase(self.cb_autoOwn),
            "veh_type": phase(self.cb_vehType),
            "mandatory": phase(self.cb_mandatory),
            "tour": phase(self.cb_tour),
            "stop": phase(self.cb_stop),
            "trip": phase(self.cb_trip),
            "visitor": visitor,
            "visitor_veh": visitor,
        }

    def _sync_config(self):
        """Push the dialog fields into the Config store (no UI feedback)."""
        settings = Config()
        layer = self.comboBox_Landuse.currentData()
        if layer:
            settings.set("landuse_layer", layer.name())
            settings.set("landuse_layer_path", self.get_layer_path(layer))
        settings.set("synHH_file", self.lineEdit_SynHH.text())
        settings.set("synPer_file", self.lineEdit_SynPer.text())
        settings.set("skim_file", self.lineEdit_Skim.text())
        settings.set("telework_share", self.comboBox_TeleworkShare.currentText())
        if self.lineEdit_OutDir.text():
            settings.set("scenarioDir", self.lineEdit_OutDir.text())
        # Persist the model-selection + phase checkboxes (incl. Visitor).
        for key, cb in getattr(self, "_cb_settings", {}).items():
            settings.set(key, cb.isChecked())

    def update_settings(self):
        self._sync_config()
        Config().check_and_save_to_file("scenario_settings_file")
        QMessageBox.information(self, "Settings Updated", "Project Specific settings have been updated.")

    def run_SDT_resident(self, show_message=False):
        if not self.comboBox_Landuse.currentData():
            QMessageBox.critical(self, "Error", "Please select a land-use layer.")
            return False
        if not self.lineEdit_SynHH.text():
            QMessageBox.critical(self, "Error", "Please select a synthetic household file.")
            return False
        if not self.lineEdit_SynPer.text():
            QMessageBox.critical(self, "Error", "Please select a synthetic person file.")
            return False
        if not self.lineEdit_Skim.text():
            QMessageBox.critical(self, "Error", "Please select a skim file.")
            return False
        if not self.lineEdit_OutDir.text():
            QMessageBox.critical(self, "Error", "Please select an output directory.")
            return False
        if not (self.cb_runResident.isChecked() or self.cb_runVisitor.isChecked()):
            QMessageBox.critical(self, "Error", "Select at least one model to run (Resident and/or Visitor).")
            return False

        self._sync_config()
        ok, msg = run_sdt_models(self._model_flags())
        if not ok:
            QMessageBox.critical(self, "Error", msg)
            return False
        if show_message:
            QMessageBox.information(self, "Success", msg)
        return True

    def cancel_action(self):
        self.reject()

    def select_file(self, line_edit, type):
        if type == "open":
            file_path, _ = QFileDialog.getOpenFileName(self, "Select File", "", "csv (*.csv) ;; skim (*.omx);; All Files (*)")
        else:
            file_path, _ = QFileDialog.getSaveFileName(self, "Select File", "", "csv (*.csv) ;; All Files (*)")
        if file_path:
            line_edit.setText(file_path)

    def select_directory(self, line_edit):
        directory = QFileDialog.getExistingDirectory(self, "Select Directory")
        if directory:
            line_edit.setText(directory)

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
