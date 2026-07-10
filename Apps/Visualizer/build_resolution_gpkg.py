#!/usr/bin/env python3
"""TSM Visualizer builder: multi-resolution GPKG layers from a HyDRA run.

Network detail splits by tier -- macro = the loaded link layer (one feature
per link, built by Summarization), and this tool adds:

  meso_segments.gpkg   ONE feature per sub-link SEGMENT (the link split at
                       its meso segment boundaries), time-period data as
                       COLUMNS:  veh_<t>, queued_<t>  (+ static storage_veh).
  micro_lanes.gpkg     ONE feature per LANE x link (lane lines offset from
                       the mainline; offsets are computed on the whole
                       corridor chain so lanes stay smooth and parallel
                       across link ends), columns: speed_<t>, density_<t>,
                       flow_<t> (+ static lane, lane_type).

Time columns, NOT time features: the same segment/lane feature carries every
selected period, so link use and lane use by period are compared on one
feature (style by any column; no duplicated geometry). <t> is HHMM of the
period start. Default periods = AM peak hour + two PM peak hours (8,17,18)
at 15-min resolution; --hours all = the whole day hourly (24 columns/var).

INPUTS (from the HyDRA run dir): meso_segment_log.csv (MESO_SEGMENT_LOG YES),
micro_lane_performance.csv + resolution_map.csv (automatic), plus the link
GPKG with A/B fields for geometry (netprep TSM_Link gpkg or a loaded layer).

USAGE
  python build_resolution_gpkg.py --links TSM_Link_ML.gpkg --run-dir exp_x
      [--hours 8,17,18 | --hours all] [--time-res 15|60]
      [--lane-width-ft 12] [--out-dir <dir>]
Importable for the QGIS plugin: build(links, run_dir, hours=..., ...).
"""
import argparse
import csv
import math
import os
import sys
from collections import defaultdict

from osgeo import ogr, osr

ogr.UseExceptions()

NI_DAY = 96  # 15-min intervals in the 24-h day (extended-day intervals fold away)


# ---------------------------------------------------------------- geometry ---
def read_link_lines(gpkg, layer_name=None):
    ds = ogr.Open(gpkg)
    if ds is None:
        sys.exit(f"cannot open {gpkg}")
    lyr = ds.GetLayerByName(layer_name) if layer_name else ds.GetLayer(0)
    defn = lyr.GetLayerDefn()
    names = {defn.GetFieldDefn(i).GetName() for i in range(defn.GetFieldCount())}
    a_field = next((c for c in ("A", "a", "a_node", "A_NODE") if c in names), None)
    b_field = next((c for c in ("B", "b", "b_node", "B_NODE") if c in names), None)
    if not a_field or not b_field:
        sys.exit(f"no A/B fields in {gpkg}")
    srs = lyr.GetSpatialRef()
    lines = {}
    for f in lyr:
        g = f.GetGeometryRef()
        if g is None:
            continue
        if g.GetGeometryType() in (ogr.wkbMultiLineString, ogr.wkbMultiLineString25D):
            g = g.GetGeometryRef(0)
        pts = [(g.GetX(i), g.GetY(i)) for i in range(g.GetPointCount())]
        if len(pts) >= 2:
            lines[(int(f.GetField(a_field)), int(f.GetField(b_field)))] = pts
    wkt = srs.ExportToWkt() if srs else None
    ft_to_unit = 0.3048 / srs.GetLinearUnits() if srs and srs.GetLinearUnits() else 1.0
    ds = None
    return lines, wkt, ft_to_unit


def line_length(pts):
    return sum(math.hypot(x2 - x1, y2 - y1)
               for (x1, y1), (x2, y2) in zip(pts, pts[1:]))


def substring(pts, f0, f1):
    total = line_length(pts)
    if total <= 0:
        return pts[:2]
    d0, d1 = max(0.0, f0) * total, min(1.0, f1) * total
    out, acc = [], 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        seg = math.hypot(x2 - x1, y2 - y1)
        if seg <= 0:
            continue
        lo, hi = acc, acc + seg
        if hi >= d0 and lo <= d1:
            t0 = max(0.0, (d0 - lo) / seg)
            t1 = min(1.0, (d1 - lo) / seg)
            p0 = (x1 + (x2 - x1) * t0, y1 + (y2 - y1) * t0)
            p1 = (x1 + (x2 - x1) * t1, y1 + (y2 - y1) * t1)
            if not out or out[-1] != p0:
                out.append(p0)
            out.append(p1)
        acc = hi
    return out if len(out) >= 2 else pts[:2]


def offset_line(pts, dist):
    """Perpendicular offset (left of travel = +dist), averaged joint normals."""
    if len(pts) < 2:
        return pts
    out, n = [], len(pts)
    for i in range(n):
        if i == 0:
            dx, dy = pts[1][0] - pts[0][0], pts[1][1] - pts[0][1]
        elif i == n - 1:
            dx, dy = pts[-1][0] - pts[-2][0], pts[-1][1] - pts[-2][1]
        else:
            dx = pts[i + 1][0] - pts[i - 1][0]
            dy = pts[i + 1][1] - pts[i - 1][1]
        ln = math.hypot(dx, dy) or 1.0
        out.append((pts[i][0] - dy / ln * dist, pts[i][1] + dx / ln * dist))
    return out


def dedupe(pts, tol=1e-6):
    out = [pts[0]]
    for p in pts[1:]:
        if math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > tol:
            out.append(p)
    return out


def make_line(pts):
    g = ogr.Geometry(ogr.wkbLineString)
    for x, y in pts:
        g.AddPoint_2D(x, y)
    return g


def create_layer(out_path, name, srs_wkt, fields):
    drv = ogr.GetDriverByName("GPKG")
    if os.path.exists(out_path):
        try:
            drv.DeleteDataSource(out_path)
        except Exception:
            pass
        if os.path.exists(out_path):
            try:
                os.remove(out_path)
            except OSError:
                sys.exit(f"{out_path} exists and is locked (open in QGIS?) -- "
                         "close it or pass a different --out-dir")
    ds = drv.CreateDataSource(out_path)
    srs = osr.SpatialReference()
    if srs_wkt:
        srs.ImportFromWkt(srs_wkt)
    lyr = ds.CreateLayer(name, srs if srs_wkt else None, ogr.wkbLineString)
    for fname, ftype in fields:
        lyr.CreateField(ogr.FieldDefn(fname, ftype))
    return ds, lyr


# ------------------------------------------------------------ time periods ---
def build_periods(hours, time_res):
    """[(column suffix HHMM, [15-min interval indices])] for the selected hours."""
    if hours == "all":
        hrs, res = range(24), 60 if time_res is None else time_res
    else:
        hrs = sorted({int(h) for h in str(hours).split(",")})
        res = 15 if time_res is None else time_res
    periods = []
    for h in hrs:
        if res == 60:
            periods.append((f"{h:02d}00", [h * 4 + q for q in range(4)]))
        else:
            for q in range(4):
                periods.append((f"{h:02d}{q * 15:02d}", [h * 4 + q]))
    return periods


# ------------------------------------------------------------ meso segments ---
def build_meso_segments(run_dir, lines, srs_wkt, out_path, periods):
    log = os.path.join(run_dir, "meso_segment_log.csv")
    if not os.path.exists(log):
        print(f"[skip] {log} not found (run with MESO_SEGMENT_LOG YES)")
        return None
    # seg -> static info + per-interval (veh, queued); intervals 0..95 only.
    veh = defaultdict(dict)
    info = {}
    len_mi = defaultdict(float)
    with open(log, newline="") as f:
        for r in csv.DictReader(f):
            a, b, si = int(r["a_node"]), int(r["b_node"]), int(r["seg_idx"])
            itv = int(r["interval"])
            e = float(r["end_mi"])
            len_mi[(a, b)] = max(len_mi[(a, b)], e)
            key = (a, b, si)
            info[key] = (int(r["ftype"]), float(r["start_mi"]), e,
                         float(r["storage_veh"]))
            if itv < NI_DAY:
                veh[key][itv] = (float(r["veh"]), max(0.0, float(r["queued_veh"])))
    fields = [("a_node", ogr.OFTInteger64), ("b_node", ogr.OFTInteger64),
              ("ftype", ogr.OFTInteger), ("seg_idx", ogr.OFTInteger),
              ("start_mi", ogr.OFTReal), ("end_mi", ogr.OFTReal),
              ("storage_veh", ogr.OFTReal), ("veh_max", ogr.OFTReal),
              ("queued_max", ogr.OFTReal)]
    for suf, _ in periods:
        fields += [(f"veh_{suf}", ogr.OFTReal), (f"queued_{suf}", ogr.OFTReal)]
    ds, lyr = create_layer(out_path, "meso_segments", srs_wkt, fields)
    lyr.StartTransaction()
    n, miss = 0, set()
    for key, itvs in veh.items():
        a, b, si = key
        pts = lines.get((a, b))
        if pts is None:
            miss.add((a, b))
            continue
        ftype, s_mi, e_mi, storage = info[key]
        L = len_mi[(a, b)] or 1.0
        feat = ogr.Feature(lyr.GetLayerDefn())
        feat.SetField("a_node", a); feat.SetField("b_node", b)
        feat.SetField("ftype", ftype); feat.SetField("seg_idx", si)
        feat.SetField("start_mi", s_mi); feat.SetField("end_mi", e_mi)
        feat.SetField("storage_veh", storage)
        feat.SetField("veh_max", max((v for v, _ in itvs.values()), default=0.0))
        feat.SetField("queued_max", max((q for _, q in itvs.values()), default=0.0))
        for suf, idxs in periods:
            vals = [itvs.get(i, (0.0, 0.0)) for i in idxs]
            feat.SetField(f"veh_{suf}", sum(v for v, _ in vals) / len(vals))
            feat.SetField(f"queued_{suf}", sum(q for _, q in vals) / len(vals))
        feat.SetGeometry(make_line(substring(pts, s_mi / L, e_mi / L)))
        lyr.CreateFeature(feat)
        n += 1
    lyr.CommitTransaction()
    ds = None
    print(f"[meso_segments] {n} features ({len(periods)} periods x 2 columns) -> {out_path}"
          + (f" ({len(miss)} log links missing geometry)" if miss else ""))
    return out_path


# -------------------------------------------------------------- micro lanes ---
def build_micro_lanes(run_dir, lines, srs_wkt, out_path, periods, lane_w_units):
    perf = os.path.join(run_dir, "micro_lane_performance.csv")
    rmap = os.path.join(run_dir, "resolution_map.csv")
    if not (os.path.exists(perf) and os.path.exists(rmap)):
        print(f"[skip] micro: need {os.path.basename(perf)} + {os.path.basename(rmap)}")
        return None
    micro = []
    with open(rmap, newline="") as f:
        for r in csv.DictReader(f):
            if r["tier"] == "MICRO":
                micro.append((int(r["a_node"]), int(r["b_node"])))
    # lane x interval -> (speed, density, flow); intervals 0..95.
    lane_t = {}
    dat = defaultdict(dict)
    with open(perf, newline="") as f:
        for r in csv.DictReader(f):
            itv = int(r["interval"])
            if itv >= NI_DAY:
                continue
            L = int(r["lane"])
            lane_t[L] = r["lane_type"]
            dat[L][itv] = (float(r["speed_mph"]), float(r["density_vpmpl"]),
                           float(r["flow_vph"]))
    if not dat:
        print("[skip] micro_lane_performance.csv empty")
        return None
    n_lanes = max(dat) + 1

    # Chain the micro links into the corridor mainline so lane offsets are
    # computed ONCE on the continuous polyline (smooth, parallel across link
    # ends), then cut back into per-link spans. Links that don't chain (spurs)
    # fall back to per-link offsets.
    nxt = {a: (a, b) for a, b in micro}
    is_to = {b for _, b in micro}
    starts = [k for k in micro if k[0] not in is_to]
    chains, used = [], set()
    for s in starts or micro[:1]:
        chain, cur = [], s
        while cur and cur not in used:
            used.add(cur)
            chain.append(cur)
            cur = nxt.get(cur[1])
        if chain:
            chains.append(chain)
    leftovers = [k for k in micro if k not in used]

    fields = [("a_node", ogr.OFTInteger64), ("b_node", ogr.OFTInteger64),
              ("lane", ogr.OFTInteger), ("lane_type", ogr.OFTString)]
    for suf, _ in periods:
        fields += [(f"speed_{suf}", ogr.OFTReal), (f"density_{suf}", ogr.OFTReal),
                   (f"flow_{suf}", ogr.OFTReal)]
    ds, lyr = create_layer(out_path, "micro_lanes", srs_wkt, fields)
    lyr.StartTransaction()

    def emit(a, b, seg_pts):
        for L in range(n_lanes):
            off = (L - (n_lanes - 1) / 2.0) * lane_w_units
            lane_pts = offset_line(seg_pts, off)
            feat = ogr.Feature(lyr.GetLayerDefn())
            feat.SetField("a_node", a); feat.SetField("b_node", b)
            feat.SetField("lane", L)
            feat.SetField("lane_type", lane_t.get(L, "GP"))
            for suf, idxs in periods:
                vals = [dat[L].get(i) for i in idxs if dat[L].get(i)]
                if vals:
                    fw = sum(v[2] for v in vals)
                    spd = (sum(v[0] * v[2] for v in vals) / fw if fw > 0
                           else sum(v[0] for v in vals) / len(vals))
                    feat.SetField(f"speed_{suf}", spd)
                    feat.SetField(f"density_{suf}", sum(v[1] for v in vals) / len(vals))
                    feat.SetField(f"flow_{suf}", fw / len(vals))
            feat.SetGeometry(make_line(lane_pts))
            lyr.CreateFeature(feat)

    n, miss = 0, set()
    for chain in chains:
        pts_all, cuts = [], [0.0]  # cumulative length fraction at each link end
        for (a, b) in chain:
            pts = lines.get((a, b))
            if pts is None:
                miss.add((a, b))
                continue
            pts_all += pts if not pts_all else pts[0 if pts[0] != pts_all[-1] else 1:]
            cuts.append(line_length(pts_all))
        if len(pts_all) < 2:
            continue
        pts_all = dedupe(pts_all)
        total = line_length(pts_all)
        for i, (a, b) in enumerate(chain):
            if (a, b) in miss or i + 1 >= len(cuts):
                continue
            seg_pts = substring(pts_all, cuts[i] / total, cuts[i + 1] / total)
            emit(a, b, seg_pts)
            n += n_lanes
    for (a, b) in leftovers:
        pts = lines.get((a, b))
        if pts is None:
            miss.add((a, b))
            continue
        emit(a, b, dedupe(pts))
        n += n_lanes
    lyr.CommitTransaction()
    ds = None
    print(f"[micro_lanes] {n} features ({n_lanes} lanes, {len(chains)} chain(s), "
          f"{len(periods)} periods x 3 columns) -> {out_path}"
          + (f" ({len(miss)} links missing geometry)" if miss else ""))
    return out_path


# --------------------------------------------------------------------- API ---
def build(links, run_dir, layer=None, out_dir=None, hours="8,17,18",
          time_res=None, lane_width_ft=12.0, do_meso=True, do_micro=True):
    """Programmatic entry (used by the tsm_panel Visualizer dialog).
    Returns {'meso': path|None, 'micro': path|None}."""
    out_dir = out_dir or run_dir
    os.makedirs(out_dir, exist_ok=True)
    periods = build_periods(hours, time_res)
    lines, srs_wkt, ft_to_unit = read_link_lines(links, layer)
    print(f"[links] {len(lines)} geometries | {len(periods)} time columns/variable")
    res = {"meso": None, "micro": None}
    if do_meso:
        res["meso"] = build_meso_segments(
            run_dir, lines, srs_wkt, os.path.join(out_dir, "meso_segments.gpkg"),
            periods)
    if do_micro:
        res["micro"] = build_micro_lanes(
            run_dir, lines, srs_wkt, os.path.join(out_dir, "micro_lanes.gpkg"),
            periods, lane_width_ft * ft_to_unit)
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--links", required=True)
    ap.add_argument("--layer", default=None)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--hours", default="8,17,18",
                    help='comma hours (default "8,17,18" = AM + 2 PM peaks) or "all"')
    ap.add_argument("--time-res", type=int, choices=(15, 60), default=None,
                    help="column resolution in minutes (default: 15 for chosen hours, 60 for all)")
    ap.add_argument("--lane-width-ft", type=float, default=12.0)
    ap.add_argument("--no-meso", action="store_true")
    ap.add_argument("--no-micro", action="store_true")
    a = ap.parse_args()
    build(a.links, a.run_dir, a.layer, a.out_dir, a.hours, a.time_res,
          a.lane_width_ft, not a.no_meso, not a.no_micro)


if __name__ == "__main__":
    main()
