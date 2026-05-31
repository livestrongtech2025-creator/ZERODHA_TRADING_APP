"""
services/kite_auth_service.py
------------------------------
Handles Zerodha KiteConnect authentication:
  - get_login_url()           → returns the Kite login URL
  - generate_token(req_token) → exchanges request_token for access_token,
                                saves it to access_token.txt AND updates ../../.env
  - get_token_status()        → checks if a saved token is still valid
"""

import os
import re
from pathlib import Path
from kiteconnect import KiteConnect
from config import ZERODHA_API_KEY, ZERODHA_API_SECRET

TOKEN_FILE = "access_token.txt"

# ../../.env relative to this file (services/kite_auth_service.py)
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
ENV_KEY  = "ZERODHA_ACCESS_TOKEN"


def _get_kite():
    return KiteConnect(api_key=ZERODHA_API_KEY)


def _update_env_file(token: str):
    """
    Write the new access token into ../../.env.
    - If the key already exists (with or without a value), it is replaced.
    - If the key is missing entirely, it is appended.
    Also updates os.environ in-process so config.py picks it up immediately
    without a server restart.
    """
    env_path = ENV_FILE

    if env_path.exists():
        content = env_path.read_text()
    else:
        content = ""

    new_line = f"{ENV_KEY}={token}"
    pattern  = re.compile(rf"^{re.escape(ENV_KEY)}=.*$", re.MULTILINE)

    if pattern.search(content):
        # Replace the existing line
        updated = pattern.sub(new_line, content)
    else:
        # Key not found — append it
        updated = content.rstrip("\n") + f"\n{new_line}\n"

    env_path.write_text(updated)

    # Also update the live process environment
    os.environ[ENV_KEY] = token


def get_login_url() -> str:
    """Return the Zerodha login URL to redirect the user to."""
    kite = _get_kite()
    return kite.login_url()


def generate_token(request_token: str) -> dict:
    """
    Exchange a request_token for an access_token.
    Saves the token to access_token.txt and updates ../../.env
    """
    kite = _get_kite()
    try:
        data         = kite.generate_session(request_token, api_secret=ZERODHA_API_SECRET)
        access_token = data["access_token"]

        # 1. Save to access_token.txt (used by services that read the file directly)
        with open(TOKEN_FILE, "w") as f:
            f.write(access_token)

        # 2. Update ../../.env + os.environ
        _update_env_file(access_token)

        kite.set_access_token(access_token)
        profile = kite.profile()
        return {
            "success"  : True,
            "message"  : f"Login successful! Welcome, {profile.get('user_name', '')}",
            "user_name": profile.get("user_name", ""),
        }
    except Exception as e:
        return {"success": False, "message": f"Login failed: {str(e)}"}


def get_token_status() -> dict:
    """
    Check whether a saved access token exists and is still valid.
    Returns a dict with: has_token, is_valid, user_name, message
    """
    if not os.path.exists(TOKEN_FILE):
        return {
            "has_token": False,
            "is_valid" : False,
            "user_name": None,
            "message"  : "No token found. Please log in.",
        }

    with open(TOKEN_FILE, "r") as f:
        token = f.read().strip()

    if not token:
        return {
            "has_token": False,
            "is_valid" : False,
            "user_name": None,
            "message"  : "Token file is empty. Please log in.",
        }

    kite = _get_kite()
    kite.set_access_token(token)
    try:
        profile = kite.profile()
        return {
            "has_token": True,
            "is_valid" : True,
            "user_name": profile.get("user_name", ""),
            "message"  : "Session active.",
        }
    except Exception:
        return {
            "has_token": True,
            "is_valid" : False,
            "user_name": None,
            "message"  : "Token expired. Please log in again.",
        }