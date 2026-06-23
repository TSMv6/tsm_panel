"""
run_improved_popsim.py
──────────────────────
Orchestrates the full improved PopSim run:
  1. Prep seed — add per-HH person age/sex count columns
  2. Run C++ popsim with improved controls (popsim_improved.toml)
  3. Combine HH output (copy for single-profile run)
  4. Print quick comparison summary

Run from C:\\Projects\\tsm_PopSim\\cpp:
    python run_improved_popsim.py

Or with --skip-prep if seed already exists:
    python run_improved_popsim.py --skip-prep
"""
import os
import sys
import subprocess
import time
import shutil

# ── Paths ─────────────────────────────────────────────────────────────────────
HERE       = os.path.dirname(os.path.abspath(__file__))
EXE        = os.path.join(HERE, "out", "Release", "popsim-run.exe")
TOML       = os.path.join(HERE, "popsim_improved.toml")
PREP_SCRIPT= os.path.join(HERE, "prep_seed_with_persons.py")

CONTROLS   = r"C:\TSM_NextGen_v6\PopSim\Florida\Setup\configs\HH\controls_with_age.csv"
SEED_HH_IN = r"C:\TSM_NextGen_v6\Base\TSMv6_2024_fullrun\popsim_seed\seed_hh_prepped.csv"
SEED_PER   = r"C:\TSM_NextGen_v6\Base\TSMv6_2024_fullrun\popsim_seed\seed_persons_Y5_2022_1D_NAICS_OCC.csv"
SEED_HH_OUT= r"C:\TSM_NextGen_v6\Base\popsim_improved\data\seed_hh_with_age.csv"
OUTPUT_HH  = r"C:\TSM_NextGen_v6\Base\popsim_improved\output\HH"
COMBINED   = r"C:\TSM_NextGen_v6\Base\popsim_improved\Combined"


def run(cmd, desc):
    print(f"\n{'='*60}")
    print(f"  {desc}")
    print(f"{'='*60}")
    t0 = time.time()
    result = subprocess.run(cmd, shell=True)
    elapsed = time.time() - t0
    if result.returncode != 0:
        print(f"  ERROR: exit code {result.returncode}")
        sys.exit(result.returncode)
    print(f"  Done in {elapsed:.1f}s")


def main():
    skip_prep = "--skip-prep" in sys.argv

    # ── Step 1: Prep seed ────────────────────────────────────────────────────
    if skip_prep and os.path.exists(SEED_HH_OUT):
        print(f"Skipping seed prep (--skip-prep): {SEED_HH_OUT}")
    else:
        run(
            f'python "{PREP_SCRIPT}" "{CONTROLS}" "{SEED_HH_IN}" "{SEED_PER}" "{SEED_HH_OUT}"',
            "Step 1: Prep seed with per-HH person age/sex counts"
        )

    # ── Step 2: Run popsim ───────────────────────────────────────────────────
    if not os.path.exists(EXE):
        print(f"\nERROR: popsim-run.exe not found at {EXE}")
        print("Build it first: run build_release.bat")
        sys.exit(1)

    run(f'"{EXE}" "{TOML}"', "Step 2: Run C++ PopSim with improved controls")

    # ── Step 3: Copy HH output to Combined (no GQ in this run) ───────────────
    print(f"\nStep 3: Copy HH output to Combined folder")
    os.makedirs(COMBINED, exist_ok=True)
    for fname in ["synthetic_households.csv", "synthetic_persons.csv"]:
        src = os.path.join(OUTPUT_HH, fname)
        dst = os.path.join(COMBINED, fname)
        if os.path.exists(src):
            shutil.copy2(src, dst)
            print(f"  Copied {fname}")
        else:
            print(f"  WARNING: {src} not found")

    # ── Step 4: Quick summary ────────────────────────────────────────────────
    print("\nStep 4: Quick output summary")
    try:
        import pandas as pd
        hh = pd.read_csv(os.path.join(COMBINED, "synthetic_households.csv"), usecols=["NP","workers","HHINCADJ"])
        per = pd.read_csv(os.path.join(COMBINED, "synthetic_persons.csv"), usecols=["AGEP","SEX"])
        print(f"  Synthetic households: {len(hh):,}")
        print(f"  Synthetic persons:    {len(per):,}")
        print(f"  Avg HH size:          {hh['NP'].mean():.2f}")
        print(f"  Age 0-4:    {(per['AGEP']<=4).sum():,}  ({(per['AGEP']<=4).mean()*100:.1f}%)")
        print(f"  Age 65+:    {(per['AGEP']>=65).sum():,}  ({(per['AGEP']>=65).mean()*100:.1f}%)")
        print(f"  Inc <15k:   {(hh['HHINCADJ']<=14999).sum():,}  ({(hh['HHINCADJ']<=14999).mean()*100:.1f}%)")
    except Exception as e:
        print(f"  (summary skipped: {e})")

    print(f"\nImproved output ready at: {COMBINED}")
    print(f"\nTo compare: edit popsim_comparison.py CONFIG:")
    print(f'  "run_b_hh":  r"{os.path.join(COMBINED, "synthetic_households.csv")}"')
    print(f'  "run_b_per": r"{os.path.join(COMBINED, "synthetic_persons.csv")}"')


if __name__ == "__main__":
    main()
