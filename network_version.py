# -*- coding: utf-8 -*-
"""GeoMaster network version dropdown, shared by Project Settings and the Link
Consolidator.

The dropdown shows the Navteq release a network is built from; each entry
carries the TSM version as its value, and that value is what the code branches
on, what the settings JSON stores ("network_version") and what netPrep's
control file gets -- so relabelling never changes a saved scenario.
"""

# (label shown, value stored)
NETWORK_VERSIONS = (("Navteq24", "TSMv6"), ("Navteq11", "TSMv5"))


def fill_versions(combo):
    """Replace the combo's items with the labelled versions."""
    combo.blockSignals(True)
    combo.clear()
    for label, value in NETWORK_VERSIONS:
        combo.addItem(label, value)
    combo.blockSignals(False)


def set_version(combo, value):
    """Select by stored value ("TSMv6"); a label ("Navteq24") also matches."""
    value = (value or "").strip()
    i = combo.findData(value)
    if i < 0:
        i = combo.findText(value)
    if i >= 0:
        combo.setCurrentIndex(i)


def version(combo):
    """Stored value of the selected entry ("TSMv6" / "TSMv5")."""
    return combo.currentData() or combo.currentText()
