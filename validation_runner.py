"""Loaded-network validation workbook (.xlsx), written in Python from the
summarize CSV.

This is the optional post-step of the Summarization tool. summarize.exe writes a
per-link loaded CSV (assigned volumes + the ground-count field); here we read that
CSV and write an Excel workbook comparing assigned volume to ground counts --
overall, by facility type, and by volume group (%RMSE, %error, correlation).

Pure Python (pandas + openpyxl). It reports progress through the `log` callback
(the panel History box + log file) and never opens a console window.

Counts in the GeoMaster are bidirectional, while the loaded CSV has one row per
directed link, so volumes are summed over BOTH directions of each (A,B) pair and
compared to the single two-way count. That assumption is recorded on the Notes
sheet of the workbook.
"""
import os

# (lower, upper) ground-count groups for the by-volume-group breakdown.
_VOLUME_GROUPS = [
    (0, 5000), (5000, 10000), (10000, 20000),
    (20000, 35000), (35000, 50000), (50000, float("inf")),
]


def _group_label(lo, hi):
    if hi == float("inf"):
        return "{:,}+".format(int(lo))
    return "{:,}-{:,}".format(int(lo), int(hi))


def _pick_count_col(df, preferred):
    """Resolve the ground-count column: the caller's preference if present, else
    the first column whose name contains 'count' that actually carries positive
    values."""
    import pandas as pd
    if preferred and preferred in df.columns:
        return preferred
    cands = [c for c in df.columns if "count" in c.lower()]
    for c in cands:
        if pd.to_numeric(df[c], errors="coerce").fillna(0).gt(0).any():
            return c
    return cands[0] if cands else None


def _pick_assigned_col(df, preferred):
    """Resolve the model-volume column: the caller's preference if present,
    else the known daily-total names -- legacy summarize CSVs carry 'Total',
    HyDRA-mode loaded networks carry 'VOL_DAILY' (matched case-insensitively)."""
    if preferred and preferred in df.columns:
        return preferred
    lower = {c.lower(): c for c in df.columns}
    for name in ("total", "vol_daily"):
        if name in lower:
            return lower[name]
    return None


def _stats_row(label, a, c):
    """Validation metrics for one group: a=assigned array, c=count array."""
    import numpy as np
    n = len(a)
    sa, sc = float(a.sum()), float(c.sum())
    diff = a - c
    rmse = float(np.sqrt(np.mean(diff ** 2))) if n else 0.0
    mean_c = sc / n if n else 0.0
    return {
        "Group": label,
        "N (count locations)": n,
        "Total Count": round(sc),
        "Total Assigned": round(sa),
        "Assigned/Count": round(sa / sc, 4) if sc else 0.0,
        "% Error": round((sa - sc) / sc * 100, 2) if sc else 0.0,
        "RMSE": round(rmse, 1),
        "% RMSE": round(rmse / mean_c * 100, 2) if mean_c else 0.0,
    }


def write_validation_xlsx(csv_path, xlsx_path, count_field=None,
                          assigned_col="Total", facility_col=None,
                          a_col="A", b_col="B", log=print):
    """Read the summarize loaded CSV and write the validation workbook.

    Returns the number of counted (two-way) locations validated. Raises on
    missing dependencies or unusable input so the caller can surface the error.
    """
    try:
        import pandas as pd
        import numpy as np
    except ImportError as e:
        raise RuntimeError(
            "Validation stats need pandas + openpyxl in the QGIS Python "
            "environment (%s)." % e)

    if not os.path.exists(csv_path):
        raise FileNotFoundError("loaded CSV not found: %s" % csv_path)

    log("[validation] reading %s ..." % os.path.basename(csv_path))
    df = pd.read_csv(csv_path, low_memory=False)
    log("[validation] %d link rows read" % len(df))

    count_col = _pick_count_col(df, count_field)
    if not count_col:
        raise RuntimeError("no ground-count column found in the loaded CSV")
    assigned_col = _pick_assigned_col(df, assigned_col)
    if not assigned_col:
        raise RuntimeError("no assigned-volume column ('Total' / 'VOL_DAILY') "
                           "in the loaded CSV")
    if facility_col is None:
        facility_col = "FNAME" if "FNAME" in df.columns else (
            "FTYPE" if "FTYPE" in df.columns else None)
    log("[validation] count='%s'  assigned='%s'  facility='%s'"
        % (count_col, assigned_col, facility_col or "(none)"))

    # Fold the two directed rows of each (A,B) pair into one two-way record:
    # assigned summed, count taken once (bidirectional), facility kept.
    a = pd.to_numeric(df[a_col], errors="coerce")
    b = pd.to_numeric(df[b_col], errors="coerce")
    df = df.assign(
        _lo=np.minimum(a, b), _hi=np.maximum(a, b),
        _asg=pd.to_numeric(df[assigned_col], errors="coerce").fillna(0.0),
        _cnt=pd.to_numeric(df[count_col], errors="coerce").fillna(0.0),
    )
    agg = {"_asg": "sum", "_cnt": "max"}
    if facility_col:
        agg[facility_col] = "first"
    tw = df.groupby(["_lo", "_hi"], as_index=False).agg(agg)

    counted = tw[tw["_cnt"] > 0].copy()
    if counted.empty:
        raise RuntimeError("no links carry a positive count -- nothing to validate")
    log("[validation] %d two-way counted locations" % len(counted))

    asg = counted["_asg"].to_numpy(float)
    cnt = counted["_cnt"].to_numpy(float)

    # ---- Summary sheet --------------------------------------------------------
    overall = _stats_row("ALL counted links", asg, cnt)
    corr = float(np.corrcoef(asg, cnt)[0, 1]) if len(asg) > 1 else 0.0
    overall["R"] = round(corr, 4)
    overall["R2"] = round(corr * corr, 4)
    summary_df = pd.DataFrame([overall])

    # ---- By facility type -----------------------------------------------------
    fac_rows = []
    if facility_col:
        for fac, g in counted.groupby(facility_col):
            fac_rows.append(_stats_row(str(fac), g["_asg"].to_numpy(float),
                                       g["_cnt"].to_numpy(float)))
    fac_df = pd.DataFrame(fac_rows) if fac_rows else pd.DataFrame(
        [{"Group": "(no facility column)"}])

    # ---- By volume group ------------------------------------------------------
    vol_rows = []
    for lo, hi in _VOLUME_GROUPS:
        m = (cnt >= lo) & (cnt < hi)
        if m.any():
            vol_rows.append(_stats_row(_group_label(lo, hi), asg[m], cnt[m]))
    vol_df = pd.DataFrame(vol_rows) if vol_rows else pd.DataFrame(
        [{"Group": "(none)"}])

    # ---- Per-location detail (for scatter plots) ------------------------------
    detail_cols = {"A_node": counted["_lo"].astype("Int64"),
                   "B_node": counted["_hi"].astype("Int64"),
                   "Count": counted["_cnt"].round().astype("Int64"),
                   "Assigned": counted["_asg"].round().astype("Int64")}
    if facility_col:
        detail_cols["Facility"] = counted[facility_col].astype(str)
    detail_df = pd.DataFrame(detail_cols)
    detail_df["Diff"] = detail_df["Assigned"] - detail_df["Count"]

    notes_df = pd.DataFrame({"Notes": [
        "Source CSV: %s" % csv_path,
        "Count column: %s   Assigned column: %s" % (count_col, assigned_col),
        "Volumes are summed over BOTH directions of each (A,B) pair and compared",
        "to the single bidirectional ground count.",
        "%% RMSE = RMSE / mean(count) x 100, over the counted locations in the group.",
        "%% Error = (total assigned - total count) / total count x 100.",
    ]})

    # ---- Write workbook -------------------------------------------------------
    log("[validation] writing %s ..." % os.path.basename(xlsx_path))
    try:
        with pd.ExcelWriter(xlsx_path, engine="openpyxl") as xw:
            summary_df.to_excel(xw, sheet_name="Summary", index=False)
            fac_df.to_excel(xw, sheet_name="By_FacilityType", index=False)
            vol_df.to_excel(xw, sheet_name="By_VolumeGroup", index=False)
            detail_df.to_excel(xw, sheet_name="Counted_Links", index=False)
            notes_df.to_excel(xw, sheet_name="Notes", index=False)
            for ws in xw.book.worksheets:
                for col in ws.columns:
                    width = max((len(str(c.value)) for c in col if c.value is not None),
                                default=10)
                    ws.column_dimensions[col[0].column_letter].width = min(width + 2, 40)
    except PermissionError:
        raise RuntimeError(
            "cannot write %s -- close it in Excel and re-run." % xlsx_path)

    log("[validation] DONE -- %d locations, overall %%RMSE %.1f, R2 %.3f"
        % (len(counted), overall["% RMSE"], overall["R2"]))
    return len(counted)
