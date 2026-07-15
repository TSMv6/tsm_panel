import os
from qgis.PyQt.QtWidgets import QDialog, QFileDialog, QMessageBox
from qgis.PyQt import uic  # For loading .ui dynamically
from .tsm_settings import Config
from . import tsm_auth_token

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

        # TSM location: show the persisted value (survives restarts) or the v6
        # default. tsm_root() reads in-memory -> disk -> default so the dialog
        # never displays the default over a previously-saved custom path.
        tsm_location = settings.tsm_root()
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

        # TSM authentication token (per-user, stored in the QGIS profile and
        # ~/.tsm/token.txt; used to authorize the Black Box model steps).
        # Masked by default; "Show" reveals it, "Load from file…" replaces it.
        token_edit = getattr(self, "lineEdit_TSMToken", None)
        if token_edit is not None:
            token_edit.setText(tsm_auth_token.get_token())
        show_btn = getattr(self, "pushButton_ShowToken", None)
        if show_btn is not None:
            show_btn.toggled.connect(self.toggle_token_visibility)
        load_btn = getattr(self, "pushButton_LoadToken", None)
        if load_btn is not None:
            load_btn.clicked.connect(self.load_token_from_file)

        # Connections
        self.pushButton_Browse_TSMPath.clicked.connect(lambda: self.select_directory(self.lineEdit_ModelPath))
        self.pushButton_Browse_PluginsPath.clicked.connect(lambda: self.select_directory(self.lineEdit_PluginsPath))
        self.buttonBox_GenConfig.accepted.connect(self.update_settings)
        self.buttonBox_GenConfig.rejected.connect(self.cancel_action)

    def cancel_action(self):
        self.reject()

    def select_directory(self, line_edit):
        directory = QFileDialog.getExistingDirectory(self, "Select Directory")
        if directory:
            line_edit.setText(directory)

    def toggle_token_visibility(self, checked):
        """Show/hide the token text and flip the button label."""
        from qgis.PyQt.QtWidgets import QLineEdit
        token_edit = getattr(self, "lineEdit_TSMToken", None)
        if token_edit is not None:
            token_edit.setEchoMode(QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password)
        btn = getattr(self, "pushButton_ShowToken", None)
        if btn is not None:
            btn.setText("Hide" if checked else "Show")

    def load_token_from_file(self):
        """Load a token from a file the Dev Team sent (e.g. token.txt), replacing
        whatever is currently in the field. Saving still happens on OK."""
        token_edit = getattr(self, "lineEdit_TSMToken", None)
        if token_edit is None:
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Load TSM Token", "", "Token Files (*.txt *.token);;All Files (*)"
        )
        if not file_path:
            return
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                token = f.read().strip()
        except Exception as e:
            QMessageBox.warning(self, "Could Not Read Token",
                                f"Failed to read token from:\n{file_path}\n\n{e}")
            return
        token_edit.setText(token)  # replaces the current key
        if not token:
            QMessageBox.warning(self, "Empty Token",
                                "That file did not contain a token.")

    def update_settings(self):
        settings = Config()
        if self.lineEdit_ModelPath.text():
            settings.set("tsm_location", self.lineEdit_ModelPath.text())
        if self.lineEdit_PluginsPath.text():
            settings.set("plugin_dir", self.lineEdit_PluginsPath.text())
        if self.lineEdit_NumProcessors.text():
            settings.set("num_processors", self.lineEdit_NumProcessors.text())
        # Persist the TSM token per-user (NOT into the shared scenario JSON).
        token_edit = getattr(self, "lineEdit_TSMToken", None)
        if token_edit is not None:
            tsm_auth_token.set_token(token_edit.text())
        settings.check_and_save_to_file("scenario_settings_file")
        QMessageBox.information(self, "Settings Updated", "Configuration has been updated.")
