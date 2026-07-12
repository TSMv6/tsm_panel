#!/usr/bin/env python3
"""Interchange volume aggregation + Excel workbook (blueprint #3, phase 2).

Given the interchange spine (interchanges.gpkg + members from phase 1) and a
HyDRA run, aggregate mainline / ramp / cross-street volumes per interchange and
write the planner deliverable:

  interchange_volumes.xlsx
    Summary          one row per interchange -- route, cross-street, county,
                     mainline AADT (both directions), total ramp volume, model
                     vs count on the mainline, worst v/c.
    <interchange>    one detail sheet per interchange (capped): mainline table
                     (by direction: daily / AM / PM volume, speed, count),
                     ramp table (each on/off/system ramp), cross-street table.
  interchange_volumes.csv   the flat summary (also feeds the HTML dashboard).

Volumes come from link_performance_{macro,meso,micro}DTA.csv (disjoint by tier)
-- daily = Σ volume over the 24 h, AM = hour 8, PM = hour 17, speed =
volume-weighted mean, toll = mean toll_rate. Counts come from the member table
(FTI_COUNT_24 carried from the link GPKG). No new engine output is required.

  python interchange_volumes.py --run-dir <dir> --interchanges interchanges.gpkg
      [--out interchange_volumes.xlsx] [--max-detail 40]
      [--county Broward] [--route I-95] [--am-hour 8] [--pm-hour 17]
"""
import argparse
import os

import numpy as np
import pandas as pd

NI = 96


def _link_perf(run_dir, am_hour, pm_hour):
    """(a,b) -> daily/AM/PM volume, vol-weighted speed, mean toll, across the
    three disjoint tiers."""
    frames = []
    for tier in ("macro", "meso", "micro"):
        fp = os.path.join(run_dir, f"link_performance_{tier}DTA.csv")
        if not os.path.exists(fp):
            continue
        cols = ["a_node", "b_node", "hour", "interval", "volume",
                "speed_mph", "toll_rate"]
        df = pd.read_csv(fp, usecols=lambda c: c in cols)
        df = df[df["interval"] < NI]
        # guard against garbage link speeds (tiny travel time -> 100+ mph) that
        # would dominate the volume-weighted mean; nothing legit exceeds ~85 mph.
        df["speed_mph"] = df["speed_mph"].clip(0, 85)
        df["vs"] = df["volume"] * df["speed_mph"]
        g = df.groupby(["a_node", "b_node"]).agg(
            daily=("volume", "sum"), vs=("vs", "sum"),
            vol=("volume", "sum"),
            toll=("toll_rate", "max") if "toll_rate" in df else ("volume", "size"))
        am = df[df["hour"] == am_hour].groupby(["a_node", "b_node"])["volume"].sum()
        pm = df[df["hour"] == pm_hour].groupby(["a_node", "b_node"])["volume"].sum()
        g["am"] = am; g["pm"] = pm
        g["speed"] = g["vs"] / g["vol"].replace(0, np.nan)
        frames.append(g[["daily", "am", "pm", "speed", "toll"]])
    if not frames:
        return pd.DataFrame(columns=["daily", "am", "pm", "speed", "toll"])
    allg = pd.concat(frames)
    # a link is in exactly one tier, so no cross-tier dup; guard anyway
    allg = allg[~allg.index.duplicated(keep="first")]
    return allg.fillna(0.0)


def _members(interchanges_gpkg):
    from osgeo import ogr
    ds = ogr.Open(interchanges_gpkg)
    ml = ds.GetLayerByName("members")
    rows = [{"ix": f["interchange_id"], "a": f["a_node"], "b": f["b_node"],
             "role": f["role"], "direction": f["direction"], "ftype": f["ftype"],
             "count": f["count_24"], "label": f["label"] or ""} for f in ml]
    pt = ds.GetLayerByName("interchanges")
    ix = {f["ix_id"]: {"name": f["name"] or "", "route": f["route"] or "",
                       "county": f["county"] or "",
                       "n_ramps": f["n_ramps"]} for f in pt}
    ds = None
    return pd.DataFrame(rows), ix


def aggregate(run_dir, interchanges_gpkg, am_hour=8, pm_hour=17):
    perf = _link_perf(run_dir, am_hour, pm_hour)
    mem, ix = _members(interchanges_gpkg)
    if mem.empty:
        raise SystemExit("no members in interchanges.gpkg (run phase 1 first)")
    key = list(zip(mem["a"], mem["b"]))
    for col in ("daily", "am", "pm", "speed", "toll"):
        mem[col] = [perf[col].get((a, b), 0.0) if (a, b) in perf.index else 0.0
                    for a, b in key]
    return mem, ix


def _dir_of(role):
    return role


def summarize(mem, ix):
    """One summary row per interchange."""
    EL_FT = {96, 97, 98}
    rows = []
    for ixid, g in mem.groupby("ix"):
        info = ix.get(ixid, {})
        mn = g[g["role"] == "mainline"]
        rmp = g[g["role"].isin(["on_ramp", "off_ramp", "system_ramp"])]
        crs = g[g["role"] == "cross_street"]
        # mainline AADT = a representative two-way cross-section, NOT the sum over
        # every member link (which double-counts sequential segments): per travel
        # direction take the MEDIAN daily of the general-purpose links plus the
        # median of the express-lane links, then sum the directions.
        aadt = 0.0
        for _dir, gd in mn.groupby("direction"):
            gp = gd[~gd["ftype"].isin(EL_FT)]
            el = gd[gd["ftype"].isin(EL_FT)]
            aadt += (gp["daily"].median() if len(gp) else 0.0)
            aadt += (el["daily"].median() if len(el) else 0.0)
        cnt = mn[mn["count"] > 0]["count"].sum()
        model_on_cnt = mn[mn["count"] > 0]["daily"].sum()
        ratio = (model_on_cnt / cnt) if cnt > 0 else np.nan
        rows.append({
            "ix_id": ixid, "route": info.get("route", ""),
            "cross_street": info.get("name", ""), "county": info.get("county", ""),
            "mainline_AADT": round(aadt),
            "mainline_speed": round(mn["daily"].mul(mn["speed"]).sum() /
                                    max(mn["daily"].sum(), 1e-9), 1),
            "ramp_vol": round(rmp["daily"].sum()),
            "n_on": int((rmp["role"] == "on_ramp").sum()),
            "n_off": int((rmp["role"] == "off_ramp").sum()),
            "n_sys": int((rmp["role"] == "system_ramp").sum()),
            "cross_vol": round(crs["daily"].sum()),
            "mainline_count": round(cnt) if cnt else "",
            "model_obs": round(ratio, 2) if not np.isnan(ratio) else "",
            "toll_peak": round(mn["toll"].max(), 2) if mn["toll"].max() > 0 else "",
        })
    df = pd.DataFrame(rows).sort_values("mainline_AADT", ascending=False)
    return df


# ------------------------------------------------------------------ workbook --
def _hdr(ws, cols, row=1, bold=True):
    from openpyxl.styles import Font
    for j, c in enumerate(cols, 1):
        cell = ws.cell(row=row, column=j, value=c)
        if bold:
            cell.font = Font(bold=True)


def _fit(ws, cols):
    for j, c in enumerate(cols, 1):
        ws.column_dimensions[chr(64 + j) if j <= 26 else "A" + chr(38 + j)].width = \
            max(11, len(str(c)) + 2)


def write_workbook(summary, mem, ix, out_xlsx, max_detail=40,
                   county=None, route=None):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws["A1"] = "Interchange Volumes — HyDRA"
    ws["A1"].font = Font(bold=True, size=13)
    cols = ["ix_id", "route", "cross_street", "county", "mainline_AADT",
            "mainline_speed", "ramp_vol", "n_on", "n_off", "n_sys",
            "cross_vol", "mainline_count", "model_obs", "toll_peak"]
    _hdr(ws, cols, row=3)
    for i, (_, r) in enumerate(summary.iterrows(), 4):
        for j, c in enumerate(cols, 1):
            ws.cell(row=i, column=j, value=r[c])
        # color the model/obs cell
        mo = r["model_obs"]
        if isinstance(mo, (int, float)) and mo != "":
            d = abs(mo - 1.0)
            col = "C6EFCE" if d <= 0.10 else ("FFEB9C" if d <= 0.20 else "FFC7CE")
            ws.cell(row=i, column=13).fill = PatternFill("solid", fgColor=col)
    ws.freeze_panes = "A4"
    for j, c in enumerate(cols, 1):
        ws.column_dimensions[ws.cell(row=3, column=j).column_letter].width = \
            max(11, len(c) + 2)

    # detail sheets for the filtered / top-N set
    sel = summary
    if county:
        sel = sel[sel["county"].str.contains(county, case=False, na=False)]
    if route:
        sel = sel[sel["route"].str.contains(route, case=False, na=False)]
    sel = sel.head(max_detail)
    used = set()
    for _, r in sel.iterrows():
        ixid = r["ix_id"]
        g = mem[mem["ix"] == ixid]
        base = f"{r['route']} @ {r['cross_street']}".strip(" @")[:26] or f"IX{ixid}"
        name = base
        k = 2
        while name.lower() in used:
            name = f"{base[:23]}~{k}"; k += 1
        used.add(name.lower())
        try:
            sh = wb.create_sheet(name)
        except Exception:
            sh = wb.create_sheet(f"IX{ixid}")
        sh["A1"] = f"Interchange {ixid} — {r['route']} @ {r['cross_street']} ({r['county']})"
        sh["A1"].font = Font(bold=True, size=12)
        row = 3
        for title, roles in (("Mainline", ["mainline"]),
                             ("Ramps", ["on_ramp", "off_ramp", "system_ramp"]),
                             ("Cross-streets", ["cross_street"])):
            sub = g[g["role"].isin(roles)]
            sh.cell(row=row, column=1, value=title).font = Font(bold=True)
            row += 1
            dcols = ["role", "direction", "a", "b", "daily", "am", "pm",
                     "speed", "toll", "count", "label"]
            _hdr(sh, ["ROLE", "DIR", "A_NODE", "B_NODE", "DAILY", "AM", "PM",
                      "SPEED", "TOLL", "COUNT", "LABEL"], row=row)
            row += 1
            for _, m in sub.iterrows():
                for j, c in enumerate(dcols, 1):
                    v = m[c]
                    if c in ("daily", "am", "pm"):
                        v = round(v)
                    elif c in ("speed", "toll", "count"):
                        v = round(v, 2)
                    sh.cell(row=row, column=j, value=v)
                row += 1
            row += 1
        for col_cells in sh.columns:
            w = max((len(str(c.value)) for c in col_cells if c.value is not None), default=10)
            sh.column_dimensions[col_cells[0].column_letter].width = min(34, max(10, w + 2))

    wb.save(out_xlsx)
    return out_xlsx, len(sel)


def build(run_dir, interchanges_gpkg, out_xlsx=None, max_detail=40,
          county=None, route=None, am_hour=8, pm_hour=17):
    out_xlsx = out_xlsx or os.path.join(run_dir, "interchange_volumes.xlsx")
    mem, ix = aggregate(run_dir, interchanges_gpkg, am_hour, pm_hour)
    summary = summarize(mem, ix)
    csv_path = os.path.splitext(out_xlsx)[0] + ".csv"
    summary.to_csv(csv_path, index=False)
    xpath, n_detail = write_workbook(summary, mem, ix, out_xlsx, max_detail,
                                     county, route)
    print(f"[interchange-vol] {len(summary)} interchanges "
          f"({n_detail} detail sheets) -> {xpath}")
    print(f"[interchange-vol] summary CSV -> {csv_path}")
    return xpath


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--interchanges", required=True)
    ap.add_argument("--out")
    ap.add_argument("--max-detail", type=int, default=40)
    ap.add_argument("--county")
    ap.add_argument("--route")
    ap.add_argument("--am-hour", type=int, default=8)
    ap.add_argument("--pm-hour", type=int, default=17)
    a = ap.parse_args()
    build(a.run_dir, a.interchanges, a.out, a.max_detail, a.county, a.route,
          a.am_hour, a.pm_hour)
