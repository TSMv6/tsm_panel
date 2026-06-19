import os
from PyQt5.QtWidgets import QDialog, QFileDialog, QMessageBox
from qgis.core import QgsProject
from PyQt5 import uic  # For loading .ui dynamically
from .tsm_settings import Config
from .sdt_runner import run_sdt_models

from .SDT_visitor_ui import Ui_Dialog_SDTVis


class SDTVisitorModel(QDialog, Ui_Dialog_SDTVis):
    def __init__(self):
        super().__init__()

        settings = Config()
        plugin_dir = settings.get("plugin_dir")
        ui_file = os.path.join(plugin_dir, "ui/SDT_visitor.ui")
        if not os.path.exists(ui_file):
            print(f"UI file not found at: {ui_file}")
            return
        uic.loadUi(ui_file, self)

        self.textBrowser.setOpenExternalLinks(True)
        self._load_help_doc(os.path.join(plugin_dir, "docs", "SDT_VISITOR.md"))

        self.populate_layer_combobox(self.comboBox_Landuse, "Polygon")
        self.browse_Skim.clicked.connect(lambda: self.select_file(self.lineEdit_Skim, "open"))
        self.browse_SDTVisOut.clicked.connect(lambda: self.select_directory(self.lineEdit_OutDir))
        self.button_OkCancel.accepted.connect(self.update_settings)
        self.button_OkCancel.rejected.connect(self.cancel_action)
        self.Run_SDTVis.clicked.connect(lambda: self.run_SDT_visitor(show_message=True))

        if settings.get("landuse_layer"):
            name = settings.get("landuse_layer")
            if name in [self.comboBox_Landuse.itemText(i) for i in range(self.comboBox_Landuse.count())]:
                self.comboBox_Landuse.setCurrentText(name)
        if settings.get("skim_file"):
            self.lineEdit_Skim.setText(settings.get("skim_file"))
        if settings.get("scenarioDir"):
            self.lineEdit_OutDir.setText(settings.get("scenarioDir"))

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

    def _sync_config(self):
        settings = Config()
        layer = self.comboBox_Landuse.currentData()
        if layer:
            settings.set("landuse_layer", layer.name())
            settings.set("landuse_layer_path", self.get_layer_path(layer))
        if self.lineEdit_Skim.text():
            settings.set("skim_file", self.lineEdit_Skim.text())
        if self.lineEdit_OutDir.text():
            settings.set("scenarioDir", self.lineEdit_OutDir.text())

    def update_settings(self):
        self._sync_config()
        Config().check_and_save_to_file("scenario_settings_file")
        QMessageBox.information(self, "Settings Updated", "Project Specific settings have been updated.")

    def run_SDT_visitor(self, show_message=False):
        if not self.comboBox_Landuse.currentData():
            QMessageBox.critical(self, "Error", "Please select a land-use layer.")
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
        # The visitor dialog has no resident-phase granularity: if Resident is
        # also selected here it runs the full resident model.
        resident = self.cb_runResident.isChecked()
        visitor = self.cb_runVisitor.isChecked()
        flags = {"resident": resident, "wfh": resident, "mandatory": resident,
                 "auto_own": resident, "veh_type": resident, "tour": resident,
                 "stop": resident, "trip": resident,
                 "visitor": visitor, "visitor_veh": visitor}
        ok, msg = run_sdt_models(flags)
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
