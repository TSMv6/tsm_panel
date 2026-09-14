import os, re
import subprocess
from qgis.PyQt.QtWidgets import QDialog, QFileDialog, QDockWidget, QMessageBox
from qgis.core import QgsProject, QgsVectorLayer
from qgis.PyQt import uic  # For loading .ui dynamically
from .tsm_settings import Config
from . import tsm_history
# from .helper_functions import HelperFun

import processing

from .summary_loadedNetwork_ui import Ui_QDailog_LoadedNetwork

class Summary_Dialog(QDialog, Ui_QDailog_LoadedNetwork):
    def __init__(self):
        super().__init__()
        # self.setupUi(self)

        settings = Config()
        plugin_dir = settings.get("plugin_dir")
        ui_file = os.path.join(plugin_dir, "ui/summary_loadedNetwork.ui")
        print(f"UI file found at: {ui_file}")

        # Check if the UI file exists
        if not os.path.exists(ui_file):
            print(f"UI file not found at: {ui_file}")
            return  # If the file doesn't exist, stop further execution

        # Load the UI dynamically if the file exists
        uic.loadUi(ui_file, self)  # This will automatically load the UI and set it up

        # Multi-DTA inputs (macro required; meso/micro optional) + the
        # agentAnalysis tabs (Path Trace / Subarea / Select Link / Turns),
        # injected programmatically so the .ui stays Designer-clean.
        from .agent_analysis_tabs import (add_dta_inputs, add_common_section,
                                          add_agent_analysis_tabs)
        self.lineEdit_volumeMeso, self.lineEdit_volumeMicro = add_dta_inputs(self)
        add_common_section(self)   # shared agentPaths.duckdb + separators
        add_agent_analysis_tabs(self)

        # Populate the dropdowns with available land-use layers (polygons)
        self.populate_layer_combobox(self.comboBox_linkLayer, "LineString")

        # Restore from Config. Factored into load_settings() so the Load button
        # can re-apply a settings file to the open dialog, not just __init__.
        self.load_settings()

        self.browse_volume.clicked.connect(lambda: self.select_file(self.lineEdit_volume, "open"))
        self.browse_loadedOut.clicked.connect(lambda: self.select_file(self.lineEdit_loadedOut, "save"))
        self.checkBox_isSubarea.stateChanged.connect(self.toggle_TSM_or_subarea)

        self.browse_ValidationStats.clicked.connect(lambda: self.select_file_xlsx(self.lineEdit_validationStats, "save"))
        self.browse_ValidationStats.setEnabled(False)
        self.checkBox_ValidationStats.stateChanged.connect(self.toggle_validation_stats)

        # The .ui no longer wires accepted -> accept(), so there may be nothing
        # to disconnect; PyQt raises if you disconnect an unconnected signal.
        try:
            self.buttonBox_OkCancel.accepted.disconnect()
        except TypeError:
            pass
        # Save persists and keeps the dialog open; Cancel is the only close.
        self.buttonBox_OkCancel.accepted.connect(self.update_settings)
        self.buttonBox_OkCancel.rejected.connect(self.cancel_action)

        self.pushButton_Save.clicked.connect(self.save_settings_to_file)
        self.pushButton_Load.clicked.connect(self.load_settings_from_file)
        self.pushButton_Run.clicked.connect(self.run_summary)
       
        self.toggle_validation_stats()
        self.toggle_TSM_or_subarea()

    def load_settings(self):
        """Apply the current Config() to the widgets. Called from __init__ and
        again after Load, so a loaded file is reflected in the open dialog."""
        settings = Config()
        if settings.get("link_layer_name") != "":
            link_layer_name = settings.get("link_layer_name")
            if link_layer_name in [self.comboBox_linkLayer.itemText(i)
                                   for i in range(self.comboBox_linkLayer.count())]:
                self.comboBox_linkLayer.setCurrentText(link_layer_name)
        if settings.get("volume_file"):
            self.lineEdit_volume.setText(settings.get("volume_file"))
        # Optional meso/micro DTA inputs read back just like the macro volume.
        # (The injected browse rows also self-load from Config, but mirror the
        # macro handling here so the read path is explicit and order-independent.)
        if settings.get("volume_file_meso"):
            self.lineEdit_volumeMeso.setText(settings.get("volume_file_meso"))
        if settings.get("volume_file_micro"):
            self.lineEdit_volumeMicro.setText(settings.get("volume_file_micro"))
        if settings.get("aa_trace_db"):
            self.lineEdit_agentPaths.setText(settings.get("aa_trace_db"))
        if settings.get("loadedOut_file"):
            self.lineEdit_loadedOut.setText(settings.get("loadedOut_file"))
        if settings.get("isSubareaLevel"):
            self.checkBox_isSubarea.setChecked(settings.get("isSubareaLevel"))
        if settings.get("validationStats_file"):
            self.lineEdit_validationStats.setText(settings.get("validationStats_file"))
        if settings.get("validationStats"):
            self.checkBox_ValidationStats.setChecked(settings.get("validationStats"))

    def save_settings_to_file(self):
        """Export the current settings to a JSON file.

        update_settings() runs first on purpose: Config holds what was last
        persisted, so saving without it would write stale values and silently
        drop whatever the user just typed.
        """
        self.update_settings(notify=False)
        settings = Config()
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Settings", "",
                                                   "JSON Files (*.json);;All Files (*)")
        if not file_path:
            return
        try:
            settings.save_to_file(file_path)
            QMessageBox.information(self, "Information", f"Saved settings to: {file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save settings: {e}")

    def load_settings_from_file(self):
        """Read settings from a JSON file and refresh this dialog."""
        settings = Config()
        file_path, _ = QFileDialog.getOpenFileName(self, "Open Settings", "",
                                                   "JSON Files (*.json);;All Files (*)")
        if not file_path:
            return
        try:
            settings.load_from_file(file_path)
            plugin_dir = os.path.dirname(__file__).replace("\\", "/")
            settings.set("plugin_dir", plugin_dir)
            self.load_settings()
            self.toggle_validation_stats()
            self.toggle_TSM_or_subarea()
            QMessageBox.information(self, "Information", f"Read settings from: {file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load settings: {e}")

    def toggle_TSM_or_subarea(self):
        """Enable or disable the TSM or subarea button based on the checkbox state."""
        settings = Config()
        if self.checkBox_isSubarea.isChecked():
            settings.set("isSubareaLevel", True)
        else:
            settings.set("isSubareaLevel", False)

    def toggle_validation_stats(self):
        """Enable or disable the validation stats button based on the checkbox state."""
        settings = Config()
        if self.checkBox_ValidationStats.isChecked():
            self.browse_ValidationStats.setEnabled(True)
            self.lineEdit_validationStats.setEnabled(True)
            settings.set("validationStats", True)
        else:
            self.browse_ValidationStats.setEnabled(False)
            self.lineEdit_validationStats.setEnabled(False)
            self.lineEdit_validationStats.clear()
            settings.set("validationStats", False)

    def cancel_action(self):
        """Handles the Cancel button."""
        print("Action canceled. Closing dialog.")
        self.reject()  # Closes the dialog without executing any code

    @staticmethod
    def _ensure_suffix(path, suffix):
        """Append `suffix` (e.g. '.xlsx') if `path` doesn't already end with it.
        QFileDialog.getSaveFileName does not reliably auto-append the filter
        extension, so the chosen/typed path can come back bare."""
        if path and not path.lower().endswith(suffix.lower()):
            path += suffix
        return path

    def select_file(self, line_edit, type):
        if type == "open":
            file_path, _ = QFileDialog.getOpenFileName(self, "Select File", "", "All Files (*)") #"", "JSON Files (*.json);;All Files (*)")
        elif type == "save":
            file_path, _ = QFileDialog.getSaveFileName(self, "Select File", "", "GeoPackage (*.gpkg);;Shapefiles (*.shp)")
            if file_path and "." not in os.path.basename(file_path):
                file_path = self._ensure_suffix(file_path, ".gpkg")

        if file_path:
            line_edit.setText(file_path)

    def select_file_xlsx(self, line_edit, type):
        if type == "open":
            file_path, _ = QFileDialog.getOpenFileName(self, "Select File", "", "Excel File (*.xlsx)") #"", "JSON Files (*.json);;All Files (*)")
        elif type == "save":
            file_path, _ = QFileDialog.getSaveFileName(self, "Select File", "", "Excel File (*.xlsx);;All Files (*)")
            file_path = self._ensure_suffix(file_path, ".xlsx")

        if file_path:
            line_edit.setText(file_path)

    def populate_layer_combobox(self, combobox, geom_type):
        """Populate the dropdown with layers of the specified geometry type."""
        combobox.clear()
        combobox.addItem("Select a layer", None)  # Default option

        # Get all layers in QGIS
        layers = QgsProject.instance().mapLayers().values()
        vector_layers = [layer for layer in layers if hasattr(layer, "geometryType")]
        for layer in vector_layers:
            # if isinstance(layer, QgsVectorLayer) and 
            if layer.geometryType() == {"Point": 0, "LineString": 1, "Polygon": 2}[geom_type]:
                combobox.addItem(layer.name(), layer)

    def get_layer_path(self, layer):
        """Retrieve the data source path of a layer."""
        if layer:
            provider = layer.dataProvider()
            return provider.dataSourceUri().split("|")[0]  # Remove extra filter params
        return None
    
    def update_settings(self, notify=True):
        """Persist the dialog to the scenario settings; the dialog stays open.

        notify=False is used by Save-to-file, which needs Config to be current
        but should not stack a second message box on top of its own.
        """
        settings = Config()
        if self.comboBox_linkLayer.currentData():
            link_layer = self.comboBox_linkLayer.currentData()
            settings.set("link_layer_name", link_layer.name())  
        if self.lineEdit_volume.text():
            settings.set("volume_file", self.lineEdit_volume.text())
        if self.lineEdit_loadedOut.text():
            settings.set("loadedOut_file", self.lineEdit_loadedOut.text())
        if self.lineEdit_validationStats.text():
            settings.set("validationStats_file", self.lineEdit_validationStats.text())
        if self.checkBox_ValidationStats.isChecked():
            settings.set("validationStats", True)
        else:
            settings.set("validationStats", False)
        if self.checkBox_isSubarea.isChecked():
            settings.set("isSubareaLevel", True)
        else:
            settings.set("isSubareaLevel", False)

        # Persist the optional meso/micro DTA inputs + every agentAnalysis tab
        # field into the same scenario settings JSON, just like volume_file.
        from .agent_analysis_tabs import save_agent_settings
        save_agent_settings(self)

        settings.check_and_save_to_file("scenario_settings_file")
        if notify:
            QMessageBox.information(self, "Settings Saved",
                                    "Summarization settings saved. The dialog stays open -- "
                                    "use Cancel to close.")
           # Keep the dialog open
        # self.show()
    def _remove_layers_by_path(self, file_path):
        """Drop every project layer that points to `file_path` (matched by the
        actual file on disk, not the layer name). QGIS holds an open handle on a
        loaded GeoPackage; if we rewrite it while loaded, the new write appends a
        second layer (file size doubles, two layers appear). Removing the layer
        first releases the handle so summarize.exe can overwrite cleanly."""
        if not file_path:
            return 0
        target = os.path.normcase(os.path.abspath(file_path))
        proj = QgsProject.instance()
        removed = 0
        for lyr in list(proj.mapLayers().values()):
            try:
                src = lyr.source().split("|")[0]      # strip "|layername=..."
                if os.path.normcase(os.path.abspath(src)) == target:
                    proj.removeMapLayer(lyr.id())
                    removed += 1
            except Exception:
                continue
        if removed:
            # removeMapLayer only SCHEDULES the layer's C++ destruction; its OGR/
            # GeoPackage file handle lingers until the event loop + GC run. Without
            # forcing that here the file stays locked and summarize.exe fails with
            # "ERROR 1: ... already exists". Pump events + GC so the handle is
            # released before the exe runs.
            try:
                import gc
                from qgis.PyQt.QtWidgets import QApplication
                gc.collect()
                QApplication.processEvents()
                gc.collect()
            except Exception:
                pass
        return removed

    def load_output_layer(self, file_path, layer_name):
        """Load the output GPKG file into QGIS."""
        if os.path.exists(file_path):
            layer = QgsVectorLayer(file_path, layer_name, "ogr")
            if layer.isValid():
                QgsProject.instance().addMapLayer(layer)
                print(f"Loaded {layer_name} successfully.")
            else:
                print(f"Failed to load {layer_name}.")
        else:
            print(f"File not found: {file_path}")

    def load_layer_symbology(self, qml_file, layer_name):        
            # Apply a QML Style for the opened layer
            if qml_file and os.path.exists(qml_file):
                layer = QgsProject.instance().mapLayersByName(layer_name)[0]
                layer.loadNamedStyle(qml_file)
                layer.triggerRepaint()
                print(f"Success Loaded output layer: {layer_name}")
            else:
                print(f"Error Unable to Layer Symbology to: {layer_name}")
                
    def _write_validation_stats(self, loadedOut_file, xlsx_path):
        """Build the validation workbook (.xlsx) from the daily CSV that
        summarize.exe just wrote. Pure Python -- logs live to the History box +
        log file, no console window."""
        from qgis.PyQt.QtWidgets import QApplication
        out = (loadedOut_file or "").replace("\\", "/")
        daily_csv = (out[:-5] + "_daily.csv") if out.lower().endswith(".gpkg") \
            else (out + "_daily.csv")

        def logf(m):
            tsm_history.log_action(m, "Summarization")
            QApplication.processEvents()  # repaint the History box live (we're on the UI thread)
        try:
            from .validation_runner import write_validation_xlsx
            # The ground-count column is the user's Link Consolidation choice
            # (Config "count_field"). That key may list SEVERAL fields (daily +
            # period/hourly); daily validation compares against the FIRST one.
            # Falls back to auto-detect if unset.
            cf = (Config().get("count_field") or "").split(",")[0].strip() or None
            n = write_validation_xlsx(daily_csv, xlsx_path, count_field=cf, log=logf)
            QMessageBox.information(
                self, "Validation Stats",
                "Validation workbook written (%d counted locations):\n%s" % (n, xlsx_path))
        except Exception as ve:
            logf("Summarization: validation FAILED -- %s" % ve)
            QMessageBox.warning(self, "Validation Stats",
                                "Validation stats could not be written:\n%s" % ve)

    def run_summary(self):
        # Save first, silently: a run must use exactly what is on screen.
        self.update_settings(notify=False)
        settings = Config()
        plugin_dir = settings.get("plugin_dir")
        link_layer = self.comboBox_linkLayer.currentData()
        volume_file = self.lineEdit_volume.text()
        loadedOut_file = self.lineEdit_loadedOut.text()
        if not link_layer:
            QMessageBox.warning(self, "Warning", "Please select a link layer.")
            return
        if not volume_file:
            QMessageBox.warning(self, "Warning", "Please select a volume file.")
            return
        
        validationStats = settings.get("validationStats")
        if validationStats and not self.lineEdit_validationStats.text():
            QMessageBox.warning(self, "Warning", "Please select a validation stats file.")
            return

        if validationStats:
            bool_validation_stats = "TRUE"
            # Guarantee the .xlsx extension even if the path was typed by hand
            # (the save dialog enforces it, manual entry does not). Reflect the
            # corrected path back into the field so the user sees what's written.
            validationStats_file = self._ensure_suffix(self.lineEdit_validationStats.text(), ".xlsx")
            self.lineEdit_validationStats.setText(validationStats_file)
        else:
            bool_validation_stats = "FALSE"
            validationStats_file = "None"

        # Get the path of the link layer
        link_layer_path = self.get_layer_path(link_layer)
        if not link_layer_path:
            QMessageBox.warning(self, "Warning", "Link layer path not found.")
            return
        
        from .summarize_runner import run_summary
        is_subarea = bool(settings.get("isSubareaLevel"))

        # Optional meso / micro DTA link-performance files -> [input2]/[input3].
        # Any hydra link_performance input switches to the hydra template.
        meso_file = self.lineEdit_volumeMeso.text().strip()
        micro_file = self.lineEdit_volumeMicro.text().strip()
        is_hydra = "link_performance" in os.path.basename(volume_file).lower() \
                   or meso_file or micro_file
        template = "summarize_hydra.toml" if is_hydra else "summarize_loaded.toml"

        print("link_layer_path:", link_layer_path)
        print("volume_file:", volume_file)
        print("meso_file:", meso_file, "micro_file:", micro_file, "template:", template)
        print("loadedOut_file:", loadedOut_file)
        print("is_subarea:", is_subarea)

        loaded_qml_file = os.path.join(plugin_dir, "qgis_styles/TSM_Loaded_Symbology.qml").replace("\\","/")

        # Overwrite: if the output GPKG is already loaded (matched by file path),
        # drop it so the rewrite doesn't append a second layer / double the file.
        dropped = self._remove_layers_by_path(loadedOut_file)
        if dropped:
            tsm_history.log_action(
                "Summarization: dropped %d loaded layer(s) for overwrite of %s"
                % (dropped, os.path.basename(loadedOut_file)), "Summarization")

        try:
            # C++ summarize.exe (port of Summarise_Loaded_Volumes.R)
            result1 = run_summary(template, link_layer_path, volume_file, loadedOut_file,
                                  subarea=is_subarea, vol2=meso_file or None,
                                  vol3=micro_file or None)

            if result1.returncode == 0:  # Check if the R script ran successfully
                print("loaded entwork volumes script ran successfully.")

                self.load_output_layer(loadedOut_file, "LoadedNetwork")
                self.load_layer_symbology(loaded_qml_file, "LoadedNetwork")

                # Validation stats: Python post-step (pandas/openpyxl) reading the
                # daily CSV summarize just wrote. Logs live to the History box + log
                # file; no extra console window.
                if validationStats:
                    self._write_validation_stats(loadedOut_file, validationStats_file)

                QMessageBox.information(self, "Success", "Loaded network volumes script ran successfully.")
            else:
                print("error running loaded networks or validation.")
        except Exception as e:
            print("Error running loaded networks or validation:", e)
            QMessageBox.critical(self, "Error", f"Error running summary script: {e}") 
            # self.close()
        # QMessageBox.information(self, "Success", "Loaded network volumes script ran successfully.")

