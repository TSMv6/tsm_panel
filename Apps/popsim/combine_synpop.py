"""
combine_synpop.py — Merge HH and GQ synthetic population outputs.

Reads synthetic_households.csv + synthetic_persons.csv from both the HH and GQ
output directories, re-numbers GQ household_ids to avoid conflict with HH ids,
and writes combined files to an output directory.

Usage:
    python combine_synpop.py <hh_dir> <gq_dir> <out_dir>

Example:
    python combine_synpop.py ^
      "C:/TSM_NextGen_v6/Base/popsim_test/output/HH" ^
      "C:/TSM_NextGen_v6/Base/popsim_test/output/GQ" ^
      "C:/TSM_NextGen_v6/Base/popsim_test/output/combined"

Output:
    <out_dir>/synthetic_households.csv  — HH rows then GQ rows, unified household_id
    <out_dir>/synthetic_persons.csv     — HH persons then GQ persons, matched household_id
"""
import sys
import os
import csv

def combine(hh_dir: str, gq_dir: str, out_dir: str):
    os.makedirs(out_dir, exist_ok=True)

    hh_hh_path = os.path.join(hh_dir, "synthetic_households.csv")
    hh_per_path = os.path.join(hh_dir, "synthetic_persons.csv")
    gq_hh_path  = os.path.join(gq_dir, "synthetic_households.csv")
    gq_per_path = os.path.join(gq_dir, "synthetic_persons.csv")

    for p in [hh_hh_path, hh_per_path, gq_hh_path, gq_per_path]:
        if not os.path.exists(p):
            raise FileNotFoundError(f"Missing input: {p}")

    # ── Pass 1: find max HH household_id (streaming, no memory load) ──────────
    print("Pass 1: scanning HH household ids...")
    max_hh_id = 0
    with open(hh_hh_path, newline='') as f:
        for row in csv.DictReader(f):
            hid = int(row['household_id'])
            if hid > max_hh_id:
                max_hh_id = hid
    print(f"  Max HH household_id = {max_hh_id:,}")
    gq_offset = max_hh_id  # GQ ids become: original_gq_id + gq_offset

    # ── Pass 2: write combined households ─────────────────────────────────────
    out_hh_path  = os.path.join(out_dir, "synthetic_households.csv")
    out_per_path = os.path.join(out_dir, "synthetic_persons.csv")

    print(f"Writing combined households -> {out_hh_path}")
    n_hh_hh = n_gq_hh = 0
    hh_cols = gq_cols = None

    with open(out_hh_path, 'w', newline='') as fout:
        writer = None

        # HH households (pass-through, unchanged)
        with open(hh_hh_path, newline='') as f:
            reader = csv.DictReader(f)
            hh_cols = reader.fieldnames
            writer  = csv.DictWriter(fout, fieldnames=hh_cols)
            writer.writeheader()
            for row in reader:
                writer.writerow(row)
                n_hh_hh += 1
            if n_hh_hh % 500000 == 0 or True:
                print(f"  HH households written: {n_hh_hh:,}")

        # GQ households (re-number household_id)
        with open(gq_hh_path, newline='') as f:
            reader = csv.DictReader(f)
            gq_cols = reader.fieldnames
            if set(gq_cols) != set(hh_cols):
                raise ValueError(
                    f"Column mismatch: HH={hh_cols}, GQ={gq_cols}")
            for row in reader:
                row['household_id'] = str(int(row['household_id']) + gq_offset)
                writer.writerow(row)
                n_gq_hh += 1

    print(f"  HH: {n_hh_hh:,}  GQ: {n_gq_hh:,}  Total: {n_hh_hh+n_gq_hh:,}")

    # ── Pass 3: write combined persons ────────────────────────────────────────
    print(f"Writing combined persons -> {out_per_path}")
    n_hh_per = n_gq_per = 0

    with open(out_per_path, 'w', newline='') as fout:
        writer = None

        with open(hh_per_path, newline='') as f:
            reader = csv.DictReader(f)
            writer  = csv.DictWriter(fout, fieldnames=reader.fieldnames)
            writer.writeheader()
            for row in reader:
                writer.writerow(row)
                n_hh_per += 1

        with open(gq_per_path, newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                row['household_id'] = str(int(row['household_id']) + gq_offset)
                writer.writerow(row)
                n_gq_per += 1

    print(f"  HH persons: {n_hh_per:,}  GQ persons: {n_gq_per:,}  "
          f"Total: {n_hh_per+n_gq_per:,}")

    # ── Summary ────────────────────────────────────────────────────────────────
    print(f"\nCombined synthetic population:")
    print(f"  Households: {n_hh_hh+n_gq_hh:,}  "
          f"(HH={n_hh_hh:,}, GQ={n_gq_hh:,})")
    print(f"  Persons:    {n_hh_per+n_gq_per:,}  "
          f"(HH={n_hh_per:,}, GQ={n_gq_per:,})")
    print(f"  Output:     {out_dir}")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)
    combine(sys.argv[1], sys.argv[2], sys.argv[3])
