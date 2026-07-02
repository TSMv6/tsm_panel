"""Shared user-action history logger for the TSM panel and its dialogs.

The panel registers its History box via set_message_box(). Every dialog the panel
opens is auto-instrumented by instrument_dialog(): field edits, checkbox/combo
changes, button clicks, and OK/Cancel are logged with the UI's name — and on OK a
full snapshot of the dialog's fields is recorded, so the user can go back and see
whether any key was left unset.

Lines are appended to the History box (if registered) and to
<scenarioDir>/tsm_panel_history.log so the trail persists across sessions.
"""
import os
from datetime import datetime

from .tsm_settings import Config

_box = None  # the panel's QPlainTextEdit, registered by the main panel


def set_message_box(box):
    """Register the panel's History text box so dialog actions show there live."""
    global _box
    _box = box


def _history_file():
    scen = Config().get("scenarioDir")
    return os.path.join(scen, "tsm_panel_history.log").replace("\\", "/") if scen else None


def _append(line):
    if _box is not None:
        try:
            _box.appendPlainText(line)
            sb = _box.verticalScrollBar()
            sb.setValue(sb.maximum())
        except Exception:
            pass
    hist = _history_file()
    if hist:
        try:
            with open(hist, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception as e:
            print(f"history write failed: {e}")


def log_action(text, ui=None):
    """Append a timestamped action line, optionally tagged with the UI name."""
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _append(f"[{stamp}] " + (f"[{ui}] " if ui else "") + text)


# ----------------------------------------------------------------------
# Auto-instrumentation
# ----------------------------------------------------------------------
_PREFIXES = ("lineEdit_", "comboBox_", "checkBox_", "radioButton_", "pushButton_",
             "browse_", "button_", "btn_", "okcancel_", "buttonBox_", "run_", "run")


def _field_name(widget):
    name = widget.objectName() or widget.__class__.__name__
    for p in _PREFIXES:
        if name.startswith(p) and len(name) > len(p):
            return name[len(p):]
    return name or "field"


def _log_snapshot(dialog, ui_name, action):
    """Record every input field's current value so empties are visible."""
    from qgis.PyQt.QtWidgets import QLineEdit, QComboBox, QCheckBox, QRadioButton
    log_action(f"{action} — fields:", ui_name)
    for w in dialog.findChildren(QLineEdit):
        _append(f"    • {_field_name(w)} = {w.text().strip() or '(empty)'}")
    for w in dialog.findChildren(QComboBox):
        _append(f"    • {_field_name(w)} = {w.currentText() or '(none)'}")
    for w in (dialog.findChildren(QCheckBox) + dialog.findChildren(QRadioButton)):
        _append(f"    • {_field_name(w)} = {'yes' if w.isChecked() else 'no'}")


def instrument_dialog(dialog, ui_name):
    """Connect a dialog's interactive widgets to the history log. Call once, AFTER
    the dialog is fully built/prefilled (so initial prefills are not logged).
    Idempotent per dialog instance."""
    if dialog is None or getattr(dialog, "_history_instrumented", False):
        return
    dialog._history_instrumented = True

    from qgis.PyQt.QtWidgets import (QLineEdit, QCheckBox, QRadioButton, QComboBox,
                                 QPushButton, QDialogButtonBox)

    def edit_logger(w, nm):
        def _fire():
            val = w.text()
            if getattr(w, "_hist_last", None) == val:
                return  # editingFinished fires on focus-out even with no change
            w._hist_last = val
            log_action(f"set {nm} = {val.strip() or '(empty)'}", ui_name)
        return _fire

    for w in dialog.findChildren(QLineEdit):
        w.editingFinished.connect(edit_logger(w, _field_name(w)))

    for w in dialog.findChildren(QCheckBox):
        nm = _field_name(w)
        w.toggled.connect(lambda checked=False, nm=nm:
                          log_action(f"{nm} = {'checked' if checked else 'unchecked'}", ui_name))

    for w in dialog.findChildren(QRadioButton):
        nm = _field_name(w)
        w.toggled.connect(lambda checked=False, nm=nm:
                          log_action(f"selected {nm}", ui_name) if checked else None)

    for w in dialog.findChildren(QComboBox):
        nm = _field_name(w)
        w.currentTextChanged.connect(lambda text="", nm=nm:
                                     log_action(f"{nm} = {text or '(none)'}", ui_name))

    for w in dialog.findChildren(QPushButton):
        if isinstance(w.parent(), QDialogButtonBox):
            continue  # OK/Cancel handled via the button box below
        nm = _field_name(w)
        w.clicked.connect(lambda checked=False, nm=nm: log_action(f"clicked {nm}", ui_name))

    for bb in dialog.findChildren(QDialogButtonBox):
        bb.accepted.connect(lambda dlg=dialog: _log_snapshot(dlg, ui_name, "OK / Save"))
        bb.rejected.connect(lambda: log_action("Cancel", ui_name))
