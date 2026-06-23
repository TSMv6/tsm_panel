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

import collections
import ctypes
import functools
import os
import re
import subprocess
import time
from ctypes import wintypes
from PyQt5.QtWidgets import QMessageBox

from . import tsm_usage

# Window creation flags (Windows). NEW_CONSOLE = own visible console (live output,
# interruptible); NO_WINDOW = none (output captured/redirected).
_NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# HIGH priority so Windows Thread Director runs heavy model exes on P-cores at turbo
# clock instead of parking them on E-cores at base clock (i9-13950HX P/E hybrid;
# observed ~5x slowdown). Child exes inherit the parent's priority class.
_HIGH = getattr(subprocess, "HIGH_PRIORITY_CLASS", 0)

# Full path so the console launch never depends on PATH being intact.
_POWERSHELL = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                           "System32", "WindowsPowerShell", "v1.0", "powershell.exe")


# ---------------------------------------------------------------------------
# Kill-on-close Job Object (Windows). Closing a model's console window kills the
# powershell wrapper but NOT the model exe / its worker children -- they decouple
# (the Tee pipe / detached workers) and keep eating CPU. Putting the launched
# process tree in a Job Object with KILL_ON_JOB_CLOSE means that when we close the
# job handle (the run ended -- normally, or because the window was closed and the
# wrapper died), every remaining process in the tree is terminated. ctypes only, so
# no pywin32 dependency.
# ---------------------------------------------------------------------------
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_JobObjectExtendedLimitInformation = 9


def _make_kill_on_close_job():
    """Create a Job Object that kills all member processes when its last handle is
    closed. Returns the job handle (int) or None if unavailable (non-Windows / error)."""
    if os.name != "nt":
        return None
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                ctypes.c_void_p, wintypes.DWORD]

        class _BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
                        ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
                        ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class _IOC(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in
                        ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                         "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class _EXT(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", _BASIC), ("IoInfo", _IOC),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        job = k32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = _EXT()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(job, _JobObjectExtendedLimitInformation,
                                           ctypes.byref(info), ctypes.sizeof(info)):
            k32.CloseHandle(job)
            return None
        return job
    except Exception:
        return None


def _assign_to_job(job, proc_handle):
    """Add a process (and, by default, its future children) to the job."""
    if not job:
        return
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.AssignProcessToJobObject(wintypes.HANDLE(job), wintypes.HANDLE(int(proc_handle)))
    except Exception:
        pass


def _close_job(job):
    """Close the job handle. With KILL_ON_JOB_CLOSE this terminates any survivors."""
    if not job:
        return
    try:
        ctypes.WinDLL("kernel32").CloseHandle(wintypes.HANDLE(job))
    except Exception:
        pass

# Errors are at the end of the output, so show the tail to keep the box readable.
_MAX_DETAIL_CHARS = 2000

# PowerShell wraps a native exe's stderr in "NativeCommandError" noise (At line:N,
# "+ & '...'", a ~~~~ underline, CategoryInfo / FullyQualifiedErrorId). Strip it so
# the message box shows only the model's / auth sidecar's own words.
_PS_NOISE = re.compile(r"^(?:At line:\d+ char:\d+.*|\s*\+.*|\s*~+\s*)$")


def _strip_ps_noise(text):
    if not text:
        return text
    kept = []
    for ln in text.splitlines():
        if _PS_NOISE.match(ln):
            continue
        if any(tok in ln for tok in ("CategoryInfo", "FullyQualifiedErrorId",
                                     "NativeCommandError", "RemoteException")):
            continue
        # PS prefixes native stderr lines with "<exe>.exe : "; drop that prefix.
        m = re.match(r"^\S+\.exe\s*:\s*(.*)$", ln)
        if m:
            ln = m.group(1)
        kept.append(ln)
    return "\n".join(kept).strip()


def _tail(text, limit=_MAX_DETAIL_CHARS):
    text = (text or "").strip()
    return ("...\n" + text[-limit:]) if len(text) > limit else text


def _tail_file(path, limit=_MAX_DETAIL_CHARS):
    try:
        with open(path, "rb") as f:
            data = f.read()
        # PowerShell 5.1 Tee-Object writes UTF-16LE; the streamed log mode writes UTF-8.
        enc = "utf-16" if data[:2] in (b"\xff\xfe", b"\xfe\xff") or b"\x00" in data[:200] else "utf-8"
        return _tail(data.decode(enc, errors="replace"), limit)
    except OSError:
        return ""


def _ps_quote(s):
    return "'" + str(s).replace("'", "''") + "'"


def _record_usage(args, model_label, started, exit_code, ok):
    """Append one local usage event for this run (never raises)."""
    try:
        tool = os.path.splitext(os.path.basename(args[0]))[0] if args else "(unknown)"
        tsm_usage.record_run(tool, model_label, started, time.monotonic(), exit_code, ok)
    except Exception:
        pass


def open_log_console(log_path, title="TSM run log"):
    """Open ONE console window that live-tails log_path and stays open until the user
    closes it. Non-blocking (returns the Popen). Truncates the log so the window
    starts clean. Pair with steps that stream-append to the same log_path
    (run_gated_model_result/run_app with console=False, append=True) so a whole
    dialog run shows live in a single window instead of one flashing window per step."""
    try:
        open(log_path, "w", encoding="utf-8").close()  # start fresh
    except OSError:
        pass
    ps = (f"$host.ui.RawUI.WindowTitle = {_ps_quote(title)}; "
          f"Get-Content -LiteralPath {_ps_quote(log_path)} -Wait -Tail 5000")
    try:
        return subprocess.Popen([_POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass",
                                 "-Command", ps], creationflags=_NEW_CONSOLE)
    except Exception:
        return None


# When a dialog run is active, ALL console=True steps redirect into this single
# shared log (streamed, windowless) instead of each popping its own console -- one
# live-tail window (begin_run_console) shows the whole run. None = per-call behavior.
_RUN_LOG = None
_RUN_CONSOLE = None  # Popen of the live-tail window, so end_run_console() can close it.


def _close_console_proc(proc):
    """Terminate a live-tail console process, which closes its window."""
    if proc is None:
        return
    try:
        if proc.poll() is None:
            proc.terminate()  # kills the powershell tail -> its console window closes
    except Exception:
        pass


def begin_run_console(log_path, title="TSM run log"):
    """Start a one-window run: open ONE live-tail console on log_path and route every
    subsequent console=True step (run_gated_model / run_app) to stream-append into it,
    so a whole dialog run shows in a single window with no per-step black windows.
    Closes any leftover window from a previous run first."""
    global _RUN_LOG, _RUN_CONSOLE
    _close_console_proc(_RUN_CONSOLE)  # don't leak a prior run's window
    _RUN_LOG = log_path
    _RUN_CONSOLE = open_log_console(log_path, title)
    return _RUN_CONSOLE

def end_run_console():
    """Stop redirecting console=True steps AND close the live-tail window (called when
    a dialog's run finishes, so the run-log window does not linger)."""
    global _RUN_LOG, _RUN_CONSOLE
    _RUN_LOG = None
    _close_console_proc(_RUN_CONSOLE)
    _RUN_CONSOLE = None


def closes_run_console(fn):
    """Decorator for a dialog's run method: after it returns (success, failure, or
    exception), close the live-tail run-log window opened via begin_run_console so it
    does not linger. Robust to the method's many early-return paths."""
    @functools.wraps(fn)
    def _wrap(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        finally:
            end_run_console()
    return _wrap


def run_gated_model_result(args, model_label="This model", log_path=None, console=False,
                           append=False, **kwargs):
    """Run a gated model exe; return (ok: bool, title: str, message: str). No UI.

    console=True: launch in its OWN console window (tee'd to log_path if given).
    console=False + log_path: stream output to the log file (no window); append=True
      appends instead of truncating, so several steps + a live-tail window
      (open_log_console) share one log shown in one window.
    console=False, no log_path: capture output (shown only on failure)."""
    # One-window run active: redirect this console step into the shared run log
    # (streamed, windowless) instead of its own console window.
    if console and _RUN_LOG:
        console, log_path, append = False, _RUN_LOG, True
    kwargs.setdefault("text", True)
    started = time.monotonic()

    try:
        if console:
            # Own console window; tee to log_path if given, propagate the model's code.
            if log_path:
                inner = "& " + " ".join(_ps_quote(a) for a in args)
                ps = f"{inner} 2>&1 | Tee-Object -FilePath {_ps_quote(log_path)}; exit $LASTEXITCODE"
                cmd = [_POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps]
            else:
                cmd = list(args)
            kwargs.pop("text", None)
            # Kill-on-close job: closing the console window kills the powershell
            # wrapper; closing the job handle then kills the model exe + its workers
            # so nothing is left orphaned.
            job = _make_kill_on_close_job()
            p = subprocess.Popen(cmd, creationflags=_NEW_CONSOLE | _HIGH, **kwargs)
            _assign_to_job(job, p._handle)
            try:
                p.wait()
            finally:
                _close_job(job)
            rc = p.returncode
            out = _tail_file(log_path) if log_path else ""
            err = ""
        elif log_path:
            tail = collections.deque(maxlen=400)
            job = _make_kill_on_close_job()
            # Timestamp every line so the log reads as an activity log with a clock.
            with open(log_path, "a" if append else "w", encoding="utf-8", errors="replace") as lf:
                lf.write(f"\n[{time.strftime('%H:%M:%S')}] $ {' '.join(args)}\n\n"); lf.flush()
                p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     creationflags=_NO_WINDOW | _HIGH, **kwargs)
                _assign_to_job(job, p._handle)
                try:
                    for line in p.stdout:
                        stamped = f"[{time.strftime('%H:%M:%S')}] {line}"
                        lf.write(stamped); lf.flush()
                        tail.append(stamped)
                    p.wait()
                finally:
                    _close_job(job)
            rc, out, err = p.returncode, "".join(tail), ""
        else:
            kwargs["stdout"] = subprocess.PIPE
            kwargs["stderr"] = subprocess.PIPE
            r = subprocess.run(args, creationflags=_NO_WINDOW | _HIGH, **kwargs)
            rc, out, err = r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        exe = args[0] if args else "(unknown)"
        _record_usage(args, model_label, started, -1, False)
        return False, f"{model_label} Not Found", \
            f"Could not start {model_label}.\n\nExecutable not found:\n{exe}"
    except Exception as e:
        _record_usage(args, model_label, started, -1, False)
        return False, f"{model_label} Failed To Start", \
            f"Could not start {model_label}.\n\n{e}"

    _record_usage(args, model_label, started, rc, rc == 0)

    if rc == 0:
        return True, "", ""

    # Classify by the auth sidecar's MESSAGE, not the exit code: a model's own exit
    # code can also be 1 or 2 (e.g. sdt-run returns 2 on a fatal missing-config error),
    # so keying off rc would mislabel real model errors as auth failures.
    low = ((err or "") + (out or "")).lower()

    # --- Auth outcomes. Show ONLY the issue + who to contact: no PowerShell wrapper
    #     noise, no log path, no other text. ---
    if ("offline beyond the grace" in low or
            "could not confirm you have the latest" in low or
            "could not verify" in low):
        return False, "Could Not Verify Token", (
            f"{model_label} could not run because your access token could not be "
            "verified (you appear to be offline).\n\nPlease connect to the internet "
            "and run again, or contact the TSM Model Development Team.")

    auth = None
    if "access token is invalid" in low or "invalid token" in low:
        auth = ("Invalid Token", "your access token is invalid")
    elif "has expired" in low or "token has expired" in low:
        auth = ("Token Expired", "your access token has expired")
    elif "revoked" in low:
        auth = ("Token Revoked", "your access token has been revoked")
    elif "needs your personal tsm access token" in low or "save the token" in low:
        auth = ("No Access Token", "no TSM access token was found on this machine")
    elif "out of date" in low or "outdated" in low:
        auth = ("Update Required", "this copy of the model is out of date")
    if auth:
        title, reason = auth
        return False, title, (
            f"{model_label} could not run because {reason}.\n\n"
            "Please contact the TSM Model Development Team to pick up the current "
            "version and token.")

    # --- The model's own error: show the real reason (PowerShell noise stripped). ---
    detail = _strip_ps_noise(_tail(err) or _tail(out))
    if not detail:
        detail = f"{model_label} stopped unexpectedly (exit code {rc})."
    if log_path:
        detail += f"\n\nFull log: {log_path}"
    return False, f"{model_label} Did Not Run", detail


def run_gated_model(parent, args, model_label="This model", **kwargs):
    """Run a gated model exe; on failure show a QMessageBox. Returns True on success."""
    ok, title, message = run_gated_model_result(args, model_label, **kwargs)
    if not ok:
        QMessageBox.critical(parent, title, message)
    return ok
