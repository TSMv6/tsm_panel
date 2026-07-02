import os
from qgis.PyQt.QtWidgets import QDialog, QFileDialog, QMessageBox
from qgis.PyQt import uic  # For loading .ui dynamically
from .tsm_settings import Config
from . import msr_run

from .MSR_ui import Ui_Dialog_MSR


class MSR_Disaggregate(QDialog, Ui_Dialog_MSR):
    """Standalone MSR (Multi-Spatial Resolution) editor. Disaggregates a TSM
    trip list to subarea subzones by running msr.exe (see msr_run). The same
    engine runs as a sub-step of agentPlans; this dialog exposes it directly."""

    def __init__(self):
        super().__init__()

        settings = Config()
        plugin_dir = settings.get("plugin_dir")
        ui_file = os.path.join(plugin_dir, "ui/MSR.ui")
        if not os.path.exists(ui_file):
            print(f"UI file not found at: {ui_file}")
            return
        uic.loadUi(ui_file, self)

        self._populate_help()
        scen = (settings.get("scenarioDir") or "").replace("\\", "/")
        self.label_outDir.setText(f"Scenario directory: {scen}" if scen else
                                  "Scenario directory not set — set it in Project / Scenario Specs.")

        # Browse buttons
        self.browse_MSRTrips.clicked.connect(lambda: self.select_file(self.lineEdit_MSRTrips, "Trip list (*.csv.gz *.csv)"))
        self.browse_MSRSubarea.clicked.connect(lambda: self.select_file(self.lineEdit_MSRSubarea, "Subarea zones (*.csv)"))
        self.browse_MSRLookup.clicked.connect(lambda: self.select_file(self.lineEdit_MSRLookup, "Subzone lookup (*.csv *.gpkg)"))

        self.button_OkCancel.accepted.connect(self.update_settings)
        self.button_OkCancel.rejected.connect(self.cancel_action)
        self.Run_MSR.clicked.connect(lambda: self.run_MSR(show_message=True))

        # Size-term coefficient TOMLs: shown with their bundled default paths so the
        # user can see (and replace) them. disaggregate recomputes size terms from
        # these every run, so pointing here at a recalibrated TOML is how size terms
        # change -- there is no cached size-term file.
        self._bundled_tomls = msr_run.bundled_sizeterm_tomls(settings)
        self._toml_fields = {
            "sdt_resident": self.lineEdit_TomlSdtRes,
            "sdt_visitor":  self.lineEdit_TomlSdtVis,
            "ldt":          self.lineEdit_TomlLdt,
            "truck":        self.lineEdit_TomlTruck,
        }
        for k, edit in self._toml_fields.items():
            edit.setText(settings.get(msr_run.SIZETERM_KEYS[k]) or self._bundled_tomls[k])
        self.browse_TomlSdtRes.clicked.connect(lambda: self.select_file(self.lineEdit_TomlSdtRes, "Size-term TOML (*.toml)"))
        self.browse_TomlSdtVis.clicked.connect(lambda: self.select_file(self.lineEdit_TomlSdtVis, "Size-term TOML (*.toml)"))
        self.browse_TomlLdt.clicked.connect(lambda: self.select_file(self.lineEdit_TomlLdt, "Size-term TOML (*.toml)"))
        self.browse_TomlTruck.clicked.connect(lambda: self.select_file(self.lineEdit_TomlTruck, "Size-term TOML (*.toml)"))

        # Prefill from saved settings (shared keys with the agentPlans MSR step).
        if settings.get("msr_trip_list"):
            self.lineEdit_MSRTrips.setText(settings.get("msr_trip_list"))
        if settings.get("msr_subarea"):
            self.lineEdit_MSRSubarea.setText(settings.get("msr_subarea"))
        if settings.get("msr_lookup"):
            self.lineEdit_MSRLookup.setText(settings.get("msr_lookup"))
        self.checkBox_SizeTerms.setChecked(
            str(settings.get("msr_export_sizeterms")).lower() in ("true", "1", "yes"))

    # ------------------------------------------------------------------
    def _populate_help(self):
        html = """
<html><body style='font-family:Segoe UI,Arial; font-size:9pt; line-height:1.35;'>
<h3 style='margin:0 0 6px 0;'>MSR &#8211; Multi-Spatial Resolution</h3>
<p>SE data is held at the regional planning resolution (~26k subzones) for
portability, but the model runs at the TSM resolution (~8.7k zones) for speed.
MSR <b>disaggregates</b> a TSM-resolution trip list down to the finer subzones
inside a chosen <b>subarea</b>, so a corridor / project area can be analysed at
high resolution without re-running the whole statewide model at 26k.</p>

<h4>Where MSR fits</h4>
<pre style='font-family:Consolas,monospace; font-size:9pt; background:#f4f4f4; padding:6px;'>
Regular:  RPM zones &#8594; TSM zones &#8594; Skims / Demand Models &#8594; agentPlans &#8594; agentFlow

MSR:      RPM zones &#8594; TSM zones &#8594; Skims / Demand Models &#8594; <b>MSR</b> &#8594; <b>MSR agentPlans</b> &#8594; agentFlow
                                                          (subarea subzones)
</pre>
<p><i>RPM = Regional Planning Model (~26k zones). MSR inserts the subarea
sub-zone disaggregation step into the otherwise TSM-zone pipeline.</i></p>

<h4>Inputs</h4>
<ul>
<li><b>Trip list (.csv.gz)</b> &#8211; the TSM-resolution trip list to split
(<code>tripList_&lt;res&gt;min.csv.gz</code> from agentPlans).</li>
<li><b>Subarea zone list</b> &#8211; the parent TSM zones that define the subarea.</li>
<li><b>Subzone lookup (26k)</b> &#8211; the land-use table mapping each subzone to its
parent TSM zone (<code>parent_col = TSM_NG</code>).</li>
</ul>

<h4>Size terms &#8211; recomputed every run</h4>
<p>Destination <b>size terms</b> are computed from the bundled SDT / LDT / truck
coefficient <b>TOMLs</b>. <code>msr disaggregate</code> <b>recomputes them on every
run</b> &#8211; there is <u>no cached size-term file</u> to keep in sync. So you do not
need a &quot;recompute&quot; step: if a coefficient TOML changes, the next run already
reflects it.</p>
<ul>
<li>To use <b>recalibrated</b> coefficients, point the <b>Size-term coefficients</b>
fields at the modified <code>.toml</code>(s) (they show the bundled defaults by
default). That override is what changes the size terms.</li>
<li><b>Check the box</b> &quot;Also export size-terms review CSV&quot; only if you want a
QA copy of the computed terms written to
<code>subarea_taz_sizeTerms.csv</code> (<code>TSM_NG, Index, market, purpose,
sizeTerm, probability</code>). It runs <code>msr sizeterms</code> and is <b>not</b>
reused by the disaggregation.</li>
</ul>

<h4>Outputs (scenario directory)</h4>
<ul>
<li><code>subarea_msr_triplist.csv.gz</code> &#8211; MSR trip list with O_MSR/D_MSR.</li>
<li><code>ELToD_MSR_Hourly_tt.csv</code> &#8211; hourly MSR OD trip table.</li>
<li><code>subarea_taz_sizeTerms.csv</code> &#8211; only if the QA box is checked.</li>
</ul>
<p>Runs <code>msr.exe disaggregate</code> on a control file written to
<code>msr_control.toml</code>. The same engine also runs inside the
<b>agentPlans (Trip List &#8594; Table)</b> step.</p>
</body></html>
"""
        self.textBrowser_Help.setHtml(html)

    def cancel_action(self):
        self.reject()

    def select_file(self, line_edit, file_filter):
        path, _ = QFileDialog.getOpenFileName(self, "Select File", "", file_filter + ";; All Files (*)")
        if path:
            line_edit.setText(path.replace("\\", "/"))

    def _apply_to_config(self, settings):
        """Push the dialog's fields into Config (no file write). A size-term TOML
        override is stored only when it differs from the bundled default, so
        unchanged fields stay dynamic (follow the plugin config)."""
        settings.set("msr_trip_list", self.lineEdit_MSRTrips.text())
        settings.set("msr_subarea", self.lineEdit_MSRSubarea.text())
        settings.set("msr_lookup", self.lineEdit_MSRLookup.text())
        settings.set("msr_export_sizeterms", self.checkBox_SizeTerms.isChecked())
        for k, edit in self._toml_fields.items():
            val = edit.text().strip().replace("\\", "/")
            settings.set(msr_run.SIZETERM_KEYS[k],
                         "" if (not val or val == self._bundled_tomls[k]) else val)

    def update_settings(self):
        settings = Config()
        self._apply_to_config(settings)
        settings.check_and_save_to_file("scenario_settings_file")
        QMessageBox.information(self, "Settings Updated", "MSR settings have been updated.")

    def run_MSR(self, show_message=False):
        settings = Config()
        # Apply current fields (incl. any TOML override) so msr_run sees them.
        self._apply_to_config(settings)
        scenario_dir = settings.get("scenarioDir")
        ok, msg = msr_run.run(
            scenario_dir,
            self.lineEdit_MSRTrips.text().strip(),
            self.lineEdit_MSRSubarea.text().strip(),
            self.lineEdit_MSRLookup.text().strip(),
            settings=settings,
            export_sizeterms=self.checkBox_SizeTerms.isChecked(),
        )
        if not ok:
            QMessageBox.critical(self, "Error", msg)
            return False
        if show_message:
            QMessageBox.information(self, "Success", msg)
        return True
