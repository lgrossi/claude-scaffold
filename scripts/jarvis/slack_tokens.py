#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pycookiecheat", "requests"]
# ///
"""
Jarvis: Slack Token Extraction & Validation

Extracts xoxc/xoxd tokens from the Slack desktop app's local storage,
validates them via auth.test, and optionally updates ~/.bashrc exports.

Importable module: call extract_and_validate() to get (xoxc, xoxd, user).
Standalone: updates SLACK_XOXC_TOKEN / SLACK_XOXD_TOKEN in ~/.bashrc.
"""

import re
import subprocess
import sys
from pathlib import Path

import requests
from pycookiecheat import chrome_cookies

SLACK_COOKIE_FILE = Path.home() / ".config" / "Slack" / "Cookies"
SLACK_LEVELDB_DIR = Path.home() / ".config" / "Slack" / "Local Storage" / "leveldb"
BASHRC = Path.home() / ".bashrc"
TOKEN_CHARSET = set(b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")


def _get_keyring_password() -> str:
    result = subprocess.run(
        ["secret-tool", "lookup", "application", "Slack"],
        capture_output=True, text=True,
    )
    password = result.stdout.strip()
    if not password:
        raise ValueError("Could not retrieve Slack keyring password via secret-tool")
    return password


def _extract_xoxd() -> str:
    password = _get_keyring_password()
    cookies = chrome_cookies(
        "https://slack.com",
        cookie_file=str(SLACK_COOKIE_FILE),
        password=password,
    )
    xoxd = cookies.get("d", "")
    if not xoxd or not xoxd.startswith("xoxd-"):
        raise ValueError(f"No valid xoxd cookie found (got: {xoxd[:20]}...)" if xoxd else "No 'd' cookie found")
    return xoxd


def _extract_xoxc_candidates() -> list[str]:
    if not SLACK_LEVELDB_DIR.is_dir():
        raise ValueError(f"LevelDB directory not found: {SLACK_LEVELDB_DIR}")

    ldb_files = sorted(SLACK_LEVELDB_DIR.glob("*.ldb"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not ldb_files:
        raise ValueError(f"No .ldb files found in {SLACK_LEVELDB_DIR}")

    seen = set()
    candidates = []
    prefix = b"xoxc-"

    for ldb_file in ldb_files:
        try:
            data = ldb_file.read_bytes()
        except OSError:
            continue

        start = 0
        while True:
            idx = data.find(prefix, start)
            if idx == -1:
                break
            end = idx + len(prefix)
            while end < len(data) and data[end:end + 1] and data[end] in TOKEN_CHARSET:
                end += 1
            token = data[idx:end].decode("ascii", errors="ignore")
            if token not in seen and len(token) > 20:
                seen.add(token)
                candidates.append(token)
            start = end

    if not candidates:
        raise ValueError("No xoxc tokens found in LevelDB files")
    return candidates


def _validate(xoxc: str, xoxd: str) -> str | None:
    try:
        resp = requests.get(
            "https://slack.com/api/auth.test",
            headers={"Authorization": f"Bearer {xoxc}"},
            cookies={"d": xoxd},
            timeout=5,
        )
        data = resp.json()
        if data.get("ok"):
            return data.get("user", "unknown")
    except Exception:
        pass
    return None


def extract_and_validate() -> tuple[str, str, str]:
    xoxd = _extract_xoxd()
    candidates = _extract_xoxc_candidates()

    for xoxc in candidates:
        user = _validate(xoxc, xoxd)
        if user is not None:
            return xoxc, xoxd, user

    raise ValueError(
        f"All {len(candidates)} xoxc candidate(s) failed auth.test. "
        "Tokens may be expired — re-login to Slack desktop app."
    )


def _update_bashrc(xoxc: str, xoxd: str) -> None:
    content = BASHRC.read_text()

    new_content = re.sub(
        r'export SLACK_XOXC_TOKEN=.*',
        f'export SLACK_XOXC_TOKEN="{xoxc}"',
        content,
    )
    new_content = re.sub(
        r'export SLACK_XOXD_TOKEN=.*',
        f'export SLACK_XOXD_TOKEN="{xoxd}"',
        new_content,
    )

    tmp = BASHRC.with_suffix(".tmp")
    tmp.write_text(new_content)
    tmp.replace(BASHRC)


if __name__ == "__main__":
    try:
        xoxc, xoxd, user = extract_and_validate()
        _update_bashrc(xoxc, xoxd)
        print(f"Refreshed tokens for user: {user}")
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
