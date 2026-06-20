"""
Shared runner for gated TSM model executables.

Every gated model (Skimmy/PathSkim, POPSIM, SDT, LDT, ELToD, Hydra) is launched
through here so they all behave identically:

  * stdout + stderr are captured and the REAL reason for any failure is shown to the
    user (never "see the console" — the QGIS GUI has no console).
  * The auth sidecar (tsm_auth_check.exe) exit codes are interpreted:
        0 = ran
        1 = declined  (missing / invalid / expired / revoked token, outdated build,
                       or the model's own error — reason is in the captured output)
        2 = could not verify the token (offline) -> ask the user to get online

Two entry points:
  run_gated_model(parent, args, label, **kw) -> bool      (shows a QMessageBox)
  run_gated_model_result(args, label, **kw)  -> (ok, title, message)   (no UI)
"""

import subprocess
from PyQt5.QtWidgets import QMessageBox

# Errors are at the end of the output, so show the tail to keep the box readable.
_MAX_DETAIL_CHARS = 2000


def _tail(text, limit=_MAX_DETAIL_CHARS):
    text = (text or "").strip()
    return ("...\n" + text[-limit:]) if len(text) > limit else text


def run_gated_model_result(args, model_label="This model", **kwargs):
    """Run a gated model exe; return (ok: bool, title: str, message: str). No UI.
    message/title are user-facing; message is empty on success."""
    kwargs["stdout"] = subprocess.PIPE
    kwargs["stderr"] = subprocess.PIPE
    kwargs.setdefault("text", True)

    try:
        r = subprocess.run(args, **kwargs)
    except FileNotFoundError:
        exe = args[0] if args else "(unknown)"
        return False, f"{model_label} Not Found", \
            f"Could not start {model_label}.\n\nExecutable not found:\n{exe}"
    except Exception as e:
        return False, f"{model_label} Failed To Start", \
            f"Could not start {model_label}.\n\n{e}"

    if r.returncode == 0:
        return True, "", ""

    detail = _tail(r.stderr) or _tail(r.stdout)
    if r.returncode == 2:
        msg = ("TSM could not verify your access token.\n\n"
               "Please connect to the internet so your token can be verified, "
               f"then run {model_label} again.")
        if detail:
            msg += f"\n\n{detail}"
        return False, "Could Not Verify Token", msg

    if not detail:
        detail = f"{model_label} stopped unexpectedly (exit code {r.returncode})."
    return False, f"{model_label} Did Not Run", detail


def run_gated_model(parent, args, model_label="This model", **kwargs):
    """Run a gated model exe; on failure show a QMessageBox. Returns True on success."""
    ok, title, message = run_gated_model_result(args, model_label, **kwargs)
    if not ok:
        QMessageBox.critical(parent, title, message)
    return ok
