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


def _tab_subarea(dlg):
    """Boundary and land use come from LOADED GPKG LAYERS (dropdowns); the
    interior-node CSV the CLI needs (network nodes + zone centroids inside the
    boundary) is derived here. Outputs: subarea link gpkg + node gpkg (clipped)
    + the subarea trip list."""
    w = QWidget()
    v = QVBoxLayout(w)

    def combo_row(label, geom, key):
        lay = QHBoxLayout()
        lab = QLabel(label, w); lab.setMinimumWidth(150)
        cb = _layer_combo(w, geom, key)
        lay.addWidget(lab); lay.addWidget(cb)
        return lay, cb

    b_lay, w.boundary = combo_row("subarea boundary (polygon layer)", "Polygon", "aa_sub_boundary_lyr")
    z_lay, w.zones = combo_row("land use zones - statewide (polygon layer)", "Polygon", "aa_sub_zones_lyr")
    n_lay, w.nodes_lyr = combo_row("network nodes (point layer)", "Point", "aa_sub_nodes_lyr")
    l_lay, w.links_lyr = combo_row("network links (line layer)", "LineString", "aa_sub_links_lyr")
    for lay in (b_lay, z_lay, n_lay, l_lay):
        v.addLayout(lay)
    tl_lay, w.trips = _browse_row(w, "trip list (csv/gz)",
                                  filt="Trip list (*.csv *.gz);;All Files (*)", key="aa_trips")
    v.addLayout(tl_lay)
    v.addWidget(_hline(w))
    ol_lay, w.out_links = _browse_row(w, "output subarea links (gpkg)", "save",
                                      "GeoPackage (*.gpkg)", "aa_sub_out_links")
    on_lay, w.out_nodes = _browse_row(w, "output subarea nodes (gpkg)", "save",
                                      "GeoPackage (*.gpkg)", "aa_sub_out_nodes")
    ot_lay, w.out_trips = _browse_row(w, "output subarea trip list (csv/gz)", "save",
                                      "CSV (*.csv *.gz)", "aa_sub_out")
    for lay in (ol_lay, on_lay, ot_lay):
        v.addLayout(lay)
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
        try:
            # 1) network nodes inside the boundary
            sel_nodes = processing.run("native:extractbylocation",
                {"INPUT": nodes_lyr, "PREDICATE": [0], "INTERSECT": boundary,
                 "OUTPUT": "memory:sub_nodes"})["OUTPUT"]
            # 2) zone centroids inside (TAZ ids double as centroid node ids)
            sel_zones = processing.run("native:extractbylocation",
                {"INPUT": zones, "PREDICATE": [0], "INTERSECT": boundary,
                 "OUTPUT": "memory:sub_zones"})["OUTPUT"]
            zfields = [f.name().upper() for f in sel_zones.fields()]
            zi = zfields.index("TAZ") if "TAZ" in zfields else 0
            nfields = [f.name().upper() for f in sel_nodes.fields()]
            ni = nfields.index("N") if "N" in nfields else 0
            nodes_csv = os.path.join(tempfile.gettempdir(), "subarea_nodes_ui.csv")
            with open(nodes_csv, "w", newline="") as f:
                cw = _csv.writer(f); cw.writerow(["node"])
                for feat in sel_nodes.getFeatures():
                    cw.writerow([int(feat[ni])])
                for feat in sel_zones.getFeatures():
                    cw.writerow([int(feat[zi])])
            _log("Subarea: %d nodes + %d zone centroids inside boundary -> %s"
                 % (sel_nodes.featureCount(), sel_zones.featureCount(), nodes_csv))
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
        args = ["subarea", "--db", _db(dlg), "--mem", "32GB", "--nodes", nodes_csv,
                "--trips", w.trips.text(),
                "--links", links_csv,
                "--out", w.out_trips.text()]
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
        n_ext = 0
        if w.out_nodes.text():
            try:
                inside_ids = set()
                for feat in sel_nodes.getFeatures():
                    inside_ids.add(int(feat[ni]))
                ext_ids = _subarea_external_nodes(w.out_trips.text(), inside_ids)
                want = inside_ids | ext_ids
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

        # 5) show the extracted network
        _add_layer(w.out_links.text(), "Subarea links")
        _add_layer(w.out_nodes.text(), "Subarea nodes")

        QMessageBox.information(dlg, "Subarea",
            "Subarea outputs written:\n%s\n%s  (+%d external boundary nodes, "
            "DTA_Type=99 so they load as subarea zones)"
            "\n%s\n\nThe trip list keeps the statewide origin/destination as "
            "TSM_O / TSM_D beside the boundary-crossing O / D." % (
                w.out_links.text() or "(links skipped)",
                w.out_nodes.text() or "(nodes skipped)", n_ext,
                w.out_trips.text()))
    run.clicked.connect(go)
    return w


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
    w.cb_hour = QCheckBox("by hour (period clock)", w)
    w.cb_hour.setChecked(True)
    opts.addWidget(w.cb_five)
    opts.addWidget(w.cb_hour)
    v.addLayout(opts)
    # Persist the two option checkboxes (by-hour defaults on).
    _five = Config().get("aa_turns_five")
    if _five is not None:
        w.cb_five.setChecked(bool(_five))
    _byhour = Config().get("aa_turns_byhour")
    if _byhour is not None:
        w.cb_hour.setChecked(bool(_byhour))
    w.cb_five.toggled.connect(lambda ch: Config().set("aa_turns_five", ch))
    w.cb_hour.toggled.connect(lambda ch: Config().set("aa_turns_byhour", ch))
    hint = QLabel("Periods are the agents' DEPARTURE hour (stored paths carry "
                  "no per-link arrival times).", w)
    hint.setStyleSheet("color: gray;")
    v.addWidget(hint)

    by_lay, w.by = _by_row(w, "aa_turns_by", "volumes")
    v.addLayout(by_lay)
    trips_lay, w.trips = _browse_row(w, "trip list (for market)", mode="open",
                                     filt="Trip list (*.csv.gz *.csv)",
                                     key="aa_turns_trips")
    v.addLayout(trips_lay)
    out_lay, w.out = _browse_row(w, "output turns (csv)", mode="save",
                                 filt="CSV (*.csv)", key="aa_turns_out")
    v.addLayout(out_lay)
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
        if w.cb_hour.isChecked():
            args += ["--by-hour"]
        by = _by_args(dlg, w.by, w.trips.text(), "Turning Movements")
        if by is None:
            return
        args += by
        if by and w.trips.text():
            args += ["--trips", w.trips.text()]
        r = _run(args, "agentAnalysis_turns.log")
        if r.returncode == 0:
            QMessageBox.information(dlg, "Turning Movements",
                                    "Turns written:\n%s" % w.out.text())
        else:
            QMessageBox.critical(dlg, "Turning Movements", "agentAnalysis turns failed - see History log.")
    run.clicked.connect(go)
    return w


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
    tabs.addTab(dlg._aa_trace, "Path Trace")
    tabs.addTab(dlg._aa_subarea, "Subarea")
    tabs.addTab(dlg._aa_selectlink, "Select Link")
    tabs.addTab(dlg._aa_turns, "Turning Movements")

    grid = dlg.gridLayout
    row = grid.rowCount()
    grid.addWidget(tabs, row, 0, 1, 1)
    dlg.resize(dlg.width() + 140, dlg.height() + 420)
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
        cfg.set("aa_turns_out", tn.out.text().strip())
