# -*- coding: utf-8 -*-
"""Summarization dialog extensions: multi-DTA volume inputs + agentAnalysis tabs.

Injected into the Summarization dialog AFTER uic.loadUi (the base layout stays
in ui/summary_loadedNetwork.ui; everything here is built programmatically so
the .ui file remains Qt-Designer-clean):

1. Two extra link-performance rows under the macroDTA one: mesoDTA and
   microDTA (both optional; macro is required). All three stream into one
   daily summary via summarize.exe [input]/[input2]/[input3].

2. A QTabWidget (SubareaAssignment-style, tabs at the bottom of the dialog)
   wrapping agentAnalysis.exe:
     - Path Trace       : trace  --hh [--person [--tour [--trip]]]
     - Subarea          : subarea --nodes --trips --links --out
     - Select Link      : agents --link A B [...] --logic AND|OR [--volumes]
     - Turning Movements: turns  --nodes csv | --node list [--five] [--by-hour]
"""
import csv
import os
import re
import tempfile

from qgis.PyQt import QtCore, QtWidgets
from qgis.PyQt.QtWidgets import (QFileDialog, QMessageBox, QWidget, QLabel,
                                 QLineEdit, QPushButton, QCheckBox, QRadioButton,
                                 QGridLayout, QHBoxLayout, QVBoxLayout,
                                 QTabWidget, QGroupBox, QPlainTextEdit,
                                 QComboBox)

from .tsm_settings import Config
from . import tsm_history


# ----------------------------------------------------------------- helpers --
BROWSE_W = 34   # one width for every '...' button so the rows line up


# Volume breakdown offered on Select Link and Turning Movements. agentAnalysis
# splits the per-key agent weight by category BEFORE the route-key rollup, so the
# wide columns always sum back to the total volume.
#   purpose    -- native to the agents table, no trip list needed
#   market     -- market / marketVot live only in the trip list, which is joined
#                 by ROW NUMBER, so it must be the list this duckdb was built from
_BY_CHOICES = [("(none) - total volume only", ""),
               ("Purpose", "purpose"),
               ("Market", "market"),
               ("Market x VOT", "marketVot")]


def _by_row(parent, key, what):
    """Breakdown combo + hint; returns (layout, combo)."""
    lay = QHBoxLayout()
    lab = QLabel("break %s down by" % what, parent)
    lab.setMinimumWidth(150)
    combo = QComboBox(parent)
    for text, _ in _BY_CHOICES:
        combo.addItem(text)
    combo.setToolTip(
        "Adds one wide volume column per category beside the total.\n"
        "Purpose comes from the agentPaths duckdb. Market / Market x VOT come "
        "from the trip list, so the Trip list field above must point at the "
        "tripList that produced this duckdb.")
    saved = Config().get(key)
    if saved:
        vals = [v for _, v in _BY_CHOICES]
        if saved in vals:
            combo.setCurrentIndex(vals.index(saved))
    combo.currentIndexChanged.connect(
        lambda i: Config().set(key, _BY_CHOICES[i][1]))
    lay.addWidget(lab)
    lay.addWidget(combo, 1)
    return lay, combo


def _by_value(combo):
    """Control-file value for the picked breakdown ("" = none)."""
    i = combo.currentIndex()
    return _BY_CHOICES[i][1] if 0 <= i < len(_BY_CHOICES) else ""


def _by_args(dlg, combo, trips, what):
    """--by flags for the picked breakdown, or None if the user must fix input."""
    by = _by_value(combo)
    if not by:
        return []
    if by in ("market", "marketVot") and not trips:
        QMessageBox.warning(
            dlg, what,
            "Breaking volumes down by %s needs the trip list: the market segment "
            "is not stored in the duckdb.\n\nSet 'trip list' above to the "
            "tripList that produced this agentPaths.duckdb." % by)
        return None
    return ["--by", by]


def _browse_row(parent, label, mode="open", filt="All Files (*)", key=None):
    """label + line-edit + '...' browse button; returns (layout, line_edit)."""
    lay = QHBoxLayout()
    lab = QLabel(label, parent)
    lab.setMinimumWidth(150)
    edit = QLineEdit(parent)
    btn = QPushButton("...", parent)
    btn.setFixedWidth(BROWSE_W)

    def pick():
        if mode == "open":
            p, _ = QFileDialog.getOpenFileName(parent, "Select File", "", filt)
        else:
            p, _ = QFileDialog.getSaveFileName(parent, "Select File", "", filt)
        if p:
            edit.setText(p)
            # setText() does NOT emit editingFinished, so persist here too --
            # otherwise a browsed path never reaches Config and is lost on save.
            if key:
                Config().set(key, p)
    btn.clicked.connect(pick)

    if key:
        saved = Config().get(key)
        if saved:
            edit.setText(saved)
        edit.editingFinished.connect(lambda: Config().set(key, edit.text()))
    lay.addWidget(lab)
    lay.addWidget(edit)
    lay.addWidget(btn)
    return lay, edit


# FTYPE 51 is the centroid connector (agentflow-dta tsm_network_reader.cpp
# FTYPE_CONNECTOR). A connector is an abstraction, not a road: half of one
# carries no meaning, so a connector whose far end sits outside the subarea is
# dropped rather than clipped. A real link is kept whole even when it only
# clips the boundary, because dropping it would break the path through it.
FTYPE_CONNECTOR = 51

# NODE.csv DTA_Type: 99 = zone centroid (agentflow-dta core/network.h:37 --
# "90=express entry/DMN, 91/94=join, 99=zone"). In the parent network every 99
# sits in the zone-number range; everything else is 0.
DTA_TYPE_ZONE = 99


def _drop_layers_for(path):
    """Remove any loaded layer reading `path`, and return how many went.

    GDAL cannot rewrite a GeoPackage that QGIS still holds open, so a second
    run silently failed to overwrite the first run's output. Matching on the
    resolved filename (not the layer name) catches the copy the user renamed.
    """
    if not path:
        return 0
    try:
        from qgis.core import QgsProject
    except Exception:
        return 0
    target = os.path.normcase(os.path.abspath(path.replace("/", os.sep)))
    proj = QgsProject.instance()
    gone = 0
    for lyr in list(proj.mapLayers().values()):
        try:
            src = lyr.source().split("|")[0]
            if os.path.normcase(os.path.abspath(src)) == target:
                proj.removeMapLayer(lyr.id())
                gone += 1
        except Exception:
            continue
    if gone:
        # Release the file handles before the writer opens the same path.
        try:
            import gc
            from qgis.PyQt.QtWidgets import QApplication
            gc.collect(); QApplication.processEvents(); gc.collect()
        except Exception:
            pass
        _log("dropped %d loaded layer(s) reading %s" % (gone, path))
    return gone


def _mark_zone_nodes(path, ext_ids, node_field="N"):
    """Set DTA_Type = 99 on the external boundary nodes of a subarea node layer.

    Those nodes are ordinary network nodes in the parent model (DTA_Type 0), but
    in the SUBAREA they are where demand enters and leaves -- the trip list gives
    them as O/D -- so the subarea assignment has to read them as zones. Interior
    centroids already carry 99 from the parent file and are left alone.

    Returns the number of nodes marked, or -1 if the layer could not be edited.
    """
    if not path or not os.path.exists(path) or not ext_ids:
        return 0
    try:
        from qgis.core import QgsVectorLayer, QgsField
        from qgis.PyQt.QtCore import QVariant
    except Exception:
        return -1
    lyr = QgsVectorLayer(path, "subarea nodes (edit)", "ogr")
    if not lyr.isValid():
        _log("Subarea: cannot open %s to set DTA_Type" % path)
        return -1
    ni = lyr.fields().lookupField(node_field)          # case-insensitive
    if ni < 0:
        _log("Subarea: node layer has no '%s' column; DTA_Type not set" % node_field)
        return -1
    di = lyr.fields().lookupField("DTA_Type")
    if di < 0:
        # A node layer without the column still has to carry it downstream.
        lyr.dataProvider().addAttributes([QgsField("DTA_Type", QVariant.Int)])
        lyr.updateFields()
        di = lyr.fields().lookupField("DTA_Type")
        if di < 0:
            _log("Subarea: could not add a DTA_Type column to %s" % path)
            return -1
    changes, n = {}, 0
    for feat in lyr.getFeatures():
        try:
            if int(feat[ni]) in ext_ids:
                changes[feat.id()] = {di: DTA_TYPE_ZONE}
                n += 1
        except (TypeError, ValueError):
            continue
    if changes and not lyr.dataProvider().changeAttributeValues(changes):
        _log("Subarea: DTA_Type update rejected by the provider")
        return -1
    del lyr
    return n


def _add_layer(path, name):
    """Load a written GPKG into the project. Returns True when it loaded."""
    if not path or not os.path.exists(path):
        return False
    try:
        from qgis.core import QgsProject, QgsVectorLayer
        lyr = QgsVectorLayer(path, name, "ogr")
        if lyr.isValid():
            QgsProject.instance().addMapLayer(lyr)
            _log("loaded layer %s <- %s" % (name, path))
            return True
        _log("layer %s did not load from %s" % (name, path))
    except Exception as e:
        _log("could not load %s: %s" % (path, e))
    return False


def _log(msg):
    tsm_history.log_action(msg, "agentAnalysis")
    # While a one-window run is open (begin_run_console), the steps done inside
    # QGIS show in it too, between the exes' own output.
    try:
        from . import model_run as _mr
        if getattr(_mr, "_RUN_LOG", None):
            import time as _t
            with open(_mr._RUN_LOG, "a", encoding="utf-8", errors="replace") as f:
                f.write("[%s] %s\n" % (_t.strftime("%H:%M:%S"), msg))
    except Exception:
        pass


def _exe():
    exe = Config().app_exe("agentAnalysis/agentAnalysis.exe")
    if not os.path.exists(exe):
        raise FileNotFoundError("agentAnalysis.exe not found at: %s" % exe)
    return exe


def _links_as_csv(layer, tag):
    """Path to a CSV link table for agentAnalysis, converting a GeoPackage layer.

    agentAnalysis' --links expects a delimited table. The panel's link layer is
    a GeoPackage, and handing the .gpkg straight over makes it try to sniff the
    binary as CSV and fail with "Error when sniffing file ... not possible to
    automatically detect the CSV Parsing dialect/types". Convert with
    gpkgcsv.exe first -- the same tool and --drop-geom flag the HyDRA dialog
    uses to feed afdta. A layer that is already a CSV is passed through.
    """
    src = _layer_path(layer)
    if not src:
        return None
    if os.path.splitext(src)[1].lower() in (".csv", ".txt"):
        return src
    settings = Config()
    gpkgcsv = settings.app_exe("utilities/gpkgcsv.exe")
    if not os.path.exists(gpkgcsv):
        _log("agentAnalysis: gpkgcsv.exe not found at %s" % gpkgcsv)
        return None
    out_csv = os.path.join(tempfile.gettempdir(),
                           "%s_links_%s.csv" % (tag, os.path.splitext(os.path.basename(src))[0]))
    _log("agentAnalysis: converting link layer to CSV -> %s" % out_csv)
    r = settings.run_app([gpkgcsv, "to-csv", src, out_csv, "--drop-geom"],
                         log_path=os.path.join(tempfile.gettempdir(),
                                               "gpkgcsv_%s.log" % tag),
                         console=True)
    if r.returncode != 0 or not os.path.exists(out_csv):
        _log("agentAnalysis: gpkgcsv conversion failed for %s" % src)
        return None
    return out_csv


def _run(args, log_name):
    """Launch agentAnalysis.exe through the plugin's console runner."""
    settings = Config()
    log_path = os.path.join(
        os.path.dirname(args[args.index("--out") + 1]) if "--out" in args else
        settings.get("output_dir") or os.path.expanduser("~"),
        log_name)
    _log("agentAnalysis: " + " ".join(str(a) for a in args))
    return settings.run_app([_exe()] + [str(a) for a in args],
                            log_path=log_path, console=True)


def _check(parent, text, key):
    """Checkbox persisted under `key`."""
    cb = QCheckBox(text, parent)
    cb.setChecked(str(Config().get(key)).lower() in ("true", "1", "yes"))
    cb.toggled.connect(lambda ch: Config().set(key, ch))
    return cb


def _align_labels(rows):
    """Give the leading label of each row the width of the widest one, so the
    controls after them start in one column."""
    labels = [r.itemAt(0).widget() for r in rows
              if r.count() and isinstance(r.itemAt(0).widget(), QLabel)]
    if labels:
        wmax = max(lab.sizeHint().width() for lab in labels)
        for lab in labels:
            lab.setFixedWidth(wmax)


def _set_row_enabled(lay, on):
    """Enable/disable every widget in a _browse_row layout."""
    for i in range(lay.count()):
        wid = lay.itemAt(i).widget()
        if wid is not None:
            wid.setEnabled(on)


def _hline(parent):
    """Horizontal separator line between dialog sections."""
    ln = QtWidgets.QFrame(parent)
    ln.setFrameShape(QtWidgets.QFrame.Shape.HLine)
    ln.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
    return ln


def _layer_combo(parent, geom_type, key=None):
    """Dropdown of loaded QGIS layers of the given geometry type."""
    from qgis.core import QgsProject
    combo = QtWidgets.QComboBox(parent)
    combo.addItem("Select a layer", None)
    gcode = {"Point": 0, "LineString": 1, "Polygon": 2}[geom_type]
    for layer in QgsProject.instance().mapLayers().values():
        if hasattr(layer, "geometryType") and layer.geometryType() == gcode:
            combo.addItem(layer.name(), layer)
    if key:
        saved = Config().get(key)
        if saved:
            i = combo.findText(saved)
            if i >= 0:
                combo.setCurrentIndex(i)
        combo.currentTextChanged.connect(lambda t: Config().set(key, t))
    return combo


def _layer_path(layer):
    if layer is None:
        return None
    return layer.dataProvider().dataSourceUri().split("|")[0]


# ------------------------------------------------- summarization: 3 inputs --
def add_dta_inputs(dlg):
    """Relabel the existing volume row as macroDTA and insert mesoDTA/microDTA
    rows right below it. Returns (meso_edit, micro_edit)."""
    dlg.label_4.setText("macroDTA link performance (csv)")
    dlg.lineEdit_volume.setToolTip("link_performance_macroDTA.csv (required)")
    # Line the original rows' browse buttons up with the injected ones.
    for name in ("browse_volume", "browse_loadedOut", "browse_ValidationStats"):
        b = getattr(dlg, name, None)
        if b is not None:
            b.setFixedWidth(BROWSE_W)

    grid = dlg.gridLayout
    meso_lay, meso_edit = _browse_row(dlg, "mesoDTA link performance (csv)",
                                      key="volume_file_meso")
    micro_lay, micro_edit = _browse_row(dlg, "microDTA link performance (csv)",
                                        key="volume_file_micro")
    meso_edit.setToolTip("link_performance_mesoDTA.csv (optional; meso links "
                         "are disjoint from the macro file and add into the "
                         "same summary)")
    micro_edit.setToolTip("link_performance_microDTA.csv (optional)")

    # Existing grid rows: 0 layer / 1 volume / 2 loadedOut / 3 checkboxes /
    # 4 validation / 5 buttons. Shift rows >=2 down two slots, insert at 2,3.
    items = []
    for r in range(2, 6):
        it = grid.itemAtPosition(r, 0)
        if it is not None:
            grid.removeItem(it)
            items.append((r, it))
    grid.addLayout(meso_lay, 2, 0, 1, 1)
    grid.addLayout(micro_lay, 3, 0, 1, 1)
    for r, it in items:
        grid.addItem(it, r + 2, 0, 1, 1)
    return meso_edit, micro_edit


# ------------------------------------------------------ agentAnalysis tabs --
def add_common_section(dlg):
    """The agentPaths duckdb is one input shared by every tab -- keep it once,
    between the summarization block and the tab widget, framed by separators."""
    grid = dlg.gridLayout
    row = grid.rowCount()
    grid.addWidget(_hline(dlg), row, 0, 1, 1)
    db_lay, dlg.lineEdit_agentPaths = _browse_row(
        dlg, "agentPaths (duckdb)",
        filt="DuckDB (*.duckdb);;All Files (*)", key="aa_trace_db")
    dlg.lineEdit_agentPaths.setToolTip(
        "agentPaths.duckdb from a HyDRA run (agents + full key paths). "
        "Used by every tab below.")
    grid.addLayout(db_lay, row + 1, 0, 1, 1)
    grid.addWidget(_hline(dlg), row + 2, 0, 1, 1)


def _db(dlg):
    return dlg.lineEdit_agentPaths.text().strip()


def _tab_trace(dlg):
    w = QWidget()
    v = QVBoxLayout(w)
    tl_lay, w.trips = _browse_row(w, "trip list (csv/gz)",
                                  filt="Trip list (*.csv *.gz);;All Files (*)",
                                  key="aa_trips")
    v.addLayout(tl_lay)

    ids = QHBoxLayout()
    w.hh = QLineEdit(w);     w.hh.setPlaceholderText("hh_id (required)")
    w.person = QLineEdit(w); w.person.setPlaceholderText("person_id")
    w.tour = QLineEdit(w);   w.tour.setPlaceholderText("tour_id")
    w.trip = QLineEdit(w);   w.trip.setPlaceholderText("trip_id")
    ids.addWidget(QLabel("IDs (hierarchy):", w))
    for e in (w.hh, w.person, w.tour, w.trip):
        ids.addWidget(e)
    v.addLayout(ids)
    # Persist the ID hierarchy fields (not browse rows -> wire them by hand).
    for e, k in ((w.hh, "aa_trace_hh"), (w.person, "aa_trace_person"),
                 (w.tour, "aa_trace_tour"), (w.trip, "aa_trace_trip")):
        saved = Config().get(k)
        if saved:
            e.setText(saved)
        e.editingFinished.connect(lambda e=e, k=k: Config().set(k, e.text()))
    hint = QLabel("hh_id alone = all household trips; + person_id = that "
                  "person's; + tour_id = that tour's; + trip_id = one trip.", w)
    hint.setStyleSheet("color: gray;")
    v.addWidget(hint)

    out_lay, w.out = _browse_row(w, "output paths (csv)", mode="save",
                                 filt="CSV (*.csv)", key="aa_trace_out")
    v.addLayout(out_lay)

    run = QPushButton("Run Path Trace", w)
    v.addWidget(run)
    v.addStretch(1)

    def go():
        if not (_db(dlg) and w.trips.text() and w.hh.text()):
            QMessageBox.warning(dlg, "Path Trace",
                                "agentPaths duckdb (common field above), trip list and hh_id are required.")
            return
        args = ["trace", "--db", _db(dlg), "--trips", w.trips.text(),
                "--hh", w.hh.text()]
        for flag, e in (("--person", w.person), ("--tour", w.tour), ("--trip", w.trip)):
            if e.text().strip():
                args += [flag, e.text().strip()]
        if w.out.text():
            args += ["--out", w.out.text()]
        r = _run(args, "agentAnalysis_trace.log")
        if r.returncode == 0:
            QMessageBox.information(dlg, "Path Trace", "Trace written:\n%s" % w.out.text())
        else:
            QMessageBox.critical(dlg, "Path Trace", "agentAnalysis trace failed - see History log.")
    run.clicked.connect(go)
    return w


def _link_performance_files(dlg):
    """The macro/meso/micro link-performance files from the COMMON section.

    The dialog already asks for all three at the top for the loaded-network
    summary; asking again per tab would be a second place to get it wrong.
    Whatever is filled in there is what the boundary walk uses -- the three
    resolutions partition the network, so each link is priced at its own.
    """
    out = []
    for name in ("lineEdit_volume", "lineEdit_volumeMeso", "lineEdit_volumeMicro"):
        e = getattr(dlg, name, None)
        p = e.text().strip() if e is not None else ""
        if p and os.path.exists(p):
            out.append(p.replace("\\", "/"))
    return out


def _subarea_external_nodes(trips_path, inside_ids):
    """Node ids the subarea trip list references from OUTSIDE the boundary.

    agentAnalysis rewrites an IE/EI/EE trip's O or D to the first node beyond
    the boundary on the crossing link, so those ids are real and load-bearing
    but are not among the nodes inside. Read them back off the emitted trip
    list rather than recomputing the geometry -- the engine already decided
    which crossing node each trip uses, and guessing again could disagree.
    """
    import csv as _csv
    import gzip
    ext = set()
    if not trips_path or not os.path.exists(trips_path):
        return ext
    try:
        op = gzip.open if trips_path.lower().endswith(".gz") else open
        with op(trips_path, "rt", newline="") as f:
            rd = _csv.DictReader(f)
            for row in rd:
                for k in ("O", "D"):
                    v = row.get(k)
                    if v in (None, ""):
                        continue
                    try:
                        n = int(float(v))
                    except ValueError:
                        continue
                    if n not in inside_ids:
                        ext.add(n)
    except (OSError, ValueError) as e:
        _log("Subarea: could not read %s for external nodes: %s" % (trips_path, e))
    return ext


def _msr_subarea_defaults():
    """MSR scenario (Project Settings > Model Resolution): the subarea inputs
    default to the MSR region and network -- {config key: layer name or path}.
    Boundary / zonal land use are loaded into the project when they are not, so
    the dropdowns can show them. Empty for a Standard TSM scenario."""
    from qgis.core import QgsProject, QgsVectorLayer
    cfg = Config()
    if not cfg.is_msr():
        return {}
    plugin_dir = cfg.get("plugin_dir") or os.path.dirname(__file__)

    def layer_for(path, style=None):
        if not (path and os.path.exists(path)):
            return ""
        want = os.path.normcase(os.path.abspath(path))
        for lyr in QgsProject.instance().mapLayers().values():
            src = lyr.source().split("|")[0] if hasattr(lyr, "source") else ""
            if src and os.path.normcase(os.path.abspath(src)) == want:
                return lyr.name()
        lyr = QgsVectorLayer(path, os.path.splitext(os.path.basename(path))[0], "ogr")
        if not lyr.isValid():
            return ""
        if style and os.path.exists(style):
            lyr.loadNamedStyle(style)
        QgsProject.instance().addMapLayer(lyr)
        return lyr.name()

    return {
        "aa_sub_boundary_lyr": layer_for(cfg.get("msr_boundary_file")),
        "aa_sub_zones_lyr": layer_for(cfg.get("zone_landuse_file"), os.path.join(
            plugin_dir, "qgis_styles", "TSM_and_RPM_model_zones_landuse.qml")),
        "aa_sub_nodes_lyr": cfg.get("msr_node_layer_name") or "",
        "aa_sub_links_lyr": cfg.get("msr_link_layer_name") or "",
        "aa_trips": cfg.get("msr_triplist_file") or "",
    }


def _tab_subarea(dlg):
    """Boundary and land use come from LOADED GPKG LAYERS (dropdowns); the
    interior-node CSV the CLI needs (network nodes + zone centroids inside the
    boundary) is derived here. Outputs: subarea link gpkg + node gpkg (clipped)
    + the subarea trip list."""
    w = QWidget()
    v = QVBoxLayout(w)
    # MSR scenario: default to the MSR region / zonal land use / network / trip
    # list wherever nothing was saved (a saved pick wins -- a subarea can differ
    # from the MSR region).
    msr_defaults = _msr_subarea_defaults()

    def combo_row(label, geom, key):
        lay = QHBoxLayout()
        lab = QLabel(label, w); lab.setMinimumWidth(150)
        cb = _layer_combo(w, geom, key)
        if not Config().get(key) and msr_defaults.get(key):
            i = cb.findText(msr_defaults[key])
            if i >= 0:
                cb.setCurrentIndex(i)
        lay.addWidget(lab); lay.addWidget(cb, 1)
        return lay, cb

    b_lay, w.boundary = combo_row("subarea boundary (polygon layer)", "Polygon", "aa_sub_boundary_lyr")
    z_lay, w.zones = combo_row("land use zones - statewide (polygon layer)", "Polygon", "aa_sub_zones_lyr")
    n_lay, w.nodes_lyr = combo_row("network nodes (point layer)", "Point", "aa_sub_nodes_lyr")
    l_lay, w.links_lyr = combo_row("network links (line layer)", "LineString", "aa_sub_links_lyr")
    for lay in (b_lay, z_lay, n_lay, l_lay):
        v.addLayout(lay)
    tl_lay, w.trips = _browse_row(w, "trip list (csv/gz)",
                                  filt="Trip list (*.csv *.gz);;All Files (*)", key="aa_trips")
    if not w.trips.text().strip() and msr_defaults.get("aa_trips"):
        w.trips.setText(msr_defaults["aa_trips"])
    v.addLayout(tl_lay)
    _align_labels((b_lay, z_lay, n_lay, l_lay, tl_lay))
    # Opt-in, because it is the expensive half of the extraction: every EI/EE
    # path is walked link by link to find when the trip actually reaches the
    # boundary. Off, the trip keeps its statewide departure time and
    # boundary_t_min is left empty for a time-of-day model to fill later.
    w.cb_boundary = QCheckBox(
        "Compute external arrival time from paths and link performance "
        "(adds ~30 min)", w)
    w.cb_boundary.setToolTip(
        "ON: walk each EI/EE path against the macro/meso/micro link-performance "
        "files from the top of this dialog, pricing every link at the interval "
        "the trip reaches it, and set depart_time to the CONGESTED arrival at "
        "the boundary.\n\n"
        "OFF (default): depart_time keeps the statewide departure and "
        "boundary_t_min is empty. Much faster, and honest about what is not "
        "known -- it never substitutes a free-flow guess.")
    _b = Config().get("aa_sub_boundary_time")
    w.cb_boundary.setChecked(str(_b).lower() in ("true", "1", "yes"))
    w.cb_boundary.toggled.connect(
        lambda ch: Config().set("aa_sub_boundary_time", ch))

    # Two sub-tabs under the inputs: what the extraction writes, and the
    # optional renumbering + ELToD trip table done by subarea.exe finalize.
    sub_tabs = QTabWidget(w)
    out_page, tt_page = QWidget(), QWidget()
    vo, vt = QVBoxLayout(out_page), QVBoxLayout(tt_page)
    sub_tabs.addTab(out_page, "Outputs")
    sub_tabs.addTab(tt_page, "ELToD TripTable")
    v.addWidget(sub_tabs)
    vo.addWidget(w.cb_boundary)
    vo.addWidget(_hline(out_page))
    ol_lay, w.out_links = _browse_row(w, "output subarea links (gpkg)", "save",
                                      "GeoPackage (*.gpkg)", "aa_sub_out_links")
    on_lay, w.out_nodes = _browse_row(w, "output subarea nodes (gpkg)", "save",
                                      "GeoPackage (*.gpkg)", "aa_sub_out_nodes")
    ot_lay, w.out_trips = _browse_row(w, "output subarea trip list (csv/gz)", "save",
                                      "CSV (*.csv *.gz)", "aa_sub_out")
    for lay in (ol_lay, on_lay, ot_lay):
        vo.addLayout(lay)
    hint = QLabel("Link and node CSVs (A,B / N for HyDRA) are always written beside "
                  "the GeoPackages.", out_page)
    hint.setStyleSheet("color: gray;")
    vo.addWidget(hint)
    vo.addStretch(1)
    # Renumbering + trip table are done by subarea.exe finalize -- the same
    # numbering engine as the Subarea Extraction dialog, so one equivalency file
    # means the same numbers in both tools.
    w.cb_renum = _check(w, "Renumber subarea nodes (zones 1..n, external stations "
                           "next; network nodes keep their TSM ids)", "aa_sub_renumber")
    w.cb_renum.setToolTip(
        "Rewrites the link/node layers (Sub_A/Sub_B on links, N on nodes with the "
        "statewide id kept as TSM_N), writes a renumbered copy of the trip list "
        "(<name>_renumbered.csv) and the node equivalency file. The CSVs carry "
        "A,B = subarea ids and TSM_A,TSM_B = statewide ids.")
    cwi_lay, w.cw_in = _browse_row(w, "node equivalency in (csv, optional)", "open",
                                   "CSV (*.csv);;All Files (*)", "aa_sub_cw_in")
    w.cw_in.setToolTip("N,Sub_N file from an earlier run (either tool). Blank = "
                       "generate new numbers. Nodes it lists keep its numbers; new "
                       "nodes are numbered after it.")
    cwo_lay, w.cw_out = _browse_row(w, "node equivalency out (csv)", "save",
                                    "CSV (*.csv)", "aa_sub_cw_out")
    w.cw_out.setToolTip("Blank = <subarea nodes>_equivalency.csv")
    w.cb_table = _check(w, "Aggregate the subarea trip list to an hourly trip table "
                           "(ELToD subarea assignment)", "aa_sub_triptable")
    tt_lay, w.tt_out = _browse_row(w, "ELToD trip table out (csv)", "save",
                                   "CSV (*.csv)", "aa_sub_tt_out")
    w.tt_out.setToolTip("STARTTIME,O,D,<marketVot...> (the ELTOD_tt_HourClock layout). "
                        "Blank = ELTOD_subarea_tt_HourClock.csv beside the trip list.")
    vt.addWidget(w.cb_renum)
    vt.addLayout(cwi_lay)
    vt.addLayout(cwo_lay)
    vt.addWidget(_hline(tt_page))
    vt.addWidget(w.cb_table)
    vt.addLayout(tt_lay)
    vt.addStretch(1)
    for cb, rows in ((w.cb_renum, (cwi_lay, cwo_lay)), (w.cb_table, (tt_lay,))):
        cb.toggled.connect(lambda on, rows=rows: [_set_row_enabled(r, on) for r in rows])
        for r in rows:
            _set_row_enabled(r, cb.isChecked())
    run = QPushButton("Run Subarea Extraction", w)
    v.addWidget(run)
    v.addStretch(1)

    def go():
        import processing, tempfile, csv as _csv
        from qgis.core import QgsProject, QgsVectorLayer
        boundary = w.boundary.currentData()
        zones = w.zones.currentData()
        nodes_lyr = w.nodes_lyr.currentData()
        links_lyr = w.links_lyr.currentData()
        if not (boundary and zones and nodes_lyr and links_lyr and _db(dlg)
                and w.trips.text() and w.out_trips.text()):
            QMessageBox.warning(dlg, "Subarea",
                                "Boundary, zones, node & link layers, the common agentPaths "
                                "duckdb, trip list and trip-list output are required.")
            return
        # One live run-log window for the whole extraction (agentAnalysis, the
        # in-QGIS steps, subarea finalize), beside the subarea trip list.
        from .model_run import begin_run_console
        begin_run_console(os.path.join(os.path.dirname(os.path.abspath(w.out_trips.text())),
                                       "Subarea.log"), "Subarea - run log")
        _log("Subarea extraction: boundary '%s', zones '%s', nodes '%s', links '%s'"
             % (boundary.name(), zones.name(), nodes_lyr.name(), links_lyr.name()))
        try:
            # 1) network nodes inside the boundary
            sel_nodes = processing.run("native:extractbylocation",
                {"INPUT": nodes_lyr, "PREDICATE": [0], "INTERSECT": boundary,
                 "OUTPUT": "memory:sub_nodes"})["OUTPUT"]
            # 2) zone centroids inside (zone ids double as centroid node ids).
            #    The id is TAZ (TSM land use), ZONE (Project Settings' zonal
            #    land use: TSM ids outside, PopSyn_Index inside an MSR region)
            #    or TSM_NG. A zone is inside when a point INSIDE it lies in the
            #    boundary: "intersects" also took every zone that only shares
            #    an edge with the boundary -- all of an MSR region's neighbours.
            sel_zones = processing.run("native:extractbylocation",
                {"INPUT": zones, "PREDICATE": [0], "INTERSECT": boundary,
                 "OUTPUT": "memory:sub_zones"})["OUTPUT"]
            zfields = [f.name().upper() for f in sel_zones.fields()]
            zi = next((zfields.index(c) for c in ("TAZ", "ZONE", "TSM_NG") if c in zfields), -1)
            if zi < 0:
                QMessageBox.warning(dlg, "Subarea",
                                    "The land use zones layer needs a zone id field: TAZ, ZONE "
                                    "or TSM_NG.")
                return
            from qgis.core import QgsGeometry, QgsCoordinateTransform
            bgeoms = []
            xf = QgsCoordinateTransform(boundary.crs(), sel_zones.crs(), QgsProject.instance())
            for bf in boundary.getFeatures():
                g = QgsGeometry(bf.geometry())
                g.transform(xf)
                bgeoms.append(g)
            bpoly = QgsGeometry.unaryUnion(bgeoms)
            inside_zones = [feat for feat in sel_zones.getFeatures()
                            if bpoly.contains(feat.geometry().pointOnSurface())]
            nfields = [f.name().upper() for f in sel_nodes.fields()]
            ni = nfields.index("N") if "N" in nfields else 0
            nodes_csv = os.path.join(tempfile.gettempdir(), "subarea_nodes_ui.csv")
            with open(nodes_csv, "w", newline="") as f:
                cw = _csv.writer(f); cw.writerow(["node"])
                for feat in sel_nodes.getFeatures():
                    cw.writerow([int(feat[ni])])
                for feat in inside_zones:
                    cw.writerow([int(feat[zi])])
            _log("Subarea: %d nodes + %d zone centroids inside boundary (zone id %s; %d "
                 "edge-only neighbours skipped) -> %s"
                 % (sel_nodes.featureCount(), len(inside_zones), sel_zones.fields()[zi].name(),
                    sel_zones.featureCount() - len(inside_zones), nodes_csv))
            # 3) subarea links. Two different rules, because a centroid
            #    connector is an abstraction rather than a road:
            #      real links  -- keep the WHOLE link if it touches the boundary
            #                     (predicate 0 = intersects). Clipping one would
            #                     leave a path through it with a missing piece.
            #      connectors  -- keep only if WHOLLY within (predicate 6). Half
            #                     a connector loads a centroid that is not in
            #                     the subarea, which is why they were appearing
            #                     as stray stubs across the boundary.
            if w.out_links.text():
                touching = processing.run("native:extractbylocation",
                    {"INPUT": links_lyr, "PREDICATE": [0], "INTERSECT": boundary,
                     "OUTPUT": "memory:sub_links_touch"})["OUTPUT"]
                inside = processing.run("native:extractbylocation",
                    {"INPUT": links_lyr, "PREDICATE": [6], "INTERSECT": boundary,
                     "OUTPUT": "memory:sub_links_in"})["OUTPUT"]
                lf_names = [f.name().upper() for f in touching.fields()]
                fi = lf_names.index("FTYPE") if "FTYPE" in lf_names else -1
                keep_ids = set()
                if fi >= 0:
                    whole = set()
                    for feat in inside.getFeatures():
                        whole.add(feat.id())
                    for feat in touching.getFeatures():
                        try:
                            is_conn = int(feat[fi]) == FTYPE_CONNECTOR
                        except (TypeError, ValueError):
                            is_conn = False
                        if not is_conn or feat.id() in whole:
                            keep_ids.add(feat.id())
                    dropped = touching.featureCount() - len(keep_ids)
                else:
                    keep_ids = {f.id() for f in touching.getFeatures()}
                    dropped = 0
                    _log("Subarea: link layer has no FTYPE column - centroid "
                         "connectors could not be filtered")
                touching.selectByIds(sorted(keep_ids))
                _drop_layers_for(w.out_links.text())
                processing.run("native:saveselectedfeatures",
                    {"INPUT": touching, "OUTPUT": w.out_links.text()})
                _log("Subarea: %d links kept, %d part-outside centroid "
                     "connectors dropped" % (len(keep_ids), dropped))
        except Exception as e:
            QMessageBox.critical(dlg, "Subarea", "Boundary processing failed:\n%s" % e)
            return
        if not _ensure_index(dlg, _db(dlg), "Subarea"):
            return
        links_csv = _links_as_csv(links_lyr, "subarea")
        if not links_csv:
            QMessageBox.critical(dlg, "Subarea",
                                 "Could not build a CSV link table from the selected "
                                 "link layer (gpkgcsv conversion failed) - see History log.")
            return
        # Congested boundary times are opt-in; the files come from the common
        # section at the top of the dialog, not from a second field here.
        lps = []
        if w.cb_boundary.isChecked():
            lps = _link_performance_files(dlg)
            if not lps:
                QMessageBox.warning(
                    dlg, "Subarea",
                    "External arrival times need the link-performance files, and "
                    "none of the three rows at the top of this dialog point at a "
                    "file that exists.\n\nFill in at least the macroDTA row (and "
                    "meso/micro if the run had them) with output from the SAME run "
                    "as the agentPaths duckdb, or untick the box to extract without "
                    "boundary times.")
                return
            _log("Subarea: boundary times from %d link-performance file(s): %s"
                 % (len(lps), ", ".join(os.path.basename(p) for p in lps)))
        else:
            _log("Subarea: boundary-time walk skipped (checkbox off); EI/EE trips "
                 "keep their statewide departure time")
        args = ["subarea", "--db", _db(dlg), "--mem", "32GB", "--nodes", nodes_csv,
                "--trips", w.trips.text(),
                "--links", links_csv,
                "--out", w.out_trips.text()]
        for p in lps:
            args += ["--linkperf", p]
        r = _run(args, "agentAnalysis_subarea.log")
        if r.returncode != 0:
            QMessageBox.critical(dlg, "Subarea", "agentAnalysis subarea failed - see History log.")
            return

        # 4) subarea nodes = the nodes inside the boundary PLUS the external
        #    nodes the extraction just introduced. IE/EI/EE trips have their O
        #    or D rewritten to the first node OUTSIDE the boundary, so those
        #    ids are referenced by the trip list but sit outside it -- they were
        #    missing from the node layer, leaving the trip list pointing at
        #    nodes the subarea network did not contain.
        #    Zone centroids inside and every endpoint of a kept link go in too:
        #    a real link clipping the boundary has its far node outside, and a
        #    link whose endpoint has no node row cannot be loaded.
        n_ext = 0
        if w.out_nodes.text():
            try:
                inside_ids = set()
                for feat in sel_nodes.getFeatures():
                    inside_ids.add(int(feat[ni]))
                zone_ids = set()
                for feat in inside_zones:
                    try:
                        zone_ids.add(int(feat[zi]))
                    except (TypeError, ValueError):
                        continue
                ext_ids = _subarea_external_nodes(w.out_trips.text(), inside_ids | zone_ids)
                want = inside_ids | zone_ids | ext_ids | _link_endpoints(w.out_links.text())
                n_ext = len(ext_ids)
                keep = []
                for feat in nodes_lyr.getFeatures():
                    try:
                        if int(feat[ni]) in want:
                            keep.append(feat.id())
                    except (TypeError, ValueError):
                        continue
                nodes_lyr.selectByIds(keep)
                _drop_layers_for(w.out_nodes.text())
                processing.run("native:saveselectedfeatures",
                    {"INPUT": nodes_lyr, "OUTPUT": w.out_nodes.text()})
                nodes_lyr.removeSelection()
                marked = _mark_zone_nodes(w.out_nodes.text(), ext_ids,
                                          nfields[ni] if ni < len(nfields) else "N")
                _log("Subarea: %d nodes written (%d inside + %d external "
                     "boundary nodes); DTA_Type=%d set on %s"
                     % (len(keep), len(keep) - n_ext, n_ext, DTA_TYPE_ZONE,
                        ("%d of them" % marked) if marked >= 0
                        else "NONE - see above"))
            except Exception as e:
                _log("Subarea: node layer failed: %s" % e)

        # 5) CSVs (+ optional renumbering / ELToD trip table) via subarea.exe
        fin = _subarea_finalize(dlg, w, nodes_csv)
        if fin is None:
            return

        # 6) show the extracted network
        _add_layer(w.out_links.text(), "Subarea links")
        _add_layer(w.out_nodes.text(), "Subarea nodes")

        QMessageBox.information(dlg, "Subarea",
            "Subarea outputs written:\n%s\n%s  (+%d external boundary nodes, "
            "DTA_Type=99 so they load as subarea zones)"
            "\n%s%s\n\nThe trip list keeps the statewide origin/destination as "
            "TSM_O / TSM_D beside the boundary-crossing O / D." % (
                w.out_links.text() or "(links skipped)",
                w.out_nodes.text() or "(nodes skipped)", n_ext,
                w.out_trips.text(), "".join("\n" + p for p in fin)))
    # closes_run_console: the run-log window closes before any message box.
    from .model_run import closes_run_console
    go = closes_run_console(go)
    run.clicked.connect(lambda: go())
    return w


def _link_endpoints(path):
    """A/B node ids of a link GeoPackage (empty set if it can't be read).

    Read with plain OGR and closed explicitly: a QgsVectorLayer leaves a pooled
    handle on the file, which then blocks subarea.exe from rewriting it."""
    ids = set()
    if not path or not os.path.exists(path):
        return ids
    try:
        from osgeo import ogr
        ds = ogr.Open(path)
        lyr = ds.GetLayer(0)
        defn = lyr.GetLayerDefn()
        if defn.GetFieldIndex("A") < 0 or defn.GetFieldIndex("B") < 0:
            ds = None
            return ids
        for feat in lyr:
            for k in ("A", "B"):
                v = feat.GetField(k)
                if v is not None:
                    ids.add(int(v))
        ds = None
    except Exception as e:
        _log("Subarea: could not read link endpoints from %s: %s" % (path, e))
    return ids


def _renumbered_path(p):
    """trips.csv -> trips_renumbered.csv; trips.csv.gz -> trips_renumbered.csv.gz"""
    base, gz = (p[:-3], ".gz") if p.lower().endswith(".gz") else (p, "")
    root, ext = os.path.splitext(base)
    return root + "_renumbered" + (ext or ".csv") + gz


def _subarea_finalize(dlg, w, inside_csv):
    """Run `subarea.exe finalize` on the extraction just written: link/node CSVs
    always, plus (opt-in) renumbering of network + trip list against a generated
    or supplied node equivalency, and the hourly ELToD trip table.

    Returns the list of extra output paths, or None on failure (already reported).
    """
    links, nodes, trips = (w.out_links.text().strip(), w.out_nodes.text().strip(),
                           w.out_trips.text().strip())
    if not (links and nodes and os.path.exists(links) and os.path.exists(nodes)):
        _log("Subarea: link/node GeoPackage outputs not set - CSVs, renumbering "
             "and trip table skipped")
        return []
    renum, table = w.cb_renum.isChecked(), w.cb_table.isChecked()
    cw_in = w.cw_in.text().strip() if renum else ""
    if cw_in and not os.path.exists(cw_in):
        QMessageBox.warning(dlg, "Subarea", "Node equivalency file not found:\n%s" % cw_in)
        return None
    fwd = lambda p: p.replace("\\", "/")
    link_csv = os.path.splitext(links)[0] + ".csv"
    node_csv = os.path.splitext(nodes)[0] + ".csv"
    S = {"link_file": links, "node_file": nodes, "inside_nodes": inside_csv,
         "trip_file": trips, "link_csv": link_csv, "node_csv": node_csv,
         "renumber": renum, "readCW_file": cw_in,
         "max_zone": Config().get("subarea_max_zone") or "11560"}
    out = [link_csv, node_csv]
    if renum:
        S["saveCW_file"] = w.cw_out.text().strip() or os.path.splitext(nodes)[0] + "_equivalency.csv"
        S["boundary_linklist"] = os.path.splitext(links)[0] + "_Boundary_LinkList.csv"
        S["trip_out"] = _renumbered_path(trips)
        out += [S["saveCW_file"], S["boundary_linklist"], S["trip_out"]]
    if table:
        if not w.tt_out.text().strip():
            w.tt_out.setText(fwd(os.path.join(os.path.dirname(trips),
                                              "ELTOD_subarea_tt_HourClock.csv")))
            Config().set("aa_sub_tt_out", w.tt_out.text())
        S["triptable_out"] = w.tt_out.text().strip()
        out.append(S["triptable_out"])
    exe = Config().app_exe("utilities/subarea.exe")
    if not os.path.exists(exe):
        QMessageBox.critical(dlg, "Subarea", "subarea.exe not found at %s" % exe)
        return None
    settings_file = os.path.splitext(links)[0] + "_finalize_settings.txt"
    with open(settings_file, "w") as f:
        for k, val in S.items():
            f.write("%s = %s\n" % (k, fwd(str(val))))
    for p in (links, nodes):
        _drop_layers_for(p)    # gpkgs are rewritten in place when renumbering
    _log("Subarea: subarea finalize %s" % settings_file)
    r = Config().run_app([exe, "finalize", settings_file],
                         log_path=os.path.splitext(settings_file)[0] + ".log", console=True)
    if r.returncode != 0:
        QMessageBox.critical(dlg, "Subarea", "subarea finalize failed - see %s"
                             % (os.path.splitext(settings_file)[0] + ".log"))
        return None
    return out


_LINK_RE = re.compile(r"(\d+)\s*[->]+\s*(\d+)")


def _ensure_index(dlg, db, what):
    """One-time link->key sidecar index (agentPaths_index.duckdb beside the db).
    Shared by every link-keyed query (Select Link / Subarea / Turning Movements)
    -- built once at 64 GB (the 2.45B-row sort mostly fits in RAM; queries then
    run at 32 GB), reused forever after. Returns True when the index exists (or
    the user declines and accepts the slow full-scan path)."""
    idx = os.path.join(os.path.dirname(db), "agentPaths_index.duckdb")
    if os.path.exists(idx):
        return True
    resp = QMessageBox.question(
        dlg, "Build link index",
        "No link index found for this run. Build it once now?\n\n"
        "It's heavy (a full path sort, capped at 64 GB RAM, spills to disk) but "
        "only happens once — every later Select Link / Subarea / Turning-movement "
        "run is then fast.\n\nNo = run %s without the index (slow full scan)." % what,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        | QMessageBox.StandardButton.Cancel)
    if resp == QMessageBox.StandardButton.Cancel:
        return False
    if resp == QMessageBox.StandardButton.No:
        return True     # proceed on the engine's fallback scan
    ri = _run(["index", "--db", db, "--mem", "64GB"], "agentAnalysis_index.log")
    if ri.returncode != 0 or not os.path.exists(idx):
        QMessageBox.critical(dlg, what, "Index build failed — see History log.")
        return False
    return True


def _tab_selectlink(dlg):
    w = QWidget()
    v = QVBoxLayout(w)
    tl_lay, w.trips = _browse_row(w, "trip list (csv/gz, optional)",
                                  filt="Trip list (*.csv *.gz);;All Files (*)", key="aa_trips")
    v.addLayout(tl_lay)

    v.addWidget(QLabel("Links (one per line or comma-separated, as A-B node pairs, "
                       "e.g. 43618174-43618594):", w))
    w.links = QPlainTextEdit(w)
    w.links.setMaximumHeight(70)
    w.links.setPlaceholderText("a1-b1, a2-b2 ...")
    v.addWidget(w.links)
    # Persist the A-B link list.
    saved_links = Config().get("aa_sl_links")
    if saved_links:
        w.links.setPlainText(saved_links)
    w.links.textChanged.connect(
        lambda: Config().set("aa_sl_links", w.links.toPlainText()))

    pick_lay = QHBoxLayout()
    use_sel = QPushButton("Use selected links from map layer", w)
    pick_lay.addWidget(use_sel)
    grp = QGroupBox("Logic", w)
    gl = QHBoxLayout(grp)
    w.rb_or = QRadioButton("OR (any link)", grp)
    w.rb_and = QRadioButton("AND (all links)", grp)
    w.rb_each = QRadioButton("EACH (per link)", grp)
    w.rb_each.setToolTip("Run each link independently and produce one loaded-"
                         "volume column per link (SL_<A>_<B>) in the output.")
    gl.addWidget(w.rb_or)
    gl.addWidget(w.rb_and)
    gl.addWidget(w.rb_each)
    pick_lay.addWidget(grp)
    v.addLayout(pick_lay)
    # Persist the OR/AND/EACH choice (default OR).
    _lg0 = Config().get("aa_sl_logic")
    w.rb_and.setChecked(_lg0 == "AND")
    w.rb_each.setChecked(_lg0 == "EACH")
    w.rb_or.setChecked(_lg0 not in ("AND", "EACH"))

    def _save_logic():
        Config().set("aa_sl_logic", "AND" if w.rb_and.isChecked()
                     else ("EACH" if w.rb_each.isChecked() else "OR"))
    w.rb_and.toggled.connect(lambda ch: _save_logic())
    w.rb_each.toggled.connect(lambda ch: _save_logic())

    out_lay, w.out = _browse_row(w, "output agents (csv)", mode="save",
                                 filt="CSV (*.csv)", key="aa_sl_out")
    vol_lay, w.vols = _browse_row(w, "output loaded volumes (csv)", mode="save",
                                  filt="CSV (*.csv)", key="aa_sl_vols")
    by_lay, w.by = _by_row(w, "aa_sl_by", "volumes")
    v.addLayout(out_lay)
    v.addLayout(vol_lay)
    v.addLayout(by_lay)
    run = QPushButton("Run Select Link", w)
    v.addWidget(run)
    v.addStretch(1)

    def grab_selected():
        """Pull A/B from the active layer's selected features."""
        from qgis.utils import iface
        lyr = iface.activeLayer()
        if lyr is None or not hasattr(lyr, "selectedFeatures"):
            QMessageBox.warning(dlg, "Select Link", "Select link features on a line layer first.")
            return
        pairs = []
        flds = [f.name().upper() for f in lyr.fields()]
        ai = flds.index("A") if "A" in flds else -1
        bi = flds.index("B") if "B" in flds else -1
        if ai < 0 or bi < 0:
            QMessageBox.warning(dlg, "Select Link", "Active layer needs A and B fields.")
            return
        for f in lyr.selectedFeatures():
            pairs.append("%s-%s" % (f[ai], f[bi]))
        if not pairs:
            QMessageBox.warning(dlg, "Select Link", "No features selected on %s." % lyr.name())
            return
        cur = w.links.toPlainText().strip()
        w.links.setPlainText((cur + ("\n" if cur else "")) + "\n".join(pairs))
    use_sel.clicked.connect(grab_selected)

    def go():
        pairs = _LINK_RE.findall(w.links.toPlainText())
        db = _db(dlg)
        if not (db and pairs):
            QMessageBox.warning(dlg, "Select Link",
                                "agentPaths duckdb (common field above) and at least one A-B link are required.")
            return
        logic = ("AND" if w.rb_and.isChecked()
                 else ("EACH" if w.rb_each.isChecked() else "OR"))

        # One-time link->key index (heavy, RAM-capped). Later runs reuse it and
        # drop from ~20 min to seconds. Shared by Select Link / Subarea / Turns.
        if not _ensure_index(dlg, db, "Select Link"):
            return

        args = ["agents", "--db", db, "--mem", "32GB", "--logic", logic]
        for a, b in pairs:
            args += ["--link", a, b]
        if w.trips.text():
            args += ["--trips", w.trips.text()]
        if w.out.text():
            args += ["--out", w.out.text()]
        vols = w.vols.text()
        if vols:
            args += ["--volumes", vols]
            # --by only shapes the volumes file, so it is pointless without one.
            by = _by_args(dlg, w.by, w.trips.text(), "Select Link")
            if by is None:
                return
            args += by
        elif _by_value(w.by):
            QMessageBox.warning(dlg, "Select Link",
                                "A volume breakdown needs an 'output loaded volumes "
                                "(csv)' file - that is the file the wide SL_VOL_* "
                                "columns are written to.")
            return
        r = _run(args, "agentAnalysis_selectlink.log")
        if r.returncode != 0:
            QMessageBox.critical(dlg, "Select Link", "agentAnalysis agents failed — see History log.")
            return

        # Loaded volumes CSV -> a GPKG with one loaded-volume column per select
        # link (SL_<A>_<B>), joined onto the dialog's link layer via summarize.
        gpkg_note = ""
        if vols and os.path.exists(vols):
            gp = _selectlink_to_gpkg(dlg, vols, pairs, logic)
            gpkg_note = ("\nGPKG (loaded volumes on links): %s" % gp) if gp else \
                        "\n(GPKG skipped: pick a Link layer in the dialog to enable it.)"
        QMessageBox.information(dlg, "Select Link",
                                "Select-link outputs written (%d links, %s).%s" %
                                (len(pairs), logic, gpkg_note))
    run.clicked.connect(go)
    return w


def _sl_volume_cols(vols_csv, pairs, logic):
    """Volume columns to summarize, read from the CSV agentAnalysis wrote.

    Three shapes come out of `agents --volumes`, and the control file has to
    match whichever one is on disk -- listing columns that are not there means
    they silently never reach the loaded CSV or the GPKG, which is how the
    purpose breakdown went missing:

      EACH            a_node,b_node,SL_<A>_<B>...        (no veh_weight)
      OR/AND          a_node,b_node,agents,veh_weight
      OR/AND --by     ...,veh_weight,SL_VOL_<cat>...     (categories sum to it)

    Reading the header rather than rebuilding the list from the UI keeps this
    correct when the categories are data-derived: agentAnalysis discovers which
    purposes/markets are actually in the selection, so the dialog cannot know
    the column names in advance.

    Returns (sum_cols, label). NOTE the categories are returned WITHOUT
    veh_weight: summarize sets total_col to the sum of every sum_col
    (summarize.cpp, `rowtot`), so carrying both would double the total.
    """
    header = []
    try:
        with open(vols_csv, newline="") as f:
            header = next(csv.reader(f), []) or []
    except (OSError, StopIteration):
        pass
    present = set(header)

    by_cols = [h for h in header if h.startswith("SL_VOL_")]
    if by_cols:
        return by_cols, "%d purpose/market classes" % len(by_cols)
    if logic == "EACH":
        each = [c for c in ("SL_%s_%s" % (a, b) for a, b in pairs) if c in present]
        if each:
            return each, "%d per-link columns" % len(each)
    return ["veh_weight"], "total volume"


def _sl_breakdown_is_exhaustive(vols_csv, by_cols, tol=0.01):
    """True when the class columns still add up to veh_weight.

    total_col is DERIVED by summing the class columns, so if they ever stopped
    being an exhaustive split of veh_weight the map's SL_VOL would quietly stop
    being the select-link volume. Checked on the file, not assumed.
    """
    try:
        with open(vols_csv, newline="") as f:
            rd = csv.DictReader(f)
            if "veh_weight" not in (rd.fieldnames or []):
                return True            # EACH has no total to check against
            for i, row in enumerate(rd):
                if i >= 500:           # a sample is enough to catch a schema drift
                    break
                tot = float(row.get("veh_weight") or 0.0)
                s = sum(float(row.get(c) or 0.0) for c in by_cols)
                if abs(s - tot) > max(tol, abs(tot) * tol):
                    return False
    except (OSError, ValueError):
        pass
    return True


def _selectlink_to_gpkg(dlg, vols_csv, pairs, logic):
    """Join the select-link loaded-volumes CSV onto the dialog's link layer and
    write a GPKG (via the bundled summarize.exe legacy mode).

    The columns carried across follow whatever agentAnalysis actually wrote --
    see _sl_volume_cols: one SL_<A>_<B> per link under EACH, the SL_VOL_<cat>
    classes when a purpose/market breakdown was requested, otherwise the plain
    veh_weight total. SL_VOL is always their sum. All columns are actual
    vehicles, matching the loaded network's vehicle-unit link_performance
    volumes. Returns the GPKG path, or None."""
    settings = Config()
    link_combo = getattr(dlg, "comboBox_linkLayer", None)
    getpath = getattr(dlg, "get_layer_path", None)
    if link_combo is None or getpath is None:
        return None
    link_path = getpath(link_combo.currentData())
    if not link_path:
        return None
    sumexe = settings.app_exe("utilities/summarize.exe")
    if not os.path.exists(sumexe):
        return None
    value_cols, what = _sl_volume_cols(vols_csv, pairs, logic)
    if value_cols and value_cols[0].startswith("SL_VOL_") and \
            not _sl_breakdown_is_exhaustive(vols_csv, value_cols):
        # Fall back to the plain total rather than map an SL_VOL that is not
        # the select-link volume.
        _log("select-link: %s do not sum to veh_weight; mapping the total only"
             % what)
        value_cols, what = ["veh_weight"], "total volume"
    _log("select-link GPKG: summarizing %s (%s)" % (what, ", ".join(value_cols[:6]) +
                                                    (" ..." if len(value_cols) > 6 else "")))
    out_gpkg = os.path.splitext(vols_csv)[0] + ".gpkg"
    out_csv = os.path.splitext(vols_csv)[0] + "_loaded.csv"
    sum_cols = ",\n  ".join('"%s"' % c for c in value_cols)
    fwd = lambda p: p.replace("\\", "/")
    toml = (
        'name = "selectlink"\n'
        'group_by = ["A", "B"]\n'
        'sum_cols = [\n  %s\n]\n' % sum_cols +
        'total_col = "SL_VOL"\n'
        'emit_class_sums = %s\n\n' % ("true" if len(value_cols) > 1 else "false") +
        '[input]\nformat = "csv"\npath = "%s"\nrename = ["a_node=A", "b_node=B"]\n\n' % fwd(vols_csv) +
        '[join]\nformat = "gpkg"\npath = "%s"\n\n' % fwd(link_path) +
        '[output]\ncsv = "%s"\ngpkg = "%s"\n' % (fwd(out_csv), fwd(out_gpkg)))
    # Strip the .gpkg before appending: out_gpkg + ".toml" produced the sidecar
    # pair select_link_volumes.gpkg.toml / .gpkg.log, which read as GeoPackage
    # files in the scenario folder. Base them on the stem instead.
    # GDAL cannot rewrite a GeoPackage QGIS still has open, so a re-run used to
    # leave the previous run's file in place while reporting success. Release
    # both targets first.
    _drop_layers_for(out_gpkg)
    _drop_layers_for(out_csv)
    ctl = os.path.splitext(out_gpkg)[0] + ".toml"
    try:
        with open(ctl, "w") as f:
            f.write(toml)
    except Exception:
        return None
    r = settings.run_app([sumexe, ctl], log_path=os.path.splitext(ctl)[0] + ".log", console=True)
    if r.returncode == 0 and os.path.exists(out_gpkg):
        _add_layer(out_gpkg, "SelectLink loaded (%s)" % logic)
        return out_gpkg
    return None


def _tab_turns(dlg):
    w = QWidget()
    v = QVBoxLayout(w)
    nd_lay, w.nodes = _browse_row(w, "node list (csv)",
                                  filt="CSV (*.csv);;All Files (*)", key="aa_turns_nodes")
    v.addLayout(nd_lay)

    opts = QHBoxLayout()
    w.cb_five = QCheckBox("5-node movements (FROM-1, FROM, THRU, TO, TO+1)", w)
    w.cb_hour = QCheckBox("by time of day (15-min, HH:MM:SS)", w)
    w.cb_hour.setChecked(True)
    opts.addWidget(w.cb_five)
    opts.addWidget(w.cb_hour)
    v.addLayout(opts)
    # Persist the option checkboxes (time of day defaults on).
    _five = Config().get("aa_turns_five")
    if _five is not None:
        w.cb_five.setChecked(bool(_five))
    _byhour = Config().get("aa_turns_byhour")
    if _byhour is not None:
        w.cb_hour.setChecked(bool(_byhour))
    w.cb_five.toggled.connect(lambda ch: Config().set("aa_turns_five", ch))
    w.cb_hour.toggled.connect(lambda ch: Config().set("aa_turns_byhour", ch))
    # Network time, not departure time: the paths carry no per-link times, so
    # each agent cohort is walked to the node against the link-performance
    # files at the top of the dialog (the engine's own path timing).
    w.cb_arrival = _check(w, "Time = arrival at the node (walk each path against the "
                             "link performance files above)", "aa_turns_arrival")
    w.cb_arrival.setToolTip(
        "ON: each movement is timed when the agents reach the node -- departure "
        "cohorts walked link by link, every link priced at the 15-min interval "
        "the cohort enters it, using the macro/meso/micro link_performance files "
        "at the top of this dialog (same run as the duckdb). Implies time of day.\n\n"
        "OFF: time = the agents' departure, spread over the slot's 15-min "
        "cohorts as the engine loads them.\n\n"
        "Times after midnight fold onto the clock (24:15 -> 00:15).")
    w.cb_arrival.toggled.connect(lambda on: w.cb_hour.setChecked(True) if on else None)
    v.addWidget(w.cb_arrival)

    by_lay, w.by = _by_row(w, "aa_turns_by", "volumes")
    v.addLayout(by_lay)
    trips_lay, w.trips = _browse_row(w, "trip list (market / exact departures)", mode="open",
                                     filt="Trip list (*.csv.gz *.csv)",
                                     key="aa_turns_trips")
    w.trips.setToolTip("The tripList this duckdb was built from. Needed for a market "
                       "breakdown. When its clocks carry time within the 30-min slot, "
                       "each agent's own clock places it; otherwise agents are spread "
                       "over the engine's 15-min cohorts.")
    v.addLayout(trips_lay)
    out_lay, w.out = _browse_row(w, "output turns (csv)", mode="save",
                                 filt="CSV (*.csv)", key="aa_turns_out")
    v.addLayout(out_lay)
    ag_lay, w.agents_out = _browse_row(w, "list agents (csv, optional)", mode="save",
                                       filt="CSV (*.csv)", key="aa_turns_agents_out")
    w.agents_out.setToolTip("One row per agent per movement: ids, purpose, O/D, "
                            "vehicles, depart time and (with arrival on) arrive time "
                            "at the node, HH:MM:SS. Blank = not written.")
    v.addLayout(ag_lay)
    _align_labels((nd_lay, by_lay, trips_lay, out_lay, ag_lay))
    run = QPushButton("Run Turning Movements", w)
    v.addWidget(run)
    v.addStretch(1)

    def go():
        if not (_db(dlg) and w.nodes.text() and w.out.text()):
            QMessageBox.warning(dlg, "Turning Movements",
                                "agentPaths duckdb (common field above), node list csv and output are required.")
            return
        if not _ensure_index(dlg, _db(dlg), "Turning Movements"):
            return
        args = ["turns", "--db", _db(dlg), "--mem", "32GB", "--nodes", w.nodes.text(),
                "--out", w.out.text()]
        if w.cb_five.isChecked():
            args += ["--five"]
        if w.cb_hour.isChecked() or w.cb_arrival.isChecked():
            args += ["--by-time"]
        if w.cb_arrival.isChecked():
            lps = _link_performance_files(dlg)
            if not lps:
                QMessageBox.warning(
                    dlg, "Turning Movements",
                    "Arrival times at the node need the link-performance files, and "
                    "none of the rows at the top of this dialog point at a file that "
                    "exists.\n\nFill in the macroDTA row (and meso/micro if the run "
                    "had them) from the SAME run as the agentPaths duckdb, or untick "
                    "the arrival box.")
                return
            args += ["--arrival"]
            for p in lps:
                args += ["--linkperf", p]
        by = _by_args(dlg, w.by, w.trips.text(), "Turning Movements")
        if by is None:
            return
        args += by
        agents_out = w.agents_out.text().strip()
        if agents_out:
            args += ["--agents-out", agents_out]
        if w.trips.text() and (by or agents_out):
            args += ["--trips", w.trips.text()]
        r = _run(args, "agentAnalysis_turns.log")
        if r.returncode == 0:
            QMessageBox.information(dlg, "Turning Movements",
                                    "Turns written:\n%s%s" % (
                                        w.out.text(),
                                        ("\nAgents: %s" % agents_out) if agents_out else ""))
        else:
            QMessageBox.critical(dlg, "Turning Movements", "agentAnalysis turns failed - see History log.")
    run.clicked.connect(go)
    return w


def _agent_analysis_help(parent):
    """Right-hand panel: what the four tabs are for, and where the numbers come
    from. Deliberately about the CONCEPTS -- every field already has a tooltip,
    so repeating them here would just go stale."""
    from qgis.PyQt.QtWidgets import QTextBrowser
    html = """
<html><body style='font-family:Segoe UI,Arial; font-size:9pt; line-height:1.35;'>
<h2 style='margin:0 0 6px 0;'>agentAnalysis &#8211; reading the assignment back</h2>

<p>Every tab here answers a question about <b>the routes HyDRA actually chose</b>,
by querying two things the assignment leaves behind.</p>

<h4>1. Where the data comes from</h4>
<p><b><code>agentPaths.duckdb</code></b> &#8211; written by HyDRA when
<i>Agent paths</i> is ticked. Two tables carry everything:</p>
<ul>
<li><code>agents</code> &#8211; one row per vehicle trip: the 4-part identity
(<code>hh_id</code>&#183;<code>person_id</code>&#183;<code>tour_id</code>&#183;<code>trip_id</code>),
<code>origin</code>, <code>dest</code>, <code>depart_slot</code> (30-min),
<code>weight</code> (vehicles), <code>purpose</code>, and a
<b><code>key_id</code></b>.</li>
<li><code>key_paths</code> &#8211; the ordered links of each <b>route key</b>:
<code>key_id, seq, a_node, b_node</code>. Trips taking the identical route share
one key, which is why 77M agents compress into ~35M keys.</li>
</ul>
<p><b>No travel times are stored</b> &#8211; only <code>cost_min</code> for the
whole path. Anything time-dependent is therefore recomputed from:</p>
<p><b><code>link_performance_&lt;macro|meso|micro&gt;DTA.csv</code></b> &#8211;
<code>travel_time_min</code> for every link in every 15-minute interval. The three
files <b>partition</b> the network (a link is written to exactly one), so supplying
all three prices each link at <b>its own resolution</b>. They must come from the
same run as the duckdb.</p>
<p>The <b>link&#8594;key index</b> (<code>agentPaths_index.duckdb</code>) is built
once beside the duckdb and reused; it turns a ~20-minute scan into seconds.</p>

<h4>2. Path Trace</h4>
<p><i>Where did this particular trip go?</i> Give a household (optionally person /
tour / trip) and it lists that agent's route link by link, in order, from
<code>key_paths</code>. Use it to sanity-check a suspicious OD pair or to see why
a trip avoided a facility.</p>

<h4>3. Subarea</h4>
<p><i>Cut a window out of the statewide model.</i> Each trip's stored path is
tested against the boundary and classified:</p>
<ul>
<li><b>II</b> &#8211; both ends inside; the row passes through unchanged.</li>
<li><b>IE / EI</b> &#8211; one end inside; the outside end is rewritten to the
<b>boundary crossing node</b>.</li>
<li><b>EE</b> &#8211; neither end inside but the path crosses the window: a
<b>through</b> trip, rewritten at both ends.</li>
</ul>
<p><code>TSM_O</code> / <code>TSM_D</code> keep the statewide origin and
destination so a subarea trip can be traced back to the parent run. Outputs are a
subarea <b>link</b> layer (whole links kept; centroid connectors only if wholly
inside), a <b>node</b> layer (interior nodes plus the external boundary nodes,
marked <code>DTA_Type&nbsp;=&nbsp;99</code> so they load as subarea zones), and the
<b>trip list</b>. Link and node <b>CSVs</b> (<code>A,B</code> / <code>N</code>,
plus the statewide <code>TSM_A,TSM_B</code> / <code>TSM_N</code>) are written
beside the GeoPackages for HyDRA.</p>
<p><i>Renumber subarea nodes</i> numbers zones <code>1..n</code> and the external
stations after them (network nodes keep their TSM ids), rewrites the layers, writes
<code>&lt;trip list&gt;_renumbered.csv</code> and the node equivalency file. Give
an equivalency from an earlier run (this tab or Subarea Extraction &#8211; same
engine) to keep its numbers. <i>Aggregate &#8230; trip table</i> writes the hourly
ELToD table (<code>STARTTIME,O,D,&lt;marketVot&gt;</code>) for an ELToD subarea
assignment, in subarea numbers when renumbering.</p>
<p>Ticking <i>compute external arrival time</i> walks each EI/EE path against the
link-performance files &#8211; the same walk as Turning Movements' arrival time:
the engine's 15-min loading cohorts, every link priced at the interval the trip
reaches it, past midnight on the 30-hour day. <code>depart_time</code> becomes the
trip's own departure plus that <b>congested</b> time to the boundary, to the
second (<code>boundary_t_min</code> records the offset); a trip reaching the
boundary after midnight stays <code>24:xx</code>, which HyDRA loads natively. Left
off, the trip keeps its statewide departure and the offset is empty &#8211; never a
free-flow guess.</p>

<h4>4. Select Link</h4>
<p><i>Who uses this link?</i> Give one or more A&#8211;B links; every agent whose
route key contains them is selected. <b>OR</b> = uses any, <b>AND</b> = uses all,
<b>EACH</b> = an independent select-link per link. Outputs the selected agents and
their <b>loaded volumes</b> per link (<code>SL_VOL</code>), optionally split into
<code>SL_VOL_&lt;purpose&gt;</code> or <code>&lt;market&gt;</code> columns. The
split happens at agent level <i>before</i> the route-key rollup, so the columns
always sum back to the total. Volumes are joined onto the link layer as a GPKG for
mapping.</p>

<h4>5. Turning Movements</h4>
<p><i>How much turns where?</i> At each requested node, consecutive links of the
same route key are paired &#8211; FROM&#8594;THRU&#8594;TO, or five nodes with
<i>--five</i> &#8211; and agent weights summed per movement. The output is
<b>aggregate</b>: one row per movement with an agent count and vehicle volume
(plus per-purpose or per-market columns if asked). <i>List agents</i> also writes
every agent through each movement.</p>
<p><i>By time of day</i> splits volumes into <b>15-minute intervals</b> labelled by
their start (<code>07:15:00</code>). The stored paths carry no per-link times, so
the time is either:</p>
<ul>
<li><b>departure</b> (default) &#8211; the agents' departure on the slot's 15-min
cohorts, as the engine releases them; or</li>
<li><b>arrival at the node</b> (box ticked) &#8211; each cohort walked along its
path, every link priced at the interval the cohort enters it, from the
link-performance files at the top of the dialog. This is the engine's own path
timing, so turns into a link add up to that link's path-based volume.</li>
</ul>
<p>Times after midnight fold onto the clock (24:15 &#8594; 00:15). Agent lists
give departure and arrival to the second, with a <code>next_day</code> flag. HyDRA
keeps only each agent's 30-min slot and releases it as two 15-min cohorts; every
agent is placed in one &#8211; by its own trip-list clock when that carries time
within the slot, otherwise alternately &#8211; and the timed volumes are summed
from those same agents, so the agent list adds up to them exactly.</p>
<p style='color:#b9770e;'><b>Note:</b> link travel times do not include time spent
<b>waiting to enter</b> the network &#8211; at a saturated origin, or in the meso
admission queue. Where the run is that congested, the engine's discharged link
volumes run later than any path-based timing, arrival included.</p>

<h4>Units</h4>
<p>All volumes are <b>actual vehicles</b> (raw agent weight), matching the
vehicle-unit <code>link_performance</code> volumes &#8211; not person trips and not
PCE.</p>
</body></html>"""
    tb = QTextBrowser(parent)
    tb.setHtml(html)
    tb.setOpenExternalLinks(True)
    tb.setMinimumWidth(360)
    return tb


# ---------------------------------------------------- link performance tab --
# Breakdown label -> (engine link_volume_by_<kind> stem or "" for the inline
# purpose columns, agentAnalysis linkvol --by value). None = no breakdown.
_LP_BY = [("None - totals only", None, None),
          ("Purpose", "", "purpose"),
          ("Market", "market", "market"),
          ("Market x VOT (marketVot)", "segment", "marketvot"),
          ("VOT bins ($/hr)", "votbin", "votbin")]


def _combo_saved(parent, items, key, default=0):
    """Combo of `items` (labels) persisted by label under `key`."""
    c = QComboBox(parent)
    c.addItems(items)
    saved = Config().get(key)
    c.setCurrentIndex(items.index(saved) if saved in items else default)
    c.currentTextChanged.connect(lambda t: Config().set(key, t))
    return c


def _labeled(parent, text, widget):
    lay = QHBoxLayout()
    lab = QLabel(text, parent)
    lab.setMinimumWidth(150)
    lay.addWidget(lab)
    lay.addWidget(widget, 1)
    return lay


def _selected_links_csv(dlg):
    """A,B of the features selected on the dialog's link layer, as a temp CSV
    (the link filter of summarize linkperf / agentAnalysis linkvol)."""
    lyr = dlg.comboBox_linkLayer.currentData()
    if lyr is None:
        return None, "Pick the Link layer at the top of the dialog."
    names = [f.name() for f in lyr.fields()]
    up = [n.upper() for n in names]
    if "A" not in up or "B" not in up:
        return None, "The link layer needs A and B fields."
    fa, fb = names[up.index("A")], names[up.index("B")]
    feats = list(lyr.selectedFeatures())
    if not feats:
        return None, "No links are selected on %s." % lyr.name()
    path = os.path.join(tempfile.gettempdir(), "linkperf_links.csv")
    with open(path, "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["A", "B"])
        for ft in feats:
            wr.writerow([ft[fa], ft[fb]])
    return path.replace("\\", "/"), "%d selected links" % len(feats)


def _tab_linkperf(dlg):
    """Link performance by link x time period, from the run's link_performance
    files (loaded volumes, speed, queue, VMT, VHT) or from agentPaths.duckdb
    (routed demand by departure time), with an optional breakdown."""
    w = QWidget()
    v = QVBoxLayout(w)

    src_box = QGroupBox("Source", w)
    sl = QVBoxLayout(src_box)
    w.rb_loaded = QRadioButton("Loaded network: the link performance files above "
                               "(volume, speed, queue, VMT, VHT, toll)", src_box)
    w.rb_routed = QRadioButton("Routed demand: agentPaths duckdb above "
                               "(volume by departure time; no speed or queue)", src_box)
    w.rb_routed.setToolTip(
        "Every agent's vehicles on every link of its path, in the period it DEPARTS, "
        "before network loading -- higher than the loaded volumes wherever the "
        "network could not serve all demand. Use it for breakdowns the run did not write.")
    sl.addWidget(w.rb_loaded)
    sl.addWidget(w.rb_routed)
    v.addWidget(src_box)
    routed0 = Config().get("lp_source") == "routed"
    w.rb_routed.setChecked(routed0)
    w.rb_loaded.setChecked(not routed0)

    w.by = _combo_saved(w, [b[0] for b in _LP_BY], "lp_by")
    v.addLayout(_labeled(w, "break volumes down by", w.by))
    w.res = _combo_saved(w, ["15 min", "30 min", "60 min"], "lp_res", default=2)
    v.addLayout(_labeled(w, "time period", w.res))

    bd_lay, w.bd_file = _browse_row(w, "breakdown file (loaded)",
                                    filt="CSV (*.csv);;All Files (*)", key="lp_bd_file")
    w.bd_file.setPlaceholderText("auto: link_volume_by_<kind>.csv beside the macro file")
    w.bd_file.setToolTip(
        "Written by HyDRA when the breakdown is ticked in its Outputs (Market, "
        "Market x VOT, VOT bins). Purpose needs no file: it is in the link "
        "performance files.")
    v.addLayout(bd_lay)
    tl_lay, w.trips = _browse_row(w, "trip list (routed, market)",
                                  filt="Trip list (*.csv *.gz);;All Files (*)", key="aa_trips")
    w.trips.setToolTip("The tripList that produced this agentPaths.duckdb -- needed for "
                       "Market / Market x VOT from the duckdb (joined by row number).")
    v.addLayout(tl_lay)
    w.vot_edges = QLineEdit(Config().get("lp_vot_edges") or "10,20,40,80", w)
    w.vot_edges.setToolTip("VOT bin edges in $/hr for routed demand (the loaded "
                           "breakdown uses the run's VOT_BIN_EDGES).")
    w.vot_edges.editingFinished.connect(lambda: Config().set("lp_vot_edges", w.vot_edges.text()))
    v.addLayout(_labeled(w, "VOT bin edges (routed)", w.vot_edges))

    w.cb_sel = _check(w, "Only the links selected on the link layer (recommended "
                         "statewide at 15 min)", "lp_selected")
    v.addWidget(w.cb_sel)
    out_lay, w.out = _browse_row(w, "output (csv)", mode="save",
                                 filt="CSV (*.csv)", key="lp_out")
    v.addLayout(out_lay)
    w.cb_gpkg = _check(w, "Also write a GeoPackage layer (one feature per link and "
                          "period, for the Temporal Controller; loaded source)", "lp_gpkg")
    v.addWidget(w.cb_gpkg)
    run = QPushButton("Build Link Performance", w)
    v.addWidget(run)
    v.addStretch(1)

    def sync():
        routed = w.rb_routed.isChecked()
        Config().set("lp_source", "routed" if routed else "loaded")
        _set_row_enabled(bd_lay, not routed)
        _set_row_enabled(tl_lay, routed)
        w.vot_edges.setEnabled(routed)
        w.cb_gpkg.setEnabled(not routed)
    w.rb_routed.toggled.connect(lambda _: sync())
    sync()

    def go():
        label, stem, by_aa = _LP_BY[w.by.currentIndex()]
        res = w.res.currentText().split()[0]
        out = w.out.text().strip()
        if not out:
            QMessageBox.warning(dlg, "Link Performance", "Pick the output CSV.")
            return
        out = _ensure_ext(out, ".csv")
        w.out.setText(out)
        link_csv = None
        if w.cb_sel.isChecked():
            link_csv, msg = _selected_links_csv(dlg)
            if not link_csv:
                QMessageBox.warning(dlg, "Link Performance", msg)
                return
            _log("Link Performance: " + msg)

        if w.rb_routed.isChecked():
            db = _db(dlg)
            if not db or not os.path.exists(db):
                QMessageBox.warning(dlg, "Link Performance", "Set the agentPaths duckdb above.")
                return
            args = ["linkvol", "--db", db, "--out", out, "--time-res", res, "--mem", "32GB"]
            if by_aa:
                args += ["--by", by_aa]
                if by_aa == "votbin":
                    args += ["--vot-edges", w.vot_edges.text().strip() or "10,20,40,80"]
                if by_aa in ("market", "marketvot"):
                    if not w.trips.text().strip():
                        QMessageBox.warning(dlg, "Link Performance",
                                            "Market breakdowns from the duckdb need the trip list "
                                            "that produced it.")
                        return
                    args += ["--trips", w.trips.text().strip()]
            if link_csv:
                args += ["--link-list", link_csv]
            r = _run(args, "agentAnalysis_linkvol.log")
            if r.returncode != 0:
                QMessageBox.critical(dlg, "Link Performance", "agentAnalysis linkvol failed - see History log.")
                return
            QMessageBox.information(dlg, "Link Performance",
                                    "Routed demand by %s-min departure period written:\n%s" % (res, out))
            return

        tiers = _link_performance_files(dlg)
        if not tiers:
            QMessageBox.warning(dlg, "Link Performance",
                                "Set the macroDTA link performance file above (meso / micro optional).")
            return
        kind = "none" if by_aa is None else ("purpose" if stem == "" else stem)
        bd = ""
        if stem:
            bd = w.bd_file.text().strip() or os.path.join(
                os.path.dirname(tiers[0]), "link_volume_by_%s.csv" % stem).replace("\\", "/")
            if not os.path.exists(bd):
                QMessageBox.warning(
                    dlg, "Link Performance",
                    "%s needs %s.\n\nTick it under HyDRA > Outputs > Extra volume breakdowns "
                    "and re-run (or resume with Outputs only), or use Routed demand." %
                    (label, os.path.basename(bd)))
                return
        lines = ['name = "link_performance"', 'mode = "linkperf"', 'group_by = ["A", "B"]',
                 "time_res = %s" % res, 'breakdown = "%s"' % kind]
        for sec, p in zip(("input", "input2", "input3"), tiers):
            lines += ["[%s]" % sec, 'path = "%s"' % p]
        if bd:
            lines += ["[breakdown]", 'path = "%s"' % bd]
        if link_csv:
            lines += ["[filter]", 'links = "%s"' % link_csv]
        gpkg = ""
        if w.cb_gpkg.isChecked():
            lyr = dlg.comboBox_linkLayer.currentData()
            if lyr is None:
                QMessageBox.warning(dlg, "Link Performance", "The GeoPackage needs the Link layer above.")
                return
            gpkg = os.path.splitext(out)[0] + ".gpkg"
            _drop_layers_for(gpkg)
            lines += ["[join]", 'path = "%s"' % _layer_path(lyr).replace("\\", "/")]
        lines += ["[output]", 'csv = "%s"' % out.replace("\\", "/")]
        if gpkg:
            lines += ['gpkg = "%s"' % gpkg.replace("\\", "/")]
        ctl = os.path.splitext(out)[0] + "_linkperf.toml"
        with open(ctl, "w") as f:
            f.write("\n".join(lines) + "\n")
        settings = Config()
        exe = settings.app_exe("utilities/summarize.exe")
        _log("Link Performance: summarize " + ctl)
        r = settings.run_app([exe, ctl], log_path=os.path.splitext(ctl)[0] + ".log", console=True)
        if r.returncode != 0:
            QMessageBox.critical(dlg, "Link Performance", "summarize linkperf failed - see %s.log" %
                                 os.path.splitext(ctl)[0])
            return
        note = ""
        if gpkg and os.path.exists(gpkg):
            _add_layer(gpkg, "Link Performance (%s min)" % res)
            note = "\nGeoPackage added to the map: %s" % gpkg
        QMessageBox.information(dlg, "Link Performance",
                                "Link performance by %s-min period written:\n%s%s" % (res, out, note))
    run.clicked.connect(go)
    return w


def _ensure_ext(path, ext):
    return path if path.lower().endswith(ext) else path + ext


def add_agent_analysis_tabs(dlg):
    """Append the agentAnalysis QTabWidget under the Summarization controls
    (bottom of the dialog, SubareaAssignment-style)."""
    tabs = QTabWidget(dlg)
    tabs.setTabPosition(QTabWidget.TabPosition.North)
    # Keep references to each tab's QWidget so save_agent_settings() can read
    # every field back on OK (browse buttons don't emit editingFinished).
    dlg._aa_trace = _tab_trace(dlg)
    dlg._aa_subarea = _tab_subarea(dlg)
    dlg._aa_selectlink = _tab_selectlink(dlg)
    dlg._aa_turns = _tab_turns(dlg)
    dlg._aa_linkperf = _tab_linkperf(dlg)
    tabs.addTab(dlg._aa_linkperf, "Link Performance")
    tabs.addTab(dlg._aa_trace, "Path Trace")
    tabs.addTab(dlg._aa_subarea, "Subarea")
    tabs.addTab(dlg._aa_selectlink, "Select Link")
    tabs.addTab(dlg._aa_turns, "Turning Movements")

    grid = dlg.gridLayout
    row = grid.rowCount()
    grid.addWidget(tabs, row, 0, 1, 1)
    # Help panel down the right-hand side, spanning the whole dialog the way the
    # HyDRA and agentPlans dialogs do -- the existing rows all sit in column 0,
    # so column 1 is free.
    dlg._aa_help = _agent_analysis_help(dlg)
    grid.addWidget(dlg._aa_help, 0, 1, row + 1, 1)
    grid.setColumnStretch(0, 3)
    grid.setColumnStretch(1, 2)
    dlg.resize(dlg.width() + 560, dlg.height() + 420)
    return tabs


def save_agent_settings(dlg):
    """Push every meso/micro/agentAnalysis widget's current value into Config so
    a single OK/save persists the whole dialog to the scenario settings JSON --
    exactly like the macroDTA volume_file. Called from the dialog's OK handler.

    Belt-and-suspenders: the live editingFinished/browse/toggled signals already
    keep Config current, but reading the widgets here guarantees nothing is lost
    if a signal never fired (e.g. a value typed but never de-focused)."""
    cfg = Config()

    # --- multi-DTA inputs + shared agentPaths db (exposed on the dialog) ---
    if hasattr(dlg, "lineEdit_volumeMeso"):
        cfg.set("volume_file_meso", dlg.lineEdit_volumeMeso.text().strip())
    if hasattr(dlg, "lineEdit_volumeMicro"):
        cfg.set("volume_file_micro", dlg.lineEdit_volumeMicro.text().strip())
    if hasattr(dlg, "lineEdit_agentPaths"):
        cfg.set("aa_trace_db", dlg.lineEdit_agentPaths.text().strip())

    # --- Path Trace tab ---
    # NB: the trip list uses the shared "aa_trips" key (also in Subarea/Select
    # Link), so it is left to its own live signals rather than re-saved here --
    # re-saving from one tab could clobber a newer edit made in another.
    t = getattr(dlg, "_aa_trace", None)
    if t is not None:
        cfg.set("aa_trace_hh", t.hh.text().strip())
        cfg.set("aa_trace_person", t.person.text().strip())
        cfg.set("aa_trace_tour", t.tour.text().strip())
        cfg.set("aa_trace_trip", t.trip.text().strip())
        cfg.set("aa_trace_out", t.out.text().strip())

    # --- Subarea tab (layer dropdowns store by layer name) ---
    s = getattr(dlg, "_aa_subarea", None)
    if s is not None:
        cfg.set("aa_sub_boundary_lyr", s.boundary.currentText())
        cfg.set("aa_sub_zones_lyr", s.zones.currentText())
        cfg.set("aa_sub_nodes_lyr", s.nodes_lyr.currentText())
        cfg.set("aa_sub_links_lyr", s.links_lyr.currentText())
        cfg.set("aa_sub_out_links", s.out_links.text().strip())
        cfg.set("aa_sub_out_nodes", s.out_nodes.text().strip())
        cfg.set("aa_sub_out", s.out_trips.text().strip())

    # --- Select Link tab ---
    sl = getattr(dlg, "_aa_selectlink", None)
    if sl is not None:
        cfg.set("aa_sl_links", sl.links.toPlainText().strip())
        cfg.set("aa_sl_logic", "AND" if sl.rb_and.isChecked()
                else ("EACH" if sl.rb_each.isChecked() else "OR"))
        cfg.set("aa_sl_out", sl.out.text().strip())
        cfg.set("aa_sl_vols", sl.vols.text().strip())

    # --- Turning Movements tab ---
    tn = getattr(dlg, "_aa_turns", None)
    if tn is not None:
        cfg.set("aa_turns_nodes", tn.nodes.text().strip())
        cfg.set("aa_turns_five", tn.cb_five.isChecked())
        cfg.set("aa_turns_byhour", tn.cb_hour.isChecked())
        cfg.set("aa_turns_arrival", tn.cb_arrival.isChecked())
        cfg.set("aa_turns_out", tn.out.text().strip())
        cfg.set("aa_turns_agents_out", tn.agents_out.text().strip())
