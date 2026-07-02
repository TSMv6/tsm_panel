from qgis.PyQt.QtWidgets import QAction, QMainWindow
from qgis.PyQt.QtGui import QIcon
from .tsm_subarea_plugin_dialog import TsmSubareaExtDialog

import os

class TSMSubareaExtractPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dialog = None

    def initGui(self):
        # Create toolbar button
        plugin_dir = os.path.dirname(__file__)
        icon_path = os.path.join(plugin_dir, "icons", "subarea.png")
        self.action = QAction(QIcon(icon_path), "Subarea Extaction Process", self.iface.mainWindow())

        # Create a toolbar button
        #self.action = QAction(QIcon(":/plugins/tsm_netmanager_plugin/icons/icon.png"), "Link Consolidation", self.iface.mainWindow())
        self.action.triggered.connect(self.show_dialog)

        # Add button to toolbar
        self.iface.addToolBarIcon(self.action)

    def show_dialog(self):
        if not self.dialog:
            self.dialog = TsmSubareaExtDialog()
        self.dialog.show()

    def unload(self):
        self.iface.removeToolBarIcon(self.action)
