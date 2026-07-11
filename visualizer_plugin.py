# -*- coding: utf-8 -*-
"""Visualizer dialog: multi-resolution GPKG layers from a HyDRA run.

Opens from the Analyst group's "Visualizations" button. Wraps
Apps/Visualizer/build_resolution_gpkg.py (imported in-process — QGIS's own
osgeo does the work, no subprocess) to build:

  meso_segments.gpkg  one feature per sub-link SEGMENT, time-period data as
                      COLUMNS (veh_<HHMM>, queued_<HHMM>, storage_veh)
  micro_lanes.gpkg    one feature per LANE x link, lane lines offset from the
                      corridor chain, columns speed_/density_/flow_<HHMM>

Time periods are attribute columns, never duplicated features: default =
AM peak + two PM peak hours (8,17,18) at 15-min resolution, or All hours
(hourly columns). Style any column; compare periods on the same feature.
"""
import importlib.util
import os

from qgis.PyQt import QtCore, QtWidgets
from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
                                 QGroupBox, QLabel, QLineEdit, QPushButton,
                                 QCheckBox, QRadioButton, QComboBox,
                                 QDoubleSpinBox, QFileDialog, QMessageBox,
                                 QPlainTextEdit)

from .tsm_settings import Config

BROWSE_W = 34


def _load_builder():
    """Import Apps/Visualizer/build_resolution_gpkg.py as a module."""
    path = os.path.join(os.path.dirname(__file__), "Apps", "Visualizer",
                        "build_resolution_gpkg.py")
    spec = importlib.util.spec_from_file_location("tsm_visualizer_builder", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class VisualizerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Visualizer — Multi-Resolution Layers (HyDRA)")
        self.setMinimumWidth(620)
        root = QVBoxLayout(self)

        # ---------------- inputs ----------------
        gb_in = QGroupBox("Inputs", self)
        gi = QGridLayout(gb_in)
        self.ed_run = self._dir_row(gi, 0, "HyDRA run directory",
                                    key="viz_run_dir")
        self.ed_links = self._file_row(gi, 1, "Link GPKG (A/B + geometry)",
                                       "GeoPackage (*.gpkg)", key="viz_link_gpkg")
        gi.addWidget(QLabel("Layer (blank = first)", gb_in), 2, 0)
        self.ed_layer = QLineEdit(gb_in)
        gi.addWidget(self.ed_layer, 2, 1, 1, 2)
        root.addWidget(gb_in)

        # ---------------- outputs ----------------
        gb_out = QGroupBox("Layers to build", self)
        go = QGridLayout(gb_out)
        self.cb_meso = QCheckBox("Meso segments (sub-link queue position)", gb_out)
        self.cb_meso.setChecked(True)
        self.cb_micro = QCheckBox("Micro lanes (per-lane offset lines)", gb_out)
        self.cb_micro.setChecked(True)
        self.cb_aerial = QCheckBox("Micro lanes AERIAL (true-width pavement "
                                   "ribbons + EL buffer)", gb_out)
        self.cb_aerial.setChecked(False)
        go.addWidget(self.cb_meso, 0, 0, 1, 2)
        go.addWidget(self.cb_micro, 1, 0, 1, 2)
        go.addWidget(self.cb_aerial, 2, 0, 1, 4)
        go.addWidget(QLabel("Lane width (ft)", gb_out), 1, 2)
        self.sp_lanew = QDoubleSpinBox(gb_out)
        self.sp_lanew.setRange(6.0, 30.0)
        self.sp_lanew.setValue(12.0)
        go.addWidget(self.sp_lanew, 1, 3)
        self.ed_out = self._dir_row(go, 3, "Output folder (blank = <run dir>\\visualizer)")
        root.addWidget(gb_out)

        # ---------------- time periods ----------------
        gb_t = QGroupBox("Time periods (attribute columns — features are never "
                         "duplicated per period)", self)
        gt = QGridLayout(gb_t)
        self.rb_peaks = QRadioButton("Peak hours:", gb_t)
        self.rb_peaks.setChecked(True)
        self.ed_hours = QLineEdit("8,17,18", gb_t)
        self.ed_hours.setToolTip("Comma-separated hours 0-23 (default: AM peak + two PM peak)")
        self.rb_all = QRadioButton("All hours (0-23)", gb_t)
        gt.addWidget(self.rb_peaks, 0, 0)
        gt.addWidget(self.ed_hours, 0, 1)
        gt.addWidget(self.rb_all, 0, 2)
        gt.addWidget(QLabel("Column resolution", gb_t), 1, 0)
        self.cmb_res = QComboBox(gb_t)
        self.cmb_res.addItem("15 min for chosen hours / hourly for All (auto)", None)
        self.cmb_res.addItem("15 minutes", 15)
        self.cmb_res.addItem("Hourly", 60)
        gt.addWidget(self.cmb_res, 1, 1, 1, 2)
        root.addWidget(gb_t)

        self.cb_load = QCheckBox("Add built layers to the map", self)
        self.cb_load.setChecked(True)
        root.addWidget(self.cb_load)

        # ---------------- run + log ----------------
        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_run = QPushButton("Build Layers", self)
        self.btn_run.clicked.connect(self.run_build)
        btn_close = QPushButton("Close", self)
        btn_close.clicked.connect(self.reject)
        row.addWidget(self.btn_run)
        row.addWidget(btn_close)
        root.addLayout(row)
        self.log = QPlainTextEdit(self)
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(120)
        root.addWidget(self.log)

    # ------------------------------------------------------------- helpers --
    def _file_row(self, grid, r, label, filt, key=None):
        grid.addWidget(QLabel(label, self), r, 0)
        edit = QLineEdit(self)
        if key:
            saved = Config().get(key)
            if saved:
                edit.setText(saved)
            edit.editingFinished.connect(lambda: Config().set(key, edit.text()))
        btn = QPushButton("...", self)
        btn.setFixedWidth(BROWSE_W)

        def pick():
            p, _ = QFileDialog.getOpenFileName(self, "Select File", "", filt)
            if p:
                edit.setText(p)
                if key:
                    Config().set(key, p)
        btn.clicked.connect(pick)
        grid.addWidget(edit, r, 1, 1, 2)
        grid.addWidget(btn, r, 3)
        return edit

    def _dir_row(self, grid, r, label, key=None):
        grid.addWidget(QLabel(label, self), r, 0)
        edit = QLineEdit(self)
        if key:
            saved = Config().get(key)
            if saved:
                edit.setText(saved)
            edit.editingFinished.connect(lambda: Config().set(key, edit.text()))
        btn = QPushButton("...", self)
        btn.setFixedWidth(BROWSE_W)

        def pick():
            p = QFileDialog.getExistingDirectory(self, "Select Directory")
            if p:
                edit.setText(p)
                if key:
                    Config().set(key, p)
        btn.clicked.connect(pick)
        grid.addWidget(edit, r, 1, 1, 2)
        grid.addWidget(btn, r, 3)
        return edit

    def _say(self, msg):
        self.log.appendPlainText(msg)
        QtWidgets.QApplication.processEvents()

    def _first_period_suffix(self):
        """HHMM suffix of the first built period (styles the ribbons on it)."""
        if self.rb_all.isChecked():
            return "0000"
        txt = (self.ed_hours.text().strip() or "8,17,18").split(",")[0].strip()
        try:
            return f"{int(txt):02d}00"
        except ValueError:
            return "0800"

    # ----------------------------------------------------------------- run --
    def run_build(self):
        run_dir = self.ed_run.text().strip()
        links = self.ed_links.text().strip()
        if not os.path.isdir(run_dir):
            QMessageBox.warning(self, "Visualizer", "Pick the HyDRA run directory.")
            return
        if not os.path.isfile(links):
            QMessageBox.warning(self, "Visualizer", "Pick the link GPKG.")
            return
        hours = "all" if self.rb_all.isChecked() else \
            (self.ed_hours.text().strip() or "8,17,18")
        out_dir = self.ed_out.text().strip() or os.path.join(run_dir, "visualizer")
        self.btn_run.setEnabled(False)
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        try:
            builder = _load_builder()
            # route the builder's print() lines into the dialog log
            import builtins
            orig_print = builtins.print
            builtins.print = lambda *a, **k: self._say(" ".join(str(x) for x in a))
            aerial_path = None
            try:
                res = builder.build(
                    links, run_dir,
                    layer=self.ed_layer.text().strip() or None,
                    out_dir=out_dir, hours=hours,
                    time_res=self.cmb_res.currentData(),
                    lane_width_ft=self.sp_lanew.value(),
                    do_meso=self.cb_meso.isChecked(),
                    do_micro=self.cb_micro.isChecked())
                if self.cb_aerial.isChecked():
                    import importlib.util as _u
                    _p = os.path.join(os.path.dirname(__file__), "Apps",
                                      "Visualizer", "micro_lane_aerial.py")
                    _s = _u.spec_from_file_location("tsm_micro_aerial", _p)
                    _m = _u.module_from_spec(_s); _s.loader.exec_module(_m)
                    aerial_path = _m.build(
                        links, run_dir, out_dir=out_dir,
                        layer=self.ed_layer.text().strip() or None, hours=hours,
                        time_res=self.cmb_res.currentData(),
                        lane_width_ft=self.sp_lanew.value())
            finally:
                builtins.print = orig_print
            if self.cb_load.isChecked():
                from qgis.core import QgsProject, QgsVectorLayer
                for name, path in (("Meso Segments", res.get("meso")),
                                   ("Micro Lanes", res.get("micro"))):
                    if path and os.path.exists(path):
                        lyr = QgsVectorLayer(path, name, "ogr")
                        if lyr.isValid():
                            QgsProject.instance().addMapLayer(lyr)
                            self._say(f"[map] added {name}")
                # aerial = 3 styled sublayers (ribbons / gores / markings)
                if aerial_path and os.path.exists(aerial_path):
                    try:
                        import importlib.util as _u
                        _p = os.path.join(os.path.dirname(__file__), "Apps",
                                          "Visualizer", "aerial_style.py")
                        _s = _u.spec_from_file_location("tsm_aerial_style", _p)
                        _m = _u.module_from_spec(_s); _s.loader.exec_module(_m)
                        suf = self._first_period_suffix()
                        for name, lyr in _m.apply_all(aerial_path, suf):
                            QgsProject.instance().addMapLayer(lyr)
                            self._say(f"[map] added {name}")
                    except Exception as se:
                        self._say(f"[style] aerial styling failed: {se}")
                        lyr = QgsVectorLayer(aerial_path, "Micro Lanes Aerial", "ogr")
                        if lyr.isValid():
                            QgsProject.instance().addMapLayer(lyr)
            self._say("[done]")
        except SystemExit as e:      # builder sys.exit messages
            QMessageBox.critical(self, "Visualizer", str(e))
        except Exception as e:
            QMessageBox.critical(self, "Visualizer", f"Build failed:\n{e}")
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
            self.btn_run.setEnabled(True)
