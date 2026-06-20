from PyQt5.QtWidgets import QAction, QDockWidget, QMessageBox, QLabel
from PyQt5.QtWidgets import QMainWindow, QPushButton, QFileDialog, QApplication
from qgis.PyQt.QtGui import QIcon
from qgis.utils import iface

from PyQt5.QtCore import Qt, QSettings
from PyQt5 import uic

from qgis.core import QgsApplication

import webbrowser  # Import webbrowser module

# import weakref

# from PyQt5.QtCore import pyqtSignal

# from .tsm_main_panel_ui import Ui_DockWidget
from .tsm_panel_add_more_ui2 import Ui_DockWidget
from .tsm_settings import Config

# Import secondary dialog 
from .General_Configuration import GeneralConfigDialog
from .Project_Settings import ProjectSpecsDialog
from .configurationTable_plugin import ViewSettings

# from .update_links_nodes_plugin import UpdateLinksNodesPlugin
# from .provider import UpdateLinksNodesProvider

from .tsm_linkConsolidator_plugin_dialog import TsmNetManDialog
from .tsm_subarea_plugin_dialog import TsmSubareaExtDialogX

# The Editors
from .MSR_Dialog_plugin import MSR_Disaggregate

# The "Black Box"

from .PopulationSIM_plugin import PopulatioSIMDialog
from .SkimmyDialog_plugin import FLSkim
from .SDT_residentDialog_plugin import SDTResidentModel
from .SDT_visitorDialog_plugin import SDTVisitorModel  
from .LDT_residentDialog_plugin import LDTResidentModel
from .LDT_visitorDialog_plugin import LDTVisitorModel
from .trip_list2table_Dialog_Plugin import ConvertTripListtoTable
from .TSMAssignDialog_plugin import TSMAssignDialog
from .HydraAssignDialog_plugin import HydraAssignModel
from .Subarea_Assign_Dialog_plugin import Subarea_AssignDialog

from .summary_loadedVolumes import Summary_Dialog


import os

class TsmPanelPlugin():
    # settings_changed = pyqtSignal(dict)

    def __init__(self, iface):
        self.iface = iface
        self.dock_widget = None
        self.action = None

    def initGui(self):
        """Initialize the plugin UI."""
        self.action = QAction(QIcon("icon.png"), "Open Panel", self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu("TSM UI", self.action)

        # Add website links to the Help menu
        help_menu = self.iface.helpMenu()
        if help_menu:  # Ensure the Help menu exists
            website_action1 = QAction('TSM Overview', self.iface.mainWindow())
            website_action1.triggered.connect(self.open_website)
            help_menu.addSeparator()
            help_menu.addAction(website_action1)

            website_action2 = QAction('TSM AI Chat', self.iface.mainWindow())
            website_action2.triggered.connect(self.open_website2)
            help_menu.addSeparator()
            help_menu.addAction(website_action2)
        else:
            print("Help menu not found. Unable to add website links.")

        # Read default settings from a JSON file
        settings = Config()
        plugin_dir = os.path.dirname(__file__).replace("\\", "/")
        print("Plugin dir: ", plugin_dir)
        settings.set("plugin_dir", plugin_dir)  

        icon = 'icons/TPK-mainline-logo.png'
        icon_path = os.path.join(plugin_dir, icon)
        iface.mainWindow().setWindowIcon(QIcon(icon_path))


    def open_website(self):
        """Open the TSM Overview website."""
        webbrowser.open('https://rawcdn.githack.com/4Step/NextGen_StoryTelling/81080ccbe072f7c2c4f408c1236f94fd97ed5d52/index.html')

    def open_website2(self):
        """Open the TSM AI Chat web app (primary), falling back to the Vercel host
        if the primary is unreachable."""
        primary = 'https://tsm-nextgen.com/'
        fallback = 'https://tsmchatbot.vercel.app/'
        url = primary
        try:
            import urllib.request
            req = urllib.request.Request(primary, method='HEAD')
            urllib.request.urlopen(req, timeout=4)
        except Exception as e:
            print(f"TSM chatbot primary unreachable ({e}); using fallback {fallback}")
            url = fallback
        webbrowser.open(url)
        

    def unload(self):
        """Remove UI elements when the plugin is unloaded."""
        self.iface.removePluginMenu("TSM UI", self.action)
        help_menu = self.iface.helpMenu()
        if help_menu:
            for action in help_menu.actions():
                if action.text() in ['TSM Overview', 'TSM AI Chat']:
                    help_menu.removeAction(action)
        if self.dock_widget:
            self.iface.mainWindow().removeDockWidget(self.dock_widget)
        
        # Cleanup processing provider
        # provider = self._provider_ref() if self._provider_ref else None
        # if provider:
        #     QgsApplication.processingRegistry().removeProvider(provider)
        #     self._provider_ref = None  # explicitly reset weak reference

    def run(self):
        """Show the main panel."""
        if not self.dock_widget:
            # Setup your TSM dock widget
            self.dock_widget = QDockWidget("TSM Panel", self.iface.mainWindow())
            self.dock_widget.setObjectName("TSMPanelDock")
            self.ui = Ui_DockWidget()
            self.ui.setupUi(self.dock_widget)
            self._normalize_status_columns()
            self.connect_buttons()
            self._load_history()
            self.log_message("TSM panel ready.")
            
            main_win = self.iface.mainWindow()

            # Add TSM Dock widget
            main_win.addDockWidget(Qt.LeftDockWidgetArea, self.dock_widget)

            # Identify Browser and Layers panels (existing docks)
            browser_dock = main_win.findChild(QDockWidget, "Browser")
            layers_dock = main_win.findChild(QDockWidget, "Layers")

            # Tabify TSM Panel with Browser or Layers if present
            if layers_dock:
                main_win.tabifyDockWidget(layers_dock, self.dock_widget)
            elif browser_dock:
                main_win.tabifyDockWidget(browser_dock, self.dock_widget)
            
            # Raise your panel explicitly so it opens as active
            self.dock_widget.raise_()

        # Always ensure it's visible and active
        self.dock_widget.show()
        self.dock_widget.raise_()


    def connect_buttons(self):
        """Connect buttons to the corresponding settings dialogs."""
        # Connect the save settings button to save function
        # self.save_button.clicked.connect(self.save_settings)

        # Ui_tools = ["tsm_subarea_extractor_ui", "update_links_nodes_plugin", "tsm_link_consolidator_ui"]
        # for i in range(1, 21):
            # settings_button = getattr(self.ui, f"settingsButton{i}", None)

        saveSettings_button = getattr(self.ui, "pushButton_saveSettings", None)
        saveSettings_button.clicked.connect(lambda _, tool= "save":self.save_settings())
        loadSettings_button = getattr(self.ui, "pushButton_loadSettings", None)
        loadSettings_button.clicked.connect(lambda _, tool= "load":self.load_settings())

        # Network Modeler — single button opens each tool's dialog (Hydra-style)
        linkConsolidator_button = getattr(self.ui, "run_Many2One", None)
        if linkConsolidator_button:
            linkConsolidator_button.clicked.connect(lambda _, tool="many_to_one": self.open_settings(tool))
        subareaNetworks_button = getattr(self.ui, "pushButton", None)
        if subareaNetworks_button:
            subareaNetworks_button.clicked.connect(lambda _, tool="tsm_subarea_extractor": self.open_settings(tool))

        # General & Project Settings
        GenPrjSetting_button = getattr(self.ui, "pushButton_GenPrjSetting", None)
        GenPrjSetting_button.clicked.connect(lambda _, tool= "GenConSet":self.open_settings(tool))
        ProjectSettings_button = getattr(self.ui, "pushButton_ProjectSettings", None)
        ProjectSettings_button.clicked.connect(lambda _, tool= "ProjSpecs":self.open_settings(tool))
        # View Settings (Table Widget)
        ViewSettings_button = getattr(self.ui, "pushButton_ViewSettings", None)
        ViewSettings_button.clicked.connect(lambda _, tool= "ViewSettings":self.open_settings(tool))

        # Editors
        # seDataEditor = getattr(self.ui, "pushButton_104", None)
        # seDataEditor.clicked.connect(lambda _, tool= "SEDataEditor":self.open_settings(tool))
        update_links_button = getattr(self.ui, "pushButton_UpdateLinkNodeAttr", None)
        update_links_button.clicked.connect(lambda _, tool= "UpdateLinksNodesPlugin":self.open_settings(tool))
        MSRSetting_button = getattr(self.ui, "pushButton_MSR", None)
        MSRSetting_button.clicked.connect(lambda _, tool= "MSR_Disaggregate":self.open_settings(tool))
        # MSR is now read/supported, so enable the editor under "Editors" (GeoMaster
        # Editing). The .ui ships it disabled; activate it here regardless of UI source.
        MSRSetting_button.setEnabled(True)
        MSRSetting_button.setToolTip("Open the Multi-Spatial Resolution (MSR) disaggregation editor.")
        # update_links_button.clicked.connect(self.run_update_links_nodes)

        # The "Analyst" — the Summarization button opens the summary dialog
        # (formerly the separate "properties" button, now removed).
        Summary_button = getattr(self.ui, "pushButton_74", None)
        if Summary_button:
            Summary_button.clicked.connect(lambda _, tool= "SummaryLoadedVolume":self.open_settings(tool))

        # Demand & Route Choice Models — each model's single button opens its
        # dialog (Hydra-style); the per-row "..." settings buttons were removed.
        # Actual model execution happens inside each dialog or via "Run TSM (Selected)".
        self.ui.run_PopSIM.clicked.connect(lambda _, tool="PopSIM": self.open_settings(tool))
        self.ui.run_Skimmy.clicked.connect(lambda _, tool="FL_skimmy": self.open_settings(tool))
        self.ui.run_SDTRes.clicked.connect(lambda _, tool="SDT_resident": self.open_settings(tool))
        self.ui.run_SDTVis.clicked.connect(lambda _, tool="SDT_visitor": self.open_settings(tool))
        self.ui.run_LDTRes.clicked.connect(lambda _, tool="LDT_resident": self.open_settings(tool))
        self.ui.run_LDTVis.clicked.connect(lambda _, tool="LDT_visitor": self.open_settings(tool))
        self.ui.run_TripTable.clicked.connect(lambda _, tool="TripList2Table": self.open_settings(tool))
        self.ui.run_TSMAssign.clicked.connect(lambda _, tool="tsm_assign": self.open_settings(tool))
        self.ui.run_SubAssign.clicked.connect(lambda _, tool="SubareaAssignDialog": self.open_settings(tool))
        self.ui.run_Hydra.clicked.connect(lambda _, tool="hydra": self.open_settings(tool))

        # ELToD and HyDRA are alternative assignment models (both step 9): it is
        # one or the other, never both. Selecting one clears the other; either
        # can still be left unchecked.
        self.ui.checkBox_TSMAssign.toggled.connect(self._on_eltod_toggled)
        self.ui.checkBox_Hydra.toggled.connect(self._on_hydra_toggled)

        # Check box for running all tools
        self.ui.pushButton_ClearSelection.clicked.connect(self.reset_all_step_labels)
        self.ui.pushButton_RunSelected.clicked.connect(self.run_all_tools)

    def _on_eltod_toggled(self, checked):
        """ELToD selected -> clear HyDRA (they are the same step 9, mutually exclusive)."""
        if checked:
            self.ui.checkBox_Hydra.setChecked(False)

    def _on_hydra_toggled(self, checked):
        """HyDRA selected -> clear ELToD (they are the same step 9, mutually exclusive)."""
        if checked:
            self.ui.checkBox_TSMAssign.setChecked(False)

    def run_update_links_nodes(self):
        plugin_instance = UpdateLinksNodesPlugin(self.iface)
        plugin_instance.run_tool()


    def run_all_tools(self):
        """Run all tools with saved settings, stop if any step fails."""
        self.reset_all_step_labels()
        print("Running all tools with saved settings")
        self.log_message("Running selected models…")
        selected_tools = []
        if self.ui.checkBox_PopSIM.isChecked():
            selected_tools.append("PopSIM")
        if self.ui.checkBox_Skimmy.isChecked():
            selected_tools.append("FL_skimmy")
        if self.ui.checkBox_SDTRes.isChecked():
            selected_tools.append("SDT_resident")
        if self.ui.checkBox_SDTVis.isChecked():
            selected_tools.append("SDT_visitor")
        if self.ui.checkBox_LDTRes.isChecked():
            selected_tools.append("LDT_resident")
        if self.ui.checkBox_LDTVis.isChecked():
            selected_tools.append("LDT_visitor")
        if self.ui.checkBox_TripTable.isChecked():
            selected_tools.append("TripList2Table")
        if self.ui.checkBox_TSMAssign.isChecked():
            selected_tools.append("tsm_assign")

        for tool in selected_tools:
            success = self.run_tool([tool])  # run_tool now returns True/False
            if not success:
                self.log_message(f"Stopped — remaining steps skipped.")
                QMessageBox.warning(None, "Stopped", f"Stopped at step: {tool}. Remaining steps will not be run.")
                break
        else:
            self.log_message("All selected models completed.")
            QMessageBox.information(None, "Information", "All selected models have been run with saved settings")

    def run_tool(self, tool_list):
        """Run the tool(s) using saved settings. Returns True if all succeed, False if any fail."""
        for tool_name in tool_list:
            print(f"Running tool {tool_name} with saved settings")
            try:
                if tool_name == 'MSR_Disaggregate':
                    self.mark_step_in_progress(self.ui.label_MSRDisagg)
                    QApplication.processEvents()
                    dialog = MSR_Disaggregate()
                    result = dialog.run_MSR()  # Assuming you have a method to run the tool
                    if not result:
                        self.mark_step_failed(self.ui.label_MSRDisagg)
                        return False
                    self.mark_step_completed(self.ui.label_MSRDisagg)
                    QApplication.processEvents()
                if tool_name == 'many_to_one':
                    self.mark_step_in_progress(self.ui.label_Many2One)
                    QApplication.processEvents()
                    dialog = TsmNetManDialog()
                    dialog.run_Many2One_script()
                    self.mark_step_completed(self.ui.label_Many2One)
                    QApplication.processEvents()
                elif tool_name == 'PopSIM':
                    self.mark_step_in_progress(self.ui.label_PopSIM)
                    QApplication.processEvents()
                    dialog = PopulatioSIMDialog()
                    result = dialog.run_popsim_script()
                    if not result:
                        self.mark_step_failed(self.ui.label_PopSIM)
                        return False
                    self.mark_step_completed(self.ui.label_PopSIM)
                    QApplication.processEvents()
                elif tool_name == 'FL_skimmy':
                    self.mark_step_in_progress(self.ui.label_Skimmy)
                    QApplication.processEvents()
                    dialog = FLSkim()
                    result = dialog.run_Skimmy()
                    if not result:
                        self.mark_step_failed(self.ui.label_Skimmy)
                        return False
                    self.mark_step_completed(self.ui.label_Skimmy)
                    QApplication.processEvents()
                elif tool_name == 'SDT_resident':
                    self.mark_step_in_progress(self.ui.label_SDTRes)
                    QApplication.processEvents()
                    dialog = SDTResidentModel()
                    result = dialog.run_SDT_resident()
                    if not result:
                        self.mark_step_failed(self.ui.label_SDTRes)
                        return False
                    self.mark_step_completed(self.ui.label_SDTRes)
                    QApplication.processEvents()
                elif tool_name == 'SDT_visitor':
                    self.mark_step_in_progress(self.ui.label_SDTVis)
                    QApplication.processEvents()
                    dialog = SDTVisitorModel()
                    result = dialog.run_SDT_visitor()
                    if not result:
                        self.mark_step_failed(self.ui.label_SDTVis)
                        return False
                    self.mark_step_completed(self.ui.label_SDTVis)
                    QApplication.processEvents()
                elif tool_name == 'LDT_resident':
                    self.mark_step_in_progress(self.ui.label_LDTRes)
                    QApplication.processEvents()
                    dialog = LDTResidentModel()
                    result = dialog.run_LDT_resident()
                    if not result:
                        self.mark_step_failed(self.ui.label_LDTRes)
                        return False
                    self.mark_step_completed(self.ui.label_LDTRes)
                    QApplication.processEvents()
                elif tool_name == 'LDT_visitor':
                    self.mark_step_in_progress(self.ui.label_LDTVis)
                    QApplication.processEvents()
                    dialog = LDTVisitorModel()
                    result = dialog.run_LDT_visitor()
                    if not result:
                        self.mark_step_failed(self.ui.label_LDTVis)
                        return False
                    self.mark_step_completed(self.ui.label_LDTVis)
                    QApplication.processEvents()
                elif tool_name == 'TripList2Table':
                    self.mark_step_in_progress(self.ui.label_TripList)
                    QApplication.processEvents()
                    dialog = ConvertTripListtoTable()
                    result = dialog.run_trip_table()
                    if not result:
                        self.mark_step_failed(self.ui.label_TripList)
                        return False
                    self.mark_step_completed(self.ui.label_TripList)
                    QApplication.processEvents()
                elif tool_name == 'tsm_assign':
                    self.mark_step_in_progress(self.ui.label_TSMAssign)
                    QApplication.processEvents()
                    dialog = TSMAssignDialog()
                    result = dialog.run_TSM_assignment()
                    if not result:
                        self.mark_step_failed(self.ui.label_TSMAssign)
                        return False
                    self.mark_step_completed(self.ui.label_TSMAssign)
                    QApplication.processEvents()
                elif tool_name == 'SubareaAssignDialog':
                    self.mark_step_in_progress(self.ui.label_SubAssign)
                    QApplication.processEvents()
                    dialog = Subarea_AssignDialog()
                    result = dialog.run_subarea_assignment()
                    if not result:
                        self.mark_step_failed(self.ui.label_SubAssign)
                        return False
                    self.mark_step_completed(self.ui.label_SubAssign)
                    QApplication.processEvents()
                else:
                    print(f"Unknown tool: {tool_name}")
                    return False
            except Exception as e:
                print(f"Error running {tool_name}: {e}")
                # Mark as failed
                label_attr = f'label_{tool_name}' if hasattr(self.ui, f'label_{tool_name}') else None
                if label_attr:
                    self.mark_step_failed(getattr(self.ui, label_attr))
                QMessageBox.critical(None, "Error", f"Error running {tool_name}: {e}")
                return False
        return True

    # Friendly names for tool keys, used in the Messages history.
    _TOOL_LABELS = {
        "GenConSet": "General Configuration", "ProjSpecs": "Scenario Specs",
        "ViewSettings": "View Settings", "UpdateLinksNodesPlugin": "GeoMaster Editor",
        "tsm_subarea_extractor": "Subarea Networks", "many_to_one": "Link Consolidator",
        "MSR_Disaggregate": "MSR", "PopSIM": "Population SIM", "FL_skimmy": "Skimmy",
        "SDT_resident": "SDT Resident", "SDT_visitor": "SDT Visitor",
        "LDT_resident": "LDT Resident", "LDT_visitor": "LDT Visitor",
        "TripList2Table": "agentPlans", "tsm_assign": "ELToD",
        "SubareaAssignDialog": "Subarea Assignment", "hydra": "HyDRA",
        "SummaryLoadedVolume": "Summarization",
    }

    def open_settings(self, tool_name):
        """Opens the tool-specific settings UI."""
        print("open_settings called")  # Verify if this line is printed
        self.log_message(f"Opened {self._TOOL_LABELS.get(tool_name, tool_name)}")

        if tool_name == 'GenConSet':
            dialog = GeneralConfigDialog()
        if tool_name == 'ProjSpecs':
            dialog = ProjectSpecsDialog() 
        if tool_name == 'ViewSettings':
            dialog = ViewSettings()

        if tool_name == 'UpdateLinksNodesPlugin':
            QMessageBox.information(None, "Information", "Use Update Links & Nodes from the Processing Toolbox")
            return
        if tool_name == 'tsm_subarea_extractor':
            dialog = TsmSubareaExtDialogX() 
        if tool_name == 'many_to_one':
            dialog = TsmNetManDialog() 

        if tool_name == 'MSR_Disaggregate':
            dialog = MSR_Disaggregate()

        if tool_name == 'PopSIM':
            dialog = PopulatioSIMDialog()
        if tool_name == 'FL_skimmy':
            dialog = FLSkim()
        if tool_name == 'SDT_resident':
            dialog = SDTResidentModel()
        if tool_name == 'SDT_visitor':
            dialog = SDTVisitorModel()
        if tool_name == 'LDT_resident':
            dialog = LDTResidentModel()
        if tool_name == 'LDT_visitor':
            dialog = LDTVisitorModel()
        if tool_name == 'TripList2Table':
            dialog = ConvertTripListtoTable()
        if tool_name == 'tsm_assign':
            dialog = TSMAssignDialog()
        if tool_name == 'SubareaAssignDialog':
            dialog = Subarea_AssignDialog()
        if tool_name == 'hydra':
            dialog = HydraAssignModel()

        if tool_name == 'SummaryLoadedVolume':
            dialog = Summary_Dialog()

        print("Dialog instance created")                    
        # from PyQt5 import uic
        # print("Call UI")
        dialog.exec_()
        # print("UI executed")

    
    def save_settings(self):
        """Save the current settings to a JSON file."""
        settings = Config()
        # settings.remove("plugin_dir")
        # Ensure parent is a QMainWindow, then use it as the parent for QFileDialog
        parent_main_window = self.iface.mainWindow()
        if isinstance(parent_main_window, QMainWindow):
            file_path, _ = QFileDialog.getSaveFileName(parent_main_window, "Save Settings", "", "JSON Files (*.json);;All Files (*)")
            settings.set("scenario_settings_file", file_path)
            if file_path:
                try:
                    # Save the settings as JSON
                    settings.save_to_file(file_path)
                    self.log_message(f"Settings saved → {os.path.basename(file_path)}")
                    QMessageBox.information(parent_main_window, "Information", f"Save settings to file: {file_path}")
                except Exception as e:
                    QMessageBox.critical(parent_main_window, "Error", f"Failed to save settings: {e}")
            else:
                print("No file selected.")
    
    def load_default_settings(self, default_file):
        """Auto-load the last used settings file when the app starts."""
        if os.path.exists(default_file):
            settings = Config()
            print(f"Auto-loading default settings file: {default_file}")
            settings.load_from_file(default_file)  # Call existing function with last file path
            plugin_dir = os.path.dirname(__file__).replace("\\", "/")
            settings.set("plugin_dir", plugin_dir)
        else:
            print("No previous settings file found.")

    # def load_last_used_settings(self):
    #     """Auto-load the last used settings file when the app starts."""
    #     lsettings = QSettings("TsmPanelPlugin", "FTE")  # Use a unique app identifier
    #     last_file = lsettings.value("last_used_file", "")
      
    #     if last_file and os.path.exists(last_file):
    #         print(f"Auto-loading last settings file: {last_file}")
    #         self.load_settings(last_file)  # Call existing function with last file path
    #     else:
    #         settings = Config()
    #         plugin_dir = settings.get("plugin_dir")
    #         self.default_file = os.path.join(plugin_dir, "default_settings.json")
    #         self.load_default_settings(self.default_file)

    # def save_last_used_settings(self, file_path):
    #     """Save the last opened settings file for auto-loading next time."""
    #     lsettings = QSettings("TsmPanelPlugin", "FTE")
    #     lsettings.setValue("last_used_file", file_path)

    def load_settings(self):
        """Triggered when the Load button is clicked."""
        settings = Config()

        parent_main_window = self.iface.mainWindow()
        if isinstance(parent_main_window, QMainWindow):
            file_path, _ = QFileDialog.getOpenFileName(parent_main_window, "Open Settings", "", "JSON Files (*.json);;All Files (*)")
            settings.set("scenario_settings_file", file_path)
            print(file_path)
            if file_path:
                try:
                # Load the settings using Config
                    settings.load_from_file(file_path)  # Load the settings from the selected file path
                    plugin_dir = os.path.dirname(__file__).replace("\\", "/")
                    settings.set("plugin_dir", plugin_dir)
                    # self.save_last_used_settings(file_path)  # Save the last used settings file path
                    print("UI updated with loaded settings")
                    # Show this scenario's saved action history, then log the load.
                    self._load_history()
                    self.log_message(f"Settings loaded ← {os.path.basename(file_path)}")
                    QMessageBox.information(parent_main_window, "Information", f"Read settings from file: {file_path}")
                # self.update_ui_with_settings(settings)
                except Exception as e:
                    QMessageBox.critical(parent_main_window, "Error", f"Failed to load settings: {e}")
        # self.settings_changed.emit(settings)

    # def run_tool(self, tool_name):
    #     """Simulate running the tool using saved settings."""
    #     print(f"Running tool {tool_name} with saved settings")
    def _normalize_status_columns(self):
        """Reserve a consistent width for the status (column 1) of both the
        Demand Models and Route Choice Models grids so the labels don't
        collapse when empty or jump wider when 'Running...'/'Completed'/'Failed'
        appears, and so the two groups stay visually aligned."""
        from qgis.PyQt.QtWidgets import QSizePolicy, QLabel as _QLabel
        from PyQt5.QtCore import QSize
        from PyQt5.QtGui import QFont, QFontMetrics
        # Size the status/messaging column to ~10 characters at the panel's
        # small (8pt) font. The longest message shown is "Running..." (10
        # chars); reserve just enough for it plus the 4px label padding so the
        # column is compact instead of a wide blank gap.
        fm = QFontMetrics(QFont("MS Shell Dlg 2", 8))
        STATUS_WIDTH = max(
            fm.horizontalAdvance(s) for s in ("Running...", "Completed", "Failed")
        ) + 12
        # Reserve the status column width on both independent grids.
        for grid_name in ("gridLayout_13", "gridLayout_2"):
            grid = getattr(self.ui, grid_name, None)
            if grid is not None:
                grid.setColumnMinimumWidth(1, STATUS_WIDTH)
        # Give every status label the same fixed footprint so text changes
        # don't resize the column.
        status_labels = [
            "label_PopSIM", "label_Skimmy", "label_SDTRes", "label_SDTVis",
            "label_LDTRes", "label_LDTVis", "label_Truck", "label_TripList",
            "label_TSMAssign", "label_SubAssign", "label_Hydra",
        ]
        for name in status_labels:
            lbl = getattr(self.ui, name, None)
            if not isinstance(lbl, _QLabel):
                continue
            lbl.setMinimumSize(QSize(STATUS_WIDTH, 0))
            lbl.setMaximumWidth(STATUS_WIDTH)
            sp = QSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
            sp.setHeightForWidth(lbl.sizePolicy().hasHeightForWidth())
            lbl.setSizePolicy(sp)
            lbl.setAlignment(Qt.AlignCenter)

    # Friendly names for the status labels, used in the Messages log.
    _STEP_NAMES = {
        "label_PopSIM": "Population SIM",
        "label_Skimmy": "Skimmy",
        "label_SDTRes": "SDT Resident",
        "label_SDTVis": "SDT Visitor",
        "label_LDTRes": "LDT Resident",
        "label_LDTVis": "LDT Visitor",
        "label_Truck": "Truck Trip Table",
        "label_TripList": "agentPlans",
        "label_TSMAssign": "ELToD",
        "label_SubAssign": "Subarea Assignment",
        "label_Hydra": "HyDRA",
        "label_Many2One": "Link Consolidator",
        "label_MSRDisagg": "MSR",
    }

    def _step_name(self, label):
        obj = label.objectName() if label is not None else ""
        return self._STEP_NAMES.get(obj, obj.replace("label_", "") or "Step")

    def _history_file(self):
        """Path to the per-scenario action-history log, or None if no scenario
        directory has been set yet."""
        scen_dir = Config().get("scenarioDir")
        if not scen_dir:
            return None
        return os.path.join(scen_dir, "tsm_panel_history.log").replace("\\", "/")

    def log_message(self, text):
        """Append a timestamped action line to the Messages log and, when a
        scenario directory is set, to <scenarioDir>/tsm_panel_history.log so the
        history survives across sessions. No-op on the widget if it isn't present."""
        from datetime import datetime
        line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {text}"
        box = getattr(self.ui, "plainTextEdit_Messages", None)
        if box is not None:
            box.appendPlainText(line)
            sb = box.verticalScrollBar()
            sb.setValue(sb.maximum())
        hist = self._history_file()
        if hist:
            try:
                with open(hist, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception as e:
                print(f"Could not write history log {hist}: {e}")

    def _load_history(self):
        """Load the saved action history for the current scenario into the
        Messages box (replacing its contents). No-op if there's no history yet."""
        box = getattr(self.ui, "plainTextEdit_Messages", None)
        if box is None:
            return
        hist = self._history_file()
        if not hist or not os.path.exists(hist):
            return
        try:
            with open(hist, "r", encoding="utf-8") as f:
                box.setPlainText(f.read().rstrip("\n"))
            sb = box.verticalScrollBar()
            sb.setValue(sb.maximum())
        except Exception as e:
            print(f"Could not read history log {hist}: {e}")

    def mark_step_completed(self, label: QLabel):
        label.setText("Completed")
        label.setStyleSheet("""
            QLabel {
                background-color: green;
                color: white;
                padding: 4px;
                border-radius: 4px;
            }
        """)
        self.log_message(f"{self._step_name(label)}: completed")

    def mark_step_failed(self, label: QLabel):
        label.setText("Failed")
        label.setStyleSheet("background-color: red; color: white; padding: 4px; border-radius: 4px;")
        self.log_message(f"{self._step_name(label)}: FAILED")

    def mark_step_in_progress(self, label: QLabel):
        label.setText("Running...")
        label.setStyleSheet("background-color: yellow; color: black; padding: 4px; border-radius: 4px;")
        self.log_message(f"{self._step_name(label)}: running…")

    def reset_all_step_labels(self):
        for label in [
            self.ui.label_PopSIM, self.ui.label_LDTRes, self.ui.label_LDTVis,
            self.ui.label_SDTRes, self.ui.label_SDTVis, self.ui.label_Skimmy,
            self.ui.label_TripList, self.ui.label_TSMAssign, self.ui.label_SubAssign
        ]:
            label.setText("")
            label.setStyleSheet("")
        # The Messages log is a persistent history, so it is intentionally NOT
        # cleared here — "Clear Status" only resets the per-step status labels.
