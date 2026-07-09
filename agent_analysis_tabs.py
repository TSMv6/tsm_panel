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
def _browse_row(parent, label, mode="open", filt="All Files (*)", key=None):
    """label + line-edit + '...' browse button; returns (layout, line_edit)."""
    lay = QHBoxLayout()
    lab = QLabel(label, parent)
    lab.setMinimumWidth(150)
    edit = QLineEdit(parent)
    btn = QPushButton("...", parent)
    btn.setMaximumWidth(28)

    def pick():
        if mode == "open":
            p, _ = QFileDialog.getOpenFileName(parent, "Select File", "", filt)
        else:
            p, _ = QFileDialog.getSaveFileName(parent, "Select File", "", filt)
        if p:
            edit.setText(p)
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


# ------------------------------------------------- summarization: 3 inputs --
def add_dta_inputs(dlg):
    """Relabel the existing volume row as macroDTA and insert mesoDTA/microDTA
    rows right below it. Returns (meso_edit, micro_edit)."""
    dlg.label_4.setText("macroDTA link performance (csv)")
    dlg.lineEdit_volume.setToolTip("link_performance_macroDTA.csv (required)")

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
def _tab_trace(dlg):
    w = QWidget()
    v = QVBoxLayout(w)
    db_lay, w.db = _browse_row(w, "agentPaths (duckdb)",
                               filt="DuckDB (*.duckdb);;All Files (*)",
                               key="aa_trace_db")
    tl_lay, w.trips = _browse_row(w, "trip list (csv/gz)",
                                  filt="Trip list (*.csv *.gz);;All Files (*)",
                                  key="aa_trips")
    v.addLayout(db_lay)
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
        if not (w.db.text() and w.trips.text() and w.hh.text()):
            QMessageBox.warning(dlg, "Path Trace",
                                "agentPaths duckdb, trip list and hh_id are required.")
            return
        args = ["trace", "--db", w.db.text(), "--trips", w.trips.text(),
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
    w = QWidget()
    v = QVBoxLayout(w)
    rows = [
        ("subarea boundary / nodes (csv)", "open", "CSV (*.csv);;All Files (*)", "aa_sub_nodes"),
        ("land use zones - statewide (csv/gpkg)", "open", "All Files (*)", "aa_sub_landuse"),
        ("agentPaths (duckdb)", "open", "DuckDB (*.duckdb);;All Files (*)", "aa_trace_db"),
        ("trip list (csv/gz)", "open", "Trip list (*.csv *.gz);;All Files (*)", "aa_trips"),
        ("link file (gpkg/csv)", "open", "All Files (*)", "aa_sub_links"),
        ("node file (gpkg/csv)", "open", "All Files (*)", "aa_sub_nodesgpkg"),
        ("output subarea trip list (csv/gz)", "save", "CSV (*.csv *.gz)", "aa_sub_out"),
    ]
    w.edits = {}
    for label, mode, filt, key in rows:
        lay, e = _browse_row(w, label, mode, filt, key)
        v.addLayout(lay)
        w.edits[key] = e
    hint = QLabel("Interior nodes CSV must include the subarea's ZONE "
                  "CENTROIDS (TAZ ids) as well as network nodes - the land use "
                  "file is used to verify centroid coverage. Subarea link/node "
                  "layers are clipped copies for the assignment step.", w)
    hint.setWordWrap(True)
    hint.setStyleSheet("color: gray;")
    v.addWidget(hint)
    run = QPushButton("Run Subarea Extraction", w)
    v.addWidget(run)
    v.addStretch(1)

    def go():
        need = ["aa_sub_nodes", "aa_trace_db", "aa_trips", "aa_sub_links", "aa_sub_out"]
        if any(not w.edits[k].text() for k in need):
            QMessageBox.warning(dlg, "Subarea",
                                "nodes csv, duckdb, trip list, link file and output are required.")
            return
        args = ["subarea",
                "--db", w.edits["aa_trace_db"].text(),
                "--nodes", w.edits["aa_sub_nodes"].text(),
                "--trips", w.edits["aa_trips"].text(),
                "--links", w.edits["aa_sub_links"].text(),
                "--out", w.edits["aa_sub_out"].text()]
        r = _run(args, "agentAnalysis_subarea.log")
        if r.returncode == 0:
            QMessageBox.information(dlg, "Subarea",
                                    "Subarea trip list written:\n%s" % w.edits["aa_sub_out"].text())
        else:
            QMessageBox.critical(dlg, "Subarea", "agentAnalysis subarea failed - see History log.")
    run.clicked.connect(go)
    return w


_LINK_RE = re.compile(r"(\d+)\s*[->]+\s*(\d+)")


def _tab_selectlink(dlg):
    w = QWidget()
    v = QVBoxLayout(w)
    db_lay, w.db = _browse_row(w, "agentPaths (duckdb)",
                               filt="DuckDB (*.duckdb);;All Files (*)", key="aa_trace_db")
    tl_lay, w.trips = _browse_row(w, "trip list (csv/gz, optional)",
                                  filt="Trip list (*.csv *.gz);;All Files (*)", key="aa_trips")
    v.addLayout(db_lay)
    v.addLayout(tl_lay)

    v.addWidget(QLabel("Links (one per line or comma-separated, as A-B node pairs, "
                       "e.g. 43618174-43618594):", w))
    w.links = QPlainTextEdit(w)
    w.links.setMaximumHeight(70)
    w.links.setPlaceholderText("a1-b1, a2-b2 ...")
    v.addWidget(w.links)

    pick_lay = QHBoxLayout()
    use_sel = QPushButton("Use selected links from map layer", w)
    pick_lay.addWidget(use_sel)
    grp = QGroupBox("Logic", w)
    gl = QHBoxLayout(grp)
    w.rb_or = QRadioButton("OR (any link)", grp)
    w.rb_and = QRadioButton("AND (all links)", grp)
    w.rb_or.setChecked(True)
    gl.addWidget(w.rb_or)
    gl.addWidget(w.rb_and)
    pick_lay.addWidget(grp)
    v.addLayout(pick_lay)

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
        if not (w.db.text() and pairs):
            QMessageBox.warning(dlg, "Select Link",
                                "agentPaths duckdb and at least one A-B link are required.")
            return
        args = ["agents", "--db", w.db.text()]
        for a, b in pairs:
            args += ["--link", a, b]
        args += ["--logic", "AND" if w.rb_and.isChecked() else "OR"]
        if w.trips.text():
            args += ["--trips", w.trips.text()]
        if w.out.text():
            args += ["--out", w.out.text()]
        if w.vols.text():
            args += ["--volumes", w.vols.text()]
        r = _run(args, "agentAnalysis_selectlink.log")
        if r.returncode == 0:
            QMessageBox.information(dlg, "Select Link",
                                    "Select-link outputs written (%d links, %s)." %
                                    (len(pairs), "AND" if w.rb_and.isChecked() else "OR"))
        else:
            QMessageBox.critical(dlg, "Select Link", "agentAnalysis agents failed - see History log.")
    run.clicked.connect(go)
    return w


def _tab_turns(dlg):
    w = QWidget()
    v = QVBoxLayout(w)
    db_lay, w.db = _browse_row(w, "agentPaths (duckdb)",
                               filt="DuckDB (*.duckdb);;All Files (*)", key="aa_trace_db")
    nd_lay, w.nodes = _browse_row(w, "node list (csv)",
                                  filt="CSV (*.csv);;All Files (*)", key="aa_turns_nodes")
    v.addLayout(db_lay)
    v.addLayout(nd_lay)

    opts = QHBoxLayout()
    w.cb_five = QCheckBox("5-node movements (FROM-1, FROM, THRU, TO, TO+1)", w)
    w.cb_hour = QCheckBox("by hour (period clock)", w)
    w.cb_hour.setChecked(True)
    opts.addWidget(w.cb_five)
    opts.addWidget(w.cb_hour)
    v.addLayout(opts)
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
        if not (w.db.text() and w.nodes.text() and w.out.text()):
            QMessageBox.warning(dlg, "Turning Movements",
                                "agentPaths duckdb, node list csv and output are required.")
            return
        args = ["turns", "--db", w.db.text(), "--nodes", w.nodes.text(),
                "--out", w.out.text()]
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
    tabs.addTab(_tab_trace(dlg), "Path Trace")
    tabs.addTab(_tab_subarea(dlg), "Subarea")
    tabs.addTab(_tab_selectlink(dlg), "Select Link")
    tabs.addTab(_tab_turns(dlg), "Turning Movements")

    grid = dlg.gridLayout
    row = grid.rowCount()
    grid.addWidget(tabs, row, 0, 1, 1)
    dlg.resize(dlg.width() + 140, dlg.height() + 420)
    return tabs
