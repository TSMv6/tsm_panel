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

TELEWORK_TO_SHARE = {"7%": "0.07", "10%": "0.10", "15%": "0.15", "20%": "0.20", "25%": "0.25"}


def _fwd(path):
    return str(path).replace("\\", "/")


def run_sdt_models(flags):
    """Run the SDT model(s). `flags` is a dict of the [models] toggles:
       resident, wfh, mandatory, auto_own, veh_type, tour, stop, trip,
       visitor, visitor_veh.  Returns (ok: bool, message: str)."""
    run_resident = flags.get("resident", False)
    run_visitor = flags.get("visitor", False)
    settings = Config()
    scenario_dir = settings.get("scenarioDir")
    tsm_location = settings.get("tsm_location")
    plugin_dir = settings.get("plugin_dir")

    if not (run_resident or run_visitor):
        return False, "Select at least one model to run (Resident and/or Visitor)."
    if not scenario_dir:
        return False, "No scenario directory set (Project Settings)."
    if not tsm_location:
        return False, "No TSM location set (General Configuration)."

    landuse_layer_path = settings.get("landuse_layer_path")
    skim_file = settings.get("skim_file")
    if not landuse_layer_path:
        return False, "Please select a land-use layer."
    if not skim_file:
        return False, "Please select a skim file."

    # ---- 1) Land-use prep (#8, R 1:1 for now) -> tsm_landuse.csv ----------
    r_exe_path = settings.get("r_exe_path")
    r_script = os.path.join(plugin_dir, "Rscripts", "SDT_resident_LUPrep.R")
    tsm_landuse = os.path.join(scenario_dir, "tsm_landuse.csv")
    tsm_landuse_default = os.path.join(plugin_dir, "Rscripts", "tsm_landuse_default.csv")
    if not r_exe_path or not os.path.exists(r_script):
        return False, "Land-use prep (Rscript / SDT_resident_LUPrep.R) not found. Set the Rscript path in General Configuration."
    try:
        r = subprocess.run([r_exe_path, r_script, landuse_layer_path, tsm_landuse, tsm_landuse_default], shell=True)
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

    repl = {
        "{project_dir}": _fwd(tsm_location).rstrip("/") + "/",
        "{syn_hh}": _fwd(syn_hh),
        "{syn_per}": _fwd(syn_per),
        "{tsm_landuse}": _fwd(tsm_landuse),
        "{output_dir}": _fwd(scenario_dir).rstrip("/"),
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

    template = os.path.join(plugin_dir, "templates", "sdt_model_template.toml")
    config_sdt = os.path.join(tsm_location, "config", "sdt")
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
    sdt_exe = os.path.join(tsm_location, "Apps", "sdt", "sdt-run.exe")
    if not os.path.exists(sdt_exe):
        return False, f"sdt-run.exe not found at: {sdt_exe}"
    try:
        r = subprocess.run([sdt_exe, "--config", model_toml])
    except Exception as e:
        return False, f"Error running sdt-run.exe: {e}"
    if r.returncode != 0:
        return False, "SDT model run failed. Check console for details."

    which = " + ".join([m for m, on in (("Resident", run_resident), ("Visitor", run_visitor)) if on])
    return True, f"SDT model completed ({which})."
