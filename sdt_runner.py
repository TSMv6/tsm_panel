"""Shared SDT run logic for the resident and visitor dialogs.

The SDT engine is a single exe (`sdt-run.exe --config model.toml`); resident and
visitor are toggled via the [models] flags. Either dialog can request a resident
run, a visitor run, or both — when both are requested a single process runs them
so the skims are read only once (the expensive step).

Land-use prep (26k -> 8.7k + derived columns) is converter #8, kept as the 1:1 R
step for now; it produces tsm_landuse.csv that the model reads as taz_data.
"""
import os
import subprocess
from .tsm_settings import Config
from .model_run import run_gated_model_result, begin_run_console, closes_run_console

TELEWORK_TO_SHARE = {"7%": "0.07", "10%": "0.10", "15%": "0.15", "20%": "0.20", "25%": "0.25"}


def _fwd(path):
    return str(path).replace("\\", "/")


@closes_run_console
def run_sdt_models(flags):
    """Run the SDT model(s). `flags` is a dict of the [models] toggles:
       resident, wfh, mandatory, auto_own, veh_type, tour, stop, trip,
       visitor, visitor_veh.  Returns (ok: bool, message: str)."""
    run_resident = flags.get("resident", False)
    run_visitor = flags.get("visitor", False)
    settings = Config()
    scenario_dir = settings.get("scenarioDir")
    # Resolve to the v6 default if General Configuration was never opened this
    # session, and seed it back (in-memory setting) so no step builds a path
    # relative to the process cwd. See Config.tsm_root().
    tsm_location = settings.tsm_root()
    settings.set("tsm_location", tsm_location)
    plugin_dir = settings.get("plugin_dir")

    if not (run_resident or run_visitor):
        return False, "Select at least one model to run (Resident and/or Visitor)."
    if not scenario_dir:
        return False, "No scenario directory set (Project Settings)."
    if not tsm_location:
        return False, "No TSM location set (General Configuration)."

    # One live-tail window for the whole SDT run (no per-step black windows).
    begin_run_console(os.path.join(scenario_dir, "SDT.log"), "SDT - run log")

    landuse_layer_path = settings.get("landuse_layer_path")
    skim_file = settings.get("skim_file")
    if not landuse_layer_path:
        return False, "Please select a land-use layer."
    if not skim_file:
        return False, "Please select a skim file."

    # ---- 1) Land-use prep (#8) -> tsm_landuse.csv -------------------------
    # se_aggregate.exe replaces SDT_resident_LUPrep.R (args: gpkg, out, default).
    se_exe = settings.app_exe("utilities/se_aggregate.exe")
    tsm_landuse = os.path.join(scenario_dir, "tsm_landuse.csv")
    # Default land-use table is a MODEL input ({tsm_location}/Inputs/landuse), not a plugin asset.
    tsm_landuse_default = os.path.join(tsm_location, "Inputs", "landuse",
                                       "tsm_landuse_default.csv").replace("\\", "/")
    if not os.path.exists(se_exe):
        return False, f"Land-use prep utility not found: {se_exe}"
    try:
        r = settings.run_app([se_exe, landuse_layer_path, tsm_landuse, tsm_landuse_default],
                             log_path=os.path.join(scenario_dir, "SDT_landuse.log"), console=True)
        if r.returncode != 0 or not os.path.exists(tsm_landuse):
            return False, "Land-use prep (26k -> 8.7k) failed."
    except Exception as e:
        return False, f"Land-use prep failed: {e}"

    # ---- 2) Generate config/sdt/model.toml from the template -------------
    syn_hh = settings.get("synHH_file") or os.path.join(scenario_dir, "Combined", "synthetic_households.csv")
    syn_per = settings.get("synPer_file") or os.path.join(scenario_dir, "Combined", "synthetic_persons.csv")
    telework = settings.get("telework_share") or "15%"
    wfh_share = TELEWORK_TO_SHARE.get(telework, "0.15")
    year = settings.get("scenarioYear") or settings.get("networkYear") or "2024"
    threads = settings.get("num_processors") or "0"

    # Shadow prices are SCENARIO STATE, not a plugin asset: each scenario
    # converges its own. Prefer the scenario's own file (written to
    # scenario_dir by the previous run) and fall back to the shipped TSMv4 seed
    # only to bootstrap a scenario that has never run shadow pricing -- so
    # scenarios never inherit each other's prices via the plugin config.
    # The engine writes and reads the same CSV layout
    # (TAZ,WORK_0..WORK_4,UNIV_SP,SCHOOL_SP), so the file round-trips.
    sp_scenario = os.path.join(scenario_dir, "shadowPrices")
    sp_seed = os.path.join(plugin_dir, "config", "sdt_parameters",
                           "shadowPrices_TSMv4_3.csv")
    shadow_input = sp_scenario if os.path.exists(sp_scenario) else sp_seed
    print("SDT shadow price seed: %s" % shadow_input)

    repl = {
        # SDT coefficient/parameter dirs (config/...) are shipped IN the plugin and
        # resolved relative to project_dir, so point project_dir at the plugin folder.
        "{project_dir}": _fwd(plugin_dir).rstrip("/") + "/",
        # vehicle-type-choice alts are year/scenario inputs under Inputs/vehTypeChoice.
        "{tsm_location}": _fwd(tsm_location).rstrip("/"),
        "{syn_hh}": _fwd(syn_hh),
        "{syn_per}": _fwd(syn_per),
        "{tsm_landuse}": _fwd(tsm_landuse),
        "{output_dir}": _fwd(scenario_dir).rstrip("/"),
        "{shadow_input}": _fwd(shadow_input),
        "{skim}": _fwd(skim_file),
        "{wfh_share}": str(wfh_share),
        "{year}": str(year),
        "{threads}": str(threads),
        "{run_resident}": "true" if run_resident else "false",
        "{run_wfh}": "true" if flags.get("wfh") else "false",
        "{run_mandatory}": "true" if flags.get("mandatory") else "false",
        "{run_auto_own}": "true" if flags.get("auto_own") else "false",
        "{run_veh_type}": "true" if flags.get("veh_type") else "false",
        "{run_tour}": "true" if flags.get("tour") else "false",
        "{run_stop}": "true" if flags.get("stop") else "false",
        "{run_trip}": "true" if flags.get("trip") else "false",
        "{run_visitor}": "true" if run_visitor else "false",
        "{run_visitor_veh}": "true" if flags.get("visitor_veh") else "false",
    }

    # Write the generated model.toml under the PLUGIN's config (next to the
    # coefficient/parameter dirs it references), not under tsm_location.
    template = os.path.join(plugin_dir, "templates", "sdt_model_template.toml")
    config_sdt = os.path.join(plugin_dir, "config", "sdt")
    model_toml = os.path.join(config_sdt, "model.toml")
    try:
        with open(template, "r", encoding="utf-8") as f:
            text = f.read()
        for k, v in repl.items():
            text = text.replace(k, v)
        os.makedirs(config_sdt, exist_ok=True)
        with open(model_toml, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"Wrote SDT config: {model_toml}")
    except Exception as e:
        return False, f"Error writing model.toml: {e}"

    # ---- 3) Run sdt-run.exe --config model.toml --------------------------
    sdt_exe = settings.app_exe("sdt/sdt-run.exe")
    if not os.path.exists(sdt_exe):
        return False, f"sdt-run.exe not found at: {sdt_exe}"
    # Run via the shared gated runner in its own console window (live output,
    # interruptible) with the output tee'd to a per-model log so a resident run and
    # a visitor run don't overwrite each other's log:
    #   resident only -> SDT_resident.log,  visitor only -> SDT_visitor.log,
    #   both          -> SDT_resident_visitor.log
    which = "_".join(m for m, on in (("resident", run_resident), ("visitor", run_visitor)) if on) or "sdt"
    sdt_log = os.path.join(scenario_dir, f"SDT_{which}.log")
    label = f"SDT {which.replace('_', '+')} model"
    ok, _title, msg = run_gated_model_result([sdt_exe, "--config", model_toml], label,
                                             log_path=sdt_log, console=True)
    if not ok:
        return False, msg

    which = " + ".join([m for m, on in (("Resident", run_resident), ("Visitor", run_visitor)) if on])
    return True, f"SDT model completed ({which})."
