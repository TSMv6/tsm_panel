import os
import subprocess
from qgis.PyQt.QtWidgets import QDialog, QFileDialog, QMessageBox, QComboBox
from qgis.core import QgsProject, QgsVectorLayer
from qgis.PyQt.QtWidgets import QTextBrowser
from .tsm_link_consolidator_ui import Ui_Dialog
from qgis.PyQt import uic  # For loading .ui dynamically

from qgis.PyQt.QtCore import Qt, QEvent
from qgis.PyQt.QtGui import QStandardItemModel, QStandardItem
from .tsm_settings import Config

# Name of the netPrep control file written/read in the scenario (output) directory.
SETTINGS_FILENAME = "link_consolidation_settings.txt"


class MultiFieldCombo(QComboBox):
    """Compact multi-select combo: each item is checkable, the popup stays open
    while toggling, and the closed combo shows the comma-joined checked fields.
    Used for COUNT_FIELD, where several count columns (AADT + period/hourly
    COUNT_AM / COUNT_HR7 ...) can be selected together."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.lineEdit().setReadOnly(True)
        self.setModel(QStandardItemModel(self))
        # Toggle on the view's PRESSED signal: it fires on mouse-press on both
        # Qt5 and Qt6, BEFORE any popup-close plumbing runs, so the check always
        # lands regardless of how the platform closes combo popups. (Doing the
        # toggle in the release event-filter broke on QGIS4/Qt6, whose popup
        # container handles clicks differently.)
        self.view().pressed.connect(self._toggle_index)
        # Best effort: eat the RELEASE so the popup stays open while checking
        # several fields. If a Qt version closes the popup anyway, the toggle
        # already happened on press -- reopen to check the next field.
        self.view().viewport().installEventFilter(self)

    def _toggle_index(self, idx):
        it = self.model().itemFromIndex(idx)
        if it is None:
            return
        it.setCheckState(Qt.CheckState.Unchecked
                         if it.checkState() == Qt.CheckState.Checked
                         else Qt.CheckState.Checked)
        self._refresh_text()

    def eventFilter(self, obj, ev):
        if obj is self.view().viewport() and ev.type() == QEvent.Type.MouseButtonRelease:
            return True  # keep the popup open; the toggle happened on press
        return super().eventFilter(obj, ev)

    def hidePopup(self):
        # Qt may push the activated item's text into the line edit as the popup
        # closes; re-assert the joined checked-fields display.
        super().hidePopup()
        self._refresh_text()

    def set_fields(self, names, checked):
        m = self.model()
        m.clear()
        for n in names:
            it = QStandardItem(n)
            it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if n in checked
                             else Qt.CheckState.Unchecked)
            m.appendRow(it)
        self._refresh_text()

    def checked_fields(self):
        m = self.model()
        return [m.item(r).text() for r in range(m.rowCount())
                if m.item(r).checkState() == Qt.CheckState.Checked]

    def set_checked(self, fields):
        """Check exactly `fields`, adding any that aren't listed yet (saved
        selections must survive even when the layer isn't loaded)."""
        m = self.model()
        existing = [m.item(r).text() for r in range(m.rowCount())]
        names = existing + [f for f in fields if f not in existing]
        self.set_fields(names, set(fields))

    def _refresh_text(self):
        self.lineEdit().setText(", ".join(self.checked_fields()))


class TsmNetManDialog(QDialog, Ui_Dialog):
    def __init__(self):
        super().__init__()

        # Verify the UI file path
        settings = Config()
        plugin_dir = settings.get("plugin_dir")
        ui_file = os.path.join(plugin_dir, "ui/tsm_link_consolidator.ui")
        print(f"UI file found at: {ui_file}")

        if not os.path.exists(ui_file):
            print(f"UI file not found at: {ui_file}")
            return

        # Load the UI dynamically
        uic.loadUi(ui_file, self)

        # Populate the layer dropdowns by geometry type.
        #   line     -> GeoMaster line layer        (LineString)
        #   node     -> GeoMaster node layer        (Point)
        #   centroid -> GeoMaster centroid layer    (Point)
        #   cencon   -> GeoMaster cen-con layer     (LineString)
        self.populate_layer_combobox(self.lineLayerCombo, "LineString")
        self.populate_layer_combobox(self.nodeLayerCombo, "Point")
        self.populate_layer_combobox(self.lineLayerCombo_2, "Point")        # centroid
        self.populate_layer_combobox(self.lineLayerCombo_3, "LineString")   # centroid connector

        # Year dropdown
        self.comboBox_Year.addItems(["2023", "2024", "2025", "2030", "2035", "2050"])

        # ------------------------------------------------------------------
        # Fallback prefill from Config (project settings). The settings file,
        # loaded below, takes precedence over these.
        # ------------------------------------------------------------------
        if settings.get("scenarioName"):
            self.lineEdit_ScenarioName.setText(settings.get("scenarioName"))
        if settings.get("networkYear"):
            self.comboBox_Year.setCurrentText(settings.get("networkYear"))
        if settings.get("scenarioDir"):
            self.output_directory.setText(settings.get("scenarioDir"))
        if settings.get("max_internal_zones"):
            self.lineEdit_MaxZones.setText(str(settings.get("max_internal_zones")))
        # Shared GeoMaster layers + network version come from Config (set once in
        # Project Settings, or a prior run) so they are not re-picked per widget.
        # The scenario settings file, loaded below, still overrides these.
        if settings.get("network_version"):
            self.networkVersion.setCurrentText(settings.get("network_version"))
        self._select_layer_by_name(self.lineLayerCombo,   settings.get("GM_line_layer"))
        self._select_layer_by_name(self.nodeLayerCombo,   settings.get("GM_node_layer"))
        self._select_layer_by_name(self.lineLayerCombo_2, settings.get("GM_centroid_layer"))
        self._select_layer_by_name(self.lineLayerCombo_3, settings.get("GM_cencon_layer"))
        # This widget's own fields (outputs + run options) also persist in Config,
        # so restore them here -- otherwise an OK without a Run leaves them blank
        # on reopen (the settings file below still wins when it has them).
        if settings.get("TSM_Link_File"):
            self.lineEdit_TSMLink.setText(settings.get("TSM_Link_File"))
        if settings.get("TSM_Node_File"):
            self.lineEdit_TSMNode.setText(settings.get("TSM_Node_File"))
        if settings.get("model_resolution"):
            self.modelResolution.setCurrentText(str(settings.get("model_resolution")))
        if settings.get("msr_subarea"):
            self.lineEdit_MSRSubarea.setText(settings.get("msr_subarea"))
        if settings.get("msr_lookup"):
            self.lineEdit_MSRLookup.setText(settings.get("msr_lookup"))
        if settings.get("bool_Counts") is not None:
            self.checkBox_Counts.setChecked(self._str2bool(settings.get("bool_Counts")))
        # Count field(s): user-driven (no hardcoded TSMv5.COUNT_24). Multi-select --
        # AADT plus period/hourly counts (COUNT_AM, COUNT_HR7, ...) can be picked
        # together; netPrep aggregates and outputs each as its own column. Options
        # come from the selected line layer's fields matching CNT / COUNT / AADT;
        # the selection is saved globally (Config "count_field", comma-joined) so
        # netPrep and Summarization agree. The .ui ships a plain QComboBox
        # placeholder; swap it for the checkable multi-select at load.
        # Swap the placeholder for the multi-select DETERMINISTICALLY: remove it
        # from its known grid cell (gridLayout_3 row 0, col 1) and add the new
        # widget there. (QLayout.replaceWidget left the detached placeholder
        # floating at the frame's top-left on some Qt builds, covering the
        # Scenario Name label.)
        _old = self.comboBox_CountField
        self.comboBox_CountField = MultiFieldCombo(_old.parentWidget())
        self.comboBox_CountField.setToolTip(_old.toolTip())
        self.gridLayout_3.removeWidget(_old)
        _old.hide()
        _old.setParent(None)
        _old.deleteLater()
        self.gridLayout_3.addWidget(self.comboBox_CountField, 0, 1)
        self.lineLayerCombo.currentIndexChanged.connect(self._populate_count_fields)
        self.checkBox_Counts.toggled.connect(self.comboBox_CountField.setEnabled)
        self.comboBox_CountField.setEnabled(self.checkBox_Counts.isChecked())
        self._populate_count_fields()
        # QLOS capacities file (user setting). Default to {tsm_location}/Inputs/netPrep.
        cap = settings.get("netprep_capacities_file")
        if not cap:
            tloc = settings.get("tsm_location") or ""
            cap = (os.path.join(tloc, "Inputs", "netPrep", "QLOS_capacities.csv").replace("\\", "/")
                   if tloc else "")
        self.lineEdit_Capacities.setText(cap)

        # Help text: render docs/LINK_CONSOLIDATION.md into the side panel.
        self.textBrowser = self.findChild(QTextBrowser, 'textBrowser')
        self.textBrowser.setOpenExternalLinks(True)
        self.textBrowser.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self._load_help_doc(os.path.join(plugin_dir, "docs", "LINK_CONSOLIDATION.md"))

        # ------------------------------------------------------------------
        # START FROM THE SETTINGS FILE: read link_consolidation_settings.txt
        # from the scenario directory and populate every widget from it.
        # ------------------------------------------------------------------
        self.load_from_settings_file()
        # Default the output file paths (load-output-files on by default) so a
        # run always produces loadable TSM_Link/TSM_Node layers.
        self._apply_default_output_files()

        # Connect buttons
        self.browse_Outdir.clicked.connect(self.select_directory)
        self.browse_TSMLink.clicked.connect(lambda: self.select_file(self.lineEdit_TSMLink, "save"))
        self.browse_TSMNode.clicked.connect(lambda: self.select_file(self.lineEdit_TSMNode, "save"))
        self.browse_MSRSubarea.clicked.connect(
            lambda: self.select_file(self.lineEdit_MSRSubarea, "open", "GeoPackage (*.gpkg);; Shapefiles (*.shp)"))
        self.browse_MSRLookup.clicked.connect(
            lambda: self.select_file(self.lineEdit_MSRLookup, "open", "CSV (*.csv)"))
        self.browse_Capacities.clicked.connect(
            lambda: self.select_file(self.lineEdit_Capacities, "open", "CSV (*.csv)"))

        # Enable/disable the MSR inputs based on model resolution
        self.modelResolution.currentTextChanged.connect(self.toggle_msr_fields)
        self.toggle_msr_fields()

        # Network version: TSMv6 = separate centroid/connector layers;
        # TSMv5 = link + node only (centroids in node file, connectors in link file).
        self.networkVersion.currentTextChanged.connect(self.toggle_network_version)
        self.toggle_network_version()

        # Run / OK / Cancel
        self.buttonBox_Run.clicked.connect(lambda: self.run_Many2One_script(show_message=True))
        self.buttonBox_okCancel.accepted.connect(self.update_settings)
        self.buttonBox_okCancel.rejected.connect(self.cancel_action)

    # ======================================================================
    # Settings-file helpers
    # ======================================================================
    @staticmethod
    def _str2bool(value):
        return str(value).strip().lower() in ("true", "t", "1", "yes", "y")

    @staticmethod
    def _parse_settings_file(file_path):
        """Parse a `key = value` settings file (mirrors read_properties.R)."""
        cfg = {}
        with open(file_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                cfg[key.strip()] = value.strip().strip('"')
        return cfg

    def _resolve_settings_file(self):
        """Return the path to link_consolidation_settings.txt for this scenario."""
        out_dir = self.output_directory.text().strip()
        if not out_dir or out_dir == "Select Output Directory":
            out_dir = Config().get("scenarioDir") or ""
        if not out_dir:
            return None
        return os.path.join(out_dir, SETTINGS_FILENAME).replace("\\", "/")

    def load_from_settings_file(self):
        """Populate the dialog from the existing settings file, if present."""
        out_dir = Config().get("scenarioDir")
        if not out_dir:
            print("No scenario directory set; skipping settings-file load.")
            return
        sfile = os.path.join(out_dir, SETTINGS_FILENAME)
        if not os.path.exists(sfile):
            print(f"No link consolidation settings file found at: {sfile}")
            return

        cfg = self._parse_settings_file(sfile)
        print(f"Loading link consolidation settings from: {sfile}")

        if cfg.get("scenario_name"):
            self.lineEdit_ScenarioName.setText(cfg["scenario_name"])
        if cfg.get("year"):
            self.comboBox_Year.setCurrentText(str(cfg["year"]))
        if cfg.get("max_internal_zones"):
            self.lineEdit_MaxZones.setText(str(cfg["max_internal_zones"]))

        # Network version: explicit key wins, else infer from presence of the
        # separate centroid/connector layers (v6) vs link+node only (v5).
        nv = cfg.get("network_version")
        if not nv:
            nv = "TSMv6" if (cfg.get("Geomaster_centroid_layer") or cfg.get("Geomaster_cencon_layer")) else "TSMv5"
        self.networkVersion.setCurrentText(nv.strip())

        # Layer combos store full paths in the settings file. Line/node accept the
        # legacy v5 line_layer/node_layer keys as a fallback.
        self.select_layer_by_path(self.lineLayerCombo,
                                  cfg.get("Geomaster_line_layer") or cfg.get("line_layer"))
        self.select_layer_by_path(self.nodeLayerCombo,
                                  cfg.get("Geomaster_node_layer") or cfg.get("node_layer"))
        self.select_layer_by_path(self.lineLayerCombo_2, cfg.get("Geomaster_centroid_layer"))
        self.select_layer_by_path(self.lineLayerCombo_3, cfg.get("Geomaster_cencon_layer"))

        if cfg.get("model_resolution"):
            self.modelResolution.setCurrentText(cfg["model_resolution"].strip())
        if cfg.get("msr_subarea"):
            self.lineEdit_MSRSubarea.setText(cfg["msr_subarea"])
        if cfg.get("msr_lookup"):
            self.lineEdit_MSRLookup.setText(cfg["msr_lookup"])
        if cfg.get("capacities_file"):
            self.lineEdit_Capacities.setText(cfg["capacities_file"])

        if "keep_Counts" in cfg:
            self.checkBox_Counts.setChecked(self._str2bool(cfg["keep_Counts"]))
        if cfg.get("COUNT_FIELD"):
            self.comboBox_CountField.set_checked(self._split_fields(cfg["COUNT_FIELD"]))

        if cfg.get("output_dir"):
            self.output_directory.setText(cfg["output_dir"])
        if cfg.get("TSM_Link_File"):
            self.lineEdit_TSMLink.setText(cfg["TSM_Link_File"])
        if cfg.get("TSM_Node_File"):
            self.lineEdit_TSMNode.setText(cfg["TSM_Node_File"])

        self.toggle_msr_fields()
        self.toggle_network_version()

    # ======================================================================
    # UI behaviour
    # ======================================================================
    @staticmethod
    def _split_fields(value):
        """'AADT, COUNT_HR7' -> ['AADT', 'COUNT_HR7'] (trimmed, empties dropped)."""
        return [p.strip() for p in (value or "").split(",") if p.strip()]

    def _populate_count_fields(self):
        """Fill the count-field multi-select from the selected GeoMaster line
        layer: every field whose name contains CNT, COUNT or AADT (case-
        insensitive). The previously saved selection (Config "count_field",
        comma-joined) stays checked; saved-but-unlisted fields are kept as extra
        items so a headless/full run still writes the right COUNT_FIELD."""
        import re as _re
        checked = self.comboBox_CountField.checked_fields() or \
            self._split_fields(Config().get("count_field"))
        layer = self.lineLayerCombo.currentData()
        names = []
        if layer is not None and hasattr(layer, "fields"):
            pat = _re.compile(r"CNT|COUNT|AADT", _re.I)
            names = [f.name() for f in layer.fields() if pat.search(f.name())]
        names += [c for c in checked if c not in names]
        self.comboBox_CountField.set_fields(names, set(checked))

    def toggle_msr_fields(self):
        """Enable MSR subarea/lookup inputs only for the MSR resolution."""
        is_msr = self.modelResolution.currentText() == "MSR"
        for widget in (self.label_MSRSubarea, self.lineEdit_MSRSubarea, self.browse_MSRSubarea,
                       self.label_MSRLookup, self.lineEdit_MSRLookup, self.browse_MSRLookup):
            widget.setEnabled(is_msr)

    def toggle_network_version(self):
        """TSMv5 networks embed centroids in the node file and connectors in the
        link file, so the separate centroid/connector inputs are hidden for v5.
        TSMv5 also supports the TSM resolution only (no RPM, no MSR)."""
        is_v6 = self.networkVersion.currentText() == "TSMv6"
        for widget in (self.lineLayerCombo_2, self.label_Input_Linelayer_2,
                       self.lineLayerCombo_3, self.label_Input_Linelayer_3):
            widget.setEnabled(is_v6)
        # TSMv5 is TSM-resolution only; lock the dropdown to TSM.
        if not is_v6:
            self.modelResolution.setCurrentText("TSM")
        self.modelResolution.setEnabled(is_v6)
        self.toggle_msr_fields()

    def _load_help_doc(self, md_path):
        """Render a markdown help file into the side panel (Qt >= 5.14 setMarkdown)."""
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

    def update_settings(self):
        """Persist the current selections into the Config store."""
        settings = Config()
        settings.set("scenarioName", self.lineEdit_ScenarioName.text())
        settings.set("networkYear", self.comboBox_Year.currentText())
        settings.set("max_internal_zones", self.lineEdit_MaxZones.text())
        settings.set("scenarioDir", self.output_directory.text().strip())
        settings.set("network_version", self.networkVersion.currentText())
        settings.set("model_resolution", self.modelResolution.currentText())
        settings.set("msr_subarea", self.lineEdit_MSRSubarea.text())
        settings.set("msr_lookup", self.lineEdit_MSRLookup.text())
        settings.set("netprep_capacities_file", self.lineEdit_Capacities.text())
        settings.set("bool_Counts", self.checkBox_Counts.isChecked())
        # Global count field(s), comma-joined -- netPrep, Summarization and
        # validation all read this.
        if self.comboBox_CountField.checked_fields():
            settings.set("count_field", ", ".join(self.comboBox_CountField.checked_fields()))
        settings.set("GM_line_layer", self.lineLayerCombo.currentText())
        settings.set("GM_node_layer", self.nodeLayerCombo.currentText())
        settings.set("GM_centroid_layer", self.lineLayerCombo_2.currentText())
        settings.set("GM_cencon_layer", self.lineLayerCombo_3.currentText())
        settings.set("TSM_Link_File", self.lineEdit_TSMLink.text())
        settings.set("TSM_Node_File", self.lineEdit_TSMNode.text())
        settings.check_and_save_to_file("scenario_settings_file")
        QMessageBox.information(self, "Settings Updated", "Project Specific settings have been updated.")

    def cancel_action(self):
        print("Action canceled. Closing dialog.")
        self.reject()

    def select_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Directory")
        if directory:
            self.output_directory.setText(directory)
            self._apply_default_output_files()

    def _apply_default_output_files(self):
        """Default the TSM Link/Node output paths to <output_dir>/TSM_Link.gpkg
        and TSM_Node.gpkg whenever they are blank, so netPrep always has a place
        to write and the consolidated layers load back automatically."""
        out_dir = self.output_directory.text().strip()
        if not out_dir or out_dir == "Select Output Directory":
            return
        out_dir = out_dir.replace("\\", "/")
        if not self.lineEdit_TSMLink.text().strip():
            self.lineEdit_TSMLink.setText(f"{out_dir}/TSM_Link.gpkg")
        if not self.lineEdit_TSMNode.text().strip():
            self.lineEdit_TSMNode.setText(f"{out_dir}/TSM_Node.gpkg")

    def select_file(self, line_edit, type, file_filter="GeoPackage (*.gpkg);; Shapefiles (*.shp)"):
        if type == "open":
            file_path, _ = QFileDialog.getOpenFileName(self, "Select File", "", file_filter)
        elif type == "save":
            file_path, _ = QFileDialog.getSaveFileName(self, "Select File", "", file_filter)
        else:
            return
        if file_path:
            line_edit.setText(file_path)

    def populate_layer_combobox(self, combobox, geom_type):
        """Populate the dropdown with layers of the specified geometry type."""
        combobox.clear()
        combobox.addItem("Select a layer", None)
        layers = QgsProject.instance().mapLayers().values()
        vector_layers = [layer for layer in layers if hasattr(layer, "geometryType")]
        for layer in vector_layers:
            if layer.geometryType() == {"Point": 0, "LineString": 1, "Polygon": 2}[geom_type]:
                combobox.addItem(layer.name(), layer)

    def get_layer_path(self, layer):
        """Return the data source path for a combo entry (layer object or stored path)."""
        if layer is None:
            return None
        if isinstance(layer, str):
            return layer
        provider = layer.dataProvider()
        return provider.dataSourceUri().split("|")[0]

    def _select_layer_by_name(self, combobox, name):
        """Select a combo entry by layer name (Config stores layer names, not
        paths). No-op if the name is empty or not among the loaded layers."""
        if not name:
            return
        idx = combobox.findText(name)
        if idx >= 0:
            combobox.setCurrentIndex(idx)

    def select_layer_by_path(self, combobox, path):
        """Select the combo entry whose source matches `path`.

        If no loaded layer matches, add the path itself as a selectable entry so
        the value from the settings file is preserved and still written back out.
        """
        if not path:
            return
        target = os.path.normpath(path).lower()
        for i in range(combobox.count()):
            data = combobox.itemData(i)
            if data is not None and hasattr(data, "dataProvider"):
                src = self.get_layer_path(data)
                if src and os.path.normpath(src).lower() == target:
                    combobox.setCurrentIndex(i)
                    return
        combobox.addItem(os.path.basename(path), path)
        combobox.setCurrentIndex(combobox.count() - 1)

    def load_output_layer(self, file_path, layer_name):
        if not os.path.exists(file_path):
            print(f"File not found: {file_path}")
            return False
        layer = QgsVectorLayer(file_path, layer_name, "ogr")
        if not layer.isValid():
            print(f"Failed to load {layer_name}.")
            return False
        QgsProject.instance().addMapLayer(layer)
        print(f"Loaded {layer_name} successfully.")
        return True

    def load_layer_symbology(self, qml_file, layer_name):
        if qml_file and os.path.exists(qml_file):
            layer = QgsProject.instance().mapLayersByName(layer_name)[0]
            layer.loadNamedStyle(qml_file)
            layer.triggerRepaint()
            print(f"Loaded symbology for: {layer_name}")
        else:
            print(f"Unable to load symbology for: {layer_name}")

    # ======================================================================
    # Run
    # ======================================================================
    def run_Many2One_script(self, show_message=False):
        """Write the netPrep control file and run netPrep.exe."""
        settings = Config()
        plugin_dir = settings.get("plugin_dir")
        network_version = self.networkVersion.currentText()

        # Collect layer paths
        line_path = self.get_layer_path(self.lineLayerCombo.currentData())
        node_path = self.get_layer_path(self.nodeLayerCombo.currentData())
        centroid_path = self.get_layer_path(self.lineLayerCombo_2.currentData())
        cencon_path = self.get_layer_path(self.lineLayerCombo_3.currentData())

        if not (line_path and node_path):
            QMessageBox.critical(self, "Error", "Please select the link and node layers.")
            return False
        if network_version == "TSMv6" and not (centroid_path and cencon_path):
            QMessageBox.critical(
                self, "Error",
                "TSMv6 requires separate centroid and centroid-connector layers.\n"
                "Switch Network Version to TSMv5 for link+node-only networks.")
            return False

        # Other fields
        scenario_name = self.lineEdit_ScenarioName.text()
        selected_year = self.comboBox_Year.currentText()
        max_internal_zones = self.lineEdit_MaxZones.text()
        model_resolution = self.modelResolution.currentText()
        msr_subarea = self.lineEdit_MSRSubarea.text().strip()
        msr_lookup = self.lineEdit_MSRLookup.text().strip()
        output_dir = self.output_directory.text().strip()
        # Ensure default output paths are filled so the run always has loadable
        # TSM_Link / TSM_Node targets even if the fields were cleared.
        self._apply_default_output_files()
        output_linkfile = self.lineEdit_TSMLink.text().strip()
        output_nodefile = self.lineEdit_TSMNode.text().strip()

        if not output_dir or output_dir == "Select Output Directory":
            QMessageBox.critical(self, "Error", "Please select an output directory.")
            return False
        if model_resolution == "MSR" and not (msr_subarea and msr_lookup):
            QMessageBox.critical(self, "Error", "MSR resolution requires an MSR subarea polygon and lookup table.")
            return False

        bool_Counts = self.checkBox_Counts.isChecked()
        # User-selected ground-count field(s) (multi-select next to Keep Counts),
        # comma-joined. Saved globally so Summarization / validation read the
        # same column names.
        count_field = ", ".join(self.comboBox_CountField.checked_fields())
        if count_field:
            settings.set("count_field", count_field)

        # QLOS capacities lookup (FTYPE|lanes -> capacity) is a user setting / model
        # input, not a plugin asset and NOT a hardcoded path in netPrep. Default to
        # {tsm_location}/Inputs/netPrep/QLOS_capacities.csv; overridable via Config.
        tsm_location = settings.get("tsm_location") or ""
        capacities_file = (self.lineEdit_Capacities.text().strip() or
                           settings.get("netprep_capacities_file") or
                           os.path.join(tsm_location, "Inputs", "netPrep",
                                        "QLOS_capacities.csv")).replace("\\", "/")

        settings_file = os.path.join(output_dir, SETTINGS_FILENAME).replace("\\", "/")

        try:
            with open(settings_file, "w") as f:
                print(f"Writing settings to: {settings_file}")
                f.write(f"scenario_name = {scenario_name}\n")
                f.write(f"year = {selected_year}\n")
                f.write(f"max_internal_zones = {max_internal_zones}\n")
                f.write(f"network_version = {network_version}\n")
                f.write(f"Geomaster_line_layer = {line_path}\n")
                f.write(f"Geomaster_node_layer = {node_path}\n")
                if network_version == "TSMv6":
                    f.write(f"Geomaster_centroid_layer = {centroid_path}\n")
                    f.write(f"Geomaster_cencon_layer = {cencon_path}\n")
                f.write(f"model_resolution = {model_resolution}\n")
                f.write(f"msr_subarea = {msr_subarea}\n")
                f.write(f"msr_lookup = {msr_lookup}\n")
                f.write(f"output_dir = {output_dir}\n")
                f.write(f"Settings_File = {settings_file}\n")
                f.write(f"keep_Counts = {bool_Counts}\n")
                if count_field:
                    f.write(f"COUNT_FIELD = {count_field}\n")
                f.write(f"TSM_Link_File = {output_linkfile}\n")
                f.write(f"TSM_Node_File = {output_nodefile}\n")
                f.write(f"plugin_dir = {plugin_dir}\n")
                # Capacities lookup path passed explicitly (no hardcoded path in the exe).
                f.write(f"capacities_file = {capacities_file}\n")
                # Run both consolidation and GMNS export (GMNS feeds the DTA
                # assignment; built from the consolidated network in one pass).
                f.write("RUN_MODE = both\n")
        except Exception as e:
            print("Error writing settings file:", e)
            QMessageBox.critical(self, "Error", f"Error writing settings file: {e}")
            return False

        # Resolve and run netPrep.exe (v6 C++ link consolidator). Ships self-
        # contained (exe + GDAL DLLs + gdal-data/proj) inside the plugin's Apps
        # folder, so the user installs nothing beyond the plugin.
        exe_path = os.path.join(plugin_dir, "Apps", "netPrep", "netPrep.exe")
        if not os.path.exists(exe_path):
            QMessageBox.critical(self, "Error", f"netPrep.exe not found at: {exe_path}")
            return False

        print(f"netPrep exe : {exe_path}")
        print(f"Settings    : {settings_file}")

        # netPrep ships its own self-contained GDAL beside the exe. Launch it with
        # that GDAL on PATH (plus its matching gdal-data/proj) instead of letting
        # the subprocess inherit QGIS's environment -- otherwise the shipped
        # gdal.dll tries to load QGIS's version-mismatched driver plugins and
        # spams "Can't load requested DLL ... 127" errors in the log.
        # run_app builds that GDAL env (PATH/GDAL_DRIVER_PATH/GDAL_DATA/PROJ_LIB)
        # itself, and runs in a live console tee'd to a log next to the settings file.
        try:
            result = Config().run_app([exe_path, settings_file],
                                      log_path=os.path.splitext(settings_file)[0] + ".log", console=True)
            if result.returncode != 0:
                print("netPrep execution failed.")
                if show_message:
                    QMessageBox.critical(self, "Error", "netPrep execution failed. Check console for details.")
                return False

            print("netPrep executed successfully.")
            # netPrep writes the spatial TSM_Link / TSM_Node GeoPackages directly
            # (true merged geometry in the GeoMaster CRS), plus GMNS in 'both'
            # mode. Load the consolidated layers.
            # Output layers always load; failing to load them is an error.
            link_qml_file = os.path.join(plugin_dir, "qgis_styles/TSM_Link_Symbology.qml").replace("\\", "/")
            node_qml_file = os.path.join(plugin_dir, "qgis_styles/TSM_Node_Symbology.qml").replace("\\", "/")
            link_layer_name = os.path.splitext(os.path.basename(output_linkfile))[0]
            node_layer_name = os.path.splitext(os.path.basename(output_nodefile))[0]
            ok_link = self.load_output_layer(output_linkfile, link_layer_name)
            ok_node = self.load_output_layer(output_nodefile, node_layer_name)
            if not (ok_link and ok_node):
                missing = "\n".join(p for p, ok in
                                    ((output_linkfile, ok_link), (output_nodefile, ok_node)) if not ok)
                QMessageBox.critical(
                    self, "Error",
                    f"netPrep finished but the output layer(s) could not be loaded:\n{missing}")
                return False
            self.load_layer_symbology(link_qml_file, link_layer_name)
            self.load_layer_symbology(node_qml_file, node_layer_name)
            settings.set("link_layer_name", link_layer_name)
            settings.set("node_layer_name", node_layer_name)

            if show_message:
                QMessageBox.information(self, "Success", "Link consolidation completed successfully.")
            return True
        except Exception as e:
            print("Error running netPrep:", e)
            QMessageBox.critical(self, "Error", f"Error running netPrep: {e}")
            return False
