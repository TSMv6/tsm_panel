"""GeoMaster Checker: the Editors-section UI for gmcheck.exe.

gmcheck reads the GeoMaster link / node / connector layers, builds the network
the way netPrep does and reports coding problems keyed on LINK_ID (R1 class
breaks, R2 connectivity, R3 median crossovers, R4 LANE / SPEED / ATYPE
smoothing). Two steps: 1) the check writes the review GeoPackage (link_review,
node_review) and the CSVs; 2) after review in QGIS (approved = 1 / 0, edited
changes) the corrected copy of the link GeoPackage is written from the review
file. The inputs are never modified.

The dialog writes a gmcheck control file (key = value, the same keys as the
command-line run kit) and runs Apps/netPrep/gmcheck.exe on it. Left: options.
Right: a description of the widget under the mouse, above the full help.
"""
import os

from qgis.PyQt.QtCore import Qt, QEvent
from qgis.PyQt.QtWidgets import (
    QDialog, QHBoxLayout, QVBoxLayout, QGridLayout, QFormLayout, QSplitter, QWidget,
    QScrollArea, QFrame, QGroupBox, QLabel, QLineEdit, QComboBox, QPushButton, QCheckBox,
    QSpinBox, QDialogButtonBox, QTextBrowser, QFileDialog, QMessageBox, QSizePolicy)
from qgis.PyQt.QtGui import QFont
from qgis.core import QgsProject, QgsVectorLayer
from qgis.gui import QgsCollapsibleGroupBox

from .tsm_settings import Config

GEOM = {"Point": 0, "LineString": 1}

# Threshold settings: (ctl key, label, default, max, description)
THRESHOLDS = [
    ("RUN_MAX_M", "R1 longest run (m)", 2000, 20000,
     "R1: the longest run of links that can be recoded to the class on both sides of it."),
    ("SHORT_RUN_M", "R1 short run (m)", 300, 5000,
     "R1: a run up to this length, named like the road around it, is High confidence."),
    ("THROUGH_MIN_ANGLE", "Through angle (deg)", 135, 180,
     "Minor junctions: the two links of the main road must line up within this angle "
     "(180 = straight through)."),
    ("XOVER_MAX_M", "R3 crossover gap (m)", 60, 500,
     "R3: the greatest straight-line distance between the two carriageways a median "
     "crossover joins."),
    ("XOVER_PATH_MAX_M", "R3 crossover length (m)", 150, 1000,
     "R3: the longest median crossover chain, measured along its links."),
    ("XOVER_MIN_ANGLE", "R3 opposing angle (deg)", 135, 180,
     "R3: the two carriageways must run in opposite directions within this angle."),
    ("ATTR_RUN_MAX_M", "R4 longest run (m)", 800, 10000,
     "R4: the longest LANE / SPEED / ATYPE run that can take the value on both sides of it."),
    ("ATTR_SHORT_M", "R4 short run (m)", 300, 5000,
     "R4: a run up to this length is High confidence (applied); longer ones are Medium "
     "(reported only, unless Apply confidence is Medium)."),
    ("ATTR_END_MAX_M", "R4 end run (m)", 100, 2000,
     "R4: a run up to this length at either end of a stretch takes its neighbour's value."),
    ("NEAR_MISS_M", "R2 near miss (m)", 5, 500,
     "R2: for a dangling end, the nearest other node within this distance is reported "
     "(a likely missed connection)."),
]


class GMCheckDialog(QDialog):
    """GeoMaster Checker (gmcheck.exe)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("GeoMaster Checker (gmcheck.exe)")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.resize(1260, 780)
        self._desc = {}  # widget -> description shown on the right
        self._extra = {}  # control-file keys the dialog has no widget for (kept as read)
        self.settings = Config()
        self.plugin_dir = self.settings.get("plugin_dir") or os.path.dirname(__file__)
        self._build()
        self._load_help_doc(os.path.join(self.plugin_dir, "docs", "GMCHECK.md"))
        self._prefill()

    # ------------------------------------------------------------------ UI
    def _build(self):
        top = QHBoxLayout(self)
        split = QSplitter(Qt.Orientation.Horizontal, self)
        top.addWidget(split)

        # ---- left: options --------------------------------------------------
        left = QWidget()
        lv = QVBoxLayout(left)
        title = QLabel("GeoMaster Checker  –  gmcheck.exe")
        f = QFont(); f.setBold(True)
        if f.pointSize() > 0:
            f.setPointSize(f.pointSize() + 1)
        title.setFont(f)
        lv.addWidget(title)

        # Inputs
        g_in = QGroupBox("Inputs (GeoMaster, read only)")
        gi = QGridLayout(g_in)
        self.cbLink = self._layer_row(gi, 0, "Link layer", "LineString",
            "<b>GeoMaster link layer</b> (line GeoPackage). Every link with "
            "<code>useinTSM = 1</code> and <code>LANE_&lt;yy&gt; &gt; 0</code> is checked, "
            "as netPrep reads it. Pick a loaded layer or browse to a .gpkg.")
        self.cbNode = self._layer_row(gi, 1, "Node layer", "Point",
            "<b>GeoMaster node layer</b> (point GeoPackage). Used to join link ends at the "
            "same location and ZLEV onto one node, as netPrep does.")
        self.cbCencon = self._layer_row(gi, 2, "Connector layer", "LineString",
            "<b>Centroid connector layer</b>. Connector nodes are attachment points: a "
            "road is never treated as passing through them.")
        self.leConnType = self._line_row(gi, 3, "Connector type", "TSM",
            "Connector <code>type</code> value to read from the connector layer "
            "(TSM, RPM ...).")
        self.leUseField = self._line_row(gi, 4, "Network field", "useinTSM",
            "Field that selects the links in the network (<code>= 1</code>). "
            "<code>none</code> checks every link.")
        self.leYears = self._line_row(gi, 5, "Years", "",
            "Model years to check, e.g. <code>24, 50</code>. Blank = every "
            "<code>FTYPE_&lt;yy&gt;</code> on the layer.")
        lv.addWidget(g_in)

        # Step 1: check -> review file
        g_out = QGroupBox("Step 1 – Check (writes the review file)")
        go = QGridLayout(g_out)
        self.leOutDir = self._path_row(go, 0, "Output folder", "dir",
            "Folder for <code>gmcheck_links.csv</code> (every change: LINK_ID, before, after), "
            "<code>gmcheck_nodes.csv</code> (node issues), the review GPKG and "
            "<code>gmcheck.log</code>.")
        self.leReview = self._path_row(go, 1, "Review GPKG", "review",
            "<b>Review GeoPackage</b>. Step 1 writes it; step 2 reads it. Layer "
            "<code>link_review</code>: one row per link, year and rule, with "
            "<code>confidence</code>, <code>changes</code> (<code>FIELD before-&gt;after; ...</code>), "
            "<code>approved</code> (empty) and <code>proposed</code> (gmcheck's changes, kept for "
            "reference). Layer <code>node_review</code>: dead ends, islands, one-way traps, ZLEV "
            "mismatches. A review file with approved or edited rows is never overwritten: step 1 "
            "renames it <code>&lt;name&gt;_&lt;date_time&gt;.gpkg</code> first.")
        self.leCtl = self._path_row(go, 2, "Control file", "ctl",
            "The gmcheck control file this dialog writes (and can load with "
            "<i>Load control file</i>). Run it outside QGIS with "
            "<code>gmcheck.exe &lt;file&gt;</code> (step 1) and "
            "<code>gmcheck.exe &lt;file&gt; MODE=apply_review</code> (step 2).")
        self.chkLoad = self._check(go, 3, "Load review layers into QGIS", True,
            "After step 1, add <code>link_review</code> and <code>node_review</code> to the map "
            "for review.")
        lv.addWidget(g_out)

        # Step 2: review file -> corrected copy
        g_ap = QGroupBox("Step 2 – Corrected GeoMaster (from the review file)")
        ga = QGridLayout(g_ap)
        self.leCorrLink = self._path_row(ga, 0, "Corrected link GPKG", "save",
            "<b>Corrected copy of the link layer</b>: the input link layer with the review rows "
            "applied, plus <code>median_xover</code> and <code>gmcheck</code> (rules applied). "
            "Point netPrep's link layer here to use it.")
        self.cbConf = QComboBox(); self.cbConf.addItems(["High", "Medium", "Low"])
        self.cbApproved = QComboBox()
        self.cbApproved.addItem("Also approved = 1", "also")
        self.cbApproved.addItem("Only approved = 1", "only")
        self.cbApproved.addItem("Ignore approved", "ignore")
        cw = QWidget(); ch = QHBoxLayout(cw); ch.setContentsMargins(0, 0, 0, 0)
        labA = QLabel("User approved")
        ch.addWidget(self.cbConf, 1); ch.addSpacing(12); ch.addWidget(labA); ch.addWidget(self.cbApproved, 1)
        self._row(ga, 1, "Apply confidence", cw,
            "<b>Apply confidence</b>: rows at or above this <code>confidence</code> are written "
            "(High = only the clear cases). You can change a row's <code>confidence</code> in "
            "<code>link_review</code>.")
        self._describe(
            "<b>User approved</b>, from the <code>approved</code> field of <code>link_review</code>:"
            "<br><b>Also approved = 1</b> (default): rows at Apply confidence <i>plus</i> every "
            "row with <code>approved = 1</code>; <code>approved = 0</code> is never written."
            "<br><b>Only approved = 1</b>: just the approved rows."
            "<br><b>Ignore approved</b>: confidence only."
            "<br>A row's <code>changes</code> is written as it stands, so a value you edited "
            "there is the value applied.", labA, self.cbApproved)
        self.cbApproved.currentIndexChanged.connect(
            lambda _i: self.cbConf.setEnabled(self.cbApproved.currentData() != "only"))
        lv.addWidget(g_ap)

        # Rules
        g_r = QGroupBox("Rules")
        gr = QGridLayout(g_r)
        self.chkMinor = self._check(gr, 0, "Minor junctions (local_access / Other)", True,
            "<b>R1 / R3</b>: a junction whose cross streets are only local_access (48) or "
            "Other (45) does not end the main road, so the approaches on both sides are "
            "checked as one road, and its median link can be a median cut.")
        self.chkOther = self._check(gr, 1, "Other on divided roads → Div-Arterial", True,
            "<b>R1</b>: a run still coded Other whose links are all one-way (a divided road's "
            "carriageway) becomes Div-Arterial, with FNAME, SPEED, ATYPE and LANE from the "
            "Div-Arterial beside it.")
        self.chkSmooth = self._check(gr, 2, "Smooth LANE / SPEED / ATYPE (R4)", True,
            "<b>R4</b>: a short LANE, SPEED or ATYPE blip along one road takes the value on "
            "both sides, so netPrep consolidates the road into fewer links. Two-way lanes "
            "are compared per direction.")
        self.cbXover = QComboBox()
        self.cbXover.addItem("Remove (useinTSM = 0)", "useinTSM")
        self.cbXover.addItem("Recode FTYPE", "FTYPE")
        self.cbXover.addItem("Flag only (median_xover)", "flag")
        self._row(gr, 3, "Median crossovers (R3)", self.cbXover,
            "What a median crossover becomes in the corrected copy. <b>Remove</b>: "
            "<code>useinTSM = 0</code>, so netPrep leaves it out and the two carriageways "
            "consolidate through; a crossover whose removal would cut part of the network "
            "off stays. <b>Recode FTYPE</b>: FTYPE / FNAME below (netPrep needs a capacity "
            "for that class). <b>Flag only</b>: just the <code>median_xover</code> field "
            "(1 mid-block, 2 T, 3 4-leg).")
        xf = QWidget(); xh = QHBoxLayout(xf); xh.setContentsMargins(0, 0, 0, 0)
        self.sbXoverFt = QSpinBox(); self.sbXoverFt.setRange(1, 99); self.sbXoverFt.setValue(49)
        self.leXoverFname = QLineEdit("Median")
        xh.addWidget(QLabel("FTYPE")); xh.addWidget(self.sbXoverFt)
        xh.addWidget(QLabel("FNAME")); xh.addWidget(self.leXoverFname, 1)
        self._row(gr, 4, "Crossover class", xf,
            "Class written with <i>Recode FTYPE</i>: FTYPE_&lt;yy&gt; and FNAME of every "
            "median crossover.")
        self.cbXover.currentIndexChanged.connect(
            lambda _i: xf.setEnabled(self.cbXover.currentData() == "FTYPE"))
        xf.setEnabled(False)
        lv.addWidget(g_r)

        # Thresholds (collapsed)
        g_t = QgsCollapsibleGroupBox("Thresholds")
        g_t.setCollapsed(True)
        gt = QGridLayout(g_t)
        self.sb = {}
        for i, (key, label, dflt, mx, desc) in enumerate(THRESHOLDS):
            s = QSpinBox(); s.setRange(0, mx); s.setValue(dflt)
            self.sb[key] = s
            r, c = divmod(i, 2)
            lab = QLabel(label)
            gt.addWidget(lab, r, 2 * c)
            gt.addWidget(s, r, 2 * c + 1)
            self._describe(f"<b>{label}</b> (<code>{key}</code>, default {dflt}): {desc}", lab, s)
        lv.addWidget(g_t)
        lv.addStretch(1)

        # Buttons: below the scrolling options, always in view
        bh = QHBoxLayout()
        self.btnLoadCtl = QPushButton("Load control file…")
        self.btnRun = QPushButton("1. Check (write review)")
        self.btnRun.setDefault(True)
        self.btnApply = QPushButton("2. Write corrected GPKG")
        self._describe("Fill the dialog from an existing gmcheck control file.", self.btnLoadCtl)
        self._describe("<b>Step 1</b>: write the control file and run <code>gmcheck.exe</code> "
                       "in a console window (about 1.5 minutes statewide). Writes the review "
                       "GPKG and CSVs; the GeoMaster is not changed. Log: "
                       "<code>gmcheck.log</code> in the output folder.", self.btnRun)
        self._describe("<b>Step 2</b>: write the corrected link GPKG from the review GPKG, "
                       "taking the rows chosen by Apply confidence and User approved (a few "
                       "seconds; the network is not rebuilt). Unsaved edits to "
                       "<code>link_review</code> are saved first. Log: "
                       "<code>gmcheck_apply.log</code>.", self.btnApply)
        bh.addWidget(self.btnLoadCtl); bh.addStretch(1); bh.addWidget(self.btnRun); bh.addWidget(self.btnApply)
        self.bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                     QDialogButtonBox.StandardButton.Cancel)

        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(left)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        leftpane = QWidget()
        lp = QVBoxLayout(leftpane); lp.setContentsMargins(0, 0, 0, 0)
        lp.addWidget(scroll, 1)
        lp.addLayout(bh)
        lp.addWidget(self.bbox)
        split.addWidget(leftpane)

        # ---- right: description + help ----------------------------------------
        right = QWidget()
        rv = QVBoxLayout(right)
        self.lblDesc = QLabel("Hover over an option to see what it does.")
        self.lblDesc.setWordWrap(True)
        self.lblDesc.setTextFormat(Qt.TextFormat.RichText)
        self.lblDesc.setFrameShape(QFrame.Shape.StyledPanel)
        self.lblDesc.setMinimumHeight(90)
        self.lblDesc.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.lblDesc.setStyleSheet("QLabel { background: palette(base); padding: 6px; }")
        self.lblDesc.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        rv.addWidget(self.lblDesc)
        self.textBrowser = QTextBrowser()
        self.textBrowser.setOpenExternalLinks(True)
        rv.addWidget(self.textBrowser, 1)
        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([760, 480])

        # Signals
        self.leOutDir.textChanged.connect(self._default_outputs)
        self.cbLink.currentIndexChanged.connect(lambda _i: self._default_outputs())
        self.btnLoadCtl.clicked.connect(self._load_ctl_dialog)
        self.btnRun.clicked.connect(lambda: self.run_gmcheck(show_message=True))
        self.btnApply.clicked.connect(lambda: self.apply_review(show_message=True))
        self.bbox.accepted.connect(self.update_settings)
        self.bbox.rejected.connect(self.reject)

    # widget helpers: each registers its description for the right panel
    def _describe(self, text, *widgets):
        for w in widgets:
            self._desc[w] = text
            w.setToolTip(text)
            w.installEventFilter(self)

    def _row(self, grid, r, label, widget, desc):
        lab = QLabel(label)
        grid.addWidget(lab, r, 0)
        grid.addWidget(widget, r, 1, 1, 2)
        self._describe(desc, lab, widget)
        return widget

    def _line_row(self, grid, r, label, text, desc):
        return self._row(grid, r, label, QLineEdit(text), desc)

    def _check(self, grid, r, label, on, desc):
        c = QCheckBox(label); c.setChecked(on)
        grid.addWidget(c, r, 0, 1, 3)
        self._describe(desc, c)
        return c

    def _layer_row(self, grid, r, label, geom, desc):
        cb = QComboBox()
        cb.addItem("Select a layer", None)
        for lyr in QgsProject.instance().mapLayers().values():
            if hasattr(lyr, "geometryType") and lyr.geometryType() == GEOM[geom]:
                cb.addItem(lyr.name(), lyr)
        cb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # long GeoPackage paths must not widen the pane
        cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        cb.setMinimumContentsLength(20)
        lab = QLabel(label)
        b = QPushButton("…"); b.setFixedWidth(30)
        b.clicked.connect(lambda: self._browse_layer(cb))
        grid.addWidget(lab, r, 0); grid.addWidget(cb, r, 1); grid.addWidget(b, r, 2)
        self._describe(desc, lab, cb, b)
        return cb

    def _path_row(self, grid, r, label, kind, desc):
        le = QLineEdit()
        lab = QLabel(label)
        grid.addWidget(lab, r, 0); grid.addWidget(le, r, 1)
        ws = [lab, le]
        if kind:
            b = QPushButton("Browse"); grid.addWidget(b, r, 2)
            b.clicked.connect(lambda: self._browse_path(le, kind))
            ws.append(b)
        self._describe(desc, *ws)
        return le

    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.Type.Enter, QEvent.Type.FocusIn) and obj in self._desc:
            self.lblDesc.setText(self._desc[obj])
        return super().eventFilter(obj, ev)

    def _load_help_doc(self, md_path):
        try:
            with open(md_path, "r", encoding="utf-8") as f:
                md = f.read()
        except Exception as e:
            self.textBrowser.setPlainText(f"Help not found: {md_path} ({e})")
            return
        if hasattr(self.textBrowser, "setMarkdown"):
            self.textBrowser.setMarkdown(md)
        else:
            self.textBrowser.setPlainText(md)

    # ------------------------------------------------------------ paths
    @staticmethod
    def _norm(p):
        return (p or "").strip().replace("\\", "/")

    @staticmethod
    def layer_path(data):
        if data is None:
            return ""
        if isinstance(data, str):
            return data.replace("\\", "/")
        return data.dataProvider().dataSourceUri().split("|")[0].replace("\\", "/")

    def _select_layer(self, cb, path=None, name=None):
        """Select a combo entry by source path or layer name; an unloaded path is
        added as its own entry so it is kept and written back out."""
        if name:
            i = cb.findText(name)
            if i >= 0:
                cb.setCurrentIndex(i)
                return
        if not path:
            return
        target = os.path.normcase(os.path.normpath(path))
        for i in range(cb.count()):
            src = self.layer_path(cb.itemData(i))
            if src and os.path.normcase(os.path.normpath(src)) == target:
                cb.setCurrentIndex(i)
                return
        cb.addItem(os.path.basename(path), self._norm(path))
        cb.setCurrentIndex(cb.count() - 1)

    def _browse_layer(self, cb):
        p, _ = QFileDialog.getOpenFileName(self, "Select GeoPackage", self._start_dir(),
                                           "GeoPackage (*.gpkg);;All Files (*)")
        if p:
            self._select_layer(cb, path=p)

    def _browse_path(self, le, kind):
        start = le.text().strip() or self._start_dir()
        if kind == "dir":
            p = QFileDialog.getExistingDirectory(self, "Select Output Folder", start)
        elif kind == "review":
            p, _ = QFileDialog.getSaveFileName(self, "Review GeoPackage", start, "GeoPackage (*.gpkg)",
                                               options=QFileDialog.Option.DontConfirmOverwrite)
        elif kind == "save":
            p, _ = QFileDialog.getSaveFileName(self, "Corrected Link GeoPackage", start,
                                               "GeoPackage (*.gpkg)")
        else:  # ctl
            p, _ = QFileDialog.getSaveFileName(self, "gmcheck Control File", start,
                                               "Control file (*.ctl *.txt);;All Files (*)")
        if p:
            le.setText(self._norm(p))

    def _start_dir(self):
        lp = self.layer_path(self.cbLink.currentData())
        return os.path.dirname(lp) if lp else self.settings.tsm_root()

    def _default_outputs(self, *_):
        """Blank outputs follow the link layer: <link dir>/gmcheck/, the corrected
        copy <stem>_gmcheck.gpkg and gmcheck_review.gpkg there."""
        lp = self.layer_path(self.cbLink.currentData())
        if not self.leOutDir.text().strip() and lp:
            self.leOutDir.blockSignals(True)
            self.leOutDir.setText(self._norm(os.path.join(os.path.dirname(lp), "gmcheck")))
            self.leOutDir.blockSignals(False)
        out = self._norm(self.leOutDir.text())
        if out:
            if not self.leCorrLink.text().strip() and lp:
                stem = os.path.splitext(os.path.basename(lp))[0]
                self.leCorrLink.setText(f"{out}/{stem}_gmcheck.gpkg")
            if not self.leCtl.text().strip():
                self.leCtl.setText(f"{out}/gmcheck.ctl")
            if not self.leReview.text().strip():
                self.leReview.setText(f"{out}/gmcheck_review.gpkg")

    # ------------------------------------------------------------ settings
    def _values(self):
        """Control-file values from the widgets (ordered as written)."""
        v = {
            "Geomaster_line_layer": self.layer_path(self.cbLink.currentData()),
            "Geomaster_node_layer": self.layer_path(self.cbNode.currentData()),
            "Geomaster_cencon_layer": self.layer_path(self.cbCencon.currentData()),
            "connector_type": self.leConnType.text().strip() or "TSM",
            "output_dir": self._norm(self.leOutDir.text()),
            "use_field": self.leUseField.text().strip() or "useinTSM",
            "YEARS": self.leYears.text().strip(),
            "MINOR_JUNCTIONS": str(self.chkMinor.isChecked()),
            "OTHER_DIVIDED_FTYPE": "21" if self.chkOther.isChecked() else "0",
            "SMOOTH_ATTRS": str(self.chkSmooth.isChecked()),
            "XOVER_ACTION": self.cbXover.currentData(),
            "XOVER_FTYPE": str(self.sbXoverFt.value()),
            "XOVER_FNAME": self.leXoverFname.text().strip() or "Median",
            "review_gpkg": self._norm(self.leReview.text()),
            "APPLY": "False",  # step 1 is report only; step 2 is MODE=apply_review
            "APPLY_CONFIDENCE": self.cbConf.currentText(),
            "APPLY_APPROVED": self.cbApproved.currentData(),
            "corrected_link_layer": self._norm(self.leCorrLink.text()),
        }
        for key, s in self.sb.items():
            v[key] = str(s.value())
        return v

    def _known_keys(self):
        return set(self._values()) | {"Settings_File", "MODE"}

    def _set_values(self, v):
        """Fill the widgets from control-file / saved values (missing keys kept)."""
        g = lambda k: (v.get(k) or "").strip()
        if g("Geomaster_line_layer"): self._select_layer(self.cbLink, path=g("Geomaster_line_layer"))
        if g("Geomaster_node_layer"): self._select_layer(self.cbNode, path=g("Geomaster_node_layer"))
        if g("Geomaster_cencon_layer"): self._select_layer(self.cbCencon, path=g("Geomaster_cencon_layer"))
        if g("connector_type"): self.leConnType.setText(g("connector_type"))
        if g("use_field"): self.leUseField.setText(g("use_field"))
        if "YEARS" in v: self.leYears.setText(g("YEARS"))
        if g("output_dir"): self.leOutDir.setText(self._norm(g("output_dir")))
        if g("corrected_link_layer"): self.leCorrLink.setText(self._norm(g("corrected_link_layer")))
        if g("review_gpkg"): self.leReview.setText(self._norm(g("review_gpkg")))
        tb = lambda k, d: g(k).lower() in ("true", "1", "yes") if g(k) else d
        self.chkMinor.setChecked(tb("MINOR_JUNCTIONS", self.chkMinor.isChecked()))
        self.chkSmooth.setChecked(tb("SMOOTH_ATTRS", self.chkSmooth.isChecked()))
        if g("OTHER_DIVIDED_FTYPE"): self.chkOther.setChecked(g("OTHER_DIVIDED_FTYPE") != "0")
        if g("APPLY_CONFIDENCE"):
            i = self.cbConf.findText(g("APPLY_CONFIDENCE").capitalize())
            if i >= 0: self.cbConf.setCurrentIndex(i)
        if g("APPLY_APPROVED"):
            i = self.cbApproved.findData(g("APPLY_APPROVED").lower())
            if i >= 0: self.cbApproved.setCurrentIndex(i)
        if g("XOVER_ACTION"):
            for i in range(self.cbXover.count()):
                if self.cbXover.itemData(i).lower() == g("XOVER_ACTION").lower():
                    self.cbXover.setCurrentIndex(i)
        if g("XOVER_FNAME"): self.leXoverFname.setText(g("XOVER_FNAME"))
        known = self._known_keys()
        self._extra = {k: val for k, val in v.items() if k not in known}
        for key, s in list(self.sb.items()) + [("XOVER_FTYPE", self.sbXoverFt)]:
            try:
                if g(key): s.setValue(int(float(g(key))))
            except ValueError:
                pass
        self._default_outputs()

    @staticmethod
    def parse_ctl(path):
        v = {}
        with open(path, "r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.split("#", 1)[0].strip()
                if "=" in line:
                    k, val = line.split("=", 1)
                    v[k.strip()] = val.strip()
        return v

    def _prefill(self):
        s = self.settings
        # Shared GeoMaster layers (Project Settings / Link Consolidator) first.
        self._select_layer(self.cbLink, name=s.get("GM_line_layer"))
        self._select_layer(self.cbNode, name=s.get("GM_node_layer"))
        self._select_layer(self.cbCencon, name=s.get("GM_cencon_layer"))
        # Then this tool's last control file, if any.
        ctl = s.get("gmcheck_ctl")
        if ctl and os.path.exists(ctl):
            try:
                self._set_values(self.parse_ctl(ctl))
            except Exception as e:
                print(f"gmcheck: could not read {ctl}: {e}")
            self.leCtl.setText(self._norm(ctl))
        self._default_outputs()

    def _load_ctl_dialog(self):
        p, _ = QFileDialog.getOpenFileName(self, "Load gmcheck Control File", self._start_dir(),
                                           "Control file (*.ctl *.txt);;All Files (*)")
        if not p:
            return
        try:
            v = self.parse_ctl(p)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Cannot read {p}:\n{e}")
            return
        # Outputs come from the file: clear the defaults first.
        self.leCorrLink.clear(); self.leOutDir.clear(); self.leReview.clear()
        self._set_values(v)
        self.leCtl.setText(self._norm(p))

    def write_ctl(self, path, v):
        lines = [
            "# gmcheck control file, written by the TSM panel (GeoMaster Checker)",
            "# Inputs: read only, never modified",
        ]
        order = [
            ("Geomaster_line_layer", None), ("Geomaster_node_layer", None),
            ("Geomaster_cencon_layer", None), ("connector_type", None), ("", ""),
            ("output_dir", "# Outputs: gmcheck_links.csv, gmcheck_nodes.csv, gmcheck.log"),
            ("review_gpkg", None),
            ("use_field", "# Network checked, as netPrep builds it (use_field = 1, LANE_<yy> > 0)"),
            ("YEARS", None),
            ("MINOR_JUNCTIONS", "# Rules"), ("OTHER_DIVIDED_FTYPE", None), ("SMOOTH_ATTRS", None),
            ("XOVER_ACTION", None), ("XOVER_FTYPE", None), ("XOVER_FNAME", None),
        ]
        for key, comment in order:
            if comment:
                lines += ["", comment]
            if key == "YEARS" and not v.get("YEARS"):
                lines.append("# YEARS                = 24, 50    # blank: every FTYPE_<yy>")
            elif key:
                lines.append(f"{key:<22} = {v[key]}")
        lines += ["", "# Thresholds"] + [f"{k:<22} = {v[k]}" for k, *_ in THRESHOLDS]
        if self._extra:  # from a loaded control file, kept as they were
            lines += ["", "# Other settings (from the loaded control file)"]
            lines += [f"{k:<22} = {val}" for k, val in self._extra.items()]
        lines += ["", "# Step 2: gmcheck.exe <this file> MODE=apply_review writes corrected_link_layer",
                  "# from review_gpkg: rows with confidence >= APPLY_CONFIDENCE and/or approved = 1",
                  "# (APPLY_APPROVED = also | only | ignore). APPLY = True would also write it in",
                  "# step 1 from confidence alone."]
        lines += [f"{k:<22} = {v[k]}" for k in ("APPLY", "APPLY_CONFIDENCE", "APPLY_APPROVED",
                                                 "corrected_link_layer")]
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def _check_inputs(self, v, step2=False):
        if not v["Geomaster_line_layer"]:
            return "Select the GeoMaster link layer."
        if not v["output_dir"]:
            return "Set the output folder."
        if not v["review_gpkg"]:
            return "Set the review GeoPackage."
        if step2:
            if not os.path.exists(v["review_gpkg"]):
                return f"No review GeoPackage at {v['review_gpkg']}. Run step 1 first."
            cl = v["corrected_link_layer"]
            if not cl:
                return "Set the corrected link GeoPackage."
            same = lambda a, b: os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))
            if same(cl, v["Geomaster_line_layer"]):
                return "The corrected link GeoPackage must differ from the input link layer."
            if same(cl, v["review_gpkg"]):
                return "The corrected link GeoPackage must differ from the review GeoPackage."
        return None

    def update_settings(self):
        """OK: write the control file and remember it (no run)."""
        v = self._values()
        ctl = self._norm(self.leCtl.text())
        if ctl:
            try:
                self.write_ctl(ctl, v)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Cannot write {ctl}:\n{e}")
                return
            self.settings.set("gmcheck_ctl", ctl)
        self.accept()

    # ------------------------------------------------------------ run
    def _layers_on(self, path):
        """Project layers whose source is the GeoPackage at path."""
        target = os.path.normcase(os.path.abspath(path))
        return [l for l in QgsProject.instance().mapLayers().values()
                if isinstance(l, QgsVectorLayer) and
                os.path.normcase(os.path.abspath(l.source().split("|")[0])) == target]

    def _save_review_edits(self, path, question):
        """Unsaved edits on review layers: save them (True) or cancel (False)."""
        unsaved = [l for l in self._layers_on(path) if l.isEditable() and l.isModified()]
        if not unsaved:
            return True
        r = QMessageBox.question(self, "gmcheck", question,
                                 QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel)
        if r != QMessageBox.StandardButton.Save:
            return False
        for l in unsaved:
            if not l.commitChanges():
                QMessageBox.critical(self, "gmcheck", f"Cannot save the edits to {l.name()}.")
                return False
        return True

    def _prepare(self, step2):
        """Check the inputs and write the control file; returns (values, exe, ctl) or None."""
        v = self._values()
        err = self._check_inputs(v, step2)
        if err:
            QMessageBox.critical(self, "gmcheck", err)
            return None
        exe = os.path.join(self.plugin_dir, "Apps", "netPrep", "gmcheck.exe")
        if not os.path.exists(exe):
            QMessageBox.critical(self, "Error", f"gmcheck.exe not found at: {exe}")
            return None
        ctl = self._norm(self.leCtl.text()) or f"{v['output_dir']}/gmcheck.ctl"
        self.leCtl.setText(ctl)
        try:
            self.write_ctl(ctl, v)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Cannot write {ctl}:\n{e}")
            return None
        self.settings.set("gmcheck_ctl", ctl)
        os.makedirs(v["output_dir"], exist_ok=True)
        return v, exe, ctl

    def _run(self, args, log):
        try:
            res = self.settings.run_app(args, log_path=log, console=True)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"gmcheck failed to start:\n{e}")
            return False
        if res.returncode != 0:
            QMessageBox.critical(self, "Error", f"gmcheck failed (exit {res.returncode}). See {log}.")
            return False
        return True

    def run_gmcheck(self, show_message=False):
        """Step 1: the check; writes the review GeoPackage and the CSVs."""
        p = self._prepare(step2=False)
        if not p:
            return False
        v, exe, ctl = p
        review = v["review_gpkg"]
        if not self._save_review_edits(review, "The review layer has unsaved edits. Save them "
                                       "before step 1? (A reviewed file is kept as a dated copy.)"):
            return False
        # Layers on the old review file hold it open: drop them, reload after.
        QgsProject.instance().removeMapLayers([l.id() for l in self._layers_on(review)])
        if not self._run([exe, ctl], f"{v['output_dir']}/gmcheck.log"):
            return False
        if self.chkLoad.isChecked() and os.path.exists(review):
            for name in ("link_review", "node_review"):
                lyr = QgsVectorLayer(f"{review}|layername={name}", f"gmcheck {name}", "ogr")
                if lyr.isValid():
                    QgsProject.instance().addMapLayer(lyr)
        if show_message:
            QMessageBox.information(self, "gmcheck", "\n".join([
                f"Step 1 finished. Outputs in {v['output_dir']}:",
                "  gmcheck_links.csv, gmcheck_nodes.csv, gmcheck.log",
                f"  {review}",
                "",
                "Review link_review: set approved = 1 (apply) or 0 (reject), edit changes",
                "or confidence where needed, save, then run step 2."]))
        return True

    def apply_review(self, show_message=False):
        """Step 2: the corrected link GeoPackage from the review GeoPackage."""
        p = self._prepare(step2=True)
        if not p:
            return False
        v, exe, ctl = p
        if not self._save_review_edits(v["review_gpkg"],
                                       "The review layer has unsaved edits. Save them and use them?"):
            return False
        log = f"{v['output_dir']}/gmcheck_apply.log"
        if not self._run([exe, ctl, "MODE=apply_review"], log):
            return False
        if show_message:
            QMessageBox.information(self, "gmcheck", "\n".join([
                "Step 2 finished.",
                f"Corrected link layer: {v['corrected_link_layer']}",
                f"Rows taken per rule: {log}"]))
        return True
