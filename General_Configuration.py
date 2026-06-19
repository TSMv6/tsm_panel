import os
from PyQt5.QtWidgets import QDialog, QFileDialog, QMessageBox
from PyQt5 import uic  # For loading .ui dynamically
from .tsm_settings import Config

from .General_Configuration_ui import Ui_Dialog_GenPrjSetting

DEFAULT_TSM_LOCATION = "C:/TSM_NextGen_v6"


class GeneralConfigDialog(QDialog, Ui_Dialog_GenPrjSetting):
    def __init__(self):
        super().__init__()

        settings = Config()
        plugin_dir = settings.get("plugin_dir") or os.path.dirname(__file__).replace("\\", "/")
        ui_file = os.path.join(plugin_dir, "ui/General_Configuration.ui")
        if not os.path.exists(ui_file):
            print(f"UI file not found at: {ui_file}")
            return
        uic.loadUi(ui_file, self)

        # TSM location (defaults to the v6 install)
        tsm_location = settings.get("tsm_location") or DEFAULT_TSM_LOCATION
        settings.set("tsm_location", tsm_location)
        self.lineEdit_ModelPath.setText(tsm_location)

        # Plugins path (this plugin's folder)
        self.lineEdit_PluginsPath.setText(plugin_dir)

        # Number of processors (default to detected CPU count)
        num_cores = settings.get("num_processors")
        if not num_cores:
            try:
                num_cores = str(os.cpu_count())
            except Exception:
                num_cores = "0"
        self.lineEdit_NumProcessors.setText(str(num_cores))

        self._sync_r_exe_path(tsm_location)

        # Connections
        self.pushButton_Browse_TSMPath.clicked.connect(lambda: self.select_directory(self.lineEdit_ModelPath))
        self.pushButton_Browse_PluginsPath.clicked.connect(lambda: self.select_directory(self.lineEdit_PluginsPath))
        self.buttonBox_GenConfig.accepted.connect(self.update_settings)
        self.buttonBox_GenConfig.rejected.connect(self.cancel_action)

    def _sync_r_exe_path(self, tsm_location):
        """Resolve Rscript internally (not user-facing). Only the SDT land-use prep
        (converter #8) still uses R; this keeps it working until #8 is refactored."""
        r_exe_path = os.path.join(
            tsm_location, "PopSim/Florida/Setup/software/R/R-4.3.2/bin/Rscript.exe").replace("\\", "/")
        Config().set("r_exe_path", r_exe_path)

    def cancel_action(self):
        self.reject()

    def select_directory(self, line_edit):
        directory = QFileDialog.getExistingDirectory(self, "Select Directory")
        if directory:
            line_edit.setText(directory)

    def update_settings(self):
        settings = Config()
        if self.lineEdit_ModelPath.text():
            settings.set("tsm_location", self.lineEdit_ModelPath.text())
            self._sync_r_exe_path(self.lineEdit_ModelPath.text())
        if self.lineEdit_PluginsPath.text():
            settings.set("plugin_dir", self.lineEdit_PluginsPath.text())
        if self.lineEdit_NumProcessors.text():
            settings.set("num_processors", self.lineEdit_NumProcessors.text())
        settings.check_and_save_to_file("scenario_settings_file")
        QMessageBox.information(self, "Settings Updated", "Configuration has been updated.")
