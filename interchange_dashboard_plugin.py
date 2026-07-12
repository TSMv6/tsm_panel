# -*- coding: utf-8 -*-
"""Interchange Volumes dialog: the limited-access dashboard, one click.

Opens from the Analyst group's "Interchange Volumes" button. Orchestrates the
four Apps/Dashboard steps (imported in-process — QGIS's own osgeo/pandas do the
work) over a HyDRA run:

  interchange_build      group the network into interchanges (interchanges.gpkg)
  interchange_volumes    per-interchange mainline/ramp/cross volumes -> .xlsx
  interchange_turns      ramp-terminal turning movements (agentAnalysis turns)
  interchange_dashboard  the self-contained interactive HTML dashboard

Then it loads the interchange point layer into the map and opens the dashboard
in the browser. The interchange grouping only needs the link/node network, so
it is cached (built once) unless "rebuild interchanges" is ticked. The turns
step shells out to agentAnalysis and can take a minute for many interchanges.
"""
import importlib.util
import os
import webbrowser

from qgis.PyQt import QtCore, QtWidgets
from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
                                 QGroupBox, QLabel, QLineEdit, QPushButton,
                                 QCheckBox, QSpinBox, QFileDialog, QMessageBox,
                                 QPlainTextEdit)

from .tsm_settings import Config

BROWSE_W = 34


def _load(name, fname):
    p = os.path.join(os.path.dirname(__file__), "Apps", "Dashboard", fname)
    s = importlib.util.spec_from_file_location(name, p)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


class InterchangeDashboardDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Interchange Volumes — Limited-Access Dashboard")
        self.setMinimumWidth(660)
        root = QVBoxLayout(self)

        gb = QGroupBox("Inputs", self)
        gi = QGridLayout(gb)
        self.ed_run = self._dir_row(gi, 0, "HyDRA run directory", key="ixd_run")
        self.ed_link = self._file_row(gi, 1, "Link GPKG (A/B + FTYPE + ST_NAME)",
                                      "GeoPackage (*.gpkg)", key="ixd_link")
        self.ed_node = self._file_row(gi, 2, "Node GPKG (N/X/Y)",
                                      "GeoPackage (*.gpkg)", key="ixd_node")
        self.ed_exe = self._file_row(gi, 3, "agentAnalysis.exe (blank = auto)",
                                     "Executable (*.exe)", key="ixd_exe")
        root.addWidget(gb)

        gb2 = QGroupBox("Steps to run", self)
        g2 = QGridLayout(gb2)
        self.cb_build = QCheckBox("Rebuild interchange grouping "
                                  "(else reuse interchanges.gpkg)", gb2)
        self.cb_vol = QCheckBox("Volume workbook (.xlsx)", gb2)
        self.cb_vol.setChecked(True)
        self.cb_turn = QCheckBox("Turning movements (agentAnalysis turns)", gb2)
        self.cb_turn.setChecked(True)
        self.cb_dash = QCheckBox("Interactive HTML dashboard", gb2)
        self.cb_dash.setChecked(True)
        g2.addWidget(self.cb_build, 0, 0, 1, 2)
        g2.addWidget(self.cb_vol, 1, 0)
        g2.addWidget(self.cb_turn, 1, 1)
        g2.addWidget(self.cb_dash, 2, 0)
        g2.addWidget(QLabel("Interchange radius (m)", gb2), 3, 0)
        self.sp_rad = QSpinBox(gb2); self.sp_rad.setRange(200, 3000)
        self.sp_rad.setValue(800); g2.addWidget(self.sp_rad, 3, 1)
        g2.addWidget(QLabel("Detail interchanges (top-N by AADT)", gb2), 4, 0)
        self.sp_det = QSpinBox(gb2); self.sp_det.setRange(5, 500)
        self.sp_det.setValue(80); g2.addWidget(self.sp_det, 4, 1)
        g2.addWidget(QLabel("County filter (blank = all)", gb2), 5, 0)
        self.ed_cty = QLineEdit(gb2); g2.addWidget(self.ed_cty, 5, 1)
        g2.addWidget(QLabel("Route filter (e.g. I-95)", gb2), 6, 0)
        self.ed_rt = QLineEdit(gb2); g2.addWidget(self.ed_rt, 6, 1)
        root.addWidget(gb2)

        self.cb_add = QCheckBox("Add interchange layer to the map", self)
        self.cb_add.setChecked(True)
        self.cb_open = QCheckBox("Open the dashboard when done", self)
        self.cb_open.setChecked(True)
        root.addWidget(self.cb_add); root.addWidget(self.cb_open)

        row = QHBoxLayout(); row.addStretch(1)
        self.btn_run = QPushButton("Build Dashboard", self)
        self.btn_run.clicked.connect(self.run_build)
        btn_close = QPushButton("Close", self); btn_close.clicked.connect(self.reject)
        row.addWidget(self.btn_run); row.addWidget(btn_close)
        root.addLayout(row)
        self.log = QPlainTextEdit(self); self.log.setReadOnly(True)
        self.log.setMaximumHeight(130); root.addWidget(self.log)

    # -------- helpers --------
    def _file_row(self, grid, r, label, filt, key=None):
        grid.addWidget(QLabel(label, self), r, 0)
        edit = QLineEdit(self)
        if key:
            s = Config().get(key)
            if s:
                edit.setText(s)
            edit.editingFinished.connect(lambda: Config().set(key, edit.text()))
        btn = QPushButton("...", self); btn.setFixedWidth(BROWSE_W)

        def pick():
            p, _ = QFileDialog.getOpenFileName(self, "Select File", "", filt)
            if p:
                edit.setText(p)
                if key:
                    Config().set(key, p)
        btn.clicked.connect(pick)
        grid.addWidget(edit, r, 1, 1, 2); grid.addWidget(btn, r, 3)
        return edit

    def _dir_row(self, grid, r, label, key=None):
        grid.addWidget(QLabel(label, self), r, 0)
        edit = QLineEdit(self)
        if key:
            s = Config().get(key)
            if s:
                edit.setText(s)
            edit.editingFinished.connect(lambda: Config().set(key, edit.text()))
        btn = QPushButton("...", self); btn.setFixedWidth(BROWSE_W)

        def pick():
            p = QFileDialog.getExistingDirectory(self, "Select Directory")
            if p:
                edit.setText(p)
                if key:
                    Config().set(key, p)
        btn.clicked.connect(pick)
        grid.addWidget(edit, r, 1, 1, 2); grid.addWidget(btn, r, 3)
        return edit

    def _say(self, m):
        self.log.appendPlainText(m)
        QtWidgets.QApplication.processEvents()

    # -------- run --------
    def run_build(self):
        run = self.ed_run.text().strip()
        link = self.ed_link.text().strip()
        node = self.ed_node.text().strip()
        if not os.path.isdir(run):
            QMessageBox.warning(self, "Interchange Volumes", "Pick the run directory."); return
        if not os.path.isfile(link) or not os.path.isfile(node):
            QMessageBox.warning(self, "Interchange Volumes", "Pick the link and node GPKGs."); return
        gpkg = os.path.join(run, "interchanges.gpkg")
        cty = self.ed_cty.text().strip() or None
        rt = self.ed_rt.text().strip() or None
        exe = self.ed_exe.text().strip() or None
        self.btn_run.setEnabled(False)
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        import builtins
        orig = builtins.print
        builtins.print = lambda *a, **k: self._say(" ".join(str(x) for x in a))
        dash_html = None
        try:
            if self.cb_build.isChecked() or not os.path.exists(gpkg):
                self._say("[1/4] grouping interchanges…")
                _load("ixb", "interchange_build.py").build(
                    link, node, gpkg, float(self.sp_rad.value()))
            else:
                self._say("[1/4] reusing existing interchanges.gpkg")
            if self.cb_vol.isChecked():
                self._say("[2/4] aggregating volumes → workbook…")
                _load("ixv", "interchange_volumes.py").build(
                    run, gpkg, None, self.sp_det.value(), cty, rt)
            if self.cb_turn.isChecked():
                self._say("[3/4] turning movements (agentAnalysis)… may take a minute")
                _load("ixt", "interchange_turns.py").build(
                    run, gpkg, node, exe, None, self.sp_det.value(), cty, rt)
            if self.cb_dash.isChecked():
                self._say("[4/4] building HTML dashboard…")
                dash_html = _load("ixd", "interchange_dashboard.py").build(
                    run, gpkg, node, None, None, self.sp_det.value())
        except SystemExit as e:
            builtins.print = orig
            QtWidgets.QApplication.restoreOverrideCursor(); self.btn_run.setEnabled(True)
            QMessageBox.critical(self, "Interchange Volumes", str(e)); return
        except Exception as e:
            builtins.print = orig
            QtWidgets.QApplication.restoreOverrideCursor(); self.btn_run.setEnabled(True)
            QMessageBox.critical(self, "Interchange Volumes", f"Build failed:\n{e}"); return
        finally:
            builtins.print = orig
        # add the interchange point layer, sized by ramp count
        if self.cb_add.isChecked() and os.path.exists(gpkg):
            try:
                self._add_layer(gpkg)
            except Exception as e:
                self._say(f"[map] add layer failed: {e}")
        if self.cb_open.isChecked() and dash_html and os.path.exists(dash_html):
            self._say(f"[dashboard] {dash_html}")
            webbrowser.open("file:///" + dash_html.replace("\\", "/"))
        self._say("[done]")
        QtWidgets.QApplication.restoreOverrideCursor()
        self.btn_run.setEnabled(True)

    def _add_layer(self, gpkg):
        from qgis.core import (QgsProject, QgsVectorLayer,
                               QgsGraduatedSymbolRenderer, QgsRendererRange,
                               QgsMarkerSymbol)
        lyr = QgsVectorLayer(f"{gpkg}|layername=interchanges", "Interchanges", "ogr")
        if not lyr.isValid():
            return
        ranges = []
        for lo, hi, size, col in [(0, 8, 2.0, "#7aa8e0"), (8, 16, 3.2, "#3987e5"),
                                  (16, 28, 4.6, "#1f5fb0"), (28, 999, 6.5, "#123a70")]:
            sym = QgsMarkerSymbol.createSimple(
                {"name": "circle", "color": col, "size": str(size),
                 "outline_color": "white", "outline_width": "0.2"})
            ranges.append(QgsRendererRange(lo, hi, sym, f"{lo}–{hi if hi<999 else ''} ramps"))
        lyr.setRenderer(QgsGraduatedSymbolRenderer("n_ramps", ranges))
        QgsProject.instance().addMapLayer(lyr)
        self._say("[map] added Interchanges (graduated by ramp count)")
