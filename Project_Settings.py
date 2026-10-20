import os
import subprocess
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QApplication, QButtonGroup, QDialog, QFileDialog, QMessageBox
from qgis.core import QgsProject, QgsVectorLayer
from qgis.PyQt import uic  # For loading .ui dynamically
from .tsm_settings import Config
from .network_version import fill_versions, set_version, version
from . import msr_region

from .Project_Settings_ui import Ui_Dialog_ProjectSettings

class ProjectSpecsDialog(QDialog, Ui_Dialog_ProjectSettings):
    def __init__(self):
        super().__init__()
        # self.setupUi(self)
 
         # Verify the UI file path
        # plugin_dir = os.path.dirname(__file__).replace("\\", "/")
        settings = Config()
        plugin_dir = settings.get("plugin_dir")
        ui_file = os.path.join(plugin_dir, "ui/Project_Settings.ui")
        print(f"UI file found at: {ui_file}")

        # Check if the UI file exists
        if not os.path.exists(ui_file):
            print(f"UI file not found at: {ui_file}")
            return  # If the file doesn't exist, stop further execution

        # Load the UI dynamically if the file exists
        uic.loadUi(ui_file, self)  # This will automatically load the UI and set it up

        # Populate the dropdowns with available layers
        self.populate_layer_combobox(self.lineLayerCombo, "LineString")
        self.populate_layer_combobox(self.nodeLayerCombo, "Point")
        self.populate_layer_combobox(self.landuseLayerCombo, "Polygon")
        # TSMv6 networks add separate GeoMaster centroid (Point) and
        # centroid-connector (LineString) layers, mirroring the Link Consolidator
        # inputs. TSMv5 embeds these in the node/link files (inputs hidden below).
        self.populate_layer_combobox(self.centroidLayerCombo, "Point")
        self.populate_layer_combobox(self.cenconLayerCombo, "LineString")
        # MSR user-defined boundary: a loaded polygon layer.
        self.populate_layer_combobox(self.comboBox_BoundaryLayer, "Polygon")
        # Shown as Navteq24 / Navteq11, stored as TSMv6 / TSMv5. Set before the
        # network years: which years are offered depends on the version.
        fill_versions(self.comboBox_NetworkVersion)
        set_version(self.comboBox_NetworkVersion, settings.get("network_version") or "TSMv6")

         # Populate Year specific list in dropdown
        self.comboBox_ScenYear.addItems(["2023", "2024", "2025", "2030", "2035", "2040", "2045", "2050", "2055", "2060"])
        self._fill_net_years()
        
        # Update Settings ("Main Panel -> Load Settings -> Config()")
        if settings.get("scenarioName"):
            self.lineEdit_ScenarioName.setText(settings.get("scenarioName"))
        if settings.get("scenarioYear"):
            userYear = settings.get("scenarioYear")
            # if userYear not in [self.comboBox_ScenYear.itemText(i) for i in range(self.comboBox_ScenYear.count())]:
            #     self.comboBox_ScenYear.addItem(userYear)  # Add the new text if it's not already present
            self.comboBox_ScenYear.setCurrentText(userYear)
        if settings.get("networkYear"):
            userNetYear = settings.get("networkYear")
            # Set the new text in the combo box
            self.comboBox_NetYear.setCurrentText(userNetYear)

        if(settings.get("scenarioDescription")):
            self.textEdit_ScenarioDescription.setPlainText(settings.get("scenarioDescription"))
        if settings.get("scenarioDir"):
            self.scenario_directory.setText(settings.get("scenarioDir"))
        if settings.get("GM_line_layer") != "":
            line_layer_name = settings.get("GM_line_layer")
            if line_layer_name in [self.lineLayerCombo.itemText(i) for i in range(self.lineLayerCombo.count())]:
                    self.lineLayerCombo.setCurrentText(line_layer_name)
        if settings.get("GM_node_layer") != "":
            node_layer_name = settings.get("GM_node_layer")
            if node_layer_name in [self.nodeLayerCombo.itemText(i) for i in range(self.nodeLayerCombo.count())]:
                    self.nodeLayerCombo.setCurrentText(node_layer_name)
        if settings.get("landuse_layer") != "":
            landuse_layer_name = settings.get("landuse_layer")
            if landuse_layer_name in [self.landuseLayerCombo.itemText(i) for i in range(self.landuseLayerCombo.count())]:
                    self.landuseLayerCombo.setCurrentText(landuse_layer_name)

        # TSMv6-only centroid / cen-con layers (the version itself is set above).
        if settings.get("GM_centroid_layer"):
            centroid_name = settings.get("GM_centroid_layer")
            if centroid_name in [self.centroidLayerCombo.itemText(i) for i in range(self.centroidLayerCombo.count())]:
                    self.centroidLayerCombo.setCurrentText(centroid_name)
        if settings.get("GM_cencon_layer"):
            cencon_name = settings.get("GM_cencon_layer")
            if cencon_name in [self.cenconLayerCombo.itemText(i) for i in range(self.cenconLayerCombo.count())]:
                    self.cenconLayerCombo.setCurrentText(cencon_name)

        # Model Resolution: Standard TSM, or MSR with an RPM region OR a user
        # boundary (whose RPM zones replace their TSM zones). The RPM list is
        # read from the land use's Model column. Two exclusive groups: all four
        # radios share one parent, so Qt's auto-exclusivity would merge them.
        self._grp_res = QButtonGroup(self)
        self._grp_res.addButton(self.radioButton_StdTSM)
        self._grp_res.addButton(self.radioButton_MSR)
        self._grp_region = QButtonGroup(self)
        self._grp_region.addButton(self.radioButton_RPMRegion)
        self._grp_region.addButton(self.radioButton_UserBoundary)
        self._fill_rpm_regions(settings.get("msr_rpm_model"))
        self.landuseLayerCombo.currentIndexChanged.connect(lambda _i: self._fill_rpm_regions())
        if settings.get("msr_boundary_layer"):
            self.comboBox_BoundaryLayer.setCurrentText(settings.get("msr_boundary_layer"))
        is_msr = settings.get("model_structure") == "MSR"
        self.radioButton_MSR.setChecked(is_msr)
        self.radioButton_StdTSM.setChecked(not is_msr)
        if settings.get("msr_boundary_layer"):
            self.radioButton_UserBoundary.setChecked(True)
        else:
            self.radioButton_RPMRegion.setChecked(True)
        if settings.get("msr_summary"):
            self.label_MSRSummary.setText("Last created: " + settings.get("msr_summary"))
        self.checkBox_PopSynRPM.setChecked(str(settings.get("popsyn_rpm_statewide")) in ("True", "true", "1"))
        if settings.get("zone_landuse_file"):
            self.lineEdit_ZoneLanduse.setText(settings.get("zone_landuse_file"))
        self.browse_ZoneLanduse.clicked.connect(self._browse_zone_landuse)
        self.pushButton_CreateMSRLU.clicked.connect(lambda: self.create_zone_structure())
        for w in (self.radioButton_MSR, self.radioButton_RPMRegion, self.radioButton_UserBoundary):
            w.toggled.connect(self.toggle_msr)
        self.toggle_msr()

        # Connect buttons to browse function
        self.browse_Scendir.clicked.connect(lambda: self.select_directory(self.scenario_directory))
        # Show/hide the v6-only inputs as the network version changes.
        self.comboBox_NetworkVersion.currentTextChanged.connect(self.toggle_network_version)
        self.toggle_network_version()

        # self.pushButton_Browse_TSMPath.clicked.connect(lambda: self.select_directory(self.lineEdit_ModelPath))
        # self.pushButton_Browse_TSMPath.clicked.connect(lambda: self.select_file(self.lineEdit_SettingsFile))

        # selected_year = self.comboBox_ScenYear.currentText()
        # scenarioName = self.lineEdit_ScenarioName.text()
        # scenarioDir = self.scenario_directory.text()
   


        # Run the script when the "Run" button is clicked
        # self.buttonBox_Run.clicked.connect(self.run_r_script)
        self.buttonBox_Run.accepted.connect(self.update_settings)
        self.buttonBox_Run.rejected.connect(self.cancel_action)

    def cancel_action(self):
        """Handles the Cancel button."""
        print("Action canceled. Closing dialog.")
        self.reject()  # Closes the dialog without executing any code

    def select_directory(self, scenario_directory):
        directory = QFileDialog.getExistingDirectory(self, "Select Directory")
        if directory:
            self.scenario_directory.setText(directory)

    def _fill_rpm_regions(self, keep=None):
        """RPM regions = the selected land use's Model values (needs PopSyn_Index)."""
        keep = keep or self.comboBox_RPMRegion.currentText()
        self.comboBox_RPMRegion.clear()
        layer = self.landuseLayerCombo.currentData()
        models = msr_region.regional_models(layer) if layer is not None else []
        self.comboBox_RPMRegion.addItems(models)
        if keep in models:
            self.comboBox_RPMRegion.setCurrentText(keep)

    def _browse_zone_landuse(self):
        start = self.lineEdit_ZoneLanduse.text().strip() or os.path.join(
            (self.scenario_directory.text() or "").strip(), msr_region.LANDUSE_GPKG)
        path, _ = QFileDialog.getSaveFileName(self, "Zonal land use (output)", start,
                                              "GeoPackage (*.gpkg)")
        if path:
            if not path.lower().endswith(".gpkg"):
                path += ".gpkg"
            self.lineEdit_ZoneLanduse.setText(path.replace("\\", "/"))

    @staticmethod
    def _same_file(a, b):
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))

    def _release_layers(self, *paths):
        """Remove every layer reading one of `paths` from the project: Windows
        keeps a loaded GeoPackage open, so it could not be rewritten."""
        paths = [p for p in paths if p and os.path.exists(p)]
        for lyr in list(QgsProject.instance().mapLayers().values()):
            src = lyr.source().split("|")[0] if hasattr(lyr, "source") else ""
            if src.startswith("file:"):                      # delimited-text layers
                src = src[5:].lstrip("/").split("?")[0]
            if src and any(self._same_file(src, p) for p in paths):
                QgsProject.instance().removeMapLayer(lyr.id())

    def _resolution_choice(self):
        """The Model Resolution picked in the dialog, as one comparable tuple."""
        msr = self.radioButton_MSR.isChecked()
        model = self.comboBox_RPMRegion.currentText() if (msr and self.radioButton_RPMRegion.isChecked()) else ""
        bnd = self.comboBox_BoundaryLayer.currentData() if (msr and self.radioButton_UserBoundary.isChecked()) else None
        lu = self.landuseLayerCombo.currentData()
        return ("MSR" if msr else "TSM", model, bnd.name() if bnd is not None else "",
                (not msr) and self.checkBox_PopSynRPM.isChecked(),
                lu.name() if lu is not None else "", (self.lineEdit_ZoneLanduse.text() or "").strip())

    def create_zone_structure(self):
        """'Create MSR LU': build and load the zone structure, then save the
        settings so the region the files describe is the one on record."""
        settings = Config()
        if self.scenario_directory.text().strip():
            settings.set("scenarioDir", self.scenario_directory.text().strip())
        if self.landuseLayerCombo.currentData():
            settings.set("landuse_layer", self.landuseLayerCombo.currentData().name())
        if not self._build_zone_structure(settings):
            return False
        settings.set("msr_choice", list(self._resolution_choice()))
        settings.check_and_save_to_file("scenario_settings_file")
        QMessageBox.information(self, "Model Resolution",
                                settings.get("msr_summary") + "\n\nLoaded:\n" +
                                "\n".join(p for p in (settings.get("zone_landuse_file"),
                                                       settings.get("msr_boundary_file"),
                                                       settings.get("msr_zones_file")) if p))
        return True

    def toggle_msr(self):
        msr = self.radioButton_MSR.isChecked()
        self.checkBox_PopSynRPM.setEnabled(not msr)
        for w in (self.radioButton_RPMRegion, self.radioButton_UserBoundary):
            w.setEnabled(msr)
        self.comboBox_RPMRegion.setEnabled(msr and self.radioButton_RPMRegion.isChecked())
        self.comboBox_BoundaryLayer.setEnabled(msr and self.radioButton_UserBoundary.isChecked())

    def _build_zone_structure(self, settings):
        """Write the region files + the model's zonal land use for the chosen
        Model Resolution into the scenario directory. Returns False (after
        telling the user) when the choice cannot be built."""
        msr = self.radioButton_MSR.isChecked()
        models = [self.comboBox_RPMRegion.currentText()] if (
            msr and self.radioButton_RPMRegion.isChecked() and self.comboBox_RPMRegion.currentText()) else []
        boundary = self.comboBox_BoundaryLayer.currentData() if (
            msr and self.radioButton_UserBoundary.isChecked()) else None
        if msr and not models and boundary is None:
            QMessageBox.warning(self, "Model Resolution",
                                "MSR needs an RPM region or a user-defined boundary layer.")
            return False
        landuse = self.landuseLayerCombo.currentData()
        scen = (self.scenario_directory.text() or "").strip()
        if landuse is None or not scen:
            QMessageBox.warning(self, "Model Resolution",
                                "Pick the SE Data (land use) layer and the scenario directory "
                                "to build the model's zone structure.")
            return False
        all_rpm = (not msr) and self.checkBox_PopSynRPM.isChecked()
        lu_out = (self.lineEdit_ZoneLanduse.text() or "").strip() or \
            os.path.join(scen, msr_region.LANDUSE_GPKG).replace("\\", "/")
        if landuse is not None and self._same_file(self.get_layer_path(landuse) or "", lu_out):
            QMessageBox.warning(self, "Model Resolution",
                                "The zonal land use (output) cannot overwrite the SE Data layer it is built from.")
            return False
        # Drop every layer reading the files about to be rewritten.
        self._release_layers(*msr_region.output_paths(lu_out))
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            r = msr_region.build_zone_structure(landuse, scen, models, boundary,
                                                landuse_out=lu_out, all_rpm=all_rpm)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Model Resolution", f"Could not build the zone structure:\n{e}")
            return False
        QApplication.restoreOverrideCursor()
        lo, hi = msr_region.popsyn_range(landuse)
        what = " + ".join(models + ([f"boundary '{boundary.name()}'"] if boundary is not None else []))
        summary = (f"MSR ({what}): {r['region_tsm_zones']:,} TSM zones -> {r['rpm_zones']:,} RPM zones; "
                   f"{r['tsm_zones'] + r['rpm_zones']:,} model zones" if msr
                   else f"Standard TSM, PopSyn at RPM level statewide: {r['rpm_zones']:,} RPM zones" if all_rpm
                   else f"Standard TSM: {r['tsm_zones']:,} zones")
        settings.set("model_structure", "MSR" if msr else "TSM")
        settings.set("msr_rpm_model", models[0] if models else "")
        settings.set("msr_boundary_layer", boundary.name() if boundary is not None else "")
        settings.set("msr_zones_file", r["region_csv"] or "")
        settings.set("msr_boundary_file", r["boundary_gpkg"] or "")
        settings.set("zone_landuse_file", r["landuse_gpkg"])
        settings.set("popsyn_rpm_statewide", all_rpm)
        self.lineEdit_ZoneLanduse.setText(r["landuse_gpkg"])
        # Load them, so the zonal land use can be picked in PopSyn right away.
        qml = os.path.join(settings.get("plugin_dir") or os.path.dirname(__file__),
                           "qgis_styles", "TSM_and_RPM_model_zones_landuse.qml")
        for path, style in ((r["boundary_gpkg"], None), (r["landuse_gpkg"], qml)):
            if not path:
                continue
            lyr = QgsVectorLayer(path, os.path.splitext(os.path.basename(path))[0], "ogr")
            if lyr.isValid():
                if style and os.path.exists(style):
                    lyr.loadNamedStyle(style)
                QgsProject.instance().addMapLayer(lyr)
        settings.set("rpm_zone_range", f"{lo}-{hi}" if lo else "")
        settings.set("msr_summary", summary)
        self.label_MSRSummary.setText("Last created: " + summary)
        return True

    def toggle_network_version(self):
        """TSMv6 uses separate GeoMaster centroid + cen-con layers; TSMv5 embeds
        them in the node/link files, so those inputs are hidden for v5."""
        is_v6 = version(self.comboBox_NetworkVersion) == "TSMv6"
        for widget in (self.centroidLayerCombo, self.label_Input_Centroidlayer,
                       self.cenconLayerCombo, self.label_Input_Cenconlayer):
            widget.setVisible(is_v6)
        self._fill_net_years()

    # Network years each version has networks for (keyed by stored value).
    NET_YEARS = {"TSMv6": ["2024", "2025", "2030", "2035", "2040", "2045", "2050", "2055"],  # Navteq24
                 "TSMv5": ["2023", "2024", "2025", "2030", "2035", "2050"]}                  # Navteq11

    def _fill_net_years(self):
        """Offer the network years valid for the selected version, keeping the
        current pick when it is still valid."""
        keep = self.comboBox_NetYear.currentText()
        years = self.NET_YEARS.get(version(self.comboBox_NetworkVersion), self.NET_YEARS["TSMv6"])
        self.comboBox_NetYear.clear()
        self.comboBox_NetYear.addItems(years)
        self.comboBox_NetYear.setCurrentIndex(years.index(keep) if keep in years else -1)

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

    def update_settings(self):
        settings = Config()
        if self.lineEdit_ScenarioName.text():
            settings.set("scenarioName", self.lineEdit_ScenarioName.text())
        if self.comboBox_ScenYear.currentText():
            settings.set("scenarioYear", self.comboBox_ScenYear.currentText())
        if self.comboBox_NetYear.currentText():
            settings.set("networkYear", self.comboBox_NetYear.currentText())
        if self.scenario_directory.text():
            settings.set("scenarioDir", self.scenario_directory.text())
        if self.textEdit_ScenarioDescription.toPlainText():
            settings.set("scenarioDescription", self.textEdit_ScenarioDescription.toPlainText())
        if self.lineLayerCombo.currentData():
            line_layer = self.lineLayerCombo.currentData()
            settings.set("GM_line_layer", line_layer.name())
        if self.nodeLayerCombo.currentData():
            node_layer = self.nodeLayerCombo.currentData()
            settings.set("GM_node_layer", node_layer.name())
        if self.landuseLayerCombo.currentData():
            landuse_layer = self.landuseLayerCombo.currentData()
            settings.set("landuse_layer", landuse_layer.name())
        # Network version + the TSMv6-only centroid / cen-con layers.
        settings.set("network_version", version(self.comboBox_NetworkVersion))
        if version(self.comboBox_NetworkVersion) == "TSMv6":
            if self.centroidLayerCombo.currentData():
                settings.set("GM_centroid_layer", self.centroidLayerCombo.currentData().name())
            if self.cenconLayerCombo.currentData():
                settings.set("GM_cencon_layer", self.cenconLayerCombo.currentData().name())
        # Save does not build the zone structure (Create MSR LU does); warn when
        # the Model Resolution shown is not the one last created.
        last = settings.get("msr_choice")
        if last is None or list(self._resolution_choice()) != list(last):
            QMessageBox.warning(self, "Model Resolution",
                                "The Model Resolution shown has not been created yet -- click "
                                "'Create MSR LU' to build and load its zonal land use. The rest "
                                "of the settings are saved.")
        settings.check_and_save_to_file("scenario_settings_file")
        QMessageBox.information(self, "Settings Updated", "Project Specific settings have been updated.")
        # self.close() 
        

