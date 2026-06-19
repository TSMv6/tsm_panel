from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import QCoreApplication
from .Update_tool import UpdateLinksAndNodesAlgorithm
import os

class UpdateLinksNodesProvider(QgsProcessingProvider):
    """Processing Provider for the Update Links and Nodes Plugin"""

    def __init__(self):
        super().__init__()

    def id(self):
        return "update_links_nodes"

    def name(self):
        return QCoreApplication.translate("Processing", "Update Links & Nodes")

    def icon(self):
        """Return a valid QIcon instead of None"""
        plugin_dir = os.path.dirname(__file__)
        icon_path = os.path.join(plugin_dir, "icons", "network_editor.png")
        return QIcon(icon_path) if os.path.exists(icon_path) else QIcon()  # Return a blank QIcon if file is missing.

    def loadAlgorithms(self):
        """Register processing algorithms"""
        self.addAlgorithm(UpdateLinksAndNodesAlgorithm())
