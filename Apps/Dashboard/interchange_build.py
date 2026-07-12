#!/usr/bin/env python3
"""Interchange grouping + link-role classifier (blueprint #3, phase 1).

The limited-access volume dashboard makes an INTERCHANGE the unit of analysis.
This module builds that spine once per network: it groups the network into
interchanges and classifies every nearby link's role, writing

  interchanges.gpkg   layer `interchanges` : one POINT per interchange (at the
                      junction-cluster centroid) with name / route / county and
                      member counts; layer `members` : one row per member link
                      (a_node,b_node, interchange_id, role, direction, ftype,
                      count) as a non-spatial table.
  interchange_members.csv   the same membership table as a plain CSV.

How interchanges are found (data-driven, geometry + FTYPE only):
  * limited-access mainline = FTYPE {11 freeway, 91 toll, 96/97/98 express};
  * ramps = FTYPE {71 service, 72 system};
  * a JUNCTION node lies on both a mainline and a ramp link — that is where a
    ramp meets the freeway. Junction nodes within `radius_m` are unioned into
    one interchange (a diamond/cloverleaf spans several junctions).
  * members gathered per cluster: mainline through-links, on/off/system ramps,
    the ramp-terminal nodes (ramp ends away from the freeway) and the
    cross-street arterials/collectors touching them.
  * name = dominant cross-street ST_NAME/ANAME; route = dominant mainline FNAME;
    direction NB/SB/EB/WB from each link's node geometry.

  python interchange_build.py --links TSM_Link_ML.gpkg --nodes TSM_Node_ML.gpkg
                              [--out interchanges.gpkg] [--radius-m 800]
Coordinates stay in the link CRS (FL Albers meters).
"""
import argparse
import csv
import math
import os
from collections import Counter, defaultdict

from osgeo import ogr, osr

ogr.UseExceptions()

LA_FT = {11, 91, 96, 97, 98}       # limited-access mainline (freeway/toll/EL)
RAMP_FT = {71, 72}                 # 71 service ramp, 72 system (freeway-to-freeway)
SYS_FT = {72}
ART_FT = {21, 31}                  # arterials (div / undiv)
COLL_FT = {41, 45, 48}             # collectors
CROSS_FT = ART_FT | COLL_FT


def _read_nodes(node_gpkg):
    ds = ogr.Open(node_gpkg)
    lyr = ds.GetLayer(0)
    xy, typ = {}, {}
    for f in lyr:
        n = f.GetField("N")
        xy[n] = (f.GetField("X"), f.GetField("Y"))
        typ[n] = f.GetField("DTA_Type")
    ds = None
    return xy, typ


def _read_links(link_gpkg, node_xy):
    """Return list of dicts for every link with the fields the classifier needs."""
    ds = ogr.Open(link_gpkg)
    lyr = ds.GetLayer(0)
    d = lyr.GetLayerDefn()
    names = {d.GetFieldDefn(i).GetName() for i in range(d.GetFieldCount())}
    cnt_f = next((c for c in ("FTI_COUNT_24", "TSMv5.COUNT_24", "COUNT_24") if c in names), None)
    out = []
    for f in lyr:
        try:
            a, b, ft = int(f.GetField("A")), int(f.GetField("B")), int(f.GetField("FTYPE"))
        except (TypeError, ValueError):
            continue
        out.append({
            "a": a, "b": b, "ft": ft,
            "fname": f.GetField("FNAME") or "",
            "st": (f.GetField("ST_NAME") or "").strip(),
            "aname": (f.GetField("ANAME") or "").strip(),
            "nlanes": f.GetField("NLANES") or 0,
            "dist": f.GetField("DISTANCE") or 0.0,
            "count": (f.GetField(cnt_f) or 0.0) if cnt_f else 0.0,
            "cty": f.GetField("to_county") or f.GetField("from_county") or "",
        })
    ds = None
    return out


def _cluster(junctions, xy, radius_m):
    """Union junction nodes within radius_m using a spatial grid (near-linear)."""
    parent = {n: n for n in junctions}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    cell = radius_m
    grid = defaultdict(list)
    for n in junctions:
        x, y = xy[n]
        grid[(int(x // cell), int(y // cell))].append(n)
    r2 = radius_m * radius_m
    for n in junctions:
        x, y = xy[n]
        cx, cy = int(x // cell), int(y // cell)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for m in grid.get((cx + dx, cy + dy), ()):
                    if m <= n:
                        continue
                    ax, ay = xy[m]
                    if (ax - x) ** 2 + (ay - y) ** 2 <= r2:
                        union(n, m)
    clusters = defaultdict(list)
    for n in junctions:
        clusters[find(n)].append(n)
    return list(clusters.values())


def _direction(a, b, xy):
    pa, pb = xy.get(a), xy.get(b)
    if not pa or not pb:
        return ""
    dx, dy = pb[0] - pa[0], pb[1] - pa[1]
    if abs(dy) >= abs(dx):
        return "NB" if dy > 0 else "SB"
    return "EB" if dx > 0 else "WB"


def build(link_gpkg, node_gpkg, out_gpkg=None, radius_m=800.0):
    node_xy, node_type = _read_nodes(node_gpkg)
    links = _read_links(link_gpkg, node_xy)
    out_gpkg = out_gpkg or os.path.join(os.path.dirname(link_gpkg), "interchanges.gpkg")

    # node -> incident links by class
    main_nodes, ramp_nodes = set(), set()
    by_node = defaultdict(list)
    for l in links:
        by_node[l["a"]].append(l); by_node[l["b"]].append(l)
        if l["ft"] in LA_FT:
            main_nodes.add(l["a"]); main_nodes.add(l["b"])
        if l["ft"] in RAMP_FT:
            ramp_nodes.add(l["a"]); ramp_nodes.add(l["b"])
    junctions = [n for n in (main_nodes & ramp_nodes) if n in node_xy]
    clusters = _cluster(junctions, node_xy, radius_m)

    members = []          # (ixid, a, b, role, direction, ftype, count, name)
    ix_rows = []          # (ixid, x, y, name, route, county, n_main, n_ramp, n_cross)
    for ixid, cl in enumerate(sorted(clusters, key=lambda c: -len(c)), 1):
        cset = set(cl)
        xs = [node_xy[n][0] for n in cl]; ys = [node_xy[n][1] for n in cl]
        cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
        seen = set()
        m_links, r_links, x_links = [], [], []
        ramp_terminals = set()
        for n in cl:
            for l in by_node[n]:
                key = (l["a"], l["b"], l["ft"])
                if key in seen:
                    continue
                if l["ft"] in LA_FT and (l["a"] in cset or l["b"] in cset):
                    seen.add(key); m_links.append(l)
                elif l["ft"] in RAMP_FT and (l["a"] in cset or l["b"] in cset):
                    seen.add(key); r_links.append(l)
                    term = l["b"] if l["a"] in main_nodes else l["a"]
                    if term not in main_nodes:
                        ramp_terminals.add(term)
        # cross-streets: non-freeway links at the ramp-terminal intersections
        for t in ramp_terminals:
            for l in by_node[t]:
                if l["ft"] in CROSS_FT:
                    key = (l["a"], l["b"], l["ft"])
                    if key not in seen:
                        seen.add(key); x_links.append(l)
        if not m_links or not r_links:
            continue
        # route = the mainline's ST_NAME (I-95, FLORIDA'S TPKE, ...), which is the
        # real facility; FNAME is only the generic class (Limited/Tolls/ManagedLanes)
        route = Counter(l["st"] for l in m_links if l["st"]).most_common(1)
        route = route[0][0] if route else (
            Counter(l["fname"] for l in m_links if l["fname"]).most_common(1)
            or [("", 0)])[0][0]
        xname = Counter((l["st"] or l["aname"]) for l in x_links
                        if (l["st"] or l["aname"])).most_common(1)
        name = xname[0][0] if xname else (
            Counter(l["st"] for l in m_links if l["st"]).most_common(1) or [("", 0)])[0][0]
        name = name or route or f"IX {ixid}"
        county = (Counter(l["cty"] for l in (m_links + r_links) if l["cty"]).most_common(1)
                  or [("", 0)])[0][0]
        for l in m_links:
            members.append((ixid, l["a"], l["b"], "mainline",
                            _direction(l["a"], l["b"], node_xy), l["ft"], l["count"], route))
        for l in r_links:
            if l["ft"] in SYS_FT:
                role = "system_ramp"
            elif l["a"] in main_nodes:
                role = "off_ramp"
            elif l["b"] in main_nodes:
                role = "on_ramp"
            else:
                role = "ramp"
            members.append((ixid, l["a"], l["b"], role,
                            _direction(l["a"], l["b"], node_xy), l["ft"], l["count"], ""))
        for l in x_links:
            members.append((ixid, l["a"], l["b"], "cross_street",
                            _direction(l["a"], l["b"], node_xy), l["ft"], l["count"],
                            l["st"] or l["aname"]))
        ix_rows.append((ixid, cx, cy, name, route, county,
                        len(m_links), len(r_links), len(x_links)))

    _write(out_gpkg, link_gpkg, ix_rows, members)
    csv_path = os.path.splitext(out_gpkg)[0] + "_members.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["interchange_id", "a_node", "b_node", "role", "direction",
                    "ftype", "count_24", "label"])
        w.writerows(members)
    print(f"[interchanges] {len(ix_rows)} interchanges, {len(members)} member links "
          f"({len(junctions)} junctions, radius {radius_m:.0f} m) -> {out_gpkg}")
    return out_gpkg


def _write(out_gpkg, link_gpkg, ix_rows, members):
    src = ogr.Open(link_gpkg)
    srs = src.GetLayer(0).GetSpatialRef()
    src = None
    drv = ogr.GetDriverByName("GPKG")
    if os.path.exists(out_gpkg):
        drv.DeleteDataSource(out_gpkg)
    ds = drv.CreateDataSource(out_gpkg)
    pt = ds.CreateLayer("interchanges", srs, ogr.wkbPoint)
    for n, t in (("ix_id", ogr.OFTInteger), ("name", ogr.OFTString),
                 ("route", ogr.OFTString), ("county", ogr.OFTString),
                 ("n_mainline", ogr.OFTInteger), ("n_ramps", ogr.OFTInteger),
                 ("n_cross", ogr.OFTInteger)):
        pt.CreateField(ogr.FieldDefn(n, t))
    for ixid, cx, cy, name, route, county, nm, nr, nx in ix_rows:
        f = ogr.Feature(pt.GetLayerDefn())
        f.SetField("ix_id", ixid); f.SetField("name", name); f.SetField("route", route)
        f.SetField("county", county); f.SetField("n_mainline", nm)
        f.SetField("n_ramps", nr); f.SetField("n_cross", nx)
        g = ogr.Geometry(ogr.wkbPoint); g.AddPoint_2D(cx, cy)
        f.SetGeometry(g); pt.CreateFeature(f)
    mt = ds.CreateLayer("members", None, ogr.wkbNone)
    for n, t in (("interchange_id", ogr.OFTInteger), ("a_node", ogr.OFTInteger64),
                 ("b_node", ogr.OFTInteger64), ("role", ogr.OFTString),
                 ("direction", ogr.OFTString), ("ftype", ogr.OFTInteger),
                 ("count_24", ogr.OFTReal), ("label", ogr.OFTString)):
        mt.CreateField(ogr.FieldDefn(n, t))
    for ixid, a, b, role, dr, ft, cnt, lab in members:
        f = ogr.Feature(mt.GetLayerDefn())
        f.SetField("interchange_id", ixid); f.SetField("a_node", a); f.SetField("b_node", b)
        f.SetField("role", role); f.SetField("direction", dr); f.SetField("ftype", ft)
        f.SetField("count_24", float(cnt)); f.SetField("label", lab)
        mt.CreateFeature(f)
    ds = None


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--links", required=True)
    ap.add_argument("--nodes", required=True)
    ap.add_argument("--out")
    ap.add_argument("--radius-m", type=float, default=800.0)
    a = ap.parse_args()
    build(a.links, a.nodes, a.out, a.radius_m)
