"""GMNS package tools for the HyDRA dialog.

netPrep writes gmns_network.gpkg (gmns_network_msr.gpkg for an MSR network):
node, link, lane, segment, segment_lane and movement layers plus the GMNS
signal tables (signal_controller, signal_timing_plan, signal_timing_phase,
signal_phase_mvmt), all keyed to the consolidated HyDRA links by from/to node.
This module puts them in front of the user:

- load_layers()       styled layers in a "GMNS" group, with relations so the
                      attribute forms show link -> lanes / pockets, node ->
                      movements, plan -> phases -> movements;
- ValidateDialog      checks (timing plans fit the cycle, every signal
                      movement is in a phase, lane ranges, pockets) and fills
                      in missing pocket geometry;
- SignalTimingDialog  the timing plans of one controller (a node, or the two
                      to four nodes of a divided road's intersection): time
                      of day, cycle, phases, movement-to-phase assignment,
                      ring-barrier diagram;
- import_timing() / export_timing()  timing packs (three CSVs keyed by node,
                      from node and to node) between packages;
- export_csv()        gmns_<table>.csv for afdta (GMNS_DIR) at run time.

Reads use sqlite3 (fast); writes go through OGR so the GeoPackage triggers
and feature counts stay right.
"""
import os
import sqlite3

from qgis.PyQt.QtCore import Qt, QRectF
from qgis.PyQt.QtGui import QColor, QPainter, QPen, QBrush
from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
                                 QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
                                 QComboBox, QDoubleSpinBox, QMessageBox, QWidget,
                                 QHeaderView, QAbstractItemView, QSplitter)
from qgis.core import (QgsProject, QgsVectorLayer, QgsSymbol, QgsCategorizedSymbolRenderer,
                       QgsRendererCategory, QgsSingleSymbolRenderer, QgsRelation,
                       QgsEditorWidgetSetup, QgsLineSymbol, QgsArrowSymbolLayer,
                       QgsFeatureRequest, QgsGeometry, QgsUnitTypes, Qgis)

SPATIAL = ("node", "link", "segment", "segment_lane", "lane", "movement")
SIGNAL_TABLES = ("signal_controller", "signal_timing_plan", "signal_timing_phase",
                 "signal_phase_mvmt")
EXPORT_TABLES = SPATIAL + SIGNAL_TABLES
PROTECTION = ("", "protected", "permitted")
CLEARANCE_S = 5.0
FT_PER_M = 3.28084


def default_path(settings):
    """gmns_network.gpkg (…_msr for an MSR scenario) near the netPrep outputs."""
    name = "gmns_network_msr.gpkg" if settings.is_msr() else "gmns_network.gpkg"
    link = settings.assignment_network()[0] or settings.get("TSM_Link_File") or ""
    dirs = [settings.get("output_dir") or ""]
    if link:
        d = os.path.dirname(link)
        dirs += [d, os.path.join(d, "TSM")]
        try:
            dirs += [os.path.join(d, s) for s in sorted(os.listdir(d))
                     if os.path.isdir(os.path.join(d, s))]
        except OSError:
            pass
    for d in dirs:
        p = os.path.join(d, name) if d else ""
        if p and os.path.exists(p):
            return p.replace("\\", "/")
    return ""


def _connect(path):
    """Read-only sqlite3 connection to the GeoPackage."""
    con = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True)
    con.row_factory = sqlite3.Row
    return con


def _ogr_open(path):
    from osgeo import ogr
    ogr.UseExceptions()
    return ogr.Open(path, 1)


def _sql_val(v):
    if v is None or v == "":
        return "NULL"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def _gmns_layers(path):
    """GMNS layers of this package already in the project, by table name."""
    out = {}
    norm = os.path.normcase(os.path.abspath(path))
    for lyr in QgsProject.instance().mapLayers().values():
        src = lyr.source().split("|")
        if len(src) < 2 or os.path.normcase(os.path.abspath(src[0])) != norm:
            continue
        for part in src[1:]:
            if part.startswith("layername="):
                out[part[len("layername="):]] = lyr
    return out


def _editing(path, tables):
    """Names of this package's layers (among `tables`) open in an edit session."""
    return [lyr.name() for t, lyr in _gmns_layers(path).items()
            if t in tables and lyr.isEditable()]


def _reload(path):
    for lyr in _gmns_layers(path).values():
        lyr.dataProvider().reloadData()
        lyr.triggerRepaint()


# ------------------------------------------------------------------ layers --

def _symbol(lyr, color, width=None, size=None):
    sym = QgsSymbol.defaultSymbol(lyr.geometryType())
    sym.setColor(QColor(color))
    if width is not None and hasattr(sym, "setWidth"):
        sym.setWidth(width)
    if size is not None and hasattr(sym, "setSize"):
        sym.setSize(size)
    return sym


def _categorized(lyr, field, cats, other=None):
    rnd = QgsCategorizedSymbolRenderer(field, [])
    for value, label, sym in cats:
        rnd.addCategory(QgsRendererCategory(value, sym, label))
    if other is not None:
        rnd.addCategory(QgsRendererCategory(None, other, "other"))
    lyr.setRenderer(rnd)


def _arrow(color, width=0.35):
    sym = QgsLineSymbol()
    arrow = QgsArrowSymbolLayer.create({
        "arrow_width": str(width), "arrow_start_width": str(width), "head_length": "1.6",
        "head_thickness": "1.1", "is_curved": "1", "is_repeated": "0", "arrow_type": "0",
        "head_type": "0"})
    arrow.subSymbol().setColor(QColor(color))
    sym.changeSymbolLayer(0, arrow)
    return sym


def _value_map(lyr, field, values):
    idx = lyr.fields().indexOf(field)
    if idx >= 0:
        lyr.setEditorWidgetSetup(idx, QgsEditorWidgetSetup(
            "ValueMap", {"map": [{v if v else "(blank)": v} for v in values]}))


def _style(t, lyr):
    """Symbology, scale ranges and form widgets per GMNS table."""
    ctrl = ("none", "yield", "stop", "4_stop", "signal")
    if t == "node":
        _categorized(lyr, "ctrl_type", [
            ("signal", "signal", _symbol(lyr, "#d7301f", size=2.6)),
            ("stop", "stop", _symbol(lyr, "#fc8d59", size=1.8)),
            ("yield", "yield", _symbol(lyr, "#fdbb84", size=1.6)),
            ("none", "none", _symbol(lyr, "#999999", size=0.8))])
        _value_map(lyr, "ctrl_type", ctrl)
        scale = 60000
    elif t == "link":
        lyr.setRenderer(QgsSingleSymbolRenderer(_symbol(lyr, "#bdbdbd", width=0.3)))
        scale = 150000
    elif t == "lane":
        _categorized(lyr, "lane_type", [
            ("arterial", "arterial", _symbol(lyr, "#4d4d4d", width=0.25)),
            ("GP", "freeway GP", _symbol(lyr, "#2166ac", width=0.25)),
            ("EL", "express lane", _symbol(lyr, "#1b7837", width=0.3)),
            ("ramp", "ramp", _symbol(lyr, "#762a83", width=0.25)),
            ("connector", "connector", _symbol(lyr, "#d9d9d9", width=0.2))])
        scale = 10000
    elif t == "segment":
        lyr.setRenderer(QgsSingleSymbolRenderer(_symbol(lyr, "#fdae61", width=1.4)))
        lyr.setOpacity(0.6)
        scale = 25000
    elif t == "segment_lane":
        lyr.setRenderer(QgsSingleSymbolRenderer(_symbol(lyr, "#e66101", width=0.5)))
        scale = 10000
    elif t == "movement":
        _categorized(lyr, "type", [
            ("thru", "thru", _arrow("#636363")),
            ("left", "left", _arrow("#2b8cbe")),
            ("right", "right", _arrow("#31a354")),
            ("uturn", "U-turn", _arrow("#8856a7"))])
        _value_map(lyr, "type", ("thru", "left", "right", "uturn"))
        _value_map(lyr, "ctrl_type", ctrl)
        lyr.setDisplayExpression('"mvmt_code" || \' (\' || "mvmt_id" || \')\'')
        scale = 5000
    else:
        scale = 0
        if t == "signal_phase_mvmt":
            _value_map(lyr, "protection", ("protected", "permitted"))
            lyr.setDisplayExpression('"mvmt_code" || \' \' || "protection"')
        elif t == "signal_timing_phase":
            lyr.setDisplayExpression('\'Phase \' || "signal_phase_num" || \': \' || "movements"')
        elif t == "signal_timing_plan":
            lyr.setDisplayExpression('\'Plan \' || "timing_plan_id" || \' (C=\' || "cycle_length" || \')\'')
    if scale:
        lyr.setScaleBasedVisibility(True)
        lyr.setMinimumScale(scale)   # visible when zoomed in past 1:scale
        lyr.setMaximumScale(0)


def _relations(lyrs):
    mgr = QgsProject.instance().relationManager()
    pairs = (("link", "link_id", "lane", "link_id", "Lanes"),
             ("link", "link_id", "segment", "link_id", "Segments (pockets)"),
             ("segment", "segment_id", "segment_lane", "segment_id", "Pocket lanes"),
             ("node", "node_id", "movement", "node_id", "Movements"),
             ("node", "node_id", "signal_timing_plan", "node_id", "Timing plan"),
             ("signal_timing_plan", "timing_plan_id", "signal_timing_phase", "timing_plan_id", "Phases"),
             ("signal_timing_phase", "timing_phase_id", "signal_phase_mvmt", "timing_phase_id",
              "Phase movements"),
             ("movement", "mvmt_id", "signal_phase_mvmt", "mvmt_id", "Phases serving it"))
    n = 0
    for parent, pf, child, cf, name in pairs:
        if parent not in lyrs or child not in lyrs:
            continue
        rel = QgsRelation()
        rel.setId("gmns_%s_%s_%s" % (child, parent, lyrs[parent].id()[-8:]))
        rel.setName(name)
        rel.setReferencedLayer(lyrs[parent].id())
        rel.setReferencingLayer(lyrs[child].id())
        rel.addFieldPair(cf, pf)
        if rel.isValid():
            mgr.addRelation(rel)
            n += 1
    return n


def load_layers(path, iface=None):
    """Add the package's layers in a 'GMNS - <file>' group (replacing an older
    copy of the same group). Returns {table: layer}."""
    if not path or not os.path.exists(path):
        raise FileNotFoundError("GMNS package not found: %s" % path)
    proj = QgsProject.instance()
    root = proj.layerTreeRoot()
    gname = "GMNS - %s" % os.path.basename(path)
    old = root.findGroup(gname)
    if old is not None:
        for node in old.findLayers():
            proj.removeMapLayer(node.layerId())
        root.removeChildNode(old)
    group = root.insertGroup(0, gname)
    sig = group.addGroup("Signal timing")
    with _connect(path) as con:
        have = {r[0] for r in con.execute("SELECT table_name FROM gpkg_contents")}
    lyrs = {}
    for t in SPATIAL + SIGNAL_TABLES:
        if t not in have:
            continue
        lyr = QgsVectorLayer("%s|layername=%s" % (path, t), "GMNS %s" % t, "ogr")
        if not lyr.isValid():
            continue
        _style(t, lyr)
        proj.addMapLayer(lyr, False)
        (sig if t in SIGNAL_TABLES else group).addLayer(lyr)
        lyrs[t] = lyr
    sig.setExpanded(False)
    for t in ("lane", "segment_lane"):
        node = group.findLayer(lyrs[t].id()) if t in lyrs else None
        if node is not None:
            node.setExpanded(False)
    _relations(lyrs)
    return lyrs


# ------------------------------------------------------------------ export --

def export_csv(path, out_dir, gpkgcsv, run):
    """Write gmns_<table>.csv for every table into out_dir with gpkgcsv.
    `run(args)` runs a command and returns an object with .returncode."""
    os.makedirs(out_dir, exist_ok=True)
    with _connect(path) as con:
        have = {r[0] for r in con.execute("SELECT table_name FROM gpkg_contents")}
    for t in EXPORT_TABLES:
        if t not in have:
            continue
        dst = os.path.join(out_dir, "gmns_%s.csv" % t)
        r = run([gpkgcsv, "to-csv", path, dst, "--drop-geom", "--layer", t])
        if getattr(r, "returncode", 1) != 0 or not os.path.exists(dst):
            raise RuntimeError("gpkgcsv could not export the GMNS %s table" % t)
    return out_dir.replace("\\", "/")


# ------------------------------------------------------ timing plan packs --
#
# A timing pack is three CSVs that move signal timing between packages (and
# netPrep runs): movements are keyed by node + from node + to node, which come
# from the GeoMaster, not by the package's own mvmt_id.
#   signal_timing_plan.csv   timing_plan_id, controller_id, timeday_id,
#                            cycle_length, offset[, name]
#   signal_timing_phase.csv  timing_plan_id, signal_phase_num, ring, barrier,
#                            position, min_green, max_green, clearance[,
#                            walk_time, ped_clearance]
#   signal_phase_mvmt.csv    timing_plan_id, signal_phase_num, node_id,
#                            ib_from_node_id, ob_to_node_id, protection[, mvmt_code]
# One controller drives every node its movements are at: the two to four
# nodes of a divided road's intersection run one plan.

PACK_FILES = ("signal_timing_plan.csv", "signal_timing_phase.csv", "signal_phase_mvmt.csv")


def _num(v, cast=float):
    v = (v or "").strip()
    return cast(float(v)) if v else None


def import_timing(path, pack_dir):
    """Replace the timing of every controller in the pack (and of all the
    nodes it drives). Returns {controllers, plans, phases, movements,
    unmatched: [text]}."""
    import csv
    rows = {}
    for f in PACK_FILES:
        p = os.path.join(pack_dir, f)
        if not os.path.exists(p):
            raise RuntimeError("%s is missing from %s" % (f, pack_dir))
        with open(p, newline="", encoding="utf-8-sig") as fh:
            rows[f] = list(csv.DictReader(fh))
    plans, phases, pms = (rows[f] for f in PACK_FILES)
    ctrl_of = {r["timing_plan_id"]: int(_num(r["controller_id"])) for r in plans}
    with _connect(path) as con:
        keys = {(int(_num(r["node_id"])), int(_num(r["ib_from_node_id"])), int(_num(r["ob_to_node_id"])))
                for r in pms}
        mv = {}
        for node in {k[0] for k in keys}:
            for mid, f, t, code in con.execute("SELECT mvmt_id, ib_from_node_id, ob_to_node_id, mvmt_code "
                                               "FROM movement WHERE node_id = ?", (node,)):
                mv[(node, f, t)] = (mid, code)
        unmatched = sorted("node %s: %s -> %s" % k for k in keys if k not in mv)
        nodes_of = {}
        for pid, ctl in ctrl_of.items():
            nodes_of.setdefault(ctl, {ctl})
        for r in pms:
            if r["timing_plan_id"] in ctrl_of:
                nodes_of[ctrl_of[r["timing_plan_id"]]].add(int(_num(r["node_id"])))
        cluster = sorted({n for s in nodes_of.values() for n in s})
        known = {r[0] for r in con.execute("SELECT node_id FROM node WHERE node_id IN (%s)"
                                           % ",".join(str(n) for n in cluster))} if cluster else set()
        missing = [n for n in cluster if n not in known]
        if missing:
            raise RuntimeError("nodes not in the package: %s" % ", ".join(str(n) for n in missing))
    ids = ",".join(str(n) for n in cluster)
    stats = {"controllers": len(nodes_of), "plans": 0, "phases": 0, "movements": 0, "unmatched": unmatched}
    ds = _ogr_open(path)
    try:
        ex = ds.ExecuteSQL
        ds.StartTransaction()

        def one(sql):
            lyr = ex(sql, dialect="SQLITE")
            f = lyr.GetNextFeature() if lyr is not None else None
            v = f.GetField(0) if f is not None else None
            if lyr is not None:
                ds.ReleaseResultSet(lyr)
            return v
        # Clear the old timing of every node a controller now drives.
        ex("DELETE FROM signal_phase_mvmt WHERE timing_phase_id IN (SELECT timing_phase_id FROM "
           "signal_timing_phase WHERE timing_plan_id IN (SELECT timing_plan_id FROM signal_timing_plan "
           "WHERE node_id IN (%s)))" % ids)
        ex("DELETE FROM signal_phase_mvmt WHERE node_id IN (%s)" % ids)
        ex("DELETE FROM signal_timing_phase WHERE timing_plan_id IN (SELECT timing_plan_id FROM "
           "signal_timing_plan WHERE node_id IN (%s))" % ids)
        ex("DELETE FROM signal_timing_plan WHERE node_id IN (%s)" % ids)
        ex("DELETE FROM signal_controller WHERE node_id IN (%s)" % ids)
        next_plan = int(one("SELECT COALESCE(MAX(timing_plan_id), 0) FROM signal_timing_plan"))
        next_phase = int(one("SELECT COALESCE(MAX(timing_phase_id), 0) FROM signal_timing_phase"))
        next_pm = int(one("SELECT COALESCE(MAX(signal_phase_mvmt_id), 0) FROM signal_phase_mvmt"))
        for ctl in nodes_of:
            ex("INSERT INTO signal_controller (controller_id, node_id, source) VALUES (%d, %d, 'import')"
               % (ctl, ctl))
        plan_id, phase_id, labels = {}, {}, {}
        for r in pms:
            k = (int(_num(r["node_id"])), int(_num(r["ib_from_node_id"])), int(_num(r["ob_to_node_id"])))
            if k in mv:
                labels.setdefault((r["timing_plan_id"], int(_num(r["signal_phase_num"]))), []).append(mv[k][1])
        for r in plans:                       # pack order = id order: the first is the base plan
            next_plan += 1
            plan_id[r["timing_plan_id"]] = next_plan
            ctl = ctrl_of[r["timing_plan_id"]]
            ex("INSERT INTO signal_timing_plan (timing_plan_id, controller_id, timeday_id, cycle_length, "
               "offset, node_id, source) VALUES (%d, %d, %s, %s, %s, %d, 'import')" % (
                   next_plan, ctl, _sql_val((r.get("timeday_id") or "").strip()), _num(r["cycle_length"]),
                   _num(r.get("offset")) or 0, ctl))
            stats["plans"] += 1
        for r in phases:
            pid = plan_id.get(r["timing_plan_id"])
            if pid is None:
                continue
            num = int(_num(r["signal_phase_num"]))
            next_phase += 1
            phase_id[(r["timing_plan_id"], num)] = next_phase
            walk = _num(r.get("walk_time"))
            ex("INSERT INTO signal_timing_phase (timing_phase_id, timing_plan_id, signal_phase_num, min_green, "
               "max_green, extension, clearance, walk_time, ped_clearance, ring, barrier, position, node_id, "
               "movements) VALUES (%d, %d, %d, %s, %s, 0, %s, %s, %s, %d, %d, %d, %d, %s)" % (
                   next_phase, pid, num, _num(r.get("min_green")) or 0, _num(r["max_green"]),
                   _num(r.get("clearance")) or CLEARANCE_S, _sql_val(walk),
                   _sql_val(_num(r.get("ped_clearance"))), int(_num(r["ring"])), int(_num(r["barrier"])),
                   int(_num(r.get("position")) or 1), ctrl_of[r["timing_plan_id"]],
                   _sql_val(" ".join(labels.get((r["timing_plan_id"], num), [])) or ("ped" if walk else ""))))
            stats["phases"] += 1
        for r in pms:
            k = (int(_num(r["node_id"])), int(_num(r["ib_from_node_id"])), int(_num(r["ob_to_node_id"])))
            tp = phase_id.get((r["timing_plan_id"], int(_num(r["signal_phase_num"]))))
            if k not in mv or tp is None:
                continue
            next_pm += 1
            ex("INSERT INTO signal_phase_mvmt (signal_phase_mvmt_id, timing_phase_id, mvmt_id, protection, "
               "node_id, mvmt_code) VALUES (%d, %d, %d, %s, %d, %s)" % (
                   next_pm, tp, mv[k][0], _sql_val((r.get("protection") or "protected").strip()),
                   k[0], _sql_val(mv[k][1])))
            stats["movements"] += 1
        ex("UPDATE node SET ctrl_type = 'signal' WHERE node_id IN (%s)" % ids)
        ex("UPDATE movement SET ctrl_type = 'signal' WHERE node_id IN (%s)" % ids)
        ds.CommitTransaction()
    except Exception:
        ds.RollbackTransaction()
        raise
    finally:
        ds = None
    _reload(path)
    return stats


def export_timing(path, node_ids, pack_dir):
    """Write the timing of the controllers driving `node_ids` as a pack.
    Returns the number of plans written."""
    import csv
    os.makedirs(pack_dir, exist_ok=True)
    with _connect(path) as con:
        ctls = set()
        for n in node_ids:
            ctls.add(_controller_of(con, n) or n)
        plans = con.execute("SELECT timing_plan_id, controller_id, timeday_id, cycle_length, offset "
                            "FROM signal_timing_plan WHERE node_id IN (%s) ORDER BY controller_id, timing_plan_id"
                            % ",".join(str(int(c)) for c in ctls)).fetchall() if ctls else []
        pids = ",".join(str(r[0]) for r in plans) or "NULL"
        phases = con.execute("SELECT timing_plan_id, signal_phase_num, ring, barrier, position, min_green, "
                             "max_green, clearance, walk_time, ped_clearance FROM signal_timing_phase "
                             "WHERE timing_plan_id IN (%s) ORDER BY timing_plan_id, signal_phase_num"
                             % pids).fetchall()
        pms = con.execute("SELECT h.timing_plan_id, h.signal_phase_num, m.node_id, m.ib_from_node_id, "
                          "m.ob_to_node_id, pm.protection, m.mvmt_code FROM signal_phase_mvmt pm "
                          "JOIN signal_timing_phase h ON h.timing_phase_id = pm.timing_phase_id "
                          "JOIN movement m ON m.mvmt_id = pm.mvmt_id WHERE h.timing_plan_id IN (%s) "
                          "ORDER BY h.timing_plan_id, h.signal_phase_num, m.node_id, m.mvmt_code" % pids).fetchall()
    out = ((PACK_FILES[0], ("timing_plan_id", "controller_id", "timeday_id", "cycle_length", "offset"), plans),
           (PACK_FILES[1], ("timing_plan_id", "signal_phase_num", "ring", "barrier", "position", "min_green",
                            "max_green", "clearance", "walk_time", "ped_clearance"), phases),
           (PACK_FILES[2], ("timing_plan_id", "signal_phase_num", "node_id", "ib_from_node_id",
                            "ob_to_node_id", "protection", "mvmt_code"), pms))
    for name, cols, data in out:
        with open(os.path.join(pack_dir, name), "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(cols)
            for r in data:
                w.writerow(["" if v is None else ("%g" % v if isinstance(v, float) else v) for v in r])
    return len(plans)


def _controller_of(con, node):
    """The controller node driving `node`: its own plan's, else the plan whose
    phase movements are at it. None when unsignalized."""
    r = con.execute("SELECT node_id FROM signal_timing_plan WHERE node_id = ? LIMIT 1", (node,)).fetchone()
    r = r or con.execute("SELECT p.node_id FROM signal_phase_mvmt pm JOIN signal_timing_phase h "
                         "ON h.timing_phase_id = pm.timing_phase_id JOIN signal_timing_plan p "
                         "ON p.timing_plan_id = h.timing_plan_id WHERE pm.node_id = ? LIMIT 1", (node,)).fetchone()
    return r[0] if r else None


def _cluster_of(con, ctl):
    """Nodes a controller drives (itself first)."""
    rows = con.execute("SELECT DISTINCT pm.node_id FROM signal_phase_mvmt pm JOIN signal_timing_phase h "
                       "ON h.timing_phase_id = pm.timing_phase_id JOIN signal_timing_plan p "
                       "ON p.timing_plan_id = h.timing_plan_id WHERE p.node_id = ?", (ctl,)).fetchall()
    return [ctl] + sorted(r[0] for r in rows if r[0] is not None and r[0] != ctl)


# ----------------------------------------------------------- micro package --
#
# afdta writes <output>/micro_package after a network micro run: the area's
# LINK / NODE rows, its GMNS subset as CSVs (gmns/), the frozen traffic
# (micro_demand.csv, micro_routes.csv) and micro_package.ctl. A rerun
# (MICRO_PACKAGE) needs no statewide model. micro_gmns.gpkg is the editable
# copy of gmns/: the same area cut from the statewide GMNS package, with
# geometry, built by the HyDRA dialog right after the run (or Open for
# editing); Run exports it back to gmns/ first.

def package_gpkg(pkg_dir):
    return os.path.join(pkg_dir, "micro_gmns.gpkg").replace("\\", "/")


def is_package(pkg_dir):
    return bool(pkg_dir) and os.path.exists(os.path.join(pkg_dir, "micro_package.ctl"))


def build_package_gpkg(gmns_path, pkg_dir):
    """micro_gmns.gpkg in pkg_dir: every GMNS table of the package's area
    (its LINK.csv links), cut from the statewide package with geometry. The
    same selection afdta's package uses: the area's nodes, links, lanes and
    pockets, movements with both links in the area, and every timing plan
    that serves one of them or sits on an area node (all its phases; phase
    movements only those in the area).
    Returns the path."""
    import csv
    from osgeo import gdal
    gdal.UseExceptions()
    with open(os.path.join(pkg_dir, "LINK.csv"), newline="", encoding="utf-8-sig") as f:
        pairs = {(int(r["A"]), int(r["B"])) for r in csv.DictReader(f)}
    nodes = {n for p in pairs for n in p}
    nl = ",".join(str(n) for n in sorted(nodes)) or "NULL"

    def ids(sql):
        return {r[0] for r in con.execute(sql)}

    def inlist(s):
        return ",".join(str(int(v)) for v in sorted(s)) or "NULL"
    with _connect(gmns_path) as con:
        links = {r[0] for r in con.execute("SELECT link_id, from_node_id, to_node_id FROM link "
                                           "WHERE from_node_id IN (%s)" % nl) if (r[1], r[2]) in pairs}
        lk = inlist(links)
        segs = ids("SELECT segment_id FROM segment WHERE link_id IN (%s)" % lk)
        mvmts = ids("SELECT mvmt_id FROM movement WHERE node_id IN (%s) AND ib_link_id IN (%s) "
                    "AND ob_link_id IN (%s)" % (nl, lk, lk))
        phases = ids("SELECT timing_phase_id FROM signal_phase_mvmt WHERE mvmt_id IN (%s)" % inlist(mvmts))
        plans = ids("SELECT timing_plan_id FROM signal_timing_phase WHERE timing_phase_id IN (%s)"
                    % inlist(phases))
        plans |= ids("SELECT timing_plan_id FROM signal_timing_plan WHERE node_id IN (%s)" % nl)
        ctls = ids("SELECT controller_id FROM signal_timing_plan WHERE timing_plan_id IN (%s)" % inlist(plans))
        phases = ids("SELECT timing_phase_id FROM signal_timing_phase WHERE timing_plan_id IN (%s)"
                     % inlist(plans))
        have = {r[0] for r in con.execute("SELECT table_name FROM gpkg_contents")}
        have |= {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    where = {
        "config": None,
        "node": "node_id IN (%s)" % nl,
        "link": "link_id IN (%s)" % lk,
        "lane": "link_id IN (%s)" % lk,
        "segment": "segment_id IN (%s)" % inlist(segs),
        "segment_lane": "segment_id IN (%s)" % inlist(segs),
        "movement": "mvmt_id IN (%s)" % inlist(mvmts),
        "signal_controller": "controller_id IN (%s)" % inlist(ctls),
        "signal_timing_plan": "timing_plan_id IN (%s)" % inlist(plans),
        "signal_timing_phase": "timing_plan_id IN (%s)" % inlist(plans),
        "signal_phase_mvmt": "timing_phase_id IN (%s) AND mvmt_id IN (%s)" % (inlist(phases), inlist(mvmts)),
        "time_set_definitions": None,
    }
    out = package_gpkg(pkg_dir)
    if os.path.exists(out):
        os.remove(out)
    first = True
    for t, w in where.items():
        if t not in have:
            continue
        opts = gdal.VectorTranslateOptions(format="GPKG", layers=[t], layerName=t, where=w,
                                           accessMode=None if first else "update")
        gdal.VectorTranslate(out, gmns_path, options=opts)
        first = False
    return out


# ---------------------------------------------------------- micro area / LOS --

def micro_area_links(poly_layer, link_layer, out_csv):
    """Write A,B of every link inside the (selected, else all) polygons of
    `poly_layer` -- the network micro area (MICRO_AREA_LINKS). Returns the count."""
    from qgis.core import QgsCoordinateTransform, QgsGeometry as G
    feats = poly_layer.selectedFeatures() or list(poly_layer.getFeatures())
    geoms = [f.geometry() for f in feats if f.hasGeometry()]
    if not geoms:
        return 0
    area = G.unaryUnion(geoms)
    if poly_layer.crs() != link_layer.crs():
        area.transform(QgsCoordinateTransform(poly_layer.crs(), link_layer.crs(), QgsProject.instance()))
    eng = QgsGeometry.createGeometryEngine(area.constGet())
    eng.prepareGeometry()
    req = QgsFeatureRequest().setFilterRect(area.boundingBox())
    req.setSubsetOfAttributes(["A", "B"], link_layer.fields())
    n = 0
    with open(out_csv, "w") as f:
        f.write("a_node,b_node\n")
        for ft in link_layer.getFeatures(req):
            if ft.hasGeometry() and eng.contains(ft.geometry().constGet()):
                f.write("%d,%d\n" % (int(ft["A"]), int(ft["B"])))
                n += 1
    return n


LOS_COLORS = (("A", "#1a9850"), ("B", "#91cf60"), ("C", "#d9ef8b"), ("D", "#fee08b"),
              ("E", "#fc8d59"), ("F", "#d73027"))


def build_micro_los(gmns_path, out_dir):
    """micro_los.gpkg in out_dir/visualizer: the network micro's movement and
    intersection performance (every 15-min interval and the day, interval -1)
    on the GMNS movement / node geometry. Returns its path, or None."""
    import csv
    from osgeo import ogr
    ogr.UseExceptions()
    mv_csv = os.path.join(out_dir, "micro_movement_performance.csv")
    nd_csv = os.path.join(out_dir, "micro_intersection_performance.csv")
    if not (os.path.exists(mv_csv) and os.path.exists(gmns_path)):
        return None
    with open(mv_csv, newline="") as f:
        mv_rows = list(csv.DictReader(f))
    nd_rows = []
    if os.path.exists(nd_csv):
        with open(nd_csv, newline="") as f:
            nd_rows = list(csv.DictReader(f))
    src = ogr.Open(gmns_path)
    geo_mv, geo_nd = {}, {}
    ids = sorted({int(r["mvmt_id"]) for r in mv_rows})
    lyr = src.GetLayerByName("movement")
    for i in range(0, len(ids), 500):
        lyr.SetAttributeFilter("mvmt_id IN (%s)" % ",".join(map(str, ids[i:i + 500])))
        for ft in lyr:
            g = ft.GetGeometryRef()
            if g is not None:
                geo_mv[ft.GetField("mvmt_id")] = g.Clone()
    nodes = sorted({int(r["node_id"]) for r in nd_rows})
    lyr = src.GetLayerByName("node")
    for i in range(0, len(nodes), 500):
        lyr.SetAttributeFilter("node_id IN (%s)" % ",".join(map(str, nodes[i:i + 500])))
        for ft in lyr:
            g = ft.GetGeometryRef()
            if g is not None:
                geo_nd[ft.GetField("node_id")] = g.Clone()
    srs = src.GetLayerByName("link").GetSpatialRef()
    vis = os.path.join(out_dir, "visualizer")
    os.makedirs(vis, exist_ok=True)
    path = os.path.join(vis, "micro_los.gpkg")
    drv = ogr.GetDriverByName("GPKG")
    if os.path.exists(path):
        drv.DeleteDataSource(path)
    ds = drv.CreateDataSource(path)

    def write(name, gtype, rows, geo, key, fields):
        out = ds.CreateLayer(name, srs, gtype)
        for fname, ftype in fields:
            out.CreateField(ogr.FieldDefn(fname, ftype))
        out.CreateField(ogr.FieldDefn("time", ogr.OFTDateTime))
        out.StartTransaction()
        for r in rows:
            g = geo.get(int(r[key]))
            if g is None:
                continue
            ft = ogr.Feature(out.GetLayerDefn())
            for fname, ftype in fields:
                v = r.get(fname, "")
                if v == "":
                    continue
                ft.SetField(fname, int(float(v)) if ftype == ogr.OFTInteger64 else
                            float(v) if ftype == ogr.OFTReal else v)
            itv = int(r["interval"])
            if itv >= 0:
                m = itv * 15
                day, m = divmod(m, 1440)
                ft.SetField("time", 2026, 1, 1 + day, m // 60, m % 60, 0, 0)
            ft.SetGeometry(g)
            out.CreateFeature(ft)
        out.CommitTransaction()
    I, R, S = ogr.OFTInteger64, ogr.OFTReal, ogr.OFTString
    mv_fields = [("node_id", I), ("mvmt_id", I), ("mvmt_code", S), ("type", S), ("ctrl_type", S),
                 ("interval", I), ("hour", I), ("volume", R), ("delay_s", R), ("los", S),
                 ("max_queue_veh", R)]
    nd_fields = [("node_id", I), ("ctrl_type", S), ("interval", I), ("hour", I), ("volume", R),
                 ("delay_s", R), ("los", S), ("max_queue_veh", R), ("worst_mvmt", S),
                 ("worst_delay_s", R)]
    # Whole day (interval -1) and the 15-min intervals (with a `time` for the
    # Temporal Controller) as separate tables.
    for suffix, keep in (("_day", lambda r: r["interval"] == "-1"),
                         ("", lambda r: r["interval"] != "-1")):
        write("movement_los" + suffix, ogr.wkbLineString, [r for r in mv_rows if keep(r)], geo_mv,
              "mvmt_id", mv_fields)
        write("intersection_los" + suffix, ogr.wkbPoint, [r for r in nd_rows if keep(r)], geo_nd,
              "node_id", nd_fields)
    ds.FlushCache()
    ds = src = None          # close both before QGIS opens the file
    return path


def load_micro_los(path, label=""):
    """Add the whole-day LOS layers of micro_los.gpkg, coloured by LOS. The
    15-min tables (movement_los / intersection_los) carry a `time` field for
    the Temporal Controller. `label` (a run name) goes into the layer names."""
    added = []
    tag = " - %s" % label if label else ""
    for table, name in (("movement_los_day", "Micro movement LOS (day)%s" % tag),
                        ("intersection_los_day", "Micro intersection LOS (day)%s" % tag)):
        lyr = QgsVectorLayer("%s|layername=%s" % (path, table), name, "ogr")
        if not lyr.isValid():
            continue
        if table.startswith("movement"):
            cats = [(k, "LOS " + k, _arrow(c, 0.6)) for k, c in LOS_COLORS]
        else:
            cats = [(k, "LOS " + k, _symbol(lyr, c, size=4.0)) for k, c in LOS_COLORS]
        _categorized(lyr, "los", cats)
        QgsProject.instance().addMapLayer(lyr)
        added.append(name)
    return added


# --------------------------------------------------------------- validate --

def _ring_issues(phases, cycle):
    """Messages for one plan's phases: [(ring, barrier, green, clearance, min)]."""
    msgs = []
    tot = {}
    for ring, barrier, g, clr, gmin in phases:
        tot[(barrier, ring)] = tot.get((barrier, ring), 0.0) + (g or 0) + (clr or 0)
        if gmin is not None and g is not None and gmin > g + 1e-6:
            msgs.append(("error", "a phase's min_green %.0f exceeds its max_green %.0f" % (gmin, g)))
    blen = {}
    for (b, r), s in tot.items():
        blen[b] = max(blen.get(b, 0.0), s)
    for (b, r), s in tot.items():
        if abs(s - blen[b]) > 1.0:
            msgs.append(("warning", "barrier %s: ring %s runs %.0f s, the other %.0f s" % (b, r, s, blen[b])))
    total = sum(blen.values())
    if cycle and abs(total - cycle) > 1.0:
        msgs.append(("error", "phases sum to %.0f s, cycle is %.0f s" % (total, cycle)))
    return msgs


def validate(path):
    """[(severity, table, id, node_id, message)] for the package."""
    out = []
    with _connect(path) as con:
        q = con.execute
        lanes = {}
        length = {}
        for r in q("SELECT link_id, lanes, length FROM link"):
            lanes[r[0]] = r[1] or 1
            length[r[0]] = (r[2] or 0) * 5280.0
        pocket_l, pocket_r = {}, {}
        for r in q("SELECT segment_id, link_id, start_lr, end_lr, l_lanes_added, r_lanes_added, "
                   "geometry IS NULL FROM segment"):
            sid, lid, s0, s1, ll, rl, nogeo = r
            pocket_l[lid] = max(pocket_l.get(lid, 0), ll or 0)
            pocket_r[lid] = max(pocket_r.get(lid, 0), rl or 0)
            if lid not in lanes:
                out.append(("error", "segment", sid, None, "link_id %s is not in the link table" % lid))
                continue
            if s0 is None or s1 is None or s0 < -0.5 or s1 > length[lid] + 1 or s0 >= s1:
                out.append(("error", "segment", sid, None,
                            "start_lr/end_lr %s-%s ft outside link %s (0-%.0f ft)" % (s0, s1, lid, length[lid])))
            if nogeo:
                out.append(("fix", "segment", sid, None, "no geometry (Fill in pocket geometry)"))
        for r in q("SELECT segment_lane_id FROM segment_lane WHERE geometry IS NULL"):
            out.append(("fix", "segment_lane", r[0], None, "no geometry (Fill in pocket geometry)"))
        cnt = {}
        for r in q("SELECT link_id, COUNT(*) FROM lane WHERE lane_num > 0 GROUP BY link_id"):
            cnt[r[0]] = r[1]
        bad = [lid for lid, n in lanes.items() if cnt.get(lid, 0) != n]
        for lid in bad[:500]:
            out.append(("warning", "lane", lid, None,
                        "link %s has %d lanes but %d lane rows" % (lid, lanes[lid], cnt.get(lid, 0))))
        if len(bad) > 500:
            out.append(("warning", "lane", None, None, "... %d more links with a lane-row mismatch" % (len(bad) - 500)))

        # Movements: lane ranges against the link lanes and its pockets.
        nb = 0
        for r in q("SELECT mvmt_id, node_id, mvmt_code, ib_link_id, start_ib_lane, end_ib_lane, "
                   "ob_link_id, start_ob_lane, end_ob_lane FROM movement"):
            mid, node, code, ib, s1, e1, ob, s2, e2 = r
            msg = None
            if ib not in lanes or ob not in lanes:
                msg = "inbound/outbound link not in the link table"
            else:
                for (s, e, lid, side) in ((s1, e1, ib, "inbound"), (s2, e2, ob, "outbound")):
                    if s is None or e is None:
                        continue
                    lo, hi = -pocket_l.get(lid, 0), lanes[lid] + pocket_r.get(lid, 0)
                    if s > e or s == 0 or e == 0 or s < lo or e > hi:
                        msg = "%s lanes %s..%s outside %s..%s" % (side, s, e, lo, hi)
            if msg:
                nb += 1
                if nb <= 500:
                    out.append(("error", "movement", mid, node, "%s: %s" % (code, msg)))
        if nb > 500:
            out.append(("error", "movement", None, None, "... %d more movement lane errors" % (nb - 500)))

        # Signals.
        # (Joined in Python: the signal tables are small, the movement table is not.)
        own = {r[0] for r in q("SELECT DISTINCT node_id FROM signal_timing_plan")}
        phase_ids = {r[0] for r in q("SELECT timing_phase_id FROM signal_timing_phase")}
        pm = q("SELECT signal_phase_mvmt_id, node_id, mvmt_id, timing_phase_id FROM signal_phase_mvmt").fetchall()
        # A controller also drives the nodes its phase movements are at (a
        # divided road's twin nodes); a node driven by two controllers is suspect.
        ctl_of_phase = {r[0]: r[1] for r in q("SELECT h.timing_phase_id, p.node_id FROM signal_timing_phase h "
                                              "JOIN signal_timing_plan p ON p.timing_plan_id = h.timing_plan_id")}
        drivers = {}
        for _, node, _, tp in pm:
            if node is not None and tp in ctl_of_phase:
                drivers.setdefault(node, set()).add(ctl_of_phase[tp])
        for node, ctls in drivers.items():
            if len(ctls | ({node} if node in own else set())) > 1:
                out.append(("warning", "node", node, node, "driven by more than one controller: %s"
                            % ", ".join(str(c) for c in sorted(ctls | ({node} if node in own else set())))))
        planned = own | set(drivers)
        in_phase = {r[2] for r in pm}
        used_phase = {r[3] for r in pm}
        for r in q("SELECT node_id FROM node WHERE ctrl_type = 'signal'"):
            if r[0] not in planned:
                out.append(("warning", "node", r[0], r[0], "signal without a timing plan (default g/C used)"))
        sig_mv = set()
        for r in q("SELECT mvmt_id, node_id, mvmt_code FROM movement WHERE ctrl_type = 'signal'"):
            sig_mv.add(r[0])
            if r[1] in planned and r[0] not in in_phase:
                out.append(("error", "movement", r[0], r[1], "%s is in no phase of its controller's plan" % r[2]))
        all_mv = sig_mv | {r[0] for r in q("SELECT mvmt_id FROM movement WHERE node_id IN (%s)"
                                           % ",".join(str(int(n)) for n in planned))} if planned else sig_mv
        for pid, node, mid, tp in pm:
            if mid not in all_mv or tp not in phase_ids:
                out.append(("error", "signal_phase_mvmt", pid, node, "refers to a missing movement or phase"))
        for r in q("SELECT timing_phase_id, node_id, signal_phase_num FROM signal_timing_phase "
                   "WHERE walk_time IS NULL"):
            if r[0] not in used_phase:
                out.append(("warning", "signal_timing_phase", r[0], r[1],
                            "phase %s serves no movement and has no walk time" % r[2]))
        plans = {r[0]: (r[1], r[2]) for r in q("SELECT timing_plan_id, cycle_length, node_id FROM signal_timing_plan")}
        ph = {}
        for r in q("SELECT timing_plan_id, ring, barrier, max_green, clearance, min_green FROM signal_timing_phase"):
            ph.setdefault(r[0], []).append((r[1], r[2], r[3], r[4], r[5]))
        for pid, (cycle, node) in plans.items():
            if pid not in ph:
                out.append(("error", "signal_timing_plan", pid, node, "plan has no phases"))
                continue
            for sev, m in _ring_issues(ph[pid], cycle):
                out.append((sev, "signal_timing_plan", pid, node, m))
    return out


def fill_pocket_geometry(path):
    """Segments / segment lanes without geometry get the link substring
    (start_lr..end_lr), the pocket lane drawn half a lane left of it."""
    with _connect(path) as con:
        segs = con.execute("SELECT s.fid, s.link_id, s.start_lr, s.end_lr FROM segment s "
                           "WHERE s.geometry IS NULL").fetchall()
        lsegs = con.execute("SELECT l.fid, s.link_id, s.start_lr, s.end_lr, COALESCE(l.width, 12) "
                            "FROM segment_lane l JOIN segment s ON s.segment_id = l.segment_id "
                            "WHERE l.geometry IS NULL").fetchall()
    if not segs and not lsegs:
        return 0
    links = QgsVectorLayer("%s|layername=link" % path, "link", "ogr")
    to_mu = QgsUnitTypes.fromUnitToUnitFactor(Qgis.DistanceUnit.Meters, links.crs().mapUnits())
    need = {r[1] for r in segs} | {r[1] for r in lsegs}
    geo = {}
    expr = '"link_id" IN (%s)' % ",".join(str(int(x)) for x in need)
    for f in links.getFeatures(QgsFeatureRequest().setFilterExpression(expr)):
        geo[f["link_id"]] = f.geometry()

    def sub(lid, s0, s1):
        g = geo.get(lid)
        if g is None or g.isEmpty():
            return None
        line = g.constGet()
        if hasattr(line, "geometryN"):
            line = line.geometryN(0)
        return QgsGeometry(line.curveSubstring(s0 / FT_PER_M * to_mu, s1 / FT_PER_M * to_mu))

    n = 0
    for table, rows, lane in (("segment", segs, False), ("segment_lane", lsegs, True)):
        lyr = QgsVectorLayer("%s|layername=%s" % (path, table), table, "ogr")
        changes = {}
        for r in rows:
            g = sub(r[1], r[2] or 0, r[3] or 0)
            if g is None:
                continue
            if lane:
                g = g.offsetCurve(0.5 * r[4] / FT_PER_M * to_mu, 4, Qgis.JoinStyle.Miter, 2.0)
            changes[r[0]] = g
        if changes:
            lyr.dataProvider().changeGeometryValues(changes)
            n += len(changes)
    _reload(path)
    return n


class ValidateDialog(QDialog):
    def __init__(self, path, iface=None, parent=None):
        super().__init__(parent)
        self.path, self.iface = path, iface
        self.setWindowTitle("GMNS validation - %s" % os.path.basename(path))
        self.resize(820, 480)
        lay = QVBoxLayout(self)
        self.summary = QLabel()
        lay.addWidget(self.summary)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Severity", "Table", "Id", "Node", "Message"])
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.cellDoubleClicked.connect(self._zoom)
        lay.addWidget(self.table)
        row = QHBoxLayout()
        self.btn_fix = QPushButton("Fill in pocket geometry")
        self.btn_fix.clicked.connect(self._fix)
        again = QPushButton("Validate again")
        again.clicked.connect(self.run)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        row.addWidget(QLabel("Double-click a row with a node to zoom to it."))
        row.addStretch(1)
        for b in (self.btn_fix, again, close):
            row.addWidget(b)
        lay.addLayout(row)
        self.run()

    def run(self):
        issues = validate(self.path)
        order = {"error": 0, "warning": 1, "fix": 2}
        issues.sort(key=lambda r: (order.get(r[0], 3), r[1]))
        self.table.setRowCount(len(issues))
        colors = {"error": "#fde0dd", "warning": "#fff7bc", "fix": "#e5f5e0"}
        for i, r in enumerate(issues):
            for j, v in enumerate(r):
                it = QTableWidgetItem("" if v is None else str(v))
                it.setBackground(QColor(colors.get(r[0], "#ffffff")))
                self.table.setItem(i, j, it)
        n = {k: sum(1 for r in issues if r[0] == k) for k in order}
        self.summary.setText("%d errors, %d warnings, %d fixable." % (n["error"], n["warning"], n["fix"])
                             if issues else "No issues found.")
        self.btn_fix.setEnabled(n["fix"] > 0)

    def _fix(self):
        busy = _editing(self.path, ("segment", "segment_lane"))
        if busy:
            QMessageBox.warning(self, "GMNS", "Save or stop editing first: %s" % ", ".join(busy))
            return
        n = fill_pocket_geometry(self.path)
        QMessageBox.information(self, "GMNS", "Geometry filled in for %d pocket features." % n)
        self.run()

    def _zoom(self, row, _col):
        it = self.table.item(row, 3)
        if not it or not it.text() or self.iface is None:
            return
        lyr = _gmns_layers(self.path).get("node")
        if lyr is None:
            return
        lyr.selectByExpression('"node_id" = %s' % int(it.text()))
        canvas = self.iface.mapCanvas()
        canvas.zoomToSelected(lyr)
        canvas.zoomScale(min(canvas.scale(), 2500))
        canvas.refresh()


# ----------------------------------------------------------- signal timing --

def seed_plan(con, node_id, cycle=None):
    """A fixed-time dual-ring plan for a node from its movements (as netPrep
    seeds it): major street (most lanes) phases 2/6, cross street 4/8, a
    protected left (5/1, 7/3) where a 3+ lane approach has a pocket.
    Returns (cycle, phases, assignment) with phases [{num, ring, barrier,
    position, min_green, max_green, clearance, walk_time}] and assignment
    {(mvmt_id, phase_num): protection}."""
    mv = con.execute("SELECT m.mvmt_id, m.mvmt_code, m.type, m.ib_link_id, m.start_ib_lane, l.lanes "
                     "FROM movement m JOIN link l ON l.link_id = m.ib_link_id WHERE m.node_id = ?",
                     (node_id,)).fetchall()
    if not mv:
        return None
    appr = {}
    for mid, code, typ, ib, sib, lanes in mv:
        a = appr.setdefault(ib, {"dir": (code or "??")[:2], "lanes": lanes or 1, "pocket": False})
        if sib is not None and sib < 0:
            a["pocket"] = True
    ref = max(appr.values(), key=lambda a: a["lanes"])["dir"]
    opp = {"NB": "SB", "SB": "NB", "EB": "WB", "WB": "EB"}
    ccw = {"NB": "WB", "WB": "SB", "SB": "EB", "EB": "NB"}
    slot_dir = {2: ref, 6: opp.get(ref), 4: ccw.get(ref), 8: opp.get(ccw.get(ref))}
    slot_of = {}
    for ib, a in appr.items():
        s = next((k for k, d in slot_dir.items() if d == a["dir"]), 4)
        slot_of[ib] = s
    lanes = {s: max([a["lanes"] for ib, a in appr.items() if slot_of[ib] == s] or [0]) for s in (2, 4, 6, 8)}
    pocket = {s: any(a["pocket"] and a["lanes"] >= 3 for ib, a in appr.items() if slot_of[ib] == s)
              for s in (2, 4, 6, 8)}
    left_of = {2: 5, 6: 1, 4: 7, 8: 3}
    w1, w2 = max(lanes[2], lanes[6]), max(lanes[4], lanes[8])
    ped = w2 == 0
    wminor = 0.5 * w1 if ped else w2
    mx = max(w1, w2)
    C = float(cycle or (60 if mx <= 1 else 90 if mx == 2 else 120))
    gl = 10.0 if C >= 90 else 7.0
    phases = []

    def add(num, left):
        phases.append({"num": num, "ring": 1 if num <= 4 else 2,
                       "barrier": 1 if num in (1, 2, 5, 6) else 2, "position": 1 if left else 2,
                       "left": left, "min_green": 5.0 if left else 10.0, "max_green": 0.0,
                       "clearance": CLEARANCE_S, "walk_time": None})
    for s in (2, 6, 4, 8):
        if lanes[s]:
            add(s, False)
            if pocket[s]:
                add(left_of[s], True)
    if ped:
        add(4, False)
        phases[-1]["walk_time"] = 7.0

    def need(b):
        return max(sum(p["min_green"] + CLEARANCE_S for p in phases if p["barrier"] == b and p["ring"] == r)
                   for r in (1, 2))
    B1 = round(C * w1 / (w1 + wminor)) if (w1 + wminor) else C / 2
    B1 = max(need(1), min(B1, C - need(2)))
    blen = {1: B1, 2: C - B1}
    for b in (1, 2):
        for r in (1, 2):
            rp = [p for p in phases if p["barrier"] == b and p["ring"] == r]
            if not rp:
                continue
            rest = blen[b] - CLEARANCE_S * len(rp)
            main = None
            for p in rp:
                if p["left"] and len(rp) > 1:
                    p["max_green"] = gl
                    rest -= gl
                else:
                    main = p
            main = main or rp[-1]
            main["max_green"] = max(main["min_green"], rest)
    nums = {p["num"] for p in phases}
    assign = {}
    for mid, code, typ, ib, sib, lanes_ in mv:
        s = slot_of[ib]
        if typ in ("left", "uturn"):
            if left_of[s] in nums:
                assign[(mid, left_of[s])] = "protected"
            assign[(mid, s)] = "permitted"
        else:
            assign[(mid, s)] = "permitted" if typ == "right" else "protected"
    phases.sort(key=lambda p: p["num"])
    return C, phases, assign


class RingDiagram(QWidget):
    """Two rings x two barriers, each phase a bar of green + clearance."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.phases, self.cycle = [], 0.0
        self.setMinimumHeight(86)

    def set_plan(self, phases, cycle):
        self.phases, self.cycle = phases, cycle
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width() - 20, self.height()
        tot = {}
        for ph in self.phases:
            k = (ph["barrier"], ph["ring"])
            tot[k] = tot.get(k, 0) + ph["max_green"] + ph["clearance"]
        blen = {b: max([s for (bb, r), s in tot.items() if bb == b] or [0]) for b in (1, 2)}
        span = max(self.cycle, sum(blen.values()), 1.0)
        sx = w / span
        row_h = (h - 28) / 2.0
        x_bar = {1: 10.0, 2: 10.0 + blen[1] * sx}
        for ring in (1, 2):
            y = 4 + (ring - 1) * (row_h + 4)
            for b in (1, 2):
                x = x_bar[b]
                for ph in sorted([q for q in self.phases if q["ring"] == ring and q["barrier"] == b],
                                 key=lambda q: q["position"]):
                    gw, cw = ph["max_green"] * sx, ph["clearance"] * sx
                    p.setPen(QPen(QColor("#555555")))
                    p.setBrush(QBrush(QColor("#a1d99b")))
                    p.drawRect(QRectF(x, y, gw, row_h))
                    p.setBrush(QBrush(QColor("#fec44f")))
                    p.drawRect(QRectF(x + gw, y, cw, row_h))
                    p.setPen(QPen(QColor("#000000")))
                    p.drawText(QRectF(x + 2, y, max(gw - 2, 1), row_h),
                               int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                               "Ø%d %gs" % (ph["num"], ph["max_green"]))
                    x += gw + cw
        p.setPen(QPen(QColor("#d7301f"), 2))
        xb = 10 + blen[1] * sx
        p.drawLine(int(xb), 2, int(xb), int(2 * row_h + 10))
        xe = 10 + (blen[1] + blen[2]) * sx
        p.drawLine(int(xe), 2, int(xe), int(2 * row_h + 10))
        total = blen[1] + blen[2]
        ok = abs(total - self.cycle) <= 1.0
        p.setPen(QPen(QColor("#1a9641" if ok else "#d7301f")))
        p.drawText(QRectF(10, h - 20, w, 18), int(Qt.AlignmentFlag.AlignLeft),
                   "Barriers %g + %g = %g s, cycle %g s%s" % (
                       blen[1], blen[2], total, self.cycle, "" if ok else "  -- does not match"))
        p.end()


PH_COLS = ("Phase", "Ring", "Barrier", "Position", "Min green", "Green (max)", "Clearance", "Walk")
PH_KEYS = ("num", "ring", "barrier", "position", "min_green", "max_green", "clearance", "walk_time")


class SignalTimingDialog(QDialog):
    """The timing plans of the controller driving one signalized node."""

    def __init__(self, path, iface=None, parent=None):
        super().__init__(parent)
        self.path, self.iface = path, iface
        self.node = None
        self.plan_id = None
        self.movements = []
        self.setWindowTitle("Signal timing - %s" % os.path.basename(path))
        self.resize(900, 700)
        lay = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("Node"))
        self.node_edit = QLineEdit()
        self.node_edit.setPlaceholderText("node_id")
        self.node_edit.returnPressed.connect(self.load_node)
        top.addWidget(self.node_edit)
        b = QPushButton("Load")
        b.clicked.connect(self.load_node)
        top.addWidget(b)
        b = QPushButton("From map selection")
        b.setToolTip("The selected feature of the active layer (GMNS node, HyDRA node or a "
                     "movement / timing table row).")
        b.clicked.connect(self.from_selection)
        top.addWidget(b)
        top.addStretch(1)
        lay.addLayout(top)
        self.info = QLabel("Load a node.")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)

        plan = QGridLayout()
        plan.addWidget(QLabel("Plan"), 0, 0)
        self.plan_combo = QComboBox()
        self.plan_combo.setToolTip("The controller's timing plans. The first is the base plan the macro / "
                                   "meso signal model uses; the micro tier switches plans by time of day.")
        self.plan_combo.activated.connect(self._pick_plan)
        plan.addWidget(self.plan_combo, 0, 1)
        self.btn_new_plan = QPushButton("New time-of-day plan")
        self.btn_new_plan.setToolTip("Start a new plan for this controller from the one shown; set its "
                                     "time of day and Save.")
        self.btn_new_plan.clicked.connect(self.new_plan)
        plan.addWidget(self.btn_new_plan, 0, 2)
        plan.addWidget(QLabel("Time of day"), 0, 3)
        self.timeday = QLineEdit()
        self.timeday.setPlaceholderText("all day, or HH:MM-HH:MM")
        self.timeday.setToolTip("timeday_id: blank = all day; HH:MM-HH:MM = active from..to (may wrap "
                                "midnight, e.g. 19:00-06:30).")
        plan.addWidget(self.timeday, 0, 4)
        plan.addWidget(QLabel("Cycle (s)"), 1, 0)
        self.cycle = QDoubleSpinBox()
        self.cycle.setRange(20, 300)
        self.cycle.setDecimals(0)
        self.cycle.valueChanged.connect(self._redraw)
        plan.addWidget(self.cycle, 1, 1)
        plan.addWidget(QLabel("Offset (s)"), 1, 3)
        self.offset = QDoubleSpinBox()
        self.offset.setRange(0, 300)
        self.offset.setDecimals(0)
        plan.addWidget(self.offset, 1, 4)
        plan.setColumnStretch(5, 1)
        lay.addLayout(plan)

        split = QSplitter(Qt.Orientation.Vertical)
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(QLabel("Phases (green = the fixed-time split; clearance = yellow + all-red)"))
        self.ph_table = QTableWidget(0, len(PH_COLS))
        self.ph_table.setHorizontalHeaderLabels(PH_COLS)
        self.ph_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.ph_table.itemChanged.connect(self._phase_edited)
        bl.addWidget(self.ph_table)
        row = QHBoxLayout()
        for text, fn in (("Add phase", self.add_phase), ("Remove phase", self.remove_phase),
                         ("Fit greens to cycle", self.fit_to_cycle)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        bl.addLayout(row)
        self.diagram = RingDiagram()
        bl.addWidget(self.diagram)
        split.addWidget(box)
        box2 = QWidget()
        b2 = QVBoxLayout(box2)
        b2.setContentsMargins(0, 0, 0, 0)
        b2.addWidget(QLabel("Movements served by each phase"))
        self.mv_table = QTableWidget(0, 0)
        b2.addWidget(self.mv_table)
        split.addWidget(box2)
        lay.addWidget(split, 1)

        bot = QHBoxLayout()
        self.btn_seed = QPushButton("Seed plan")
        self.btn_seed.setToolTip("Replace the phases with netPrep's default plan for this node "
                                 "(also makes an unsignalized node a signal).")
        self.btn_seed.clicked.connect(self.seed)
        self.btn_remove = QPushButton("Remove signal")
        self.btn_remove.clicked.connect(self.remove_signal)
        self.btn_save = QPushButton("Save")
        self.btn_save.clicked.connect(self.save)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        self.btn_export = QPushButton("Export plans...")
        self.btn_export.setToolTip("Write this controller's plans as a timing pack (three CSVs keyed by "
                                   "node, from node and to node) to load into another package.")
        self.btn_export.clicked.connect(self.export_pack)
        for w in (self.btn_seed, self.btn_remove, self.btn_export):
            bot.addWidget(w)
        bot.addStretch(1)
        bot.addWidget(self.btn_save)
        bot.addWidget(close)
        lay.addLayout(bot)
        self._enable(False)

    # -- loading
    def _enable(self, on):
        for w in (self.cycle, self.offset, self.ph_table, self.mv_table, self.btn_seed,
                  self.btn_remove, self.btn_save, self.plan_combo, self.btn_new_plan, self.timeday,
                  self.btn_export):
            w.setEnabled(on)

    def from_selection(self):
        lyr = self.iface.activeLayer() if self.iface else None
        if lyr is None or not hasattr(lyr, "selectedFeatures"):
            QMessageBox.information(self, "Signal timing", "Select a node on the map first.")
            return
        feats = lyr.selectedFeatures()
        if not feats:
            QMessageBox.information(self, "Signal timing", "Select a node on %s first." % lyr.name())
            return
        f = feats[0]
        for field in ("node_id", "N"):
            if f.fields().indexOf(field) >= 0 and f[field] not in (None, ""):
                self.node_edit.setText(str(int(f[field])))
                self.load_node()
                return
        QMessageBox.information(self, "Signal timing", "%s has no node_id or N field." % lyr.name())

    def load_node(self):
        try:
            node = int(self.node_edit.text().strip())
        except ValueError:
            return
        with _connect(self.path) as con:
            n = con.execute("SELECT ctrl_type FROM node WHERE node_id = ?", (node,)).fetchone()
            if n is None:
                self.info.setText("Node %s is not in the GMNS package." % node)
                self._enable(False)
                return
            # The controller driving the node, and every node it drives.
            ctl = _controller_of(con, node) or node
            self.node = ctl
            self.cluster = _cluster_of(con, ctl)
            self.movements = [dict(r) for r in con.execute(
                "SELECT mvmt_id, node_id, mvmt_code, type, start_ib_lane, end_ib_lane, ib_link_id "
                "FROM movement WHERE node_id IN (%s) ORDER BY node_id = %d DESC, node_id, mvmt_code"
                % (",".join(str(c) for c in self.cluster), ctl))]
            self.plans = [tuple(r) for r in con.execute(
                "SELECT timing_plan_id, cycle_length, offset, timeday_id FROM signal_timing_plan "
                "WHERE node_id = ? ORDER BY timing_plan_id", (ctl,))]
        self.ctrl_type = n[0]
        self.plan_combo.clear()
        for pid, cyc, off, td in self.plans:
            self.plan_combo.addItem("%s  (%s, C=%g)" % (pid, td or "all day", cyc or 0), pid)
        keep = getattr(self, "_keep_plan", None)
        i = next((k for k, p in enumerate(self.plans) if p[0] == keep), 0)
        self._keep_plan = None
        self.plan_combo.setCurrentIndex(i)
        self._show_plan(self.plans[i][0] if self.plans else None)
        self._enable(True)

    def _pick_plan(self, i):
        self._show_plan(self.plan_combo.itemData(i))

    def _show_plan(self, plan_id):
        phases, assign = [], {}
        self.plan_id = plan_id
        p = next((p for p in self.plans if p[0] == plan_id), None)
        self.cycle.setValue((p[1] if p else 90) or 90)
        self.offset.setValue((p[2] if p else 0) or 0)
        self.timeday.setText((p[3] if p else "") or "")
        if p:
            with _connect(self.path) as con:
                rows = con.execute("SELECT timing_phase_id, signal_phase_num, ring, barrier, position, min_green, "
                                   "max_green, clearance, walk_time FROM signal_timing_phase "
                                   "WHERE timing_plan_id = ? ORDER BY signal_phase_num", (plan_id,)).fetchall()
                num_of = {}
                for r in rows:
                    num_of[r[0]] = r[1]
                    phases.append({"num": r[1], "ring": r[2], "barrier": r[3], "position": r[4],
                                   "min_green": r[5], "max_green": r[6], "clearance": r[7], "walk_time": r[8]})
                if num_of:
                    q = "SELECT timing_phase_id, mvmt_id, protection FROM signal_phase_mvmt WHERE timing_phase_id IN (%s)" \
                        % ",".join(str(i) for i in num_of)
                    for tp, mid, prot in con.execute(q):
                        assign[(mid, num_of[tp])] = prot or "protected"
        nodes = "node %s" % self.node if len(self.cluster) == 1 else \
            "controller %s driving nodes %s" % (self.node, ", ".join(str(c) for c in self.cluster))
        more = "" if len(self.plans) <= 1 else ", %d time-of-day plans" % len(self.plans)
        self.info.setText("%s: %s, %d movements, %s%s." % (
            nodes, self.ctrl_type, len(self.movements),
            "plan %s" % plan_id if plan_id else "no timing plan -- Seed plan to make one", more))
        self._fill(phases, assign)

    def new_plan(self):
        """Keep the phases and movements on screen as a new, unsaved plan."""
        if self.node is None:
            return
        self.plan_id = None
        self.plan_combo.addItem("(new plan -- Save to keep)", None)
        self.plan_combo.setCurrentIndex(self.plan_combo.count() - 1)
        self.timeday.setText("")
        self.timeday.setFocus()

    def export_pack(self):
        from qgis.PyQt.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(self, "Folder for the timing pack")
        if not d:
            return
        n = export_timing(self.path, [self.node], d)
        QMessageBox.information(self, "Signal timing", "%d plans written to %s." % (n, d))

    def _fill(self, phases, assign):
        self.ph_table.blockSignals(True)
        self.ph_table.setRowCount(len(phases))
        for i, ph in enumerate(phases):
            for j, k in enumerate(PH_KEYS):
                v = ph.get(k)
                self.ph_table.setItem(i, j, QTableWidgetItem("" if v is None else "%g" % v))
        self.ph_table.blockSignals(False)
        self._build_mv_grid(assign)
        self._redraw()

    def _phases(self):
        out = []
        for i in range(self.ph_table.rowCount()):
            ph = {}
            for j, k in enumerate(PH_KEYS):
                it = self.ph_table.item(i, j)
                txt = it.text().strip() if it else ""
                try:
                    ph[k] = float(txt) if txt else None
                except ValueError:
                    ph[k] = None
            for k in ("num", "ring", "barrier", "position"):
                ph[k] = int(ph[k] or 0)
            for k in ("min_green", "max_green", "clearance"):
                ph[k] = ph[k] or 0.0
            out.append(ph)
        return out

    def _assign(self):
        out = {}
        nums = [ph["num"] for ph in self._phases()]
        for i, m in enumerate(self.movements):
            for j, num in enumerate(nums):
                cb = self.mv_table.cellWidget(i, j)
                if cb is not None and cb.currentText():
                    out[(m["mvmt_id"], num)] = cb.currentText()
        return out

    def _build_mv_grid(self, assign):
        nums = [ph["num"] for ph in self._phases()]
        self.mv_table.clear()
        self.mv_table.setRowCount(len(self.movements))
        self.mv_table.setColumnCount(len(nums))
        self.mv_table.setHorizontalHeaderLabels(["Ø%d" % n for n in nums])
        multi = len(getattr(self, "cluster", [])) > 1
        self.mv_table.setVerticalHeaderLabels([
            "%s%s  %s  lanes %s..%s" % ("%s: " % m["node_id"] if multi else "", m["mvmt_code"], m["type"],
                                        m["start_ib_lane"], m["end_ib_lane"])
            for m in self.movements])
        for i, m in enumerate(self.movements):
            for j, num in enumerate(nums):
                cb = QComboBox()
                cb.addItems(PROTECTION)
                cb.setCurrentText(assign.get((m["mvmt_id"], num), ""))
                self.mv_table.setCellWidget(i, j, cb)
        self.mv_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

    def _phase_edited(self, item):
        if item.column() == 0:                 # renumbered: rebuild the grid columns
            self._build_mv_grid(self._assign_by_row())
        self._redraw()

    def _assign_by_row(self):
        """Assignment keyed by the CURRENT phase numbers, read column by column."""
        out = {}
        nums = [ph["num"] for ph in self._phases()]
        for i, m in enumerate(self.movements):
            for j in range(min(self.mv_table.columnCount(), len(nums))):
                cb = self.mv_table.cellWidget(i, j)
                if cb is not None and cb.currentText():
                    out[(m["mvmt_id"], nums[j])] = cb.currentText()
        return out

    def _redraw(self, *_):
        self.diagram.set_plan(self._phases(), self.cycle.value())

    # -- editing
    def add_phase(self):
        nums = {ph["num"] for ph in self._phases()}
        num = next(n for n in range(1, 17) if n not in nums)
        assign = self._assign()
        r = self.ph_table.rowCount()
        self.ph_table.blockSignals(True)
        self.ph_table.insertRow(r)
        vals = (num, 1 if num <= 4 else 2, 1 if num in (1, 2, 5, 6) else 2, 2, 5, 10, CLEARANCE_S, None)
        for j, v in enumerate(vals):
            self.ph_table.setItem(r, j, QTableWidgetItem("" if v is None else "%g" % v))
        self.ph_table.blockSignals(False)
        self._build_mv_grid(assign)
        self._redraw()

    def remove_phase(self):
        r = self.ph_table.currentRow()
        if r < 0:
            return
        assign = self._assign()
        self.ph_table.removeRow(r)
        self._build_mv_grid(assign)
        self._redraw()

    def fit_to_cycle(self):
        """Scale every ring's greens (above the minimums) so each barrier fits
        its share of the cycle."""
        phases = self._phases()
        if not phases:
            return
        tot = {}
        for ph in phases:
            k = (ph["barrier"], ph["ring"])
            tot[k] = tot.get(k, 0) + ph["max_green"] + ph["clearance"]
        blen = {b: max([s for (bb, r), s in tot.items() if bb == b] or [0]) for b in (1, 2)}
        cur = sum(blen.values()) or 1.0
        target = {b: blen[b] * self.cycle.value() / cur for b in blen}
        for (b, r), s in tot.items():
            rp = [ph for ph in phases if ph["barrier"] == b and ph["ring"] == r]
            fixed = sum(ph["clearance"] + ph["min_green"] for ph in rp)
            spare = sum(ph["max_green"] - ph["min_green"] for ph in rp)
            avail = target[b] - fixed
            for ph in rp:
                extra = (ph["max_green"] - ph["min_green"]) / spare * avail if spare > 0 else avail / len(rp)
                ph["max_green"] = round(ph["min_green"] + max(0.0, extra), 1)
        self._fill(phases, self._assign())

    def seed(self):
        with _connect(self.path) as con:
            res = seed_plan(con, self.node)
        if res is None:
            QMessageBox.information(self, "Signal timing", "Node %s has no movements." % self.node)
            return
        cycle, phases, assign = res
        self.cycle.setValue(cycle)
        self.offset.setValue(0)
        self._fill(phases, assign)

    # -- saving
    def _check_editing(self):
        busy = _editing(self.path, ("node", "movement") + SIGNAL_TABLES)
        if busy:
            QMessageBox.warning(self, "Signal timing", "Save or stop editing first: %s" % ", ".join(busy))
            return False
        return True

    def save(self):
        if self.node is None or not self._check_editing():
            return
        phases = self._phases()
        nums = [ph["num"] for ph in phases]
        if len(set(nums)) != len(nums) or 0 in nums:
            QMessageBox.warning(self, "Signal timing", "Phase numbers must be unique and non-zero.")
            return
        assign = self._assign()
        sig_mv = {m["mvmt_id"] for m in self.movements}
        missing = [m["mvmt_code"] for m in self.movements if not any(k[0] == m["mvmt_id"] for k in assign)]
        msgs = [m for sev, m in _ring_issues([(p["ring"], p["barrier"], p["max_green"], p["clearance"],
                                               p["min_green"]) for p in phases], self.cycle.value())]
        if missing:
            msgs.append("not in any phase: %s" % ", ".join(missing))
        if msgs and QMessageBox.question(
                self, "Signal timing", "Save anyway?\n\n" + "\n".join(msgs)) != QMessageBox.StandardButton.Yes:
            return
        labels = {}
        code = {m["mvmt_id"]: m["mvmt_code"] for m in self.movements}
        node_of = {m["mvmt_id"]: m["node_id"] for m in self.movements}
        for (mid, num) in sorted(assign):
            labels.setdefault(num, [])
            if code[mid] not in labels[num]:
                labels[num].append(code[mid])
        node = self.node
        td = self.timeday.text().strip()
        if td and "-" not in td:
            QMessageBox.warning(self, "Signal timing", "Time of day is blank (all day) or HH:MM-HH:MM.")
            return
        cluster = ",".join(str(c) for c in self.cluster)
        ds = _ogr_open(self.path)
        try:
            ex = ds.ExecuteSQL
            ds.StartTransaction()

            def one(sql):
                lyr = ex(sql, dialect="SQLITE")
                v = None
                if lyr is not None:
                    f = lyr.GetNextFeature()
                    v = f.GetField(0) if f is not None else None
                    ds.ReleaseResultSet(lyr)
                return v
            if self.plan_id is None:
                self.plan_id = int(one("SELECT COALESCE(MAX(timing_plan_id), 0) + 1 FROM signal_timing_plan"))
                if one("SELECT COUNT(*) FROM signal_controller WHERE controller_id = %d" % node) == 0:
                    ex("INSERT INTO signal_controller (controller_id, node_id, source) VALUES (%d, %d, 'user')"
                       % (node, node))
                ex("INSERT INTO signal_timing_plan (timing_plan_id, controller_id, timeday_id, cycle_length, "
                   "offset, node_id, source) VALUES (%d, %d, %s, %s, %s, %d, 'user')"
                   % (self.plan_id, node, _sql_val(td), self.cycle.value(), self.offset.value(), node))
            else:
                ex("UPDATE signal_timing_plan SET cycle_length = %s, offset = %s, timeday_id = %s, "
                   "source = 'user' WHERE timing_plan_id = %d"
                   % (self.cycle.value(), self.offset.value(), _sql_val(td), self.plan_id))
            ex("DELETE FROM signal_phase_mvmt WHERE timing_phase_id IN (SELECT timing_phase_id FROM "
               "signal_timing_phase WHERE timing_plan_id = %d)" % self.plan_id)
            ex("DELETE FROM signal_timing_phase WHERE timing_plan_id = %d" % self.plan_id)
            next_phase = int(one("SELECT COALESCE(MAX(timing_phase_id), 0) FROM signal_timing_phase"))
            next_pm = int(one("SELECT COALESCE(MAX(signal_phase_mvmt_id), 0) FROM signal_phase_mvmt"))
            tid = {}
            for ph in phases:
                next_phase += 1
                tid[ph["num"]] = next_phase
                ex("INSERT INTO signal_timing_phase (timing_phase_id, timing_plan_id, signal_phase_num, min_green, "
                   "max_green, extension, clearance, walk_time, ped_clearance, ring, barrier, position, node_id, "
                   "movements) VALUES (%d, %d, %d, %s, %s, 0, %s, %s, NULL, %d, %d, %d, %d, %s)" % (
                       next_phase, self.plan_id, ph["num"], ph["min_green"], ph["max_green"], ph["clearance"],
                       _sql_val(ph.get("walk_time")), ph["ring"], ph["barrier"], ph["position"], node,
                       _sql_val(" ".join(labels.get(ph["num"], [])) or ("ped" if ph.get("walk_time") else ""))))
            for (mid, num), prot in sorted(assign.items()):
                next_pm += 1
                ex("INSERT INTO signal_phase_mvmt (signal_phase_mvmt_id, timing_phase_id, mvmt_id, protection, "
                   "node_id, mvmt_code) VALUES (%d, %d, %d, %s, %d, %s)" % (
                       next_pm, tid[num], mid, _sql_val(prot), node_of[mid], _sql_val(code[mid])))
            ex("UPDATE node SET ctrl_type = 'signal' WHERE node_id IN (%s)" % cluster)
            ids = ",".join(str(i) for i in sig_mv)
            if ids:
                ex("UPDATE movement SET ctrl_type = 'signal' WHERE mvmt_id IN (%s)" % ids)
            ds.CommitTransaction()
        except Exception as e:
            ds.RollbackTransaction()
            QMessageBox.critical(self, "Signal timing", "Not saved: %s" % e)
            return
        finally:
            ds = None
        _reload(self.path)
        self._keep_plan = self.plan_id
        self.load_node()
        self.info.setText(self.info.text() + "  Saved.")

    def remove_signal(self):
        if self.node is None or not self._check_editing():
            return
        if QMessageBox.question(self, "Signal timing",
                                "Remove every timing plan and make node(s) %s unsignalized (movements "
                                "'none')?" % ", ".join(str(c) for c in self.cluster)) != QMessageBox.StandardButton.Yes:
            return
        node = self.node
        cluster = ",".join(str(c) for c in self.cluster)
        ds = _ogr_open(self.path)
        try:
            ex = ds.ExecuteSQL
            ds.StartTransaction()
            ex("DELETE FROM signal_phase_mvmt WHERE timing_phase_id IN (SELECT h.timing_phase_id FROM "
               "signal_timing_phase h JOIN signal_timing_plan p ON p.timing_plan_id = h.timing_plan_id "
               "WHERE p.node_id = %d)" % node)
            ex("DELETE FROM signal_timing_phase WHERE timing_plan_id IN (SELECT timing_plan_id FROM "
               "signal_timing_plan WHERE node_id = %d)" % node)
            ex("DELETE FROM signal_timing_plan WHERE node_id = %d" % node)
            ex("DELETE FROM signal_controller WHERE node_id = %d" % node)
            ex("UPDATE node SET ctrl_type = 'none' WHERE node_id IN (%s)" % cluster)
            ex("UPDATE movement SET ctrl_type = 'none' WHERE node_id IN (%s)" % cluster)
            ds.CommitTransaction()
        except Exception as e:
            ds.RollbackTransaction()
            QMessageBox.critical(self, "Signal timing", "Not removed: %s" % e)
            return
        finally:
            ds = None
        _reload(self.path)
        self.load_node()
