#!/usr/bin/env python3
"""Micro lane AERIAL visualizer (blueprint phase 1).

Turns the micro corridor into true-width lane RIBBONS (filled polygons) instead
of the schematic offset lines in build_resolution_gpkg.py, so the lanes read as
real pavement over aerial imagery: general-purpose lanes centered on the
roadway, a painted BUFFER, then the express lanes on the median side, colored by
per-lane speed / density / flow per time period.

Why no GMNS / no consolidation utility is needed here
-----------------------------------------------------
`dta_micro` is marked on the CONSOLIDATED network, but netPrep emits the GMNS
lane/segment files from the pre-consolidation GeoMaster (keyed by GeoMaster
link_id, and today only a flat 12 ft width). Reconciling GeoMaster GMNS through
the Many_to_One_lookup to the consolidated corridor is fragile and adds nothing
while widths are flat. Instead phase 1 reads the SAME consolidated links the
user tagged: `resolution_map.csv` (written every run) carries `lanes` and
`ftype` per micro link, which is the true lane count and the GP/EL distinction.
Lane counts vary link to link (real lane adds/drops), so the cross-section is
data-driven from the network the corridor was actually defined on.

A GMNS reconciler utility (GMNS_MICRO_RECONCILE) becomes worthwhile only once
netPrep codes REAL per-lane widths and lane types and a consolidation-aware
GMNS -- see MICRO_LANE_AERIAL_BLUEPRINT.md phase 2. This module accepts an
optional lane-config override file for a study corridor in the meantime.

Output: micro_lanes_aerial.gpkg with layers
  lane_ribbons  polygon per lane x link, columns speed_/density_/flow_<HHMM>
  lane_markings line per lane boundary, `marking` = dashed|edge|buffer
Coordinates in the link layer's CRS (FL Albers meters); widths given in feet.
"""
import argparse
import csv
import math
import os
from collections import defaultdict

from osgeo import ogr, osr

# reuse geometry helpers from the schematic builder
from build_resolution_gpkg import (read_link_lines, line_length, substring,
                                    offset_line, dedupe, make_line, build_periods)

ogr.UseExceptions()
NI_DAY = 96
FT_PER_MI = 5280.0


def make_polygon(left_pts, right_pts):
    """Ribbon polygon from a left edge and a right edge (right reversed)."""
    ring = ogr.Geometry(ogr.wkbLinearRing)
    for x, y in left_pts:
        ring.AddPoint_2D(x, y)
    for x, y in reversed(right_pts):
        ring.AddPoint_2D(x, y)
    ring.AddPoint_2D(left_pts[0][0], left_pts[0][1])  # close
    poly = ogr.Geometry(ogr.wkbPolygon)
    poly.AddGeometry(ring)
    return poly


def chain_micro_gp(lines, micro_gp, node_xy):
    """Chain the GP mainline micro links head-to-tail (travel direction) into a
    single oriented spine; return the ordered [(a,b)] and per-link station span."""
    nxt = {a: (a, b) for a, b in micro_gp}
    is_to = {b for _, b in micro_gp}
    starts = [k for k in micro_gp if k[0] not in is_to] or micro_gp[:1]
    used, chains = set(), []
    for s in starts:
        chain, cur = [], s
        while cur and cur not in used:
            used.add(cur); chain.append(cur); cur = nxt.get(cur[1])
        if chain:
            chains.append(chain)
    chains.sort(key=len, reverse=True)
    return chains[0] if chains else []


def oriented_pts(a, b, lines, node_xy):
    pts = lines.get((a, b))
    if pts is None:
        return None
    na, nb = node_xy.get(a), node_xy.get(b)
    if na and nb:
        if math.hypot(pts[0][0] - nb[0], pts[0][1] - nb[1]) < \
           math.hypot(pts[0][0] - na[0], pts[0][1] - na[1]):
            return pts[::-1]
    return pts


def build_aerial(links_gpkg, run_dir, out_path, layer=None, hours="8,17,18",
                 time_res=None, lane_width_ft=12.0, buffer_ft=4.0):
    lines, srs_wkt, ft_to_unit = read_link_lines(links_gpkg, layer)
    lane_w = lane_width_ft * ft_to_unit
    buf_w = buffer_ft * ft_to_unit
    periods = build_periods(hours, time_res)

    # node coords for orientation (recurring link endpoints)
    ep = defaultdict(lambda: defaultdict(int))
    for (a, b), pts in lines.items():
        for nd, p in ((a, pts[0]), (b, pts[-1]), (a, pts[-1]), (b, pts[0])):
            ep[nd][(round(p[0], 1), round(p[1], 1))] += 1
    node_xy = {n: max(c, key=c.get) for n, c in ep.items()}

    # micro links + lane counts from resolution_map (lanes, ftype)
    rmap = os.path.join(run_dir, "resolution_map.csv")
    if not os.path.exists(rmap):
        raise SystemExit(f"need {rmap} (written every run with MICRO links)")
    gp_links, el_links = [], []       # (a,b) ; and (a,b,lanes)
    lanes_of = {}
    for r in _rows(rmap):
        if r["tier"] != "MICRO":
            continue
        a, b, ft, nl = int(r["a_node"]), int(r["b_node"]), int(r["ftype"]), int(r["lanes"])
        lanes_of[(a, b)] = (ft, nl)
        if ft == 11:
            gp_links.append((a, b))
        elif ft in (96, 97, 98):
            el_links.append((a, b))

    # per-lane performance (index/type) -> period value
    perf = _lane_perf(os.path.join(run_dir, "micro_lane_performance.csv"), periods)

    # spine = chained GP mainline
    chain = chain_micro_gp(lines, gp_links, node_xy)
    if not chain:
        raise SystemExit("no GP mainline chain among the micro links")

    # EL lane count that parallels the corridor: max EL lanes over the corridor
    # (phase 1 places a uniform EL bank on the median; per-station EL geometry is
    # phase 2). first_el_lane index follows the widest GP section.
    max_gp = max((lanes_of[k][1] for k in gp_links), default=1)
    max_el = max((lanes_of[k][1] for k in el_links), default=0)

    # ---- layers ----
    ribbon_fields = [("a_node", ogr.OFTInteger64), ("b_node", ogr.OFTInteger64),
                     ("lane", ogr.OFTInteger), ("lane_type", ogr.OFTString),
                     ("width_ft", ogr.OFTReal)]
    for suf, _ in periods:
        ribbon_fields += [(f"speed_{suf}", ogr.OFTReal),
                          (f"density_{suf}", ogr.OFTReal), (f"flow_{suf}", ogr.OFTReal)]
    drv = ogr.GetDriverByName("GPKG")
    if os.path.exists(out_path):
        try: drv.DeleteDataSource(out_path)
        except Exception: os.remove(out_path)
    ds = drv.CreateDataSource(out_path)
    srs = osr.SpatialReference()
    if srs_wkt: srs.ImportFromWkt(srs_wkt)
    rib = ds.CreateLayer("lane_ribbons", srs if srs_wkt else None, ogr.wkbPolygon)
    for n, t in ribbon_fields: rib.CreateField(ogr.FieldDefn(n, t))
    mrk = ds.CreateLayer("lane_markings", srs if srs_wkt else None, ogr.wkbLineString)
    for n, t in (("kind", ogr.OFTString),): mrk.CreateField(ogr.FieldDefn(n, t))

    # lane center offset (left of travel = +) relative to the spine.
    # GP lanes centered on the spine; buffer; EL bank on the median (left).
    def gp_center(i, gp):          # i = 0 rightmost
        return (i - (gp - 1) / 2.0) * lane_w
    def gp_left_edge(gp):
        return gp_center(gp - 1, gp) + lane_w / 2.0
    def el_center(j, gp):          # j = 0 nearest buffer
        return gp_left_edge(gp) + buf_w + (j + 0.5) * lane_w

    rib.StartTransaction()
    n_ribbon = 0
    for (a, b) in chain:
        seg = oriented_pts(a, b, lines, node_xy)
        if seg is None or len(seg) < 2:
            continue
        seg = dedupe(seg)
        gp = lanes_of[(a, b)][1]
        # GP ribbons
        for i in range(gp):
            _emit_ribbon(rib, ribbon_fields, seg, gp_center(i, gp), lane_w,
                         a, b, i, "GP", lane_width_ft, periods, perf); n_ribbon += 1
        # EL ribbons (uniform bank; phase-1 places max_el lanes alongside)
        for j in range(max_el):
            _emit_ribbon(rib, ribbon_fields, seg, el_center(j, gp), lane_w,
                         a, b, max_gp + j, "EL", lane_width_ft, periods, perf); n_ribbon += 1
        # markings: GP dashed separators, edge lines, and the EL buffer band
        for i in range(1, gp):
            _emit_line(mrk, offset_line(seg, gp_center(i, gp) - lane_w / 2.0), "dashed")
        _emit_line(mrk, offset_line(seg, gp_center(0, gp) - lane_w / 2.0), "edge")
        if max_el > 0:
            _emit_line(mrk, offset_line(seg, gp_left_edge(gp) + buf_w / 2.0), "buffer")
            _emit_line(mrk, offset_line(seg, el_center(max_el - 1, gp) + lane_w / 2.0), "edge")
    rib.CommitTransaction()
    ds = None
    print(f"[aerial] {n_ribbon} lane ribbons ({len(chain)} links, {max_gp} GP + "
          f"{max_el} EL lanes, {len(periods)} periods) -> {out_path}")
    return out_path


def _emit_ribbon(layer, fields, seg, center, w, a, b, lane, ltype, wft, periods, perf):
    left = offset_line(seg, center + w / 2.0)
    right = offset_line(seg, center - w / 2.0)
    if len(left) < 2 or len(right) < 2:
        return
    feat = ogr.Feature(layer.GetLayerDefn())
    feat.SetField("a_node", a); feat.SetField("b_node", b)
    feat.SetField("lane", lane); feat.SetField("lane_type", ltype)
    feat.SetField("width_ft", wft)
    for suf, idxs in periods:
        s, d, fl = perf.get((lane, suf)) or perf.get((ltype, suf)) or (None, None, None)
        if s is not None:
            feat.SetField(f"speed_{suf}", s); feat.SetField(f"density_{suf}", d)
            feat.SetField(f"flow_{suf}", fl)
    feat.SetGeometry(make_polygon(left, right))
    layer.CreateFeature(feat)


def _emit_line(layer, pts, kind):
    if len(pts) < 2:
        return
    feat = ogr.Feature(layer.GetLayerDefn())
    feat.SetField("kind", kind)
    feat.SetGeometry(make_line(pts))
    layer.CreateFeature(feat)


def _rows(path):
    with open(path, newline="") as f:
        yield from csv.DictReader(f)


def _lane_perf(path, periods):
    """(lane_index or lane_type, period) -> (speed, density, flow), flow-weighted."""
    if not os.path.exists(path):
        return {}
    acc = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])  # spd*flow, dens, flow, n
    typ = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    itv_of = {suf: idxs for suf, idxs in periods}
    for r in _rows(path):
        itv = int(r["interval"])
        for suf, idxs in periods:
            if itv in idxs:
                fl = float(r["flow_vph"]); sp = float(r["speed_mph"]); de = float(r["density_vpmpl"])
                for key in ((int(r["lane"]), suf), (r["lane_type"], suf)):
                    tgt = acc if isinstance(key[0], int) else typ
                    v = tgt[key]; v[0] += sp * fl; v[1] += de; v[2] += fl; v[3] += 1
    out = {}
    for tgt in (acc, typ):
        for k, v in tgt.items():
            spd = v[0] / v[2] if v[2] > 0 else (v[0] / v[3] if v[3] else 0)
            out[k] = (round(spd, 1), round(v[1] / v[3], 1) if v[3] else 0,
                      round(v[2] / v[3], 0) if v[3] else 0)
    return out


def build(links, run_dir, out_dir=None, layer=None, hours="8,17,18",
          time_res=None, lane_width_ft=12.0, buffer_ft=4.0):
    out_dir = out_dir or run_dir
    os.makedirs(out_dir, exist_ok=True)
    return build_aerial(links, run_dir, os.path.join(out_dir, "micro_lanes_aerial.gpkg"),
                        layer, hours, time_res, lane_width_ft, buffer_ft)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--links", required=True)
    ap.add_argument("--layer", default=None)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--hours", default="8,17,18")
    ap.add_argument("--time-res", type=int, choices=(15, 60), default=None)
    ap.add_argument("--lane-width-ft", type=float, default=12.0)
    ap.add_argument("--buffer-ft", type=float, default=4.0)
    a = ap.parse_args()
    build(a.links, a.run_dir, a.out_dir, a.layer, a.hours, a.time_res,
          a.lane_width_ft, a.buffer_ft)


if __name__ == "__main__":
    main()
