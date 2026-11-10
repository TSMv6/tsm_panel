"""QGIS API differences across the versions tsm_panel supports.

QgsField's type argument is a QVariant.Type up to QGIS 3.36 and a
QMetaType.Type from 3.38 (QGIS 4 / Qt6 has no QVariant.Int at all), so no
single spelling works everywhere. make_field() picks the one this QGIS takes.
"""
from qgis.core import QgsField

_KINDS = ("int", "double", "string")


def make_field(name, kind):
    """QgsField of kind 'int' | 'double' | 'string' on QGIS 3.28-3.36, 3.38+ and 4.x."""
    if kind not in _KINDS:
        raise ValueError(f"make_field: unknown kind {kind!r}")
    try:
        from qgis.PyQt.QtCore import QMetaType
        t = {"int": QMetaType.Type.Int, "double": QMetaType.Type.Double,
             "string": QMetaType.Type.QString}[kind]
        return QgsField(name, t)
    except (ImportError, AttributeError, TypeError):  # QGIS < 3.38: QVariant.Type
        from qgis.PyQt.QtCore import QVariant
        t = {"int": QVariant.Int, "double": QVariant.Double,
             "string": QVariant.String}[kind]
        return QgsField(name, t)
