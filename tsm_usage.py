"""
Local, private usage logging for TSM model runs.

Every gated model run (through model_run.run_gated_model_result) appends ONE line to
    ~/.tsm/usage.jsonl
recording which step ran, how long it took, and whether it succeeded.

This file is LOCAL ONLY -- nothing is ever sent anywhere automatically. It exists so
a user can see their own usage, and -- entirely optionally -- email usage.jsonl (or a
generated summary) to the TSM Model Development Team if they want to help improve TSM.

What is recorded: UTC timestamp, tool, friendly label, duration, exit code, success,
plugin version, OS, and the token's `jti` (a pseudonymous id). NEVER the token itself,
file paths, scenario data, or any personal information.

To turn collection off: set QgsSettings key 'tsm_panel/usage_stats' to '0'.
"""

import base64
import json
import os
import platform
from collections import defaultdict
from datetime import datetime, timezone

# Usage log + token both live under ~/.tsm so they survive plugin reinstalls/updates.
_DIR = os.path.join(os.path.expanduser("~"), ".tsm")
_FILE = os.path.join(_DIR, "usage.jsonl")
_TOKEN = os.path.join(_DIR, "token.txt")
_SETTINGS_KEY = "tsm_panel/usage_stats"   # "1" = collect (default), "0" = off


def usage_file():
    return _FILE


def is_enabled():
    """Local collection is on by default; users can disable it (consent checkbox)."""
    try:
        from qgis.core import QgsSettings
        return str(QgsSettings().value(_SETTINGS_KEY, "1")) != "0"
    except Exception:
        return True


def set_enabled(on):
    """Persist the user's consent choice in their QGIS profile."""
    try:
        from qgis.core import QgsSettings
        QgsSettings().setValue(_SETTINGS_KEY, "1" if on else "0")
    except Exception:
        pass


# Back-compat alias used internally by record_run.
def _enabled():
    return is_enabled()


def _jti():
    """Pseudonymous user id = the token's jti. Reads only the (public) payload half
    of the token; the signature/token itself is never logged."""
    try:
        with open(_TOKEN, "r", encoding="utf-8") as f:
            payload_b64 = f.read().strip().split(".")[0]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        return json.loads(base64.urlsafe_b64decode(payload_b64)).get("jti")
    except Exception:
        return None


def _plugin_version():
    try:
        meta = os.path.join(os.path.dirname(__file__), "metadata.txt")
        with open(meta, encoding="utf-8") as f:
            for ln in f:
                if ln.strip().startswith("version="):
                    return ln.split("=", 1)[1].strip()
    except Exception:
        pass
    return None


def record_run(tool, label, started, ended, exit_code, ok, extra=None):
    """Append one run event to usage.jsonl. Never raises -- usage logging must never
    break a model run. `started`/`ended` are time.monotonic() seconds."""
    if not _enabled():
        return
    try:
        os.makedirs(os.path.dirname(_FILE), exist_ok=True)
        event = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "tool": tool,
            "label": label,
            "duration_s": round(max(0.0, float(ended) - float(started)), 1),
            "exit_code": exit_code,
            "ok": bool(ok),
            "jti": _jti(),
            "plugin_version": _plugin_version(),
            "os": platform.platform(terse=True),
        }
        if extra:
            event.update(extra)
        with open(_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
    except Exception:
        pass


def summarize(path=None):
    """Read usage.jsonl and return {tool: {runs, ok, failed, total_s, avg_s, last}}.
    Handy for the user's own insight or a periodic summary email."""
    path = path or _FILE
    agg = defaultdict(lambda: {"runs": 0, "ok": 0, "failed": 0, "total_s": 0.0, "last": ""})
    try:
        with open(path, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    e = json.loads(ln)
                except Exception:
                    continue
                a = agg[e.get("tool", "(unknown)")]
                a["runs"] += 1
                a["ok"] += 1 if e.get("ok") else 0
                a["failed"] += 0 if e.get("ok") else 1
                a["total_s"] += float(e.get("duration_s", 0) or 0)
                a["last"] = max(a["last"], e.get("ts", ""))
    except OSError:
        return {}
    for a in agg.values():
        a["avg_s"] = round(a["total_s"] / a["runs"], 1) if a["runs"] else 0.0
    return dict(agg)


def format_summary(path=None):
    """A short human-readable usage report (for the user, or to paste into an email)."""
    s = summarize(path)
    if not s:
        return "No TSM usage recorded yet."
    lines = ["TSM usage summary (local):", ""]
    lines.append(f"{'tool':<16}{'runs':>6}{'ok':>5}{'fail':>6}{'avg s':>9}{'total s':>10}   last run (UTC)")
    for tool in sorted(s):
        a = s[tool]
        lines.append(f"{tool:<16}{a['runs']:>6}{a['ok']:>5}{a['failed']:>6}"
                     f"{a['avg_s']:>9}{round(a['total_s'],1):>10}   {a['last']}")
    return "\n".join(lines)
