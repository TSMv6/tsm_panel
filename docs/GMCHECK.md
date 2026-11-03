# GeoMaster Checker (gmcheck)

gmcheck checks the GeoMaster network the way netPrep builds it and lists every
problem by **LINK_ID**, with the value before and after the proposed fix. After
you review the list, it writes a corrected copy of the link GeoPackage. Point
the Link Consolidator at that copy to use the fixes. The GeoMaster inputs are
never changed.

## Two steps

1. **1. Check (write review)** writes the review GeoPackage and the CSVs. The
   layer `link_review` is loaded into QGIS.
2. Review `link_review`: filter or sort by `confidence` and `rule`, then
   - `approved` = **1** to apply a row, **0** to reject it, empty = not reviewed;
   - edit `changes` to apply your own value, e.g. `FTYPE_50 31->21` to
     `FTYPE_50 31->41` (keep the `FIELD before->after; ...` form);
   - or change `confidence` to move a row above or below **Apply confidence**.

   Save the edits. `proposed` keeps gmcheck's original `changes`.
3. **2. Write corrected GPKG** writes the corrected copy from the review file:

   | User approved | Rows written |
   |---|---|
   | Also approved = 1 (default) | confidence ≥ Apply confidence, plus `approved = 1`; never `approved = 0` |
   | Only approved = 1 | `approved = 1` only |
   | Ignore approved | confidence ≥ Apply confidence |

   It takes a few seconds (the network is not rebuilt). `gmcheck_apply.log`
   counts the rows per rule: by confidence, approved, rejected, edited, not
   taken.

Running step 1 again never loses a review: a review file with approved or
edited rows is renamed `<name>_<date_time>.gpkg` first. To apply an older
review, set **Review GPKG** to it before step 2.

## What it checks

The network is built as netPrep builds it, for each model year:

- Links with `useinTSM = 1` and `LANE_<yy> > 0`.
- `TwoWay_<yy>`: F = A→B, T = B→A, B = both directions.
- A node at one `F_ZLEV` / `T_ZLEV` level is one junction. Links at different
  levels (overpasses) never connect.

| Rule | Finds | Fix in the corrected copy |
|---|---|---|
| **R1 class break** | A run of links whose FTYPE differs from the road on both sides, away from real intersections. Examples: Ramps 71 between Div-Arterial 21; Other 45 from missing information. Junctions whose cross streets are only local_access or Other count as part of the road. | FTYPE, FNAME, SPEED, ATYPE and LANE of the road around it. Other (45) left on a one-way carriageway becomes Div-Arterial (21). |
| **R2 connectivity** | Dead ends (in, no out), sources (out, no in), stubs, islands, one-way traps, ZLEV mismatches. | ZLEV mismatches are fixed (F_ZLEV / T_ZLEV). Everything else is reported for review. |
| **R3 median crossover** | Short links that join the two carriageways of a divided road: mid-block U-turns, and median links at local_access / Other cross streets. | `median_xover` = 1 (mid-block), 2 (T) or 3 (4-leg). By default also `useinTSM = 0`, so netPrep leaves them out. A crossover whose removal would cut off part of the network stays in. |
| **R4 smoothing** | Short LANE / SPEED / ATYPE blips along one road, which make netPrep split the road into more links. | The value on both sides. Two-way lanes are compared per direction. |

**Confidence.** Each change is High, Medium or Low. Step 2 writes the changes
at or above **Apply confidence** (default High) and, with **User approved**,
the rows you approved.

## Outputs (output folder)

| File | Contents |
|---|---|
| `gmcheck_links.csv` | One row per field change: LINK_ID, year, rule, field, before, after, confidence, applied, run, neighbours, note. |
| `gmcheck_nodes.csv` | One row per node issue (R2). |
| Review GPKG (`gmcheck_review.gpkg`) | Layer `link_review` (flagged links: `confidence`, `approved`, `changes`, `proposed`) and layer `node_review` (node issues), for QGIS. |
| `gmcheck_apply.log` | Step 2: rows taken per rule. |
| `gmcheck.log` | Starts with the rule definitions. Each year has one line per category, led by a LINK_ID to look at. |
| Corrected link GPKG | The input link layer with the fixes, plus the fields `median_xover` and `gmcheck` (the rules applied). |

The **node layer is not rewritten**. ZLEV fixes are on the links, so use the
corrected link layer with the original node layer in the Link Consolidator.

## Median crossovers

- **Remove (useinTSM = 0)**, the default: the crossover is out of the network
  for every model, and the two carriageways consolidate into fewer links. To
  keep crossovers for meso or micro DTA in a study area, set `useinTSM` back to
  1 on those links. The `median_xover` field marks them.
- **Recode FTYPE**: writes the FTYPE / FNAME given. netPrep needs a capacity
  for that class.
- **Flag only**: just the `median_xover` field.

## Running outside QGIS

The dialog writes a control file (`gmcheck.ctl`, `key = value`). The same file
runs from a command prompt:

```
<plugin>\Apps\netPrep\gmcheck.exe gmcheck.ctl                      (step 1)
<plugin>\Apps\netPrep\gmcheck.exe gmcheck.ctl MODE=apply_review    (step 2)
```

**Load control file** fills the dialog from an existing file. Settings the
dialog does not show are kept and written back.

A statewide run takes about 1.5 minutes.
