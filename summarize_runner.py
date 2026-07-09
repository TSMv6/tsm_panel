"""Run the C++ summarize.exe from an editable TOML template.

The templates live in tsm_panel/templates/ and carry the *what* (class list,
pivots, metrics) so they can evolve without code changes. This module fills the
run-specific paths and the subarea-dependent column rename, writes a per-run
control file, and invokes summarize.exe (resolved via settings.app_exe).
"""
import os
import subprocess

from .tsm_settings import Config


def _rename(subarea, include_speed_ff):
    """Build the [join].rename array. Subarea swaps A/B<->Sub_A/Sub_B; the loaded
    summary also renames link SPEED to SPEED_FF (needed for the VHD metric)."""
    parts = []
    if subarea:
        parts += ["A=TSM_A", "B=TSM_B", "Sub_A=A", "Sub_B=B"]
    if include_speed_ff:
        parts += ["SPEED=SPEED_FF"]
    return ", ".join('"%s"' % p for p in parts)


def _input_block(section, path):
    """Optional [input2]/[input3] TOML block for the meso / micro DTA
    link-performance CSVs (hydra mode). Empty path -> the block vanishes."""
    if not path:
        return ""
    return '[%s]\npath = "%s"\nrename = ["a_node=A", "b_node=B"]\n' % (
        section, path.replace("\\", "/"))


def run_summary(template, link, vol, out_gpkg, subarea, vol2=None, vol3=None,
                include_speed_ff=True):
    """Fill `template` and run summarize.exe. The daily CSV path is derived from
    out_gpkg (.gpkg -> _daily.csv), matching the old R behavior. vol2/vol3 are
    the optional mesoDTA / microDTA link-performance CSVs (hydra template;
    their @INPUT2@/@INPUT3@ blocks vanish when unset). Returns the
    subprocess.CompletedProcess."""
    settings = Config()
    plugin_dir = settings.get("plugin_dir")
    tpl_path = os.path.join(plugin_dir, "templates", template)
    with open(tpl_path, "r") as f:
        text = f.read()

    out_gpkg = (out_gpkg or "").replace("\\", "/")
    if out_gpkg.lower().endswith(".gpkg"):
        out_csv = out_gpkg[:-5] + "_daily.csv"
    else:
        out_csv = out_gpkg + "_daily.csv"

    text = (text
            .replace("@VOL@", (vol or "").replace("\\", "/"))
            .replace("@VOL2@", (vol2 or "").replace("\\", "/"))
            .replace("@INPUT2@", _input_block("input2", vol2))
            .replace("@INPUT3@", _input_block("input3", vol3))
            .replace("@LINK@", (link or "").replace("\\", "/"))
            .replace("@OUT_CSV@", out_csv)
            .replace("@OUT_GPKG@", out_gpkg)
            .replace("@RENAME@", _rename(subarea, include_speed_ff)))

    ctl = os.path.join(os.path.dirname(out_gpkg), os.path.splitext(template)[0] + "_run.toml")
    with open(ctl, "w") as f:
        f.write(text)

    exe = settings.app_exe("utilities/summarize.exe")
    if not os.path.exists(exe):
        raise FileNotFoundError("summarize.exe not found at: %s" % exe)
    return settings.run_app([exe, ctl], log_path=os.path.splitext(ctl)[0] + ".log", console=True)
