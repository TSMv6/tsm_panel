#!/usr/bin/env python3
"""Model Scenario Run Report -- assignment section (blueprint #2, phase 1).

Reads a HyDRA run directory and writes a single, self-contained report card:

  scenario_report.html   demo-page quality, inline CSS + static inline SVG
                         charts (no external assets, theme-aware light/dark),
                         so it opens anywhere and attaches to a memo.
  scenario_report.md     the diffable twin (drops into a PR or memo).
  scenario_metrics.csv   one tidy long table (stage,section,metric,segment,
                         value,unit) so the report is queryable, not just visual
                         -- the standard-metrics contract the dashboards read.

Phase 1 delivers the ASSIGNMENT half -- network totals (VMT/VHT/speed by
facility), the count-validation headline (model/obs ratio, R2, %RMSE, GEH bins
overall + by facility + by county), tolling (EL toll profile + revenue proxy +
EL share), an assignment-convergence proxy, and the multi-resolution split.
Demand sections (PopSyn / SDT / LDT / trip-list) render "not run yet" and are
filled in phase 2-3. Every section checks for its inputs and degrades to a
"not available" note rather than failing, so a partial run still reports.

Metric formulas follow the canonical Summarization (valstats + GEH) so the
numbers match the validation workbook. VMT/VHT are derived from the tier link-
performance files (length = speed x tt, verified against count_validation).

  python scenario_report.py --run-dir <dir> [--out-dir <dir>]
                            [--min-mainline 5000] [--title "..."]
"""
import argparse
import csv
import html
import math
import os
import time

import numpy as np
import pandas as pd

# ---- facility classification (canonical, extended for EL + connectors) ----
FACILITY = {11: "Limited Access", 12: "Limited Access",
            96: "Express Lanes", 97: "Express Lanes", 98: "Express Lanes",
            91: "Toll", 93: "Toll", 94: "Toll", 92: "Toll",
            71: "Ramps", 72: "Ramps",
            21: "Arterial (Div)", 31: "Arterial (Undiv)",
            41: "Collector", 45: "Collector", 48: "Collector",
            51: "Connector"}
FAC_ORDER = ["Limited Access", "Express Lanes", "Toll", "Ramps",
             "Arterial (Div)", "Arterial (Undiv)", "Collector", "Other"]
FAC_COLOR = {"Limited Access": "--gp", "Express Lanes": "--el", "Toll": "--meso",
             "Ramps": "--muted", "Arterial (Div)": "--macro",
             "Arterial (Undiv)": "--macro", "Collector": "--axis",
             "Other": "--muted"}
EL_FT = {96, 97, 98}
VOL_BINS = [0, 5000, 10000, 20000, 40000, 60000, 1e9]
VOL_LABELS = ["<5k", "5-10k", "10-20k", "20-40k", "40-60k", ">60k"]
NI = 96

# priced express-lane facilities keyed by their gantry toll policy (+ I-595
# reversible, which is capacity-only / untolled). Order drives the report.
FACPOL = {4: "I-95 Express · Miami-Dade", 6: "I-95 Express · Broward/PB",
          5: "I-4 Express", 7: "I-75 Express", 9: "I-295 Express (ToD)"}
FAC_DISPLAY_ORDER = ["I-95 Express · Miami-Dade", "I-95 Express · Broward/PB",
                     "I-4 Express", "I-75 Express", "I-295 Express (ToD)",
                     "I-595 Reversible"]


def fac(ft):
    return FACILITY.get(int(ft), "Other")


# ------------------------------------------------------------------ metrics --
def valstats(g):
    """Canonical count-validation metrics for a group (obs_24h/model_24h/geh)."""
    o = g["obs_24h"].to_numpy(float)
    m = g["model_24h"].to_numpy(float)
    n = len(g)
    r2 = np.nan
    if n > 2 and o.std() > 0 and m.std() > 0:
        r2 = float(np.corrcoef(o, m)[0, 1] ** 2)
    om = o.mean() if o.mean() != 0 else np.nan
    prmse = 100.0 * math.sqrt(((m - o) ** 2).sum() / max(n - 1, 1)) / om \
        if om and not math.isnan(om) else np.nan
    geh = g["geh_hourly_avg"].to_numpy(float)
    return {"links": n, "obs": o.sum(), "model": m.sum(),
            "ratio": (m.sum() / o.sum()) if o.sum() else np.nan, "r2": r2,
            "prmse": prmse, "geh5": 100.0 * np.mean(geh < 5),
            "geh10": 100.0 * np.mean(geh < 10)}


def network_totals(run_dir):
    """VMT / VHT / mean speed by facility, summed over the disjoint tiers.
    length_mi = speed_mph * tt_min/60 (constant per link; connectors dropped)."""
    rows = []
    tiers = {}
    for tier in ("macro", "meso", "micro"):
        fp = os.path.join(run_dir, f"link_performance_{tier}DTA.csv")
        if not os.path.exists(fp):
            continue
        df = pd.read_csv(fp, usecols=["a_node", "b_node", "ftype", "interval",
                                      "volume", "travel_time_min", "speed_mph"])
        df = df[df["interval"] < NI]
        tiers[tier] = df["a_node"].astype(str).add("-").add(
            df["b_node"].astype(str)).nunique()
        df["fac"] = df["ftype"].map(fac)
        df = df[df["fac"] != "Connector"]
        good = (df["speed_mph"] > 0) & (df["travel_time_min"] > 0)
        df.loc[good, "len_mi"] = df.loc[good, "speed_mph"] * \
            df.loc[good, "travel_time_min"] / 60.0
        # per-link length = median of good intervals
        ln = df.loc[good].groupby(["a_node", "b_node"])["len_mi"].median()
        df = df.join(ln, on=["a_node", "b_node"], rsuffix="_lk")
        df["len_lk"] = df["len_mi_lk"].fillna(0.0)
        df["vmt"] = df["volume"] * df["len_lk"]
        df["vht"] = df["volume"] * df["travel_time_min"] / 60.0
        g = df.groupby("fac").agg(vmt=("vmt", "sum"), vht=("vht", "sum")).reset_index()
        g["tier"] = tier
        rows.append(g)
    if not rows:
        return None, tiers
    allg = pd.concat(rows).groupby("fac").agg(
        vmt=("vmt", "sum"), vht=("vht", "sum")).reset_index()
    allg["speed"] = allg["vmt"] / allg["vht"].replace(0, np.nan)
    return allg, tiers


def tolling(run_dir):
    """EL toll profile (mean toll by hour, volume-weighted), revenue proxy,
    EL VMT share of limited-access, from the meso tier (statewide EL)."""
    fp = os.path.join(run_dir, "link_performance_mesoDTA.csv")
    if not os.path.exists(fp):
        return None
    df = pd.read_csv(fp, usecols=["ftype", "hour", "interval", "volume",
                                  "travel_time_min", "speed_mph", "toll_rate"])
    df = df[df["interval"] < NI]
    el = df[df["ftype"].isin(EL_FT)].copy()
    if el.empty or el["toll_rate"].fillna(0).max() <= 0:
        return None
    el["rev"] = el["volume"] * el["toll_rate"]
    # volume-weighted mean toll by hour, over TOLLED link-intervals only
    # (toll_rate > 0) so time-of-day facilities' free hours don't dilute the
    # curve into a sub-floor average.
    tel = el[el["toll_rate"] > 0]
    prof = tel.groupby("hour").apply(
        lambda g: (g["volume"] * g["toll_rate"]).sum() / max(g["volume"].sum(), 1e-9),
        include_groups=False
    ).reindex(range(24)).fillna(0.0)
    return {"profile": [(h, float(prof[h])) for h in range(24)],
            "peak": float(el["toll_rate"].max()),
            "revenue": float(el["rev"].sum()),
            "el_vol": float(el["volume"].sum())}


def facility_dir_map(net_paths):
    """Map each priced/reversible link -> (facility, travel direction). Facility
    from toll_policy_id (the gantry policy) or dta_reversible (I-595); direction
    from node geometry along the facility's dominant axis (NB/SB or EB/WB)."""
    lk = _find(net_paths, "Link.csv")
    nd = _find(net_paths, "Node.csv")
    if not lk or not nd:
        return None
    nodes = pd.read_csv(nd, usecols=["N", "X", "Y"])
    xy = {int(n): (float(x), float(y))
          for n, x, y in zip(nodes["N"], nodes["X"], nodes["Y"])}
    L = pd.read_csv(lk, usecols=["A", "B", "FTYPE", "toll_policy_id",
                                 "dta_reversible"])

    def facof(tp, rev, ft):
        # gantry policy links are EL-only already; the reversible flag spans the
        # whole I-595 cross-section (GP + ramps + EL), so restrict that bucket to
        # its managed (EL) segments — the priced/operated reversible lanes.
        tp = int(tp) if pd.notna(tp) else 0
        if tp in FACPOL:
            return FACPOL[tp]
        if (int(rev) if pd.notna(rev) else 0) == 1 and int(ft) in EL_FT:
            return "I-595 Reversible"
        return None
    L["fac"] = [facof(t, r, f) for t, r, f in
                zip(L["toll_policy_id"], L["dta_reversible"], L["FTYPE"])]
    L = L[L["fac"].notna()].copy()
    if L.empty:
        return None
    # coords (loop is tiny -- only the ~200 priced/reversible links survive)
    L["xa"] = L["A"].map(lambda a: xy.get(int(a), (np.nan, np.nan))[0])
    L["ya"] = L["A"].map(lambda a: xy.get(int(a), (np.nan, np.nan))[1])
    L["xb"] = L["B"].map(lambda a: xy.get(int(a), (np.nan, np.nan))[0])
    L["yb"] = L["B"].map(lambda a: xy.get(int(a), (np.nan, np.nan))[1])
    L["dx"] = L["xb"] - L["xa"]
    L["dy"] = L["yb"] - L["ya"]
    prim = {}
    for f_, g in L.groupby("fac"):
        prim[f_] = "NS" if g["dy"].abs().sum() >= g["dx"].abs().sum() else "EW"

    def dirlab(f_, dx, dy):
        if pd.isna(dx) or pd.isna(dy):
            return "—"
        if prim[f_] == "NS":
            return "NB" if dy >= 0 else "SB"
        return "EB" if dx >= 0 else "WB"
    L["dir"] = [dirlab(f_, dx, dy) for f_, dx, dy in zip(L["fac"], L["dx"], L["dy"])]
    # reversible = one alternating carriageway; a geometric N/S/E/W split is
    # meaningless, so report it as a single series (AM/PM reversal shows in time).
    L.loc[L["fac"] == "I-595 Reversible", "dir"] = "REV"
    return L.rename(columns={"A": "a_node", "B": "b_node"})[
        ["a_node", "b_node", "fac", "dir"]]


def facility_profiles(run_dir, fm):
    """Per-facility, per-direction hourly volume / speed / toll from the tier each
    facility runs on (I-95 Miami-Dade micro; the rest meso). Toll is always the
    meso-posted rate; the summary mean excludes zero-toll hours (ToD off-peak)."""
    if fm is None or fm.empty:
        return None
    frames = []
    for tier in ("meso", "micro"):
        fp = os.path.join(run_dir, f"link_performance_{tier}DTA.csv")
        if not os.path.exists(fp):
            continue
        d = pd.read_csv(fp, usecols=["a_node", "b_node", "hour", "interval",
                                     "volume", "speed_mph", "toll_rate"])
        d = d[d["interval"] < NI]
        d = d.merge(fm, on=["a_node", "b_node"], how="inner")
        if not d.empty:
            frames.append(d)
    if not frames:
        return None
    d = pd.concat(frames, ignore_index=True)
    out = {}
    for fname in FAC_DISPLAY_ORDER:
        sub = d[d["fac"] == fname]
        if sub.empty:
            continue
        dirs = {}
        for dname, g in sub.groupby("dir"):
            if dname == "—":
                continue
            gh = g.groupby("hour")
            vol = gh["volume"].sum().reindex(range(24)).fillna(0.0)
            vs = (g["volume"] * g["speed_mph"]).groupby(g["hour"]).sum()
            sp = (vs / gh["volume"].sum().replace(0, np.nan)
                  ).reindex(range(24)).fillna(0.0)
            t = g[g["toll_rate"] > 0]
            if not t.empty:
                vt = (t["volume"] * t["toll_rate"]).groupby(t["hour"]).sum()
                tp = (vt / t.groupby("hour")["volume"].sum().replace(0, np.nan)
                      ).reindex(range(24)).fillna(0.0)
            else:
                tp = pd.Series(0.0, index=range(24))
            dirs[dname] = {
                "vol": [(h, float(vol[h])) for h in range(24)],
                "speed": [(h, float(sp[h])) for h in range(24)],
                "toll": [(h, float(tp[h])) for h in range(24)]}
        tolled = sub[(sub["toll_rate"] > 0) & (sub["volume"] > 0)]
        mean_toll = float((tolled["volume"] * tolled["toll_rate"]).sum() /
                          max(tolled["volume"].sum(), 1e-9)) if not tolled.empty else 0.0
        out[fname] = {
            "dirs": dirs,
            "daily_vol": float(sub.loc[sub["volume"] > 0, "volume"].sum()),
            "mean_toll": mean_toll,
            "peak_toll": float(sub["toll_rate"].max()),
            "revenue": float((sub["volume"] * sub["toll_rate"]).sum()),
            "tolled": bool(sub["toll_rate"].max() > 0)}
    return out or None


def convergence(run_dir):
    """Assignment-quality proxy: weighted mean relative gap from agentPlans
    (gap_min / cost_min), plus the trip/weight totals."""
    fp = os.path.join(run_dir, "agentPlans_out.csv")
    if not os.path.exists(fp):
        return None
    cols = pd.read_csv(fp, nrows=0).columns
    use = [c for c in ("weight", "cost_min", "gap_min", "purpose", "scope", "vot")
           if c in cols]
    df = pd.read_csv(fp, usecols=use)
    w = df["weight"] if "weight" in df else pd.Series(1.0, index=df.index)
    out = {"trips": float(w.sum()), "rows": len(df)}
    if {"gap_min", "cost_min"}.issubset(df.columns):
        num = (w * df["gap_min"]).sum()
        den = (w * df["cost_min"]).sum()
        out["rel_gap"] = float(num / den) if den else np.nan
    if "purpose" in df:
        wcol = "weight" if "weight" in df else None
        out["by_purpose"] = (df.groupby("purpose")["weight"].sum().to_dict()
                             if wcol else df["purpose"].value_counts().to_dict())
    if "vot" in df:
        out["vot_mean"] = float((w * df["vot"]).sum() / max(w.sum(), 1e-9))
    return out


def _find(paths, *names):
    """First existing file among names, searched over paths."""
    for p in paths:
        for n in names:
            fp = os.path.join(p, n)
            if os.path.exists(fp):
                return fp
    return None


def _market_group(m):
    m = str(m)
    if m.startswith("SDT_Res"):
        return "SDT resident"
    if m.startswith("SDT_Vis"):
        return "SDT visitor"
    if m.startswith("LDT_Res") or m.startswith("LDT_Vis") or m.startswith("LDT"):
        return "LDT visitor" if "Vis" in m else "LDT resident"
    if m.startswith("OS") or "External" in m or "ext" in m.lower():
        return "External / OS"
    return m


def triplist_summary(demand_paths, cache_dir, chunk=4_000_000):
    """Chunked aggregation of the assembled tripList (the demand handed to
    assignment): vehicle- and person-trips by market / VOT segment / purpose,
    occupancy, and the departure-time profile. Cached to a small JSON keyed on
    the source mtime so re-runs are instant (the file can be tens of millions
    of rows)."""
    import json
    fp = _find(demand_paths, "tripList_30min.csv.gz", "tripList_30min.csv",
               "tripList.csv.gz", "tripList.csv")
    if not fp:
        return None
    cache = os.path.join(cache_dir, ".triplist_cache.json")
    src_mt = os.path.getmtime(fp)
    if os.path.exists(cache):
        try:
            c = json.load(open(cache))
            if abs(c.get("_mtime", 0) - src_mt) < 1 and c.get("_src") == fp:
                return c
        except Exception:
            pass
    from collections import defaultdict
    veh_mkt, per_mkt, cnt_mkt = defaultdict(float), defaultdict(float), defaultdict(int)
    veh_vot, veh_pur = defaultdict(float), defaultdict(float)
    veh_hr = defaultdict(float)
    veh_mkt_pur = defaultdict(float)   # (market_group, purpose) -> vehTrips
    tot_v = tot_p = 0.0
    use = ["purpose", "depart_time", "marketVot", "vehTrips", "occupancy", "market"]
    for ch in pd.read_csv(fp, usecols=use, chunksize=chunk,
                          dtype={"purpose": "category", "marketVot": "category",
                                 "market": "category"}):
        v = ch["vehTrips"].to_numpy(float)
        # occupancy has garbage outliers (seen up to 12,306) and sub-1 noise;
        # clamp to a physical auto range so person-trips aren't polluted.
        occ = ch["occupancy"].fillna(1.0).clip(1.0, 8.0).to_numpy(float)
        p = v * occ
        tot_v += v.sum(); tot_p += p.sum()
        gm = ch["market"].map(_market_group)
        for key, sv in ch.groupby(gm, observed=True).indices.items():
            veh_mkt[key] += v[sv].sum(); per_mkt[key] += p[sv].sum()
            cnt_mkt[key] += len(sv)
        for key, sv in ch.groupby("marketVot", observed=True).indices.items():
            veh_vot[str(key)] += v[sv].sum()
        for key, sv in ch.groupby("purpose", observed=True).indices.items():
            veh_pur[str(key)] += v[sv].sum()
        ch2 = ch.assign(_mg=gm)
        for (mgk, pk), sv in ch2.groupby(["_mg", "purpose"], observed=True).indices.items():
            veh_mkt_pur[f"{mgk}||{pk}"] += v[sv].sum()
        hr = ch["depart_time"].astype(str).str.slice(0, 2)
        hr = pd.to_numeric(hr, errors="coerce").fillna(0).astype(int).clip(0, 23)
        for h_, sv in ch.groupby(hr).indices.items():
            veh_hr[int(h_)] += v[sv].sum()
    out = {"_src": fp, "_mtime": src_mt, "total_veh": tot_v, "total_per": tot_p,
           "by_market": dict(veh_mkt), "per_market": dict(per_mkt),
           "cnt_market": dict(cnt_mkt), "by_vot": dict(veh_vot),
           "by_purpose": dict(veh_pur),
           "by_market_purpose": dict(veh_mkt_pur),
           "by_hour": {str(k): v for k, v in veh_hr.items()}}
    try:
        json.dump(out, open(cache, "w"))
    except Exception:
        pass
    return out


def popsyn_summary(demand_paths, cache_dir, chunk=2_000_000):
    """PopSyn report: synthesized households/persons overall + by county vs the
    land-use control totals (TotHH, POP), plus HH-size / workers / vehicles
    distributions. Chunked + mtime-cached (the HH file is ~9.4M rows)."""
    import json
    hh_fp = _find(demand_paths, "Syn_households.csv")
    lu_fp = _find(demand_paths, "tsm_landuse.csv")
    if not hh_fp:
        return None
    cache = os.path.join(cache_dir, ".popsyn_cache.json")
    src_mt = os.path.getmtime(hh_fp)
    if os.path.exists(cache):
        try:
            c = json.load(open(cache))
            if abs(c.get("_mtime", 0) - src_mt) < 1 and c.get("_src") == hh_fp:
                return c
        except Exception:
            pass
    taz_cty = {}
    ctrl = {}
    if lu_fp:
        lu = pd.read_csv(lu_fp, usecols=["TAZ", "County", "TotHH", "POP"])
        taz_cty = dict(zip(lu["TAZ"], lu["County"]))
        g = lu.groupby("County")[["TotHH", "POP"]].sum()
        ctrl = {c: (float(r["TotHH"]), float(r["POP"])) for c, r in g.iterrows()}
    from collections import defaultdict
    hh_cty, per_cty = defaultdict(float), defaultdict(float)
    size_d, work_d, veh_d = defaultdict(float), defaultdict(float), defaultdict(float)
    tot_hh = tot_per = 0.0
    for ch in pd.read_csv(hh_fp, usecols=["TAZ", "NP", "workers", "VEH", "hhexpfac"],
                          chunksize=chunk):
        w = ch["hhexpfac"].fillna(1.0).to_numpy(float)
        np_ = ch["NP"].fillna(0).to_numpy(float)
        tot_hh += w.sum(); tot_per += (w * np_).sum()
        cty = ch["TAZ"].map(taz_cty).fillna("Unknown")
        for c, idx in ch.groupby(cty, observed=True).indices.items():
            hh_cty[str(c)] += w[idx].sum(); per_cty[str(c)] += (w * np_)[idx].sum()
        for col, dst, cap in (("NP", size_d, 7), ("workers", work_d, 4), ("VEH", veh_d, 4)):
            vals = ch[col].fillna(0).clip(0, cap).astype(int)
            for k, idx in ch.groupby(vals, observed=True).indices.items():
                dst[str(int(k))] += w[idx].sum()
    out = {"_src": hh_fp, "_mtime": src_mt, "total_hh": tot_hh, "total_per": tot_per,
           "hh_county": dict(hh_cty), "per_county": dict(per_cty),
           "ctrl_county": {k: list(v) for k, v in ctrl.items()},
           "size": dict(size_d), "workers": dict(work_d), "veh": dict(veh_d)}
    try:
        json.dump(out, open(cache, "w"))
    except Exception:
        pass
    return out


def skims_summary(demand_paths):
    """Skims: coverage sanity only. The skim is FREE-FLOW (no congested time),
    so OD-time statistics would imply meaning they don't have -- report just
    zones skimmed, disconnected OD pairs, and isolated-zone fallbacks."""
    out = {}
    log = _find(demand_paths, "Skimmy.log")
    if log:
        try:
            import re
            for ln in open(log, errors="ignore"):
                if "Intrazonals" in ln:
                    mm = re.search(r"for (\d+) zones, fallback [\d.]+ for (\d+)", ln)
                    if mm:
                        out["zones"] = int(mm.group(1))
                        out["isolated"] = int(mm.group(2))
        except Exception:
            pass
    dis = _find(demand_paths, "disconnected_OD_list.csv")
    if dis:
        try:
            with open(dis) as fh:
                out["disconnected"] = max(0, sum(1 for _ in fh) - 1)
        except Exception:
            pass
    omx = _find(demand_paths, "FF_Skim2.omx", "FF_Skim.omx")
    if omx:
        out["omx"] = os.path.basename(omx)
        out["omx_gb"] = os.path.getsize(omx) / 1e9
    return out or None


# Physical plausibility bounds for observed counts. Violations are DATA-SOURCE
# errors (bad station data, not a coding bug) -- they can't be auto-corrected, so
# they are excluded from the calibration stats and flagged for manual review.
COUNT_MAX_PER_LANE = 28000        # no lane carries >28k veh/day
EL_COUNT_MAX = 35000              # 1-2 lane EL single-dir ceiling
MAINLINE_MIN = 10000              # multi-lane freeway/toll floor
MINOR_COUNT_MAX = 40000           # collector/ramp can't carry mainline volume


def flag_bad_count(ftype, obs, nlanes):
    """Reason string if an observed count is physically implausible, else ''."""
    ft = int(ftype)
    perlane = obs / nlanes if nlanes and nlanes > 0 else np.nan
    if ft in EL_FT and obs > EL_COUNT_MAX:
        return "EL_too_high (parallel GP count on EL link)"
    if ft in (11, 12, 91, 92, 93, 94) and (nlanes or 0) >= 2 and obs < MAINLINE_MIN:
        return "mainline_too_low (missing/placeholder)"
    if not math.isnan(perlane) and perlane > COUNT_MAX_PER_LANE:
        return "over_28k_per_lane (bidir AADT on 1-dir link)"
    if ft not in EL_FT and ft not in (11, 12, 91, 92, 93, 94) and obs > MINOR_COUNT_MAX:
        return "minor_road_too_high (mainline count on collector/ramp)"
    return ""


def load_validation(run_dir, min_mainline=5000, count_field="FTI_COUNT_24",
                    net_paths=None):
    """Load count_validation.csv. HyDRA bakes the observed column from whichever
    COUNT_FIELD column it was pointed at -- which, after the netPrep rebuild, is
    the legacy TSMv5.COUNT_24 (half-magnitude, placeholder-ridden). Re-score
    against the authoritative FTI_COUNT_24 daily counts from Link.csv so the
    headline calibration reflects the real counts, not the legacy field. The
    daily metrics (model/obs, R2, %RMSE) recompute directly; the hourly-avg GEH
    is rescaled by each link's own hourly:daily GEH ratio (obs-magnitude stable)."""
    fp = os.path.join(run_dir, "count_validation.csv")
    if not os.path.exists(fp):
        return None
    cv = pd.read_csv(fp)
    src = "count_validation.csv (as emitted)"
    if count_field:
        lk = _find(net_paths or [run_dir], "Link.csv")
        if lk:
            cols = pd.read_csv(lk, nrows=0).columns
            if count_field in cols:
                lcols = ["A", "B", count_field] + (["NLANES"] if "NLANES" in cols else [])
                fti = pd.read_csv(lk, usecols=lcols).rename(
                    columns={"A": "a_node", "B": "b_node", "NLANES": "nlanes"})
                fti[count_field] = pd.to_numeric(fti[count_field], errors="coerce")
                cv = cv.merge(fti, on=["a_node", "b_node"], how="left")
                obs_new = cv[count_field]
                # per-link hourly:daily GEH ratio from the file (obs-independent),
                # to carry the recomputed daily GEH back to an hourly-avg basis.
                hd = (cv["geh_hourly_avg"] / cv["geh_daily"].replace(0, np.nan))
                hd = hd.fillna(hd.median())
                m = cv["model_24h"]
                cv["obs_24h"] = obs_new
                cv["ratio"] = m / obs_new.replace(0, np.nan)
                cv["pct_err"] = 100.0 * (m - obs_new) / obs_new.replace(0, np.nan)
                cv["geh_daily"] = np.sqrt(2.0 * (m - obs_new) ** 2 /
                                          (m + obs_new).replace(0, np.nan))
                cv["geh_hourly_avg"] = cv["geh_daily"] * hd
                cv = cv[cv[count_field] > 0].copy()
                src = f"{count_field} (Link.csv, re-scored)"
    cv = cv[(cv["obs_24h"] > 0)].copy()
    # exclude physically implausible counts (data-source errors) from the stats
    # and write them to a manual-review file rather than silently dropping.
    n_flag = 0
    if "nlanes" in cv.columns:
        cv["count_flag"] = [flag_bad_count(ft, ob, ln) for ft, ob, ln in
                            zip(cv["ftype"], cv["obs_24h"], cv["nlanes"])]
        bad = cv[cv["count_flag"] != ""]
        n_flag = len(bad)
        if n_flag:
            rf = os.path.join(run_dir, "count_review_flagged.csv")
            bad[["a_node", "b_node", "county", "ftype", "nlanes", "obs_24h",
                 "model_24h", "count_flag"]].sort_values(
                ["count_flag", "obs_24h"], ascending=[True, False]).to_csv(rf, index=False)
        cv = cv[cv["count_flag"] == ""].copy()
    # canonical mainline-trust filter: drop low-count mainline/toll links
    mask = cv["ftype"].isin([11, 12, 91, 92, 93, 94]) & (cv["obs_24h"] < min_mainline)
    cv = cv[~mask].copy()
    cv["fac"] = cv["ftype"].map(fac)
    cv["volgrp"] = pd.cut(cv["obs_24h"], VOL_BINS, labels=VOL_LABELS)
    cv.attrs["count_source"] = src
    cv.attrs["n_flagged"] = n_flag
    return cv


# --------------------------------------------------------------- SVG charts --
def _svg(w, h, body):
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" '
            f'style="max-width:{w}px;display:block" '
            f'xmlns="http://www.w3.org/2000/svg" '
            f'font-family="system-ui,-apple-system,Segoe UI,sans-serif">{body}</svg>')


def hbars(pairs, unit="", w=560, rowh=26, pad_l=140):
    """pairs = [(label, value, color_var)]; horizontal bars, value labels."""
    pairs = [p for p in pairs if p[1] and not (isinstance(p[1], float) and math.isnan(p[1]))]
    if not pairs:
        return "<p class='fignote'>no data</p>"
    vmax = max(p[1] for p in pairs) or 1
    h = len(pairs) * rowh + 12
    bar_w = w - pad_l - 70
    b = []
    for i, (lab, v, col) in enumerate(pairs):
        y = 8 + i * rowh
        bw = max(1.0, bar_w * v / vmax)
        b.append(f'<text x="{pad_l-8}" y="{y+13}" text-anchor="end" '
                 f'font-size="12" fill="var(--ink2)">{html.escape(str(lab))}</text>')
        b.append(f'<rect x="{pad_l}" y="{y+3}" width="{bw:.1f}" height="14" rx="3" '
                 f'fill="var({col})" opacity="0.85"/>')
        b.append(f'<text x="{pad_l+bw+6:.1f}" y="{y+14}" font-size="11.5" '
                 f'fill="var(--ink2)" font-variant-numeric="tabular-nums">'
                 f'{_fmt(v)}{unit}</text>')
    return _svg(w, h, "".join(b))


def scatter_obs_model(cv, w=460, h=460, n=500):
    """obs vs model daily volume with the y=x reference line."""
    if cv is None or cv.empty:
        return "<p class='fignote'>no counts</p>"
    d = cv.sample(min(n, len(cv)), random_state=1) if len(cv) > n else cv
    o = d["obs_24h"].to_numpy(float); m = d["model_24h"].to_numpy(float)
    hi = max(o.max(), m.max(), 1) * 1.05
    M = {"l": 56, "b": 44, "t": 12, "r": 14}
    pw, ph = w - M["l"] - M["r"], h - M["t"] - M["b"]
    def X(v): return M["l"] + pw * v / hi
    def Y(v): return M["t"] + ph * (1 - v / hi)
    b = [f'<line x1="{X(0)}" y1="{Y(0)}" x2="{X(hi)}" y2="{Y(hi)}" '
         f'stroke="var(--axis)" stroke-dasharray="5 4"/>']
    for i in range(len(o)):
        b.append(f'<circle cx="{X(o[i]):.1f}" cy="{Y(m[i]):.1f}" r="2.6" '
                 f'fill="var(--gp)" opacity="0.5"/>')
    # axes
    b.append(f'<line x1="{M["l"]}" y1="{Y(0)}" x2="{M["l"]+pw}" y2="{Y(0)}" class="axis"/>')
    b.append(f'<line x1="{M["l"]}" y1="{M["t"]}" x2="{M["l"]}" y2="{Y(0)}" class="axis"/>')
    for f_ in (0, .5, 1):
        b.append(f'<text x="{X(hi*f_):.0f}" y="{Y(0)+16}" font-size="10.5" '
                 f'text-anchor="middle" fill="var(--muted)">{_fmt(hi*f_)}</text>')
        b.append(f'<text x="{M["l"]-8}" y="{Y(hi*f_)+3:.0f}" font-size="10.5" '
                 f'text-anchor="end" fill="var(--muted)">{_fmt(hi*f_)}</text>')
    b.append(f'<text x="{M["l"]+pw/2}" y="{h-8}" font-size="11.5" '
             f'text-anchor="middle" fill="var(--ink2)">Observed daily volume</text>')
    b.append(f'<text transform="translate(14,{M["t"]+ph/2}) rotate(-90)" '
             f'font-size="11.5" text-anchor="middle" fill="var(--ink2)">Model daily volume</text>')
    return _svg(w, h, "".join(b))


def line_profile(pairs, w=560, h=220, unit="$", ylab="EL toll ($)"):
    """pairs = [(hour, value)]; area+line over 24 h."""
    if not pairs:
        return "<p class='fignote'>no data</p>"
    vmax = max(v for _, v in pairs) or 1
    M = {"l": 48, "b": 34, "t": 14, "r": 14}
    pw, ph = w - M["l"] - M["r"], h - M["t"] - M["b"]
    def X(hh): return M["l"] + pw * hh / 23.0
    def Y(v): return M["t"] + ph * (1 - v / (vmax * 1.1))
    pts = "".join(("L" if i else "M") + f"{X(x):.1f} {Y(y):.1f}"
                  for i, (x, y) in enumerate(pairs))
    area = pts + f"L{X(23):.1f} {Y(0):.1f}L{X(0):.1f} {Y(0):.1f}Z"
    b = [f'<path d="{area}" fill="var(--meso)" opacity="0.18"/>',
         f'<path d="{pts}" fill="none" stroke="var(--meso)" stroke-width="2"/>']
    for gy in (0, vmax):
        b.append(f'<line x1="{M["l"]}" y1="{Y(gy):.1f}" x2="{M["l"]+pw}" '
                 f'y2="{Y(gy):.1f}" class="grid"/>')
        gl = f"{unit}{gy:.2f}" if unit else _fmt(gy)
        b.append(f'<text x="{M["l"]-6}" y="{Y(gy)+3:.1f}" font-size="10.5" '
                 f'text-anchor="end" fill="var(--muted)">{gl}</text>')
    for hh in (0, 6, 12, 18, 23):
        lab = "12A" if hh == 0 else (f"{hh}A" if hh < 12 else ("12P" if hh == 12 else f"{hh-12}P"))
        b.append(f'<text x="{X(hh):.0f}" y="{h-8}" font-size="10.5" '
                 f'text-anchor="middle" fill="var(--muted)">{lab}</text>')
    b.append(f'<text transform="translate(12,{M["t"]+ph/2}) rotate(-90)" '
             f'font-size="11" text-anchor="middle" fill="var(--ink2)">{ylab}</text>')
    return _svg(w, h, "".join(b))


def dir_profile(series, ylab, unit="", fmt=None, w=352, h=168):
    """Multi-line 24-h profile, one line per direction.
    series = [(dir_label, [(hour, value)], color_var)]."""
    allv = [v for _, pts, _ in series for _, v in pts]
    vmax = max(allv) if allv else 1.0
    if vmax <= 0:
        vmax = 1.0
    M = {"l": 44, "b": 24, "t": 10, "r": 10}
    pw, ph = w - M["l"] - M["r"], h - M["t"] - M["b"]
    def X(hh): return M["l"] + pw * hh / 23.0
    def Y(v): return M["t"] + ph * (1 - v / (vmax * 1.12))
    def lab(v): return fmt(v) if fmt else f"{unit}{_fmt(v)}"
    b = []
    for gy in (0.0, vmax / 2.0, vmax):
        b.append(f'<line x1="{M["l"]}" y1="{Y(gy):.1f}" x2="{M["l"]+pw}" '
                 f'y2="{Y(gy):.1f}" class="grid"/>')
        b.append(f'<text x="{M["l"]-5}" y="{Y(gy)+3:.1f}" font-size="9.5" '
                 f'text-anchor="end" fill="var(--muted)">{lab(gy)}</text>')
    for hh in (0, 6, 12, 18):
        t = "12A" if hh == 0 else (f"{hh}A" if hh < 12 else ("12P" if hh == 12 else f"{hh-12}P"))
        b.append(f'<text x="{X(hh):.0f}" y="{h-8}" font-size="9.5" '
                 f'text-anchor="middle" fill="var(--muted)">{t}</text>')
    for dname, pts, col in series:
        d = "".join(("L" if i else "M") + f"{X(x):.1f} {Y(y):.1f}"
                    for i, (x, y) in enumerate(pts))
        b.append(f'<path d="{d}" fill="none" stroke="var({col})" '
                 f'stroke-width="1.8"/>')
    b.append(f'<text transform="translate(11,{M["t"]+ph/2}) rotate(-90)" '
             f'font-size="9.5" text-anchor="middle" fill="var(--ink2)">{ylab}</text>')
    return _svg(w, h, "".join(b))


def _fmt(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    v = float(v)
    if abs(v) >= 1e6:
        return f"{v/1e6:.2f}M"
    if abs(v) >= 1e3:
        return f"{v/1e3:.1f}k"
    if abs(v) >= 10:
        return f"{v:.0f}"
    return f"{v:.2f}"


def tiles(items):
    """items = [(value_html, key_label)] -> stat-tile grid."""
    c = "".join(f'<div class="tile"><div class="v">{v}</div>'
                f'<div class="k">{html.escape(k)}</div></div>' for v, k in items)
    return f'<div class="tiles">{c}</div>'


def table(headers, rows, num_cols=()):
    th = "".join(f'<th class="{"num" if i in num_cols else ""}">{html.escape(h)}</th>'
                 for i, h in enumerate(headers))
    tr = []
    for r in rows:
        td = "".join(f'<td class="{"num" if i in num_cols else ""}">{c}</td>'
                     for i, c in enumerate(r))
        tr.append(f"<tr>{td}</tr>")
    return f'<table><thead><tr>{th}</tr></thead><tbody>{"".join(tr)}</tbody></table>'


# ------------------------------------------------------------------ assemble --
CSS = """
:root{--surface:#fcfcfb;--page:#f9f9f7;--ink:#0b0b0b;--ink2:#52514e;
 --muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;--ring:rgba(11,11,11,.10);
 --macro:#2a78d6;--meso:#c98500;--micro:#4a3aa7;--el:#1baf7a;--gp:#2a78d6;
 --good:#1baf7a;--warn:#c98500;--bad:#e34948}
@media (prefers-color-scheme:dark){:root{--surface:#1a1a19;--page:#0d0d0d;
 --ink:#fff;--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;
 --ring:rgba(255,255,255,.10);--macro:#3987e5;--meso:#eda100;--micro:#9085e9;
 --el:#199e70;--gp:#3987e5;--good:#199e70;--warn:#eda100;--bad:#e66767}}
:root[data-theme="light"]{--surface:#fcfcfb;--page:#f9f9f7;--ink:#0b0b0b;
 --ink2:#52514e;--muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;--macro:#2a78d6;
 --meso:#c98500;--micro:#4a3aa7;--el:#1baf7a;--gp:#2a78d6;--good:#1baf7a;
 --warn:#c98500;--bad:#e34948;--ring:rgba(11,11,11,.10)}
:root[data-theme="dark"]{--surface:#1a1a19;--page:#0d0d0d;--ink:#fff;
 --ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;--macro:#3987e5;
 --meso:#eda100;--micro:#9085e9;--el:#199e70;--gp:#3987e5;--good:#199e70;
 --warn:#eda100;--bad:#e66767;--ring:rgba(255,255,255,.10)}
*{box-sizing:border-box}
body{background:var(--page);color:var(--ink);margin:0;
 font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:1060px;margin:0 auto;padding:38px 28px 80px}
.eyebrow{font-size:11.5px;text-transform:uppercase;letter-spacing:.12em;
 color:var(--muted);font-weight:600}
h1{font-size:29px;line-height:1.15;margin:6px 0 4px;letter-spacing:-.01em;text-wrap:balance}
h2{font-size:20px;margin:50px 0 4px;letter-spacing:-.005em;text-wrap:balance}
h3{font-size:14px;margin:24px 0 6px;color:var(--ink2)}
.sub{color:var(--ink2);max-width:74ch;margin:6px 0 0}
.fignote{color:var(--muted);font-size:12.5px;margin:8px 2px 0;max-width:90ch}
.card{background:var(--surface);border:1px solid var(--ring);border-radius:10px;
 padding:16px 20px;margin-top:14px}
.chart{overflow-x:auto;margin-top:10px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
 gap:10px;margin-top:14px}
.tile{background:var(--surface);border:1px solid var(--ring);border-radius:10px;
 padding:12px 14px}
.tile .v{font-size:21px;font-weight:700;letter-spacing:-.01em;
 font-variant-numeric:tabular-nums}
.tile .v small{font-size:13px;font-weight:600;color:var(--ink2)}
.tile .k{font-size:11.5px;color:var(--muted);margin-top:2px;line-height:1.35}
.cols2{display:grid;grid-template-columns:1fr 1fr;gap:18px;align-items:start}
@media(max-width:820px){.cols2{grid-template-columns:1fr}}
.cols3{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));
 gap:14px;align-items:start;margin-top:6px}
table{border-collapse:collapse;width:100%;font-size:13px;margin-top:10px}
th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.06em;
 color:var(--muted);font-weight:600;padding:6px 12px 6px 0;border-bottom:1px solid var(--axis)}
td{padding:7px 12px 7px 0;border-bottom:1px solid var(--grid)}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
svg .grid{stroke:var(--grid);stroke-width:1}
svg .axis{stroke:var(--axis);stroke-width:1}
.pill{display:inline-block;padding:2px 9px;border-radius:999px;font-size:11px;
 font-weight:700;letter-spacing:.03em}
.pill.good{background:color-mix(in srgb,var(--good) 18%,transparent);color:var(--good)}
.pill.warn{background:color-mix(in srgb,var(--warn) 20%,transparent);color:var(--warn)}
.pill.bad{background:color-mix(in srgb,var(--bad) 18%,transparent);color:var(--bad)}
.notrun{color:var(--muted);font-style:italic;margin-top:10px}
.tog{position:fixed;top:14px;right:16px;background:var(--surface);
 border:1px solid var(--ring);border-radius:8px;color:var(--muted);
 padding:6px 10px;font-size:12px;cursor:pointer}
.prov{display:flex;flex-wrap:wrap;gap:6px 20px;margin-top:12px;font-size:12.5px;
 color:var(--ink2)}
.prov b{color:var(--ink);font-weight:600;font-variant-numeric:tabular-nums}
a{color:var(--macro)}
"""

_THEME_JS = ("<script>document.querySelector('.tog').onclick=function(){var r="
             "document.documentElement,c=r.getAttribute('data-theme')||"
             "(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');"
             "r.setAttribute('data-theme',c==='dark'?'light':'dark')};</script>")


def _pill(label, kind):
    return f'<span class="pill {kind}">{label}</span>'


def _ratio_pill(ratio):
    if ratio is None or math.isnan(ratio):
        return ""
    d = abs(ratio - 1.0)
    k = "good" if d <= 0.10 else ("warn" if d <= 0.20 else "bad")
    return _pill(f"{ratio:.2f}", k)


def build(run_dir, out_dir=None, title=None, min_mainline=5000, demand_dir=None,
          count_field="FTI_COUNT_24"):
    run_dir = os.path.abspath(run_dir)
    out_dir = out_dir or run_dir
    os.makedirs(out_dir, exist_ok=True)
    title = title or f"Scenario Report — {os.path.basename(run_dir)}"
    metrics = []   # (stage,section,metric,segment,value,unit)

    def M(section, metric, segment, value, unit="", stage="Assignment"):
        metrics.append((stage, section, metric, segment,
                        "" if value is None else value, unit))

    def D(section, metric, segment, value, unit=""):
        M(section, metric, segment, value, unit, stage="Demand")

    # ---- compute ----
    net_paths = [run_dir,
                 os.path.join(os.path.dirname(run_dir), "netprep_ML"),
                 os.path.dirname(run_dir)]
    net, tier_links = network_totals(run_dir)
    cv = load_validation(run_dir, min_mainline, count_field=count_field,
                         net_paths=net_paths)
    toll = tolling(run_dir)
    fmap = facility_dir_map(net_paths)
    fprof = facility_profiles(run_dir, fmap) if fmap is not None else None
    conv = convergence(run_dir)
    # demand outputs live in the run dir, a given demand dir, or the parent scenario dir
    demand_paths = [p for p in (demand_dir, run_dir, os.path.dirname(run_dir)) if p]
    tlist = triplist_summary(demand_paths, out_dir)

    sections = []

    # ---- header / provenance ----
    n_links = sum(tier_links.values()) if tier_links else 0
    counties = int(cv["county"].nunique()) if cv is not None else 0
    veh = conv.get("trips") if conv else None
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(
        os.path.getmtime(os.path.join(run_dir, "link_performance_macroDTA.csv"))
        if os.path.exists(os.path.join(run_dir, "link_performance_macroDTA.csv"))
        else run_dir))
    prov = (f'<div class="prov"><span>Run&nbsp;<b>{html.escape(os.path.basename(run_dir))}</b></span>'
            f'<span>Network&nbsp;<b>{n_links:,}</b> directed links</span>'
            f'<span>Counties&nbsp;<b>{counties}</b></span>'
            f'<span>Vehicle-trips&nbsp;<b>{_fmt(veh)}</b></span>'
            f'<span>Generated&nbsp;<b>{when}</b></span></div>')
    M("Provenance", "directed_links", "all", n_links)
    M("Provenance", "counties", "all", counties)
    M("Provenance", "vehicle_trips", "all", veh)

    # ---- network totals ----
    if net is not None and not net.empty:
        vmt = float(net["vmt"].sum()); vht = float(net["vht"].sum())
        msp = vmt / vht if vht else float("nan")
        for _, r in net.iterrows():
            M("NetworkTotals", "VMT", r["fac"], round(r["vmt"], 1), "veh-mi")
            M("NetworkTotals", "VHT", r["fac"], round(r["vht"], 1), "veh-h")
            M("NetworkTotals", "mean_speed", r["fac"], round(r["speed"], 1), "mph")
        M("NetworkTotals", "VMT", "all", round(vmt, 1), "veh-mi")
        M("NetworkTotals", "VHT", "all", round(vht, 1), "veh-h")
        M("NetworkTotals", "mean_speed", "all", round(msp, 1), "mph")
        net["ord"] = net["fac"].map({f: i for i, f in enumerate(FAC_ORDER)}).fillna(9)
        net = net.sort_values("ord")
        bar = hbars([(r["fac"], r["vmt"], FAC_COLOR.get(r["fac"], "--muted"))
                     for _, r in net.iterrows()], unit="")
        tl = tiles([(f'{_fmt(vmt)} <small>veh-mi</small>', "Daily VMT"),
                    (f'{_fmt(vht)} <small>veh-h</small>', "Daily VHT"),
                    (f'{msp:.1f} <small>mph</small>', "Network mean speed"),
                    (f'{n_links:,}', "Directed links")])
        ft = table(["Facility", "VMT", "VHT", "Mean speed (mph)"],
                   [(r["fac"], _fmt(r["vmt"]), _fmt(r["vht"]), f'{r["speed"]:.1f}')
                    for _, r in net.iterrows()], num_cols=(1, 2, 3))
        sections.append(("Network totals",
            "VMT, VHT, and volume-weighted mean speed by facility class, summed "
            "over the disjoint macro / meso / micro tiers (centroid connectors "
            "excluded; link length recovered as speed × travel-time).",
            tl + '<div class="cols2"><div class="chart">' + bar +
            '<p class="fignote">Daily VMT by facility class.</p></div><div>' + ft + '</div></div>'))
    else:
        sections.append(("Network totals", "", '<p class="notrun">No link-performance files found.</p>'))

    # ---- count validation ----
    if cv is not None and not cv.empty:
        ov = valstats(cv)
        M("Validation", "model_obs_ratio", "all", round(ov["ratio"], 3))
        M("Validation", "r2", "all", round(ov["r2"], 3) if not math.isnan(ov["r2"]) else None)
        M("Validation", "pct_rmse", "all", round(ov["prmse"], 1), "%")
        M("Validation", "geh_lt5_pct", "all", round(ov["geh5"], 1), "%")
        M("Validation", "geh_lt10_pct", "all", round(ov["geh10"], 1), "%")
        M("Validation", "counted_links", "all", ov["links"])
        tl = tiles([
            (f'{_ratio_pill(ov["ratio"])}', "Model / observed"),
            (f'{ov["r2"]:.3f}' if not math.isnan(ov["r2"]) else "—", "R²"),
            (f'{ov["prmse"]:.1f}<small>%</small>', "%RMSE"),
            (f'{ov["geh5"]:.0f}<small>%</small>', "GEH < 5"),
            (f'{ov["geh10"]:.0f}<small>%</small>', "GEH < 10"),
            (f'{ov["links"]:,}', "Counted links")])
        # by facility
        fac_rows = []
        for f_ in FAC_ORDER:
            g = cv[cv["fac"] == f_]
            if len(g) < 3:
                continue
            s = valstats(g)
            for k in ("model_obs_ratio", "r2", "pct_rmse", "geh_lt5_pct"):
                pass
            M("Validation", "model_obs_ratio", f_, round(s["ratio"], 3))
            M("Validation", "r2", f_, None if math.isnan(s["r2"]) else round(s["r2"], 3))
            M("Validation", "pct_rmse", f_, round(s["prmse"], 1), "%")
            M("Validation", "geh_lt5_pct", f_, round(s["geh5"], 1), "%")
            fac_rows.append((f_, f'{s["links"]:,}', _ratio_pill(s["ratio"]),
                             f'{s["r2"]:.2f}' if not math.isnan(s["r2"]) else "—",
                             f'{s["prmse"]:.0f}', f'{s["geh5"]:.0f}'))
        fac_tbl = table(["Facility", "Links", "Model/Obs", "R²", "%RMSE", "GEH<5"],
                        fac_rows, num_cols=(1, 4, 5))
        # by county (top by counted links)
        cty_rows = []
        cc = cv.groupby("county").size().sort_values(ascending=False)
        for c in cc.index[:12]:
            g = cv[cv["county"] == c]
            s = valstats(g)
            M("Validation", "model_obs_ratio", f"county:{c}", round(s["ratio"], 3))
            cty_rows.append((c, f'{s["links"]:,}', _ratio_pill(s["ratio"]),
                             f'{s["r2"]:.2f}' if not math.isnan(s["r2"]) else "—",
                             f'{s["prmse"]:.0f}'))
        cty_tbl = table(["County", "Links", "Model/Obs", "R²", "%RMSE"],
                        cty_rows, num_cols=(1, 4))
        sc = scatter_obs_model(cv)
        sections.append(("Count validation",
            "The headline calibration: modelled vs observed daily volumes on "
            f"{ov['links']:,} counted links (low-count mainline/toll links below "
            f"{min_mainline:,} filtered, per the canonical summary). Observed = "
            f"{cv.attrs.get('count_source', 'count_validation.csv')}. "
            f"{cv.attrs.get('n_flagged', 0)} physically-implausible counts "
            "(data-source errors) excluded from the stats and written to "
            "count_review_flagged.csv for manual review. Ratio pills: "
            "green ≤10%, amber ≤20%, red beyond.",
            tl + '<div class="cols2"><div class="chart">' + sc +
            '<p class="fignote">Observed vs model daily volume (y=x reference).</p></div>'
            '<div><h3>By facility class</h3>' + fac_tbl +
            '<h3>By county (most-counted)</h3>' + cty_tbl + '</div></div>'))
    else:
        sections.append(("Count validation", "", '<p class="notrun">count_validation.csv not found.</p>'))

    # ---- tolling ----
    if toll:
        M("Tolling", "peak_el_toll", "all", round(toll["peak"], 2), "$")
        M("Tolling", "revenue_proxy", "all", round(toll["revenue"], 0), "$")
        M("Tolling", "el_daily_volume", "all", round(toll["el_vol"], 0), "veh")
        for h_, v in toll["profile"]:
            M("Tolling", "mean_el_toll", f"hour:{h_}", round(v, 3), "$")
        lp = line_profile(toll["profile"])
        tl = tiles([(f'${toll["peak"]:.2f}', "Peak EL toll"),
                    (f'${_fmt(toll["revenue"])}', "Toll revenue proxy (day)"),
                    (f'{_fmt(toll["el_vol"])} <small>veh</small>', "EL daily volume")])
        sections.append(("Tolling — express lanes",
            "Volume-weighted mean express-lane toll by hour (meso tier, all EL "
            "facilities statewide), the peak (LOS ceiling), and a first-order "
            "revenue proxy Σ(volume × toll).",
            tl + '<div class="chart">' + lp +
            '<p class="fignote">Mean EL toll by hour of day.</p></div>'))
    else:
        sections.append(("Tolling — express lanes", "",
                         '<p class="notrun">No EL toll_rate in the meso link performance.</p>'))

    # ---- facility profiles (volume / speed / toll by direction) ----
    if fprof:
        blocks = []
        for fname in FAC_DISPLAY_ORDER:
            if fname not in fprof:
                continue
            p = fprof[fname]
            dirs = p["dirs"]
            order = sorted(dirs)
            colmap = {dn: ("--macro" if i == 0 else "--el")
                      for i, dn in enumerate(order)}
            legend = " &nbsp; ".join(
                f'<span style="color:var({colmap[dn]});font-weight:800">■</span> '
                f'<span style="font-size:12px;color:var(--ink2)">{dn}</span>'
                for dn in order)
            chips = tiles([
                (f'{_fmt(p["daily_vol"])} <small>veh</small>', "Daily volume (both dir)"),
                (f'${p["mean_toll"]:.2f}' if p["tolled"] else "—", "Mean toll · tolled hours"),
                (f'${p["peak_toll"]:.2f}' if p["tolled"] else "untolled", "Peak toll"),
                (f'${_fmt(p["revenue"])}' if p["tolled"] else "—", "Revenue proxy (day)")])
            vser = [(dn, dirs[dn]["vol"], colmap[dn]) for dn in order]
            sser = [(dn, dirs[dn]["speed"], colmap[dn]) for dn in order]
            tser = [(dn, dirs[dn]["toll"], colmap[dn]) for dn in order]
            if p["tolled"]:
                toll_chart = ('<div><div class="chart">' +
                              dir_profile(tser, "toll ($)", fmt=lambda v: f"${v:.2f}") +
                              '</div><p class="fignote">Toll ($) — meso-posted '
                              'rate.</p></div>')
            else:
                toll_chart = ('<div class="card"><p class="notrun">Untolled — '
                              'reversible capacity only (no gantry). Add a '
                              'reversible toll policy to price it.</p></div>')
            charts = ('<div class="cols3"><div><div class="chart">' +
                      dir_profile(vser, "veh / hr") +
                      '</div><p class="fignote">Volume (veh/hr).</p></div>'
                      '<div><div class="chart">' +
                      dir_profile(sser, "mph", fmt=lambda v: f"{v:.0f}") +
                      '</div><p class="fignote">Speed (mph).</p></div>' +
                      toll_chart + '</div>')
            blocks.append(
                f'<h3 style="font-size:15px;color:var(--ink);margin-top:26px">'
                f'{html.escape(fname)} &nbsp; {legend}</h3>' + chips + charts)
            M("Facility", "daily_volume", fname, round(p["daily_vol"], 0), "veh")
            M("Facility", "mean_toll_tolled_hours", fname,
              round(p["mean_toll"], 2) if p["tolled"] else None, "$")
            M("Facility", "peak_toll", fname,
              round(p["peak_toll"], 2) if p["tolled"] else None, "$")
            M("Facility", "revenue_proxy", fname,
              round(p["revenue"], 0) if p["tolled"] else None, "$")
            for dn in order:
                M("Facility", "daily_volume_dir", f"{fname}|{dn}",
                  round(sum(v for _, v in dirs[dn]["vol"]), 0), "veh")
        sections.append(("Facility profiles — volume · speed · toll by direction",
            "Each priced express-lane facility (and I-595 reversible), split by "
            "travel direction: hourly volume, volume-weighted speed, and the "
            "meso-posted toll. Toll means exclude zero-toll hours, so time-of-day "
            "facilities (I-295) report their in-window rate — not a day-diluted "
            "one — and the density facilities sit at or above their $0.50 floor.",
            "".join(blocks)))

    # ---- convergence + multi-resolution ----
    conv_html = ""
    if conv:
        rg = conv.get("rel_gap")
        M("Convergence", "mean_rel_gap", "all", None if rg is None or math.isnan(rg) else round(rg, 4))
        M("Convergence", "vot_mean", "all", conv.get("vot_mean"))
        conv_html = tiles([
            (f'{rg*100:.1f}<small>%</small>' if rg is not None and not math.isnan(rg) else "—",
             "Mean relative gap (proxy)"),
            (f'{_fmt(conv.get("trips"))}', "Vehicle-trips loaded"),
            (f'${conv.get("vot_mean"):.0f}<small>/h</small>' if conv.get("vot_mean") else "—",
             "Mean value of time")])
    mr = tiles([(f'{tier_links.get("macro",0):,}', "Macro links (NodeLTM)"),
                (f'{tier_links.get("meso",0):,}', "Meso links (packets)"),
                (f'{tier_links.get("micro",0):,}', "Micro links (IDM/MOBIL)")])
    sections.append(("Convergence & multi-resolution",
        "An assignment-quality proxy (weighted mean of per-agent gap ÷ cost from "
        "the trip plans; the full relative-gap trajectory needs the run console "
        "log, wired in a later phase) and the split of the network across the "
        "three resolutions.",
        conv_html + '<h3>Resolution split</h3>' + mr))

    # ---- population synthesis ----
    ps = popsyn_summary(demand_paths, out_dir)
    if ps:
        thh, tper = ps["total_hh"], ps["total_per"]
        D("PopSyn", "households", "all", round(thh, 0))
        D("PopSyn", "persons", "all", round(tper, 0))
        D("PopSyn", "persons_per_hh", "all", round(tper / thh, 2) if thh else None)
        ctrl_hh = sum(v[0] for v in ps["ctrl_county"].values())
        ctrl_pop = sum(v[1] for v in ps["ctrl_county"].values())
        dev_hh = 100 * (thh / ctrl_hh - 1) if ctrl_hh else float("nan")
        dev_pop = 100 * (tper / ctrl_pop - 1) if ctrl_pop else float("nan")
        D("PopSyn", "hh_dev_vs_control", "all", round(dev_hh, 2), "%")
        D("PopSyn", "pop_dev_vs_control", "all", round(dev_pop, 2), "%")
        ps_tiles = tiles([
            (f'{_fmt(thh)}', "Households synthesized"),
            (f'{_fmt(tper)}', "Persons"),
            (f'{tper/thh:.2f}' if thh else "—", "Persons / household"),
            (_pill(f"{dev_hh:+.1f}%", "good" if abs(dev_hh) <= 1 else
                   ("warn" if abs(dev_hh) <= 3 else "bad")) if ctrl_hh else "—",
             "HH vs control"),
            (_pill(f"{dev_pop:+.1f}%", "good" if abs(dev_pop) <= 1 else
                   ("warn" if abs(dev_pop) <= 3 else "bad")) if ctrl_pop else "—",
             "Pop vs control")])
        # county fit table (largest 12 by control HH)
        crow = []
        byc = sorted(ps["ctrl_county"].items(), key=lambda kv: -kv[1][0])[:12]
        for c, (chh, cpop) in byc:
            shh = ps["hh_county"].get(c, 0.0)
            dv = 100 * (shh / chh - 1) if chh else float("nan")
            D("PopSyn", "hh_dev_vs_control", f"county:{c}", round(dv, 2), "%")
            crow.append((c, _fmt(chh), _fmt(shh),
                         _pill(f"{dv:+.1f}%", "good" if abs(dv) <= 1 else
                               ("warn" if abs(dv) <= 3 else "bad"))))
        ctbl = table(["County", "Control HH", "Synthesized HH", "Deviation"],
                     crow, num_cols=(1, 2))
        # HH size distribution bar
        sz = [(f"{k}{'+' if k=='7' else ''} person", ps["size"].get(k, 0.0), "--gp")
              for k in map(str, range(1, 8))]
        for k, v, _c in sz:
            D("PopSyn", "hh_by_size", k, round(v, 0))
        szbar = hbars(sz)
        sections.append(("Population synthesis",
            "Synthesized households and persons vs the land-use control totals "
            "(TotHH / POP), expansion-weighted. Deviation pills: green ≤1%, "
            "amber ≤3%.",
            ps_tiles + '<div class="cols2"><div>' + ctbl +
            '</div><div class="chart">' + szbar +
            '<p class="fignote">Households by size (expansion-weighted).</p>'
            '</div></div>'))
    else:
        sections.append(("Population synthesis", "",
            '<p class="notrun">Syn_households.csv not found in the run or parent '
            'scenario directory.</p>'))

    # ---- skims ----
    sk = skims_summary(demand_paths)
    if sk:
        it = []
        if "zones" in sk:
            it.append((f'{sk["zones"]:,}', "Zones skimmed"))
            D("Skims", "zones", "all", sk["zones"])
        if "disconnected" in sk:
            k = "good" if sk["disconnected"] == 0 else "bad"
            it.append((_pill(str(sk["disconnected"]), k), "Disconnected OD pairs"))
            D("Skims", "disconnected_od", "all", sk["disconnected"])
        if "isolated" in sk:
            it.append((f'{sk["isolated"]}', "Isolated zones (fallback intrazonal)"))
            D("Skims", "isolated_zones", "all", sk["isolated"])
        sub = (f'Coverage sanity only — {sk.get("omx","the skim")} '
               f'({sk.get("omx_gb",0):.2f} GB) is FREE-FLOW, so OD travel-time '
               'statistics are not meaningful and are deliberately not reported.')
        sections.append(("Skims", sub, tiles(it) if it else
                         '<p class="notrun">Skimmy.log found but no stats parsed.</p>'))
    else:
        sections.append(("Skims", "",
            '<p class="notrun">No Skimmy.log / FF_Skim OMX found.</p>'))

    # ---- demand composition from the assembled trip list ----
    MKT_ORDER = ["SDT resident", "SDT visitor", "LDT resident", "LDT visitor",
                 "Truck", "External / OS"]
    MKT_COLOR = {"SDT resident": "--gp", "SDT visitor": "--el",
                 "LDT resident": "--macro", "LDT visitor": "--micro",
                 "Truck": "--meso", "External / OS": "--warn"}
    if tlist:
        tv, tp = tlist["total_veh"], tlist["total_per"]
        occ = tp / tv if tv else float("nan")
        D("TripList", "vehicle_trips", "all", round(tv, 0), "veh-trips")
        D("TripList", "person_trips", "all", round(tp, 0), "person-trips")
        D("TripList", "mean_occupancy", "all", round(occ, 2))
        bm, pm = tlist["by_market"], tlist["per_market"]
        order = [m for m in MKT_ORDER if m in bm] + [m for m in bm if m not in MKT_ORDER]
        mkt_rows = []
        for m in order:
            mv, mp = bm[m], pm.get(m, 0.0)
            D("TripList", "vehicle_trips", m, round(mv, 0), "veh-trips")
            mkt_rows.append((m, _fmt(mv), _fmt(mp),
                             f"{mp/mv:.2f}" if mv else "—",
                             f"{100*mv/tv:.1f}%" if tv else "—"))
        mkt_tbl = table(["Market", "Vehicle-trips", "Person-trips", "Occ", "Share"],
                        mkt_rows, num_cols=(1, 2, 3, 4))
        mbar = hbars([(m, bm[m], MKT_COLOR.get(m, "--muted")) for m in order])
        hours = [(h, tlist["by_hour"].get(str(h), 0.0)) for h in range(24)]
        for h_, hv in hours:
            D("TripList", "departures", f"hour:{h_}", round(hv, 0), "veh-trips")
        dep = line_profile(hours, unit="", ylab="Vehicle-trips",
                           w=560, h=200)
        # purpose bar (top 8)
        pur = sorted(tlist["by_purpose"].items(), key=lambda kv: -kv[1])[:8]
        pbar = hbars([(k, v, "--macro") for k, v in pur])
        tl_tiles = tiles([(f'{_fmt(tp)}', "Person-trips"),
                          (f'{_fmt(tv)}', "Vehicle-trips"),
                          (f'{occ:.2f}', "Mean occupancy"),
                          (f'{len(bm)}', "Demand markets")])
        sections.append(("Trip-list assembly & demand composition",
            "The assembled trip list handed to assignment: person-trips reduced "
            "to vehicle-trips by occupancy, split across the demand markets (the "
            "SDT/LDT × resident/visitor pool), with the loaded departure-time "
            "profile. This is the full demand pool; the assignment section above "
            "is what THIS run loaded onto the network.",
            tl_tiles + '<div class="cols2"><div class="chart">' + mbar +
            '<p class="fignote">Vehicle-trips by market.</p>' + dep +
            '<p class="fignote">Departure-time profile (vehicle-trips by hour).</p>'
            '</div><div>' + mkt_tbl + '<h3>Trips by purpose</h3>' + pbar + '</div></div>'))

        # SDT / LDT sub-sections from the market×purpose cross
        def _market_section(name, groups, note):
            mp_cross = tlist["by_market_purpose"]
            tot = sum(bm.get(g, 0.0) for g in groups)
            if tot <= 0:
                return (name, "", f'<p class="notrun">{note}</p>')
            # per-purpose totals across the groups
            pur_tot = {}
            for k, val in mp_cross.items():
                g, p = k.split("||", 1)
                if g in groups:
                    pur_tot[p] = pur_tot.get(p, 0.0) + val
            prows = [(p, _fmt(v), f"{100*v/tot:.1f}%")
                     for p, v in sorted(pur_tot.items(), key=lambda kv: -kv[1])[:10]]
            ptbl = table(["Purpose", "Vehicle-trips", "Share"], prows, num_cols=(1, 2))
            gtiles = tiles([(f'{_fmt(bm.get(g, 0.0))}', g) for g in groups if g in bm])
            for g in groups:
                D(name.split(" ")[0], "vehicle_trips", g, round(bm.get(g, 0.0), 0), "veh-trips")
            return (name,
                    f"Vehicle-trips in the {name.split(' (')[0].lower()} markets, "
                    "by trip purpose (from the assembled trip list). " + note,
                    gtiles + '<h3>By purpose</h3>' + ptbl)

        sections.append(_market_section(
            "Short-distance travel (SDT)", ["SDT resident", "SDT visitor"],
            "Trip-length distribution and mode split need the raw SDT trip file "
            "with its code maps — a later refinement."))
        sections.append(_market_section(
            "Long-distance travel (LDT)", ["LDT resident", "LDT visitor"],
            "Ground LDT only (air tours are not in the vehicle trip list); the "
            "DMA-to-DMA matrix is a later refinement."))
    else:
        for name in ("Trip-list assembly & demand composition",
                     "Short-distance travel (SDT)", "Long-distance travel (LDT)"):
            sections.append((name, "",
                '<p class="notrun">tripList_30min not found in the run or parent '
                'scenario directory — pass --demand-dir to point at it.</p>'))

    # ---- write metrics.csv ----
    mpath = os.path.join(out_dir, "scenario_metrics.csv")
    with open(mpath, "w", newline="", encoding="utf-8") as fh:
        wr = csv.writer(fh)
        wr.writerow(["stage", "section", "metric", "segment", "value", "unit"])
        wr.writerows(metrics)

    # ---- order sections along the model pipeline ----
    # PopSyn -> Skims -> SDT -> LDT -> trip list (agentPlans) -> assignment (HyDRA)
    PIPE = ["Population synthesis", "Skims",
            "Short-distance travel (SDT)", "Long-distance travel (LDT)",
            "Trip-list assembly & demand composition",
            "Network totals", "Count validation", "Tolling — express lanes",
            "Facility profiles — volume · speed · toll by direction",
            "Convergence & multi-resolution"]
    sections.sort(key=lambda s: PIPE.index(s[0]) if s[0] in PIPE else len(PIPE))

    # ---- HTML ----
    body = []
    for i, (name, sub, content) in enumerate(sections, 1):
        body.append(f'<h2>{i} · {html.escape(name)}</h2>')
        if sub:
            body.append(f'<p class="sub">{html.escape(sub)}</p>')
        body.append(content)
    hdoc = (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{html.escape(title)}</title><style>{CSS}</style></head><body>'
            f'<button class="tog">◐ theme</button><div class="wrap">'
            f'<div class="eyebrow">HyDRA · Turnpike State Model (TSM v6) · Scenario Report</div>'
            f'<h1>{html.escape(title)}</h1>'
            f'<p class="sub">One report card for the whole model chain — population '
            f'synthesis → skims → SDT → LDT → trip-list assembly → HyDRA assignment '
            f'— generated from the run\'s own outputs.</p>{prov}'
            f'{"".join(body)}</div>{_THEME_JS}</body></html>')
    hpath = os.path.join(out_dir, "scenario_report.html")
    with open(hpath, "w", encoding="utf-8") as fh:
        fh.write(hdoc)

    # ---- markdown twin ----
    md = build_markdown(title, run_dir, n_links, counties, veh, when, net, cv,
                        toll, conv, tier_links, min_mainline, tlist, fprof)
    mdpath = os.path.join(out_dir, "scenario_report.md")
    with open(mdpath, "w", encoding="utf-8") as fh:
        fh.write(md)

    print(f"[report] {hpath}")
    print(f"[report] {mdpath}")
    print(f"[report] {mpath}  ({len(metrics)} metrics)")
    return hpath


def build_markdown(title, run_dir, n_links, counties, veh, when, net, cv,
                   toll, conv, tier_links, min_mainline, tl=None, profiles=None):
    L = [f"# {title}", "",
         f"*HyDRA · Turnpike State Model (TSM v6) · assignment report card*", "",
         f"- **Run:** `{os.path.basename(run_dir)}`",
         f"- **Network:** {n_links:,} directed links · {counties} counties",
         f"- **Vehicle-trips:** {_fmt(veh)}",
         f"- **Generated:** {when}", ""]
    if net is not None and not net.empty:
        vmt = net["vmt"].sum(); vht = net["vht"].sum()
        L += ["## Network totals", "",
              f"Daily **VMT {_fmt(vmt)}** veh-mi · **VHT {_fmt(vht)}** veh-h · "
              f"**mean speed {vmt/vht:.1f}** mph", "",
              "| Facility | VMT | VHT | Mean speed (mph) |",
              "|---|--:|--:|--:|"]
        net2 = net.assign(ord=net["fac"].map({f: i for i, f in enumerate(FAC_ORDER)}).fillna(9)).sort_values("ord")
        for _, r in net2.iterrows():
            L.append(f"| {r['fac']} | {_fmt(r['vmt'])} | {_fmt(r['vht'])} | {r['speed']:.1f} |")
        L.append("")
    if cv is not None and not cv.empty:
        ov = valstats(cv)
        L += ["## Count validation", "",
              f"Model/observed **{ov['ratio']:.2f}** · R² **{ov['r2']:.3f}** · "
              f"%RMSE **{ov['prmse']:.1f}** · GEH<5 **{ov['geh5']:.0f}%** · "
              f"GEH<10 **{ov['geh10']:.0f}%** ({ov['links']:,} counted links, "
              f"min-mainline {min_mainline:,})", "",
              "| Facility | Links | Model/Obs | R² | %RMSE | GEH<5 |",
              "|---|--:|--:|--:|--:|--:|"]
        for f_ in FAC_ORDER:
            g = cv[cv["fac"] == f_]
            if len(g) < 3:
                continue
            s = valstats(g)
            r2 = f"{s['r2']:.2f}" if not math.isnan(s["r2"]) else "—"
            L.append(f"| {f_} | {s['links']:,} | {s['ratio']:.2f} | {r2} | {s['prmse']:.0f} | {s['geh5']:.0f} |")
        L.append("")
    if toll:
        L += ["## Tolling", "",
              f"Peak EL toll **${toll['peak']:.2f}** · revenue proxy "
              f"**${_fmt(toll['revenue'])}**/day · EL volume **{_fmt(toll['el_vol'])}** veh", ""]
    if profiles:
        L += ["## Facility profiles (by direction)", "",
              "Volume/speed/toll split by direction in the HTML report; toll means "
              "below exclude zero-toll (ToD off-peak) hours.", "",
              "| Facility | Daily vol | Mean toll* | Peak | Revenue/day |",
              "|---|--:|--:|--:|--:|"]
        for fname in FAC_DISPLAY_ORDER:
            if fname not in profiles:
                continue
            p = profiles[fname]
            mt = f"${p['mean_toll']:.2f}" if p["tolled"] else "—"
            pk = f"${p['peak_toll']:.2f}" if p["tolled"] else "untolled"
            rv = f"${_fmt(p['revenue'])}" if p["tolled"] else "—"
            L.append(f"| {fname} | {_fmt(p['daily_vol'])} | {mt} | {pk} | {rv} |")
        L += ["", "*mean toll excludes zero-toll (ToD off-peak) hours.", ""]
    if conv:
        rg = conv.get("rel_gap")
        rgs = f"{rg*100:.1f}%" if rg is not None and not math.isnan(rg) else "—"
        L += ["## Convergence & multi-resolution", "",
              f"Mean relative gap (proxy) **{rgs}** · "
              f"macro {tier_links.get('macro',0):,} / meso {tier_links.get('meso',0):,} / "
              f"micro {tier_links.get('micro',0):,} links", ""]
    if tl:
        tv, tp = tl["total_veh"], tl["total_per"]
        L += ["## Trip-list assembly & demand composition", "",
              f"Assembled demand pool: **{_fmt(tp)}** person-trips → "
              f"**{_fmt(tv)}** vehicle-trips (mean occupancy "
              f"**{tp/tv:.2f}**) across {len(tl['by_market'])} markets.", "",
              "| Market | Vehicle-trips | Person-trips | Occ | Share |",
              "|---|--:|--:|--:|--:|"]
        for m, mv in sorted(tl["by_market"].items(), key=lambda kv: -kv[1]):
            mp = tl["per_market"].get(m, 0.0)
            L.append(f"| {m} | {_fmt(mv)} | {_fmt(mp)} | "
                     f"{mp/mv:.2f} | {100*mv/tv:.1f}% |")
        L.append("")
    else:
        L += ["## Demand sections", "",
              "*tripList not found; PopSyn / Skims and detailed SDT/LDT land in "
              "later phases.*", ""]
    return "\n".join(L)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--out-dir")
    ap.add_argument("--title")
    ap.add_argument("--min-mainline", type=int, default=5000)
    ap.add_argument("--demand-dir", help="dir with tripList_30min / SDT / LDT "
                    "outputs (default: run dir, then its parent)")
    ap.add_argument("--count-field", default="FTI_COUNT_24",
                    help="Link.csv count column to score validation against "
                    "(default FTI_COUNT_24; '' keeps count_validation.csv obs)")
    a = ap.parse_args()
    build(a.run_dir, a.out_dir, a.title, a.min_mainline, a.demand_dir,
          a.count_field or None)
