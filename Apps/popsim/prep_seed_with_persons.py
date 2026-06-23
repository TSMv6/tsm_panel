"""
prep_seed_with_persons.py
─────────────────────────
Extended seed preparation that adds per-household person-age-group and
sex count columns by joining the PUMS persons file.

These become HH-level COUNT controls in controls_with_age.csv, allowing
the C++ IPF engine to constrain person age/sex distribution without any
C++ changes.  The engine already handles count controls (res_pop=NP is one).

Usage:
    python prep_seed_with_persons.py <controls_csv> <seed_hh_in>
                                     <seed_persons_in> <seed_hh_out>

Example:
    python prep_seed_with_persons.py ^
      "C:/TSM_NextGen_v6/PopSim/Florida/Setup/configs/HH/controls_with_age.csv" ^
      "C:/TSM_NextGen_v6/Base/TSMv6_2024_fullrun/popsim_seed/seed_hh_prepped.csv" ^
      "C:/TSM_NextGen_v6/Base/TSMv6_2024_fullrun/popsim_seed/seed_persons_Y5_2022_1D_NAICS_OCC.csv" ^
      "C:/TSM_NextGen_v6/Base/popsim_improved/data/seed_hh_with_age.csv"
"""
import sys
import os
import time
import pandas as pd
import numpy as np


# ── Per-person age/sex indicators ─────────────────────────────────────────────
# Each entry: (output_column_name, lambda applied per-person → 0/1)
# The per-HH column will be SUM of these per-person values.
PER_PERSON_INDICATORS = [
    ("age_0_to_4",   lambda p: (p["AGEP"] <= 4).astype(int)),
    ("age_5_to_17",  lambda p: ((p["AGEP"] >= 5)  & (p["AGEP"] <= 17)).astype(int)),
    ("age_18_to_24", lambda p: ((p["AGEP"] >= 18) & (p["AGEP"] <= 24)).astype(int)),
    ("age_25_to_54", lambda p: ((p["AGEP"] >= 25) & (p["AGEP"] <= 54)).astype(int)),
    ("age_55_to_64", lambda p: ((p["AGEP"] >= 55) & (p["AGEP"] <= 64)).astype(int)),
    ("age_65_plus",  lambda p: (p["AGEP"] >= 65).astype(int)),
    ("person_male",  lambda p: (p["SEX"] == 1).astype(int)),
    ("person_female",lambda p: (p["SEX"] == 2).astype(int)),
]


def main():
    if len(sys.argv) < 5:
        print("Usage: prep_seed_with_persons.py <controls_csv> <seed_hh_in>"
              " <seed_persons_in> <seed_hh_out>")
        sys.exit(1)

    controls_path  = sys.argv[1]
    seed_hh_in     = sys.argv[2]
    seed_per_in    = sys.argv[3]
    seed_hh_out    = sys.argv[4]

    # ── Load controls (HH-level only) ─────────────────────────────────────────
    print(f"Reading controls: {controls_path}")
    ctrl = pd.read_csv(controls_path)
    hh_ctrl = ctrl[ctrl["seed_table"] == "households"].copy()
    print(f"  {len(hh_ctrl)} HH-level controls")

    # ── Load seed households ───────────────────────────────────────────────────
    print(f"Reading seed HHs: {seed_hh_in}")
    t0 = time.time()
    hh = pd.read_csv(seed_hh_in, low_memory=False)
    print(f"  {len(hh):,} rows in {time.time()-t0:.1f}s")

    # ── Join persons FIRST → compute per-HH age / sex counts ─────────────────
    # Must happen before expression evaluation so controls like
    # households['age_0_to_4'] can reference the joined columns.
    per_cols_needed = [c for c, _ in PER_PERSON_INDICATORS]
    already_present = all(c in hh.columns and hh[c].sum() > 0 for c in per_cols_needed)

    if not already_present:
        print(f"Computing per-HH person age/sex counts from persons file...")
        print(f"Reading seed persons: {seed_per_in}")
        t0 = time.time()
        per = pd.read_csv(seed_per_in, usecols=["hh_id", "AGEP", "SEX"], low_memory=False)
        print(f"  {len(per):,} rows in {time.time()-t0:.1f}s")

        for col, fn in PER_PERSON_INDICATORS:
            per[col] = fn(per)

        t0 = time.time()
        per_agg = per.groupby("hh_id")[per_cols_needed].sum().reset_index()
        print(f"  Aggregated {len(per_agg):,} households in {time.time()-t0:.1f}s")

        # Drop any stale (zero-filled) columns before merge
        for col in per_cols_needed:
            if col in hh.columns:
                hh.drop(columns=[col], inplace=True)

        hh = hh.merge(per_agg, on="hh_id", how="left")
        for col in per_cols_needed:
            hh[col] = hh[col].fillna(0).astype(int)
        print(f"  Added columns: {per_cols_needed}")

        age_sum = sum(hh[c] for c, _ in PER_PERSON_INDICATORS if "age" in c)
        print(f"  Max discrepancy (age group sum vs NP): {(age_sum - hh['NP']).abs().max()}")
    else:
        print("Per-HH person age/sex columns already present and non-zero — skipping join")

    # ── Compute HH-level indicators from controls expressions ─────────────────
    local_ns = {"households": hh, "np": np}
    added_hh = []
    for _, row in hh_ctrl.iterrows():
        col_name = row["control_field"]
        expr     = row["expression"]
        if col_name in hh.columns and hh[col_name].sum() > 0:
            added_hh.append(col_name)
            continue
        try:
            result = eval(expr, {"__builtins__": {}}, local_ns)
            hh[col_name] = result.astype(int) if hasattr(result, "astype") else int(result)
            added_hh.append(col_name)
        except Exception as e:
            print(f"  WARNING: could not evaluate '{col_name}': {e} — setting to 0")
            hh[col_name] = 0

    # ── Write output ───────────────────────────────────────────────────────────
    os.makedirs(os.path.dirname(seed_hh_out), exist_ok=True)
    print(f"Writing prepped seed: {seed_hh_out}")
    t0 = time.time()
    hh.to_csv(seed_hh_out, index=False)
    print(f"  Done. {len(hh):,} rows, {len(hh.columns)} columns in {time.time()-t0:.1f}s")

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\nSanity check — seed totals for new age/sex controls:")
    for col, _ in PER_PERSON_INDICATORS:
        if col in hh.columns:
            print(f"  {col}: {hh[col].sum():,}")
    print(f"  NP (total persons):  {hh['NP'].sum():,}")


if __name__ == "__main__":
    main()
