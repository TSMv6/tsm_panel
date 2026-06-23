"""
validate_output.py — Compare synthetic HH output to SE data control totals.

Usage:
    python validate_output.py \
        --synth  C:/TSM_NextGen_v6/Base/popsim_test/output/HH/synthetic_households.csv \
        --se     C:/TSM_NextGen_v6/Base/sdt_test/tsm_landuse.csv \
        --xwalk  C:/TSM_NextGen_v6/PopSim/Florida/Setup/data/TSM_geo_Crosswalk.csv
"""

import argparse
import pandas as pd
import numpy as np

# SE column -> meaningful label
SE_CONTROLS = {
    "TotHH": "Total HH",
    "person_1_HH": "HH size 1",
    "person_2_HH": "HH size 2",
    "person_3_HH": "HH size 3",
    "person_4_HH": "HH size 4",
    "person_5_HH": "HH size 5",
    "person_6_HH": "HH size 6",
    "person_7_plus_HH": "HH size 7+",
    "worker_0_HH": "Workers 0",
    "worker_1_HH": "Workers 1",
    "worker_2_HH": "Workers 2",
    "worker_3_plus_HH": "Workers 3+",
    "Annual_household_income_k0_to_k14999": "Inc <15k",
    "Annual_household_income_k15000_to_k24999": "Inc 15-25k",
    "Annual_household_income_k25000_to_k34999": "Inc 25-35k",
    "Annual_household_income_k35000_to_k44999": "Inc 35-45k",
    "Annual_household_income_k45000_to_k59999": "Inc 45-60k",
    "Annual_household_income_k60000_to_k99999": "Inc 60-100k",
    "Annual_household_income_k100000_to_k149999": "Inc 100-150k",
    "Annual_household_income_over_k149999": "Inc 150k+",
    "Household_with_Kids": "Has Kids",
    "Household_without_Kids": "No Kids",
    "age_15_to_24_HH": "HoH age 15-24",
    "age_25_to_54_HH": "HoH age 25-54",
    "age_55_to_64_HH": "HoH age 55-64",
    "age_65_plus_HH": "HoH age 65+",
    "Units_structure_detached": "Single-family detached",
    "Units_structure_attached": "Multi-unit",
    "Units_structure_mobile_homes": "Mobile home",
}


def compute_synth_totals(synth: pd.DataFrame) -> dict:
    """Aggregate synthetic HH columns to statewide totals."""
    totals = {}

    # Each row = one synthetic HH; hhexpfac is the expansion factor
    expfac = synth["hhexpfac"].fillna(1.0)

    totals["TotHH"] = len(synth)  # count of records = expanded HHs

    # NP (household size) categories
    np_col = synth["NP"].astype(int)
    for sz, col in [(1,"person_1_HH"),(2,"person_2_HH"),(3,"person_3_HH"),
                    (4,"person_4_HH"),(5,"person_5_HH"),(6,"person_6_HH")]:
        totals[col] = (np_col == sz).sum()
    totals["person_7_plus_HH"] = (np_col >= 7).sum()

    # Workers
    wk = synth["workers"].astype(int)
    totals["worker_0_HH"] = (wk == 0).sum()
    totals["worker_1_HH"] = (wk == 1).sum()
    totals["worker_2_HH"] = (wk == 2).sum()
    totals["worker_3_plus_HH"] = (wk >= 3).sum()

    # Income (HHINCADJ stored in output)
    inc = synth["HHINCADJ"].astype(float)
    totals["Annual_household_income_k0_to_k14999"]       = ((inc > -999999999) & (inc <= 14999)).sum()
    totals["Annual_household_income_k15000_to_k24999"]   = ((inc > 14999) & (inc <= 24999)).sum()
    totals["Annual_household_income_k25000_to_k34999"]   = ((inc > 24999) & (inc <= 34999)).sum()
    totals["Annual_household_income_k35000_to_k44999"]   = ((inc > 34999) & (inc <= 44999)).sum()
    totals["Annual_household_income_k45000_to_k59999"]   = ((inc > 44999) & (inc <= 59999)).sum()
    totals["Annual_household_income_k60000_to_k99999"]   = ((inc > 59999) & (inc <= 99999)).sum()
    totals["Annual_household_income_k100000_to_k149999"] = ((inc > 99999) & (inc <= 149999)).sum()
    totals["Annual_household_income_over_k149999"]       = (inc > 149999).sum()

    # Kids
    kid = synth["KID"].astype(int)
    totals["Household_with_Kids"]    = (kid == 1).sum()
    totals["Household_without_Kids"] = (kid == 0).sum()

    # HoH age (AGEHOH)
    age = synth["AGEHOH"].astype(float)
    totals["age_15_to_24_HH"] = ((age >= 15) & (age <= 24)).sum()
    totals["age_25_to_54_HH"] = ((age >= 25) & (age <= 54)).sum()
    totals["age_55_to_64_HH"] = ((age >= 55) & (age <= 64)).sum()
    totals["age_65_plus_HH"]  = (age >= 65).sum()

    # Building type (VEH is in output; BLD is also in output)
    bld = synth["BLD"].astype(int)
    totals["Units_structure_detached"]   = bld.isin([2, 3]).sum()
    totals["Units_structure_attached"]   = bld.isin([4, 5, 6, 7, 8, 9]).sum()
    totals["Units_structure_mobile_homes"] = bld.isin([1, 10]).sum()

    return totals


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--synth",  required=True, help="synthetic_households.csv")
    parser.add_argument("--se",     required=True, help="tsm_landuse.csv")
    parser.add_argument("--xwalk",  required=True, help="TSM_geo_Crosswalk.csv")
    args = parser.parse_args()

    print("Loading crosswalk...")
    xwalk = pd.read_csv(args.xwalk)
    taz_in_model = set(xwalk["TAZ"].astype(int))
    print(f"  {len(taz_in_model)} TAZs in crosswalk")

    print("Loading SE data...")
    se = pd.read_csv(args.se)
    se_model = se[se["TAZ"].isin(taz_in_model)].copy()
    print(f"  {len(se_model)} SE rows in crosswalk TAZs")

    print("Loading synthetic households...")
    synth = pd.read_csv(args.synth)
    print(f"  {len(synth):,} synthetic HH records")

    # SE control totals (sum over crosswalk TAZs)
    se_totals = {}
    for col in SE_CONTROLS:
        if col in se_model.columns:
            se_totals[col] = se_model[col].sum()

    # Synthetic totals
    synth_totals = compute_synth_totals(synth)

    # Report
    print("\n" + "="*72)
    print(f"{'Control':<35} {'SE Target':>12} {'Synthetic':>12} {'Diff%':>8}")
    print("-"*72)
    for col, label in SE_CONTROLS.items():
        se_val   = se_totals.get(col, 0)
        syn_val  = synth_totals.get(col, 0)
        if se_val > 0:
            pct = 100.0 * (syn_val - se_val) / se_val
            pct_s = f"{pct:+.1f}%"
        else:
            pct_s = "  n/a"
        print(f"  {label:<33} {se_val:>12,.0f} {syn_val:>12,.0f} {pct_s:>8}")

    print("="*72)
    total_se  = se_totals.get("TotHH", 0)
    total_syn = synth_totals.get("TotHH", 0)
    overall_pct = 100.0*(total_syn - total_se)/total_se if total_se > 0 else float("nan")
    print(f"\nTotal HH: SE={total_se:,}  Synthetic={total_syn:,}  "
          f"Difference={total_syn-total_se:+,} ({overall_pct:+.2f}%)")


if __name__ == "__main__":
    main()
