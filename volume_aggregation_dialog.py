"""Volume Aggregation dialog (opened from the LoadedNetwork summarization dialog).

Aggregates the HyDRA link_performance volumes to clock hours, 15-minute
intervals (columns named HH:MM) or up to five user-defined periods, optionally
node-balanced so every node's inflow equals its outflow in each bin. Runs
summarize.exe in volagg mode (templates/summarize_volagg.toml).

The inputs (link layer, macro / meso / micro link_performance CSVs, subarea
flag) come from the parent LoadedNetwork dialog. HyDRA simulates 30 hours;
the 24:00-29:59 spillover is folded onto 00:00-05:59, so periods are defined
on an ordinary 24-hour clock.
"""
import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog,
                                 QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                                 QMessageBox, QPushButton, QRadioButton, QVBoxLayout)

from . import tsm_history
from .tsm_settings import Config

PERIOD_NAMES = ["AM", "MD", "PM", "EV", "OV", "EA"]
MAX_PERIODS = 5
SLOTS = 96                                   # 15-min slots per day
DEFAULT_PERIODS = [(True, "AM", "06:00", "09:00"), (True, "MD", "09:00", "15:00"),
                   (True, "PM", "15:00", "19:00"), (True, "OV", "19:00", "06:00"),
                   (False, "EV", "19:00", "23:00")]


def _hhmm(slot):
    return "%02d:%02d" % (slot // 4, (slot % 4) * 15)


def _slot(t):
    h, m = t.split(":")
    return int(h) * 4 + int(m) // 15


def _clock(t):
    """06:00 -> 6 AM, 24:00 -> 12 AM (midnight), 12:30 -> 12:30 PM."""
    s = _slot(t) % SLOTS
    h, m = s // 4, (s % 4) * 15
    ap = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return ("%d %s" % (h12, ap)) if m == 0 else ("%d:%02d %s" % (h12, m, ap))


def check_periods(rows):
    """rows = [(name, start, end)]. Returns (ok, message). Mirrors the checks
    in summarize.exe: unique names, 15-min grid, no overlap, full 24 h."""
    if not rows:
        return False, "Define at least one period."
    names = [r[0] for r in rows]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        return False, "Period name used twice: %s" % ", ".join(dup)
    owner = [None] * SLOTS
    for name, a, b in rows:
        s0, s1 = _slot(a), _slot(b)
        n = s1 - s0 if s1 > s0 else s1 + SLOTS - s0      # end <= start wraps midnight
        for i in range(n):
            s = (s0 + i) % SLOTS
            if owner[s] is not None:
                return False, "%s and %s overlap at %s" % (owner[s], name, _hhmm(s))
            owner[s] = name
    runs, s = [], 0
    while s < SLOTS:
        if owner[s] is None:
            e = s
            while e + 1 < SLOTS and owner[e + 1] is None:
                e += 1
            runs.append("%s-%s" % (_hhmm(s), _hhmm(e + 1)))
            s = e + 1
        else:
            s += 1
    if runs:
        return False, "Not covered: %s (periods must cover all 24 hours)" % ", ".join(runs)
    return True, "OK: %d period%s cover%s all 24 hours." % (len(rows), "" if len(rows) == 1 else "s",
                                                           "s" if len(rows) == 1 else "")


class VolumeAggregationDialog(QDialog):
    def __init__(self, parent_dialog):
        super().__init__(parent_dialog)
        self.pd = parent_dialog
        self.setWindowTitle("Volume Aggregation")
        self.resize(640, 0)
        lay = QVBoxLayout(self)

        # ---- inputs (read from the LoadedNetwork dialog) ---------------------
        self.lbl_inputs = QLabel()
        self.lbl_inputs.setWordWrap(True)
        lay.addWidget(self.lbl_inputs)

        self.chk_balance = QCheckBox("Balance volumes (upstream = downstream: inflow equals outflow at every node, in each time bin)")
        self.chk_balance.setChecked(True)
        self.chk_balance.setToolTip(
            "On: node-balanced volumes (smallest volume-proportional adjustment).\n"
            "Off: the model's raw link volumes (discharge counts; upstream and\n"
            "downstream sums differ by vehicles stored on the links).")
        lay.addWidget(self.chk_balance)

        # ---- resolution -----------------------------------------------------------
        gb = QGroupBox("Report volumes as")
        g = QVBoxLayout(gb)
        self.rb_hour = QRadioButton("Hourly volumes (VOL_00 ... VOL_23)")
        self.rb_15 = QRadioButton("15-minute volumes (columns 00:00, 00:15, ... 23:45)")
        self.rb_per = QRadioButton("Period volumes (up to 5 user-defined periods)")
        self.rb_group = QButtonGroup(self)
        for rb in (self.rb_hour, self.rb_15, self.rb_per):
            self.rb_group.addButton(rb)
            g.addWidget(rb)
        self.rb_hour.setChecked(True)

        # period table
        self.per_box = QGroupBox("Periods (15-minute steps; an End of 00:00 is midnight; an end at or before the start runs past midnight)")
        pg = QGridLayout(self.per_box)
        for c, h in enumerate(["Use", "Period", "Start", "End", ""]):
            pg.addWidget(QLabel("<b>%s</b>" % h), 0, c)
        # One 24-hour clock for both ends: an End of 00:00 is midnight (the
        # end <= start rule makes 19:00-00:00 = 5 h and 00:00-00:00 = 24 h).
        starts = [_hhmm(s) for s in range(SLOTS)]                # 00:00 .. 23:45
        ends = starts
        self.rows = []
        for i in range(MAX_PERIODS):
            use = QCheckBox()
            name = QComboBox(); name.addItems(PERIOD_NAMES)
            st = QComboBox(); st.addItems(starts); st.setMaxVisibleItems(16)
            en = QComboBox(); en.addItems(ends); en.setMaxVisibleItems(16)
            span = QLabel()
            for c, w in enumerate((use, name, st, en, span)):
                pg.addWidget(w, i + 1, c)
            self.rows.append((use, name, st, en, span))
            use.toggled.connect(self._refresh)
            for w in (name, st, en):
                w.currentIndexChanged.connect(self._refresh)
        self.lbl_status = QLabel()
        self.lbl_status.setWordWrap(True)
        pg.addWidget(self.lbl_status, MAX_PERIODS + 1, 0, 1, 5)
        note = QLabel("HyDRA simulates 30 hours. Traffic between 24:00 and 29:59 (midnight to 6 AM the "
                      "next morning) is added to 00:00-05:59, so define periods on a normal 24-hour clock.")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray;")
        pg.addWidget(note, MAX_PERIODS + 2, 0, 1, 5)
        g.addWidget(self.per_box)
        lay.addWidget(gb)
        for rb in (self.rb_hour, self.rb_15, self.rb_per):
            rb.toggled.connect(self._refresh)

        # ---- output -----------------------------------------------------------------
        h = QHBoxLayout()
        h.addWidget(QLabel("Output (gpkg)"))
        self.le_out = QLineEdit()
        h.addWidget(self.le_out)
        b = QPushButton("...")
        b.clicked.connect(self._browse)
        h.addWidget(b)
        lay.addLayout(h)
        self.chk_log = QCheckBox("Also write the raw -> balanced adjustment log (<output>_balance.csv; large)")
        lay.addWidget(self.chk_log)

        h = QHBoxLayout()
        b_save = QPushButton("Save")
        b_save.setToolTip("Save this dialog (balance, resolution, periods, output) to the TSM scenario settings.")
        b_save.clicked.connect(self.save_settings)
        b_saveas = QPushButton("Save As...")
        b_saveas.setToolTip("Write just the period definitions to a JSON file.")
        b_saveas.clicked.connect(self.save_periods_as)
        b_load = QPushButton("Load...")
        b_load.setToolTip("Read period definitions from a JSON file written by Save As.")
        b_load.clicked.connect(self.load_periods)
        for w in (b_save, b_saveas, b_load):
            h.addWidget(w)
        self.btn_run = QPushButton("Run")
        self.btn_run.clicked.connect(self.run)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        h.addStretch(1)
        h.addWidget(self.btn_run)
        h.addWidget(close)
        lay.addLayout(h)

        self.chk_balance.toggled.connect(self._refresh)
        self._load()
        self._refresh()

    # ---- settings ------------------------------------------------------------------
    def _load(self):
        s = Config()
        if s.get("volagg_balance") is not None:
            self.chk_balance.setChecked(bool(s.get("volagg_balance")))
        self.chk_log.setChecked(bool(s.get("volagg_log")))
        {"15min": self.rb_15, "period": self.rb_per}.get(s.get("volagg_res"), self.rb_hour).setChecked(True)
        self._apply_periods(s.get("volagg_periods") or DEFAULT_PERIODS)
        out = s.get("volagg_out")
        if not out:
            base = self.pd.lineEdit_loadedOut.text().strip()
            out = os.path.join(os.path.dirname(base), "volume_aggregation.gpkg").replace("\\", "/") if base else ""
        self.le_out.setText(out)

    def _save(self):
        s = Config()
        s.set("volagg_balance", self.chk_balance.isChecked())
        s.set("volagg_log", self.chk_log.isChecked())
        s.set("volagg_res", self._res())
        s.set("volagg_periods", [[u.isChecked(), n.currentText(), a.currentText(), e.currentText()]
                                 for u, n, a, e, _ in self.rows])
        s.set("volagg_out", self.le_out.text().strip())

    def save_settings(self):
        """Save -> TSM GUI (scenario) settings, like the LoadedNetwork Save."""
        self._save()
        Config().check_and_save_to_file("scenario_settings_file")
        QMessageBox.information(self, "Volume Aggregation", "Settings saved to the TSM scenario settings.")

    def _apply_periods(self, per):
        for i, (use, name, st, en, _) in enumerate(self.rows):
            u, n, a, e = per[i] if i < len(per) else (False, PERIOD_NAMES[i % len(PERIOD_NAMES)], "00:00", "00:00")
            if e == "24:00":          # older settings / files: midnight was written 24:00
                e = "00:00"
            use.setChecked(bool(u))
            name.setCurrentText(n)
            st.setCurrentText(a)
            en.setCurrentText(e)
        self._refresh()

    def save_periods_as(self):
        """Save As -> just the period definitions, to a JSON file."""
        import json
        p, _ = QFileDialog.getSaveFileName(self, "Save period definitions", "", "JSON Files (*.json)")
        if not p:
            return
        if not p.lower().endswith(".json"):
            p += ".json"
        data = {"periods": [{"use": u.isChecked(), "name": n.currentText(),
                             "start": a.currentText(), "end": e.currentText()}
                            for u, n, a, e, _ in self.rows]}
        try:
            with open(p, "w") as f:
                json.dump(data, f, indent=2)
        except OSError as ex:
            QMessageBox.critical(self, "Volume Aggregation", "Could not write %s:\n%s" % (p, ex))
            return
        QMessageBox.information(self, "Volume Aggregation", "Period definitions saved to:\n%s" % p)

    def load_periods(self):
        """Load period definitions written by Save As (and switch to Periods)."""
        import json
        p, _ = QFileDialog.getOpenFileName(self, "Load period definitions", "", "JSON Files (*.json)")
        if not p:
            return
        starts = {_hhmm(s) for s in range(SLOTS)}
        ends = starts | {"24:00"}            # 24:00 accepted from older files, shown as 00:00
        try:
            with open(p) as f:
                rows = json.load(f)["periods"]
            per = []
            for r in rows[:MAX_PERIODS]:
                u, n, a, e = bool(r.get("use", True)), str(r["name"]), str(r["start"]), str(r["end"])
                if n not in PERIOD_NAMES or a not in starts or e not in ends:
                    raise ValueError("bad period %s %s-%s (names %s; times HH:MM on 15-min steps)"
                                     % (n, a, e, "/".join(PERIOD_NAMES)))
                per.append((u, n, a, e))
            if len(rows) > MAX_PERIODS:
                raise ValueError("%d periods in the file; at most %d are allowed" % (len(rows), MAX_PERIODS))
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as ex:
            QMessageBox.critical(self, "Volume Aggregation", "Not a period definition file:\n%s\n\n%s" % (p, ex))
            return
        self._apply_periods(per)
        self.rb_per.setChecked(True)
        ok, msg = check_periods(self._periods())
        (QMessageBox.information if ok else QMessageBox.warning)(
            self, "Volume Aggregation", "Loaded %d period rows from %s\n\n%s" % (len(per), os.path.basename(p), msg))

    # ---- ui logic -------------------------------------------------------------------
    def _res(self):
        return "15min" if self.rb_15.isChecked() else "period" if self.rb_per.isChecked() else "hour"

    def _periods(self):
        return [(n.currentText(), a.currentText(), e.currentText())
                for u, n, a, e, _ in self.rows if u.isChecked()]

    def _refresh(self, *_):
        per = self.rb_per.isChecked()
        self.per_box.setEnabled(per)
        for use, name, st, en, span in self.rows:
            on = use.isChecked()
            for w in (name, st, en):
                w.setEnabled(on)
            if on:
                a, e = st.currentText(), en.currentText()
                n = (_slot(e) - _slot(a)) % SLOTS or SLOTS
                span.setText("%s - %s  (%g h)" % (_clock(a), _clock(e), n / 4.0))
            else:
                span.setText("")
        ok, msg = check_periods(self._periods()) if per else (True, "")
        self.lbl_status.setText(msg)
        self.lbl_status.setStyleSheet("color: %s;" % ("darkgreen" if ok else "firebrick"))
        self.btn_run.setEnabled(ok)
        self.chk_log.setEnabled(self.chk_balance.isChecked())
        macro = self.pd.lineEdit_volume.text().strip()
        meso = self.pd.lineEdit_volumeMeso.text().strip()
        micro = self.pd.lineEdit_volumeMicro.text().strip()
        lyr = self.pd.comboBox_linkLayer.currentData()
        self.lbl_inputs.setText(
            "<b>Inputs</b> (from the LoadedNetwork dialog)<br>link layer: %s%s<br>macro: %s<br>meso: %s<br>micro: %s"
            % (lyr.name() if lyr else "<i>none selected</i>",
               " (subarea)" if self.pd.checkBox_isSubarea.isChecked() else "",
               os.path.basename(macro) or "<i>none</i>", os.path.basename(meso) or "-",
               os.path.basename(micro) or "-"))

    def _browse(self):
        p, _ = QFileDialog.getSaveFileName(self, "Output GeoPackage", self.le_out.text(), "GeoPackage (*.gpkg)")
        if p:
            if not p.lower().endswith(".gpkg"):
                p += ".gpkg"
            self.le_out.setText(p)

    # ---- run ----------------------------------------------------------------------------
    def run(self):
        self._save()
        lyr = self.pd.comboBox_linkLayer.currentData()
        macro = self.pd.lineEdit_volume.text().strip()
        meso = self.pd.lineEdit_volumeMeso.text().strip()
        micro = self.pd.lineEdit_volumeMicro.text().strip()
        out = self.le_out.text().strip()
        if not lyr:
            QMessageBox.warning(self, "Volume Aggregation", "Select a link layer in the LoadedNetwork dialog.")
            return
        if not macro or "link_performance" not in os.path.basename(macro).lower():
            QMessageBox.warning(self, "Volume Aggregation",
                                "Set the macroDTA link performance CSV (link_performance_macroDTA.csv) "
                                "in the LoadedNetwork dialog.")
            return
        if not out:
            QMessageBox.warning(self, "Volume Aggregation", "Choose an output GeoPackage.")
            return
        if not out.lower().endswith(".gpkg"):
            out += ".gpkg"
            self.le_out.setText(out)
        link_path = self.pd.get_layer_path(lyr)
        res = self._res()
        bal = self.chk_balance.isChecked()
        layer_name = "VolAgg_%s_%s" % ({"hour": "hourly", "15min": "15min", "period": "periods"}[res],
                                       "balanced" if bal else "raw")
        self.pd._remove_layers_by_path(out)
        tsm_history.log_action("Volume aggregation: %s, %s -> %s"
                               % (res, "balanced" if bal else "raw", out), "Summarization")
        try:
            from .summarize_runner import run_volagg
            r = run_volagg(link_path, macro, out, bool(self.pd.checkBox_isSubarea.isChecked()), res,
                           periods=self._periods() if res == "period" else None,
                           balance=bal, log_csv=bal and self.chk_log.isChecked(),
                           vol2=meso or None, vol3=micro or None, layer=layer_name)
        except Exception as e:
            QMessageBox.critical(self, "Volume Aggregation", "summarize.exe failed to start:\n%s" % e)
            return
        log = os.path.splitext(out)[0] + "_volagg_run.log"
        if r.returncode != 0:
            QMessageBox.critical(self, "Volume Aggregation",
                                 "summarize.exe failed (exit %s). See the log:\n%s" % (r.returncode, log))
            return
        self.pd.load_output_layer(out, layer_name)
        # same styling as the LoadedNetwork run (renders on FNAME, which the
        # aggregation layer carries over from the link layer)
        qml = os.path.join(Config().get("plugin_dir"), "qgis_styles/TSM_Loaded_Symbology.qml").replace("\\", "/")
        try:
            self.pd.load_layer_symbology(qml, layer_name)
        except IndexError:   # layer did not load (load_output_layer printed why)
            pass
        QMessageBox.information(self, "Volume Aggregation",
                                "Wrote %s and %s\n(layer '%s'; run log %s)"
                                % (out, os.path.splitext(out)[0] + ".csv", layer_name, os.path.basename(log)))
