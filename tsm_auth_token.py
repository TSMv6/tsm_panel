"""Per-user TSM authentication token storage.

TSM is freeware; this token is an *authentication / freshness* credential (not a
license) that confirms a user is authorized to run the standalone model
executables invoked by the Black Box steps. It is stored per-user in two places:

  * QgsSettings (the user's QGIS profile) -- so the plugin remembers it across
    QGIS sessions and across scenarios. It is deliberately NOT written into the
    scenario settings JSON, which can be shared between users.
  * ~/.tsm/token.txt -- the canonical location every TSM model exe auto-reads at
    startup for its authentication check.

Set it from the TSM Configuration dialog; read it wherever a Black Box step needs
to confirm the user has rights to run a model. Contact the TSM Dev Team to obtain
or renew a token.
"""
import os

# Key under the user's QGIS profile settings (QgsSettings / QSettings).
SETTINGS_KEY = "tsm_panel/tsm_token"


def token_file_path():
    """Canonical per-user token file that every TSM model exe reads."""
    return os.path.join(os.path.expanduser("~"), ".tsm", "token.txt")


def get_token():
    """Return the saved token, or "" if none.

    Reads the QGIS user profile first; falls back to ~/.tsm/token.txt in case the
    token was placed there outside QGIS (e.g. by the Dev Team's installer)."""
    token = ""
    try:
        from qgis.core import QgsSettings
        token = QgsSettings().value(SETTINGS_KEY, "", type=str) or ""
    except Exception:
        token = ""
    if token.strip():
        return token.strip()
    try:
        with open(token_file_path(), "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def set_token(token):
    """Persist the token per-user in both stores; return the cleaned token.

    An empty/whitespace token clears both stores."""
    token = (token or "").strip()

    # 1) QGIS user profile -- per-user, survives restarts and scenario changes.
    try:
        from qgis.core import QgsSettings
        QgsSettings().setValue(SETTINGS_KEY, token)
    except Exception as e:
        print(f"Could not save TSM token to QgsSettings: {e}")

    # 2) ~/.tsm/token.txt -- where the model exes look for it.
    path = token_file_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if token:
            with open(path, "w", encoding="utf-8") as f:
                f.write(token + "\n")
        elif os.path.exists(path):
            os.remove(path)
    except Exception as e:
        print(f"Could not write TSM token file {path}: {e}")

    return token


def has_token():
    """True if a non-empty token is saved for this user."""
    return bool(get_token())
