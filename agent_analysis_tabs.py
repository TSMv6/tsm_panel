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
import os
import re

from qgis.PyQt import QtCore, QtWidgets
from qgis.PyQt.QtWidgets import (QFileDialog, QMessageBox, QWidget, QLabel,
                                 QLineEdit, QPushButton, QCheckBox, QRadioButton,
                                 QGridLayout, QHBoxLayout, QVBoxLayout,
                                 QTabWidget, QGroupBox, QPlainTextEdit)

from .tsm_settings import Config
from . import tsm_history


# ----------------------------------------------------------------- helpers --
BROWSE_W = 34   # one width for every '...' button so the rows line up


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


def _log(msg):
    tsm_history.log_action(msg, "agentAnalysis")


def _exe():
    exe = Config().app_exe("agentAnalysis/agentAnalysis.exe")
    if not os.path.exists(exe):
        raise FileNotFoundError("agentAnalysis.exe not found at: %s" % exe)
    return exe


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
    ln.setFrameShape(QtWidgets.QFrame.HLine)
    ln.setFrameShadow(QtWidgets.QFrame.Sunken)
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
            # 3) clipped link / node gpkg outputs
            if w.out_links.text():
                processing.run("native:extractbylocation",
                    {"INPUT": links_lyr, "PREDICATE": [0], "INTERSECT": boundary,
                     "OUTPUT": w.out_links.text()})
            if w.out_nodes.text():
                processing.run("native:extractbylocation",
                    {"INPUT": nodes_lyr, "PREDICATE": [0], "INTERSECT": boundary,
                     "OUTPUT": w.out_nodes.text()})
        except Exception as e:
            QMessageBox.critical(dlg, "Subarea", "Boundary processing failed:\n%s" % e)
            return
        if not _ensure_index(dlg, _db(dlg), "Subarea"):
            return
        args = ["subarea", "--db", _db(dlg), "--mem", "32GB", "--nodes", nodes_csv,
                "--trips", w.trips.text(),
                "--links", _layer_path(links_lyr),
                "--out", w.out_trips.text()]
        r = _run(args, "agentAnalysis_subarea.log")
        if r.returncode == 0:
            QMessageBox.information(dlg, "Subarea",
                "Subarea outputs written:\n%s\n%s\n%s" % (
                    w.out_links.text() or "(links skipped)",
                    w.out_nodes.text() or "(nodes skipped)",
                    w.out_trips.text()))
        else:
            QMessageBox.critical(dlg, "Subarea", "agentAnalysis subarea failed - see History log.")
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
        QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
    if resp == QMessageBox.Cancel:
        return False
    if resp == QMessageBox.No:
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
    v.addLayout(out_lay)
    v.addLayout(vol_lay)
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
        # Segment params (pce): lets the engine report volumes in the same PCE
        # units the loaded network uses (trucks count > 1). Falls back to the
        # SEGMENT_PARAM_FILE named in the run's .ctl beside the duckdb.
        seg = Config().get("hydra_segment_params")
        if seg and os.path.exists(seg):
            args += ["--segments", seg]
        for a, b in pairs:
            args += ["--link", a, b]
        if w.trips.text():
            args += ["--trips", w.trips.text()]
        if w.out.text():
            args += ["--out", w.out.text()]
        vols = w.vols.text()
        if vols:
            args += ["--volumes", vols]
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


def _selectlink_to_gpkg(dlg, vols_csv, pairs, logic):
    """Join the select-link loaded-volumes CSV onto the dialog's link layer and
    write a GPKG, adding one loaded-volume column per select-link (via the
    bundled summarize.exe legacy mode). EACH -> one SL_<A>_<B> column per link;
    OR/AND -> a single SL_VOL column. Columns are in PCE units (each agent
    weighted by its segment pce) so they reconcile with the loaded network's
    link_performance volumes; raw vehicle weights stay in the CSVs
    (veh_weight / VEH_* columns). Returns the GPKG path, or None."""
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
    value_cols = (["SL_%s_%s" % (a, b) for a, b in pairs] if logic == "EACH"
                  else ["pce_vol"])
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
    ctl = out_gpkg + ".toml"
    try:
        with open(ctl, "w") as f:
            f.write(toml)
    except Exception:
        return None
    r = settings.run_app([sumexe, ctl], log_path=os.path.splitext(ctl)[0] + ".log", console=True)
    if r.returncode == 0 and os.path.exists(out_gpkg):
        try:
            from qgis.core import QgsVectorLayer, QgsProject
            lyr = QgsVectorLayer(out_gpkg, "SelectLink loaded (%s)" % logic, "ogr")
            if lyr.isValid():
                QgsProject.instance().addMapLayer(lyr)
        except Exception:
            pass
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
        seg = Config().get("hydra_segment_params")
        if seg and os.path.exists(seg):
            args += ["--segments", seg]   # pce_vol column matches loaded network
        if w.cb_five.isChecked():
            args += ["--five"]
        if w.cb_hour.isChecked():
            args += ["--by-hour"]
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
    tabs.setTabPosition(QTabWidget.North)
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
