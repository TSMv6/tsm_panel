"""
prep_seed.py — Compute PopSim indicator columns from raw PUMS seed CSV.

Reads the raw seed_households CSV (which has NP, BLD, KID, workers, AGEHOH,
HHINCADJ, WGTP, PUMA, hh_id columns) and adds one binary indicator column
for each HH-level control in controls_standard.csv.

The C++ popsim-run.exe SeedLoader reads these precomputed indicator columns
by name (matching control_field in controls_standard.csv).

Usage:
    python prep_seed.py <controls_csv> <seed_hh_in> <seed_hh_out>

Example:
    python prep_seed.py ^
      "C:/TSM_NextGen_v6/PopSim/Florida/Setup/configs/HH/controls_standard.csv" ^
      "C:/TSM_NextGen_v6/PopSim/Florida/Setup/data/seed_households_Y5_2022_updatePUMA.csv" ^
      "C:/TSM_NextGen_v6/Base/popsim_test/data/seed_hh_prepped.csv"
"""
import sys
import os
import pandas as pd
import numpy as np

def main():
    if len(sys.argv) < 4:
        print("Usage: prep_seed.py <controls_csv> <seed_hh_in> <seed_hh_out>")
        sys.exit(1)

    controls_path = sys.argv[1]
    seed_in_path  = sys.argv[2]
    seed_out_path = sys.argv[3]

    print(f"Reading controls: {controls_path}")
    ctrl = pd.read_csv(controls_path)
    # Filter HH-level controls only
    hh_ctrl = ctrl[ctrl['seed_table'] == 'households'].copy()
    print(f"  {len(hh_ctrl)} HH-level controls")

    print(f"Reading seed HHs: {seed_in_path}")
    print("  (this may take a minute for the full Florida seed...)")
    hh = pd.read_csv(seed_in_path, low_memory=False)
    print(f"  {len(hh):,} seed households loaded")

    # Evaluate each expression and store as indicator column
    local_ns = {'households': hh, 'np': np}
    added = []
    for _, row in hh_ctrl.iterrows():
        col_name  = row['control_field']
        expr      = row['expression']
        try:
            result = eval(expr, {"__builtins__": {}}, local_ns)
            hh[col_name] = result.astype(int)
            added.append(col_name)
        except Exception as e:
            print(f"  WARNING: could not evaluate '{col_name}': {e} — setting to 0")
            hh[col_name] = 0

    print(f"  Added {len(added)} indicator columns: {added[:5]}...")

    os.makedirs(os.path.dirname(seed_out_path), exist_ok=True)
    print(f"Writing prepped seed: {seed_out_path}")
    hh.to_csv(seed_out_path, index=False)
    print(f"  Done. {len(hh):,} rows, {len(hh.columns)} columns")

    # Quick sanity check
    print("\nIndicator column sums (should match state-wide HH totals):")
    for col in added[:5]:
        print(f"  {col}: {hh[col].sum():,}")

if __name__ == "__main__":
    main()
