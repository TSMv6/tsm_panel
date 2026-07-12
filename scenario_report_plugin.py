# -*- coding: utf-8 -*-
"""Scenario Report dialog: one report card for the whole model chain.

Opens from the Analyst group's "Scenario Report" button. Wraps
Apps/Report/scenario_report.py (imported in-process) which reads a HyDRA run
directory (+ the scenario/demand directory for tripList / Syn_households /
tsm_landuse / Skimmy.log) and writes:

  scenario_report.html   self-contained, theme-aware report card
  scenario_report.md     diffable markdown twin
  scenario_metrics.csv   tidy long metrics table (the dashboards' contract)

Sections follow the model pipeline: PopSyn -> Skims -> SDT -> LDT -> trip-list
assembly -> network totals -> count validation -> tolling -> convergence.
First build on a new trip list takes ~2 min (77M-row chunked read); repeats
are instant (mtime-keyed caches beside the report).
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


def _load_builder():
    path = os.path.join(os.path.dirname(__file__), "Apps", "Report",
                        "scenario_report.py")
    spec = importlib.util.spec_from_file_location("tsm_scenario_report", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ScenarioReportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Scenario Report — Model Run Report Card")
        self.setMinimumWidth(640)
        root = QVBoxLayout(self)

        gb = QGroupBox("Inputs", self)
        gi = QGridLayout(gb)
        self.ed_run = self._dir_row(gi, 0, "HyDRA run directory",
                                    key="rep_run_dir")
        self.ed_dem = self._dir_row(gi, 1, "Scenario / demand dir (blank = run dir, then its parent)",
                                    key="rep_demand_dir")
        gi.addWidget(QLabel("Report title (blank = run name)", gb), 2, 0)
        self.ed_title = QLineEdit(gb)
        gi.addWidget(self.ed_title, 2, 1, 1, 2)
        gi.addWidget(QLabel("Min mainline count", gb), 3, 0)
        self.sp_min = QSpinBox(gb)
        self.sp_min.setRange(0, 100000); self.sp_min.setValue(5000)
        self.sp_min.setToolTip("Mainline/toll links with observed counts below "
                               "this are dropped from validation (canonical filter).")
        gi.addWidget(self.sp_min, 3, 1)
        self.ed_out = self._dir_row(gi, 4, "Output folder (blank = run dir)")
        root.addWidget(gb)

        self.cb_open = QCheckBox("Open the HTML report when done", self)
        self.cb_open.setChecked(True)
        root.addWidget(self.cb_open)

        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_run = QPushButton("Generate Report", self)
        self.btn_run.clicked.connect(self.run_build)
        btn_close = QPushButton("Close", self)
        btn_close.clicked.connect(self.reject)
        row.addWidget(self.btn_run); row.addWidget(btn_close)
        root.addLayout(row)
        self.log = QPlainTextEdit(self)
        self.log.setReadOnly(True); self.log.setMaximumHeight(110)
        root.addWidget(self.log)

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

    def run_build(self):
        run_dir = self.ed_run.text().strip()
        if not os.path.isdir(run_dir):
            QMessageBox.warning(self, "Scenario Report", "Pick the HyDRA run directory.")
            return
        self.btn_run.setEnabled(False)
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        try:
            builder = _load_builder()
            import builtins
            orig_print = builtins.print
            builtins.print = lambda *a, **k: self._say(" ".join(str(x) for x in a))
            try:
                self._say("[report] building… first run on a new trip list "
                          "takes ~2 min; repeats are instant (cached)")
                hpath = builder.build(
                    run_dir,
                    out_dir=self.ed_out.text().strip() or None,
                    title=self.ed_title.text().strip() or None,
                    min_mainline=self.sp_min.value(),
                    demand_dir=self.ed_dem.text().strip() or None)
            finally:
                builtins.print = orig_print
            self._say("[done]")
            if self.cb_open.isChecked() and hpath and os.path.exists(hpath):
                webbrowser.open("file:///" + hpath.replace("\\", "/"))
        except SystemExit as e:
            QMessageBox.critical(self, "Scenario Report", str(e))
        except Exception as e:
            QMessageBox.critical(self, "Scenario Report", f"Build failed:\n{e}")
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
            self.btn_run.setEnabled(True)
