# -*- coding: utf-8 -*-
"""Programmatic QGIS styling for the micro lane AERIAL layers (blueprint phase 4).

The aerial builder (micro_lane_aerial.py) writes a GDAL-only GPKG with three
layers -- lane_ribbons (polygons), lane_markings (lines), gores (polygons).
This module, which runs inside QGIS where qgis.core is available, applies a
renderer to each so the layers load pre-symbolized, and drops a matching .qml
sidecar so the same style is reusable standalone (Layer > Properties > Load
Style, or auto-applied when the layer is added through the panel).

Why build renderers in code instead of shipping hand-written QML: the ribbon
value column is period-dependent (speed_0800, speed_1700, ...), so the graduated
classes must key off whichever period the user built; and hand-authored QML is
brittle. Building the renderer with the API guarantees valid XML, then
saveNamedStyle() serializes it to the .qml sidecar.

  apply_all(gpkg_path, period_suffix=None) -> [(name, QgsVectorLayer), ...]
    load each sublayer, style it, write <gpkg>_<sublayer>.qml, return the
    styled layers ready for QgsProject.addMapLayer.
"""
import os

from qgis.core import (QgsVectorLayer, QgsGraduatedSymbolRenderer,
                       QgsRendererRange, QgsFillSymbol, QgsLineSymbol,
                       QgsRendererCategory, QgsCategorizedSymbolRenderer,
                       QgsSingleSymbolRenderer)


# speed -> color, green (fast) to red (slow); 7 bands over 0..70 mph
_SPEED_BANDS = [
    (0, 10, "#a50026"), (10, 20, "#d73027"), (20, 30, "#f46d43"),
    (30, 40, "#fdae61"), (40, 50, "#a6d96a"), (50, 60, "#66bd63"),
    (60, 999, "#1a9850"),
]


def _first_speed_field(layer):
    for f in layer.fields().names():
        if f.startswith("speed_"):
            return f
    return None


def _ribbon_renderer(layer, period_suffix=None):
    fld = (f"speed_{period_suffix}" if period_suffix else None) \
        or _first_speed_field(layer)
    if not fld or fld not in layer.fields().names():
        # no speed column -> flat pavement fill
        sym = QgsFillSymbol.createSimple(
            {"color": "#c9ccce", "outline_color": "#ffffff",
             "outline_width": "0.2"})
        return QgsSingleSymbolRenderer(sym), None
    ranges = []
    for lo, hi, hexc in _SPEED_BANDS:
        sym = QgsFillSymbol.createSimple(
            {"color": hexc, "outline_color": "#ffffff", "outline_width": "0.2"})
        lbl = f"{lo}+ mph" if hi >= 999 else f"{lo}-{hi} mph"
        ranges.append(QgsRendererRange(lo, hi, sym, lbl))
    return QgsGraduatedSymbolRenderer(fld, ranges), fld


def _marking_renderer(layer):
    cats = []
    styles = {
        "dashed": ("#ffffff", "0.4", True),
        "edge":   ("#c8a000", "0.5", False),
        "buffer": ("#e34948", "0.9", False),
    }
    for kind, (col, w, dash) in styles.items():
        sym = QgsLineSymbol.createSimple({"line_color": col, "line_width": w})
        if dash:
            sym.symbolLayer(0).setPenStyle(2)  # Qt.DashLine
        cats.append(QgsRendererCategory(kind, sym, kind))
    return QgsCategorizedSymbolRenderer("kind", cats)


def _gore_renderer(layer):
    sym = QgsFillSymbol.createSimple(
        {"color": "#f2e6c2", "outline_color": "#d0b048", "outline_width": "0.3",
         "style": "b_diagonal"})   # hatched nose
    return QgsSingleSymbolRenderer(sym)


def apply_all(gpkg_path, period_suffix=None):
    out = []
    specs = [("lane_ribbons", "Aerial — Lane Ribbons", _ribbon_renderer),
             ("gores", "Aerial — Gores", None),
             ("lane_markings", "Aerial — Markings", None)]
    for sub, name, _ in specs:
        uri = f"{gpkg_path}|layername={sub}"
        lyr = QgsVectorLayer(uri, name, "ogr")
        if not lyr.isValid():
            continue
        if sub == "lane_ribbons":
            rnd, _fld = _ribbon_renderer(lyr, period_suffix)
        elif sub == "lane_markings":
            rnd = _marking_renderer(lyr)
        else:
            rnd = _gore_renderer(lyr)
        lyr.setRenderer(rnd)
        lyr.triggerRepaint()
        qml = f"{os.path.splitext(gpkg_path)[0]}_{sub}.qml"
        try:
            lyr.saveNamedStyle(qml)
        except Exception:
            pass
        out.append((name, lyr))
    # draw order: ribbons under gores under markings (markings on top)
    return out
