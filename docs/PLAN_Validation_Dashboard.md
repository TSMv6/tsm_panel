# PLANNED UPDATE — Model Assignment Validation Dashboard & Documentation

> **Status: NOT STARTED.** Captured during the Summarization/validation work.
> Build this **at the very end**, after the core model run is settled. It extends
> the existing pieces: `summarize.exe` (per-link loaded CSV) and
> [validation_runner.py](../validation_runner.py) (assigned-vs-count %RMSE, %Error,
> R² by facility type and volume group).

## Goal
A single Python tool that produces the **complete documentation of the model
assignment** — an interactive dashboard plus exported workbooks — so a run can be
validated and reported without manual post-processing.

## 1. Validation dashboard (HTML, interactive)
A self-contained dashboard (e.g. Plotly/Folium → static HTML, no server) with plots
and stat tables grouped by:
- **County**
- **Facility type** (FNAME / FTYPE)
- **Volume group** (count bins)

Validation statistics shown per grouping and overall:
- **R²** (assigned vs count)
- **GEH** statistic — add to `validation_runner.py` (`GEH = sqrt(2*(A-C)^2 / (A+C))`);
  report %% of locations with GEH < 5 / < 10.
- **RMSE / %RMSE**
- **% Error**, Assigned/Count ratio, N counted locations
- Narrative **description** of the stats (auto-written summary text).

## 2. New plots
- **Hourly distribution of volumes** by **direction** and by **facility type**
  (the per-hour `VOL_<hour>` pivot columns summarize already emits).
- Render volumes/hourly profiles **on an interactive map (Leaflet/Folium)** — link
  geometry styled by volume / GEH / %error, with hover detail.

## 3. Interchange stick diagrams from "pull links"
- Input: **"pull links"** — each link coded with an **ID** identifying its role at an
  interchange (mainline, northern ramps, southern ramps, etc.).
- Produce a **stick diagram of interchange flows** (mainline vs N/S ramp volumes)
  and export the structured flows **to an Excel spreadsheet**.
- Needs: a pull-link ID coding scheme / lookup (define how each link maps to an
  interchange + movement role) — design this when we build it.

## Notes / dependencies
- Builds on the loaded CSV (assigned `Total`, `VOL_<hour>` pivots, count field) and
  the link GeoPackage (geometry, county, FNAME) already produced by Summarization.
- pandas + openpyxl confirmed available in the QGIS Python env; add Plotly/Folium
  (or render Leaflet directly) when implementing.
- Likely a new `dashboard_runner.py` + an optional panel button, logging live to the
  History box like `validation_runner.py` (no extra console window).
