"""
Pandas replacement for the ldtprep syn-HH preparation steps, run as a subprocess
with QGIS's bundled Python (pandas 2.x ships with QGIS, so no extra install).

Why Python here: pandas does the 134M-row sort in ~8s and the filter in ~9s; the
only real cost is I/O. Doing sort+filter in ONE pass (read once, write once)
removes the C++ two-step (sort-synhh writes a sorted gz, synhh-incremental reads it
again) -- no intermediate gz read/write.

Modes (CLI):
  visitor  IN_ALL_YEARS_GZ  SCEN_YEAR  REF_YEAR  OUT_DAT
      Combined sort+filter for the LDT-visitor out-of-state syn-HH. SCEN==REF =>
      ABSOLUTE (Year<=scen); SCEN>REF => INCREMENTAL (ref<Year<=scen). Both keep
      hhnuma>8721, sort by (hhnuma,Year), drop Year, renumber hhid 1..N, append
      avgWorkDist/totWorkDist=0. Output tab-delimited (matches ldtprep).

  resident SYN_ALL  SYN_VEH  TEMPLATE  OUT_DAT
      Mirrors ldtprep synhh-convert: drop BLD/hh_id_pums/HH, map VEH from the SDT
      auto-ownership file (hh_id/HHID -> min(autos/VEHICLES,4)), append
      avgWorkDist/totWorkDist=0, positional-rename to the LDT template schema,
      hhincome->int, sort by hhnuma, renumber hhid 1..N. Output tab-delimited.

stdout is unbuffered/flushed so it streams to the plugin's live run log.
"""
import sys
import time
import pandas as pd


def _sep(path):
    """Detect tab vs comma from the header line (gz or plain)."""
    opener = __import__("gzip").open if path.lower().endswith(".gz") else open
    with opener(path, "rt") as f:
        head = f.readline()
    return "\t" if "\t" in head else ","


def _read(path):
    comp = "gzip" if path.lower().endswith(".gz") else None
    return pd.read_csv(path, sep=_sep(path), compression=comp)


def _normalize_whole_floats(df):
    """Match ldtprep fmt_num: write whole-valued floats as integers (1.0 -> 1)."""
    for c in df.columns:
        s = df[c]
        if s.dtype.kind == "f" and s.notna().all() and (s == s.round()).all():
            df[c] = s.astype("int64")
    return df


def visitor(in_path, scen, ref, out_path):
    t0 = time.time()
    df = _read(in_path)
    t_read = time.time() - t0
    scen2, ref2 = scen - 2000, ref - 2000
    if scen > ref:
        mode = "INCREMENTAL"
        m = (df["Year"] > ref2) & (df["Year"] <= scen2) & (df["hhnuma"] > 8721)
    else:
        mode = "ABSOLUTE"
        m = (df["Year"] <= scen2) & (df["hhnuma"] > 8721)
    print(f"[py-synhh {mode}] read {len(df):,} rows in {t_read:.0f}s; "
          f"filter+sort (scen={scen} ref={ref})...", flush=True)
    out = (df.loc[m]
             .sort_values(["hhnuma", "Year"], kind="stable")
             .drop(columns=["Year"])
             .reset_index(drop=True))
    out["hhid"] = range(1, len(out) + 1)          # renumber 1..N in hhnuma order
    out["avgWorkDist"] = 0
    out["totWorkDist"] = 0
    _normalize_whole_floats(out)
    t_proc = time.time() - t0 - t_read
    out.to_csv(out_path, sep="\t", index=False, lineterminator="\n")
    print(f"[py-synhh {mode}] {len(out):,} households "
          f"(read {t_read:.0f}s, filter+sort {t_proc:.0f}s, write {time.time()-t0-t_read-t_proc:.0f}s, "
          f"TOTAL {time.time()-t0:.0f}s) -> {out_path}", flush=True)
    return 0


def resident(syn_all, syn_veh, template, out_path):
    t0 = time.time()
    with open(template) as f:
        line = f.readline().rstrip("\r\n")
    tcols = line.split("\t") if "\t" in line else line.split(",")

    # autos lookup: hh_id/HHID -> min(autos/VEHICLES, 4)
    av = _read(syn_veh)
    idc = "hh_id" if "hh_id" in av.columns else "HHID"
    auc = "autos" if "autos" in av.columns else "VEHICLES"
    if idc not in av.columns or auc not in av.columns:
        sys.exit("SYN_VEH needs hh_id(/HHID) + autos(/VEHICLES)")
    vehmap = dict(zip(av[idc].astype("int64"),
                      av[auc].astype("int64").clip(lower=0, upper=4)))
    print(f"[py-convert] autos lookup: {len(vehmap):,} households", flush=True)

    df = _read(syn_all)
    if "household_id" not in df.columns:
        sys.exit("SYN_ALL has no household_id column")
    df = df.drop(columns=[c for c in ("BLD", "hh_id_pums", "HH") if c in df.columns])
    vehval = df["household_id"].map(vehmap)        # NaN where no SDT match (= blank)
    if "VEH" in df.columns:
        df["VEH"] = vehval                          # overwrite in place (keeps position)
    else:
        df["VEH"] = vehval                          # append after kept cols
    df["avgWorkDist"] = 0
    df["totWorkDist"] = 0

    if len(df.columns) != len(tcols):
        sys.exit(f"column count after transform ({len(df.columns)}) != template ({len(tcols)})")
    df.columns = tcols                              # positional rename to LDT schema

    df["hhincome"] = pd.to_numeric(df["hhincome"], errors="coerce").fillna(0).astype("int64")
    df = df.sort_values("hhnuma", kind="stable").reset_index(drop=True)
    df["hhid"] = range(1, len(df) + 1)             # renumber 1..N in hhnuma order
    _normalize_whole_floats(df)
    # VEH: integer where matched, blank where not (mirrors C++ blank-on-no-match)
    df["VEH"] = df["VEH"].map(lambda x: "" if pd.isna(x) else str(int(x)))
    df.to_csv(out_path, sep="\t", index=False, lineterminator="\n")
    print(f"[py-convert] {len(df):,} households in {time.time()-t0:.0f}s -> {out_path}", flush=True)
    return 0


def main(argv):
    if len(argv) < 2:
        sys.exit("usage: ldt_synhh_prep.py visitor|resident ...")
    mode = argv[1]
    if mode == "visitor":
        return visitor(argv[2], int(argv[3]), int(argv[4]), argv[5])
    if mode == "resident":
        return resident(argv[2], argv[3], argv[4], argv[5])
    sys.exit(f"unknown mode: {mode}")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
