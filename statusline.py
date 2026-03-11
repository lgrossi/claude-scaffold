#!/usr/bin/env uv run
"""Two-line Claude Code statusline with dot progress bars and quota tracking."""

import json, os, sys, subprocess, time
from datetime import datetime, timezone
from pathlib import Path

# Ayu Dark palette
GREEN = "\033[38;5;114m"
ORANGE = "\033[38;5;215m"
RED = "\033[38;5;203m"
DIM = "\033[38;5;242m"
LGRAY = "\033[38;5;250m"
BLUE = "\033[38;5;75m"
CYAN = "\033[38;5;111m"
PURPLE = "\033[38;5;183m"
YELLOW = "\033[38;5;228m"
RESET = "\033[0m"

SEP = f" {DIM}|{RESET} "
SUPERSCRIPT = str.maketrans(
    "0123456789.abcdefghijklmnoprstuvwxyz",
    "⁰¹²³⁴⁵⁶⁷⁸⁹·ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛʷˣʸᶻ",
)
SUBSCRIPT = str.maketrans(
    "0123456789.aehijklmnoprstuvx",
    "₀₁₂₃₄₅₆₇₈₉.ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ",
)

INSIGHTS_FILE = Path.home() / ".claude" / "memory" / "jarvis" / "pending-insights.json"
STRATEGIES_FILE = Path.home() / ".claude" / "memory" / "jarvis" / "active-strategies.json"
INSIGHTS_CACHE = "/tmp/claude-statusline-insights"
INSIGHTS_TTL = 30

GIT_CACHE = "/tmp/claude-statusline-git"
GIT_TTL = 5
USAGE_CACHE = "/tmp/claude-statusline-usage.json"
USAGE_TTL = 60
BEADS_CACHE = "/tmp/claude-statusline-beads"
BEADS_TTL = 10
VERSION_CACHE = "/tmp/claude-statusline-version"
VERSION_TTL = 3600
UPDATE_ICON = "\U000f0047"

PRICING = {
    "claude-opus": {"input": 15.0, "output": 75.0, "cache_write": 3.75, "cache_read": 0.3},
    "claude-sonnet": {"input": 3.0, "output": 15.0, "cache_write": 0.375, "cache_read": 0.03},
    "claude-haiku": {"input": 0.8, "output": 4.0, "cache_write": 0.10, "cache_read": 0.008},
}
COST_CACHE = "/tmp/claude-cost-session-{sid}"
COST_TTL = 30
DAILY_COST_CACHE = "/tmp/claude-cost-daily"
DAILY_TARGET = 300 / 7


def dot_bar(pct, width=10):
    pct = max(0, min(100, int(pct or 0)))
    filled = round(pct * width / 100)
    empty = width - filled
    if pct >= 80:
        col = RED
    elif pct >= 50:
        col = ORANGE
    else:
        col = GREEN
    return f"{col}{'●' * filled}{DIM}{'○' * empty}{RESET}", col


def fmt_tokens(n):
    if not n:
        return "0"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}m"
    if n >= 1000:
        return f"{n // 1000}k"
    return str(n)


def fmt_cost(usd):
    if not usd:
        return "$0"
    return f"${usd:.2f}" if usd >= 0.01 else f"${usd:.4f}"


def fmt_duration(ms):
    if not ms:
        return "0s"
    s = int(ms) // 1000
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m{s % 60:02d}s"
    return f"{s // 3600}h{(s % 3600) // 60:02d}m"


def fmt_reset(iso_str):
    if not iso_str:
        return "", 0
    try:
        dt = datetime.fromisoformat(iso_str).astimezone()
        now = datetime.now(timezone.utc).astimezone()
        delta = dt - now
        total_secs = max(0, delta.total_seconds())
        hours = int(total_secs // 3600)
        mins = int((total_secs % 3600) // 60)
        days = hours // 24
        if days > 0:
            remaining_hours = hours % 24
            return f"{days}d{remaining_hours}h", total_secs
        if hours > 0:
            return f"{hours}h{mins:02d}m", total_secs
        return f"{mins}m", total_secs
    except Exception:
        return "", 0


def quota_color(utilization, remaining_secs, window_secs):
    """Color based on remaining quota per remaining time unit."""
    if not window_secs or remaining_secs <= 0:
        if utilization >= 80:
            return RED
        if utilization >= 50:
            return ORANGE
        return CYAN
    # How many "units" (hours for 5h, days for 7d) remain?
    is_daily = window_secs > 86400
    unit_secs = 86400 if is_daily else 3600
    total_units = window_secs / unit_secs
    remaining_units = max(remaining_secs / unit_secs, 0.1)
    remaining_pct = 100 - utilization
    # How much quota per remaining unit vs even pace
    per_unit = remaining_pct / remaining_units
    even_pace = 100 / total_units
    if per_unit >= even_pace * 0.7:
        return CYAN
    if per_unit >= even_pace * 0.35:
        return ORANGE
    return RED


# -- Cache helpers --


def read_cache(path, ttl):
    try:
        if time.time() - os.stat(path).st_mtime < ttl:
            with open(path) as f:
                return f.read()
    except OSError:
        pass
    return None


def write_cache(path, value):
    try:
        with open(path, "w") as f:
            f.write(value)
    except OSError:
        pass


def latest_version():
    cached = read_cache(VERSION_CACHE, VERSION_TTL)
    if cached is not None:
        return cached or None
    try:
        raw = subprocess.check_output(
            [
                "curl",
                "-s",
                "--max-time",
                "3",
                "https://registry.npmjs.org/@anthropic-ai/claude-code/latest",
            ],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        ).strip()
        ver = json.loads(raw).get("version", "")
        write_cache(VERSION_CACHE, ver)
        return ver
    except Exception:
        write_cache(VERSION_CACHE, "")
        return None


def _run(cmd, cwd=None):
    return subprocess.check_output(
        cmd, cwd=cwd, stderr=subprocess.DEVNULL, text=True, timeout=3
    ).strip()


# -- Data fetchers --


def git_info(cwd):
    if not cwd:
        return None
    import hashlib

    cache_path = GIT_CACHE + "-" + hashlib.md5(cwd.encode()).hexdigest()[:8]
    cached = read_cache(cache_path, GIT_TTL)
    if cached is not None:
        return cached or None

    try:
        branch = _run(["git", "branch", "--show-current"], cwd)
        if not branch:
            branch = _run(["git", "rev-parse", "--short", "HEAD"], cwd)[:7]

        lines = _run(["git", "status", "--porcelain"], cwd).splitlines()
        staged = modified = 0
        for ln in lines:
            if len(ln) < 2:
                continue
            if ln[0] in "AMDRC":
                staged += 1
            if ln[1] in "MD":
                modified += 1

        parts = [f"{LGRAY}󰘬 {branch}{RESET}"]
        if staged:
            parts.append(f"{GREEN}•{staged}{RESET}")
        if modified:
            parts.append(f"{ORANGE}+{modified}{RESET}")

        try:
            raw = _run(["git", "remote", "get-url", "origin"], cwd)
            url = raw
            if url.startswith("git@"):
                url = url.replace(":", "/", 1).replace("git@", "https://")
            if url.endswith(".git"):
                url = url[:-4]
            name = url.rsplit("/", 1)[-1]
            parts.append(f"\033]8;;{url}\a{CYAN}{name}{RESET}\033]8;;\a")
        except Exception:
            parts.append(f"{CYAN}{os.path.basename(cwd)}{RESET}")

        result = " ".join(parts)
    except Exception:
        result = ""

    write_cache(cache_path, result)
    return result or None


def fetch_usage():
    cached = read_cache(USAGE_CACHE, USAGE_TTL)
    if cached is not None:
        try:
            return json.loads(cached) if cached else None
        except Exception:
            pass

    try:
        raw = _run(
            ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"]
        )
        token = json.loads(raw).get("claudeAiOauth", {}).get("accessToken")
        if not token:
            return None

        result = subprocess.check_output(
            [
                "curl",
                "-s",
                "--max-time",
                "5",
                "-H",
                "Accept: application/json",
                "-H",
                f"Authorization: Bearer {token}",
                "-H",
                "anthropic-beta: oauth-2025-04-20",
                "-H",
                "User-Agent: claude-code/2.1.34",
                "https://api.anthropic.com/api/oauth/usage",
            ],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=8,
        ).strip()

        if result:
            json.loads(result)  # validate
            write_cache(USAGE_CACHE, result)
            return json.loads(result)
    except Exception:
        pass

    write_cache(USAGE_CACHE, "")
    return None


def _is_actionable(insight):
    """An insight is actionable if it has an action that isn't purely informational."""
    action = insight.get("action") or ""
    return bool(action) and "no further action needed" not in action.lower() and "for awareness" not in action.lower()


def jarvis_insight_indicator():
    """Statusline: 🔭 strategy | 🎯 priorities | 💡 insights | 📋 notes | ⏳ pending - /brief"""
    try:
        cached = read_cache(INSIGHTS_CACHE, INSIGHTS_TTL)
        if cached is not None:
            return cached or None

        parts = []

        # Strategies (persistent, from active-strategies.json)
        if STRATEGIES_FILE.exists():
            strategies = json.loads(STRATEGIES_FILE.read_text())
            if strategies:
                n = len(strategies)
                parts.append(f"{PURPLE}🔭 {n} strateg{'ies' if n != 1 else 'y'}{RESET}")

        # Insights (queue, from pending-insights.json)
        new_insights = []
        pending_actions = []
        if INSIGHTS_FILE.exists():
            insights = json.loads(INSIGHTS_FILE.read_text())
            for i in insights:
                if not i.get("surfaced_at"):
                    new_insights.append(i)
                elif not i.get("acted_at") and _is_actionable(i):
                    pending_actions.append(i)

        if not parts and not new_insights and not pending_actions:
            write_cache(INSIGHTS_CACHE, "")
            return None

        # New insights by urgency
        red = sum(1 for i in new_insights if i.get("urgency") == "red")
        orange = sum(1 for i in new_insights if i.get("urgency") == "orange")
        green = sum(1 for i in new_insights if i.get("urgency") == "green")
        if red:
            parts.append(f"{RED}🎯 {red} priorit{'ies' if red != 1 else 'y'}{RESET}")
        if orange:
            parts.append(f"{ORANGE}💡 {orange} insight{'s' if orange != 1 else ''}{RESET}")
        if green:
            parts.append(f"{GREEN}📋 {green} note{'s' if green != 1 else ''}{RESET}")

        # Pending actions (surfaced but not acted on)
        if pending_actions:
            n = len(pending_actions)
            parts.append(f"{YELLOW}⏳ {n} pending{RESET}")

        result = f"{' | '.join(parts)} | /brief"
        write_cache(INSIGHTS_CACHE, result)
        return result
    except Exception:
        return None


def beads_task(cwd, sid=""):
    if not cwd or not sid:
        return None
    try:
        with open(f"/tmp/claude-beads-task-{sid}") as f:
            return f.read().strip() or None
    except OSError:
        return None


def _model_pricing(model):
    model = (model or "").lower()
    for prefix, rates in PRICING.items():
        if prefix in model:
            return rates
    return PRICING["claude-opus"]


def find_session_jsonl(sid):
    if not sid:
        return None
    path_cache = f"/tmp/claude-cost-path-{sid}"
    cached = read_cache(path_cache, 3600)
    if cached:
        p = Path(cached)
        if p.exists():
            return p
    matches = list(Path.home().glob(f".claude/projects/*/{sid}.jsonl"))
    if not matches:
        return None
    result = matches[0]
    write_cache(path_cache, str(result))
    return result


def compute_session_cost(sid):
    if not sid:
        return None
    cache_path = COST_CACHE.format(sid=sid)
    cached_raw = read_cache(cache_path, COST_TTL)
    if cached_raw:
        try:
            return json.loads(cached_raw).get("cost")
        except Exception:
            pass

    state = {}
    try:
        with open(cache_path) as f:
            state = json.loads(f.read())
    except Exception:
        pass

    jsonl_path = find_session_jsonl(sid)
    if not jsonl_path:
        return state.get("cost")

    session_dir = jsonl_path.parent / sid

    def _scan_new(filepath, offset):
        cost = 0.0
        try:
            file_size = filepath.stat().st_size
            if file_size < offset:
                offset = 0
            with open(filepath, "rb") as f:
                f.seek(offset)
                for raw in f:
                    try:
                        entry = json.loads(raw)
                    except Exception:
                        continue
                    if entry.get("type") != "assistant":
                        continue
                    msg = entry.get("message") or {}
                    usage = entry.get("usage") or msg.get("usage") or {}
                    model = entry.get("model") or msg.get("model") or ""
                    rates = _model_pricing(model)
                    inp = (usage.get("input_tokens") or 0) / 1_000_000
                    out = (usage.get("output_tokens") or 0) / 1_000_000
                    cw = (usage.get("cache_creation_input_tokens") or 0) / 1_000_000
                    cr = (usage.get("cache_read_input_tokens") or 0) / 1_000_000
                    cost += (
                        inp * rates["input"]
                        + out * rates["output"]
                        + cw * rates["cache_write"]
                        + cr * rates["cache_read"]
                    )
                new_offset = f.tell()
        except OSError:
            return cost, offset
        return cost, new_offset

    main_offset = state.get("offset", 0)
    main_cost, new_main_offset = _scan_new(jsonl_path, main_offset)

    sub_offsets = state.get("sub_offsets", {})
    sub_cost = 0.0
    if session_dir.exists():
        for sub_path in session_dir.glob("subagents/*.jsonl"):
            fname = sub_path.name
            sc, new_off = _scan_new(sub_path, sub_offsets.get(fname, 0))
            sub_cost += sc
            sub_offsets[fname] = new_off

    total_cost = state.get("cost", 0.0) + main_cost + sub_cost
    write_cache(cache_path, json.dumps({
        "offset": new_main_offset,
        "sub_offsets": sub_offsets,
        "cost": total_cost,
    }))
    return total_cost


def daily_cost() -> float:
    cached = read_cache(DAILY_COST_CACHE, 60)
    if cached is not None:
        try:
            return float(cached)
        except ValueError:
            pass

    result = 0.0
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        sensor_path = Path.home() / ".claude" / "memory" / "jarvis" / "sensors" / f"cost-{today}.json"
        if sensor_path.exists():
            data = json.loads(sensor_path.read_text())
            by_date = data.get("by_date") or {}
            entry = by_date.get(today)
            if entry and (entry.get("cost_usd") or 0) > 0:
                result = float(entry["cost_usd"])
                write_cache(DAILY_COST_CACHE, str(result))
                return result
    except Exception:
        pass

    # Fallback: glob today's JSONL files and sum costs using PRICING
    try:
        midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        total = 0.0
        for jsonl in Path.home().glob(".claude/projects/*/*.jsonl"):
            try:
                if os.stat(jsonl).st_mtime < midnight:
                    continue
            except OSError:
                continue
            try:
                with open(jsonl, "rb") as f:
                    for raw in f:
                        try:
                            entry = json.loads(raw)
                        except Exception:
                            continue
                        if entry.get("type") != "assistant":
                            continue
                        msg = entry.get("message") or {}
                        usage = entry.get("usage") or msg.get("usage") or {}
                        model = entry.get("model") or msg.get("model") or ""
                        rates = _model_pricing(model)
                        inp = (usage.get("input_tokens") or 0) / 1_000_000
                        out = (usage.get("output_tokens") or 0) / 1_000_000
                        cw = (usage.get("cache_creation_input_tokens") or 0) / 1_000_000
                        cr = (usage.get("cache_read_input_tokens") or 0) / 1_000_000
                        total += (
                            inp * rates["input"]
                            + out * rates["output"]
                            + cw * rates["cache_write"]
                            + cr * rates["cache_read"]
                        )
            except OSError:
                continue
        result = total
    except Exception:
        pass

    write_cache(DAILY_COST_CACHE, str(result))
    return result


# -- Main --


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.stdout.write(f"{DIM}statusline: waiting{RESET}")
        return

    model_name = (data.get("model") or {}).get("display_name", "")
    cw = data.get("context_window") or {}
    pct = int(cw.get("used_percentage") or 0)
    ctx_size = int(cw.get("context_window_size") or 200000)
    usage = cw.get("current_usage") or {}
    input_tokens = (
        (usage.get("input_tokens") or 0)
        + (usage.get("cache_creation_input_tokens") or 0)
        + (usage.get("cache_read_input_tokens") or 0)
    )

    cost_data = data.get("cost") or {}
    cwd = (data.get("workspace") or {}).get("current_dir", "")
    vim = data.get("vim")
    agent = data.get("agent")

    # Bridge context % to hooks via per-session temp file
    sid = data.get("session_id", "")
    if sid:
        try:
            with open(f"/tmp/claude-context-pct-{sid}", "w") as f:
                f.write(str(pct))
        except OSError:
            pass

    # === LINE 1: Version | Model | context bar pct tokens | cost | duration ===
    parts1 = []
    version = data.get("version", "")
    if version or model_name:
        update_prefix = ""
        if version:
            latest = latest_version()
            if latest and latest != version:
                update_prefix = f"{ORANGE}{UPDATE_ICON} {RESET}"
        small = f"{DIM}{version.translate(SUPERSCRIPT)}{RESET}" if version else ""
        sub = (
            f"{PURPLE}{model_name.lower().translate(SUBSCRIPT)}{RESET}"
            if model_name
            else ""
        )
        parts1.append(f"{update_prefix}{small}{sub}")
    bar, bar_col = dot_bar(pct)
    parts1.append(
        f"{bar} {bar_col}{pct}%{RESET} {DIM}{fmt_tokens(input_tokens)}/{fmt_tokens(ctx_size)}{RESET}"
    )
    parts1.append(f"{LGRAY}󰅐 {fmt_duration(cost_data.get('total_duration_ms'))}{RESET}")
    session_cost = compute_session_cost(sid)
    daily = daily_cost()
    cost_seg = f"{DIM}󰇁 {fmt_cost(session_cost)}{RESET}"
    if daily > 0:
        dpct = daily / DAILY_TARGET * 100
        dcol = RED if dpct >= 100 else ORANGE if dpct >= 70 else GREEN
        cost_seg += f"{SEP}{dcol}󰇁 {fmt_cost(daily)}{DIM}/{fmt_cost(DAILY_TARGET)}{RESET}"
    parts1.append(cost_seg)
    sys.stdout.write(SEP.join(parts1))

    # === LINE 2: git | 5h quota bar | weekly quota bar | vim | agent ===
    parts2 = []

    gi = git_info(cwd)
    if gi:
        parts2.append(gi)

    quota = fetch_usage()
    if quota:
        FIVE_HOURS = 5 * 3600
        SEVEN_DAYS = 7 * 24 * 3600

        fh = quota.get("five_hour") or {}
        fh_pct = int(fh.get("utilization") or 0)
        fh_reset_str, fh_remaining = fmt_reset(fh.get("resets_at"))
        fh_col = quota_color(fh_pct, fh_remaining, FIVE_HOURS)
        filled = round(fh_pct * 8 / 100)
        fh_bar = f"{fh_col}{'●' * filled}{DIM}{'○' * (8 - filled)}{RESET}"
        fh_label = f"5h: {fh_bar} {fh_col}{fh_pct}%{RESET}"
        if fh_reset_str:
            fh_label += f" {DIM}{fh_reset_str}{RESET}"
        parts2.append(fh_label)

        sd = quota.get("seven_day") or {}
        sd_pct = int(sd.get("utilization") or 0)
        sd_reset_str, sd_remaining = fmt_reset(sd.get("resets_at"))
        sd_col = quota_color(sd_pct, sd_remaining, SEVEN_DAYS)
        filled = round(sd_pct * 8 / 100)
        sd_bar = f"{sd_col}{'●' * filled}{DIM}{'○' * (8 - filled)}{RESET}"
        sd_label = f"7d: {sd_bar} {sd_col}{sd_pct}%{RESET}"
        if sd_reset_str:
            sd_label += f" {DIM}{sd_reset_str}{RESET}"
        parts2.append(sd_label)

    jarvis = jarvis_insight_indicator()
    if jarvis:
        parts2.append(jarvis)

    if vim:
        parts2.append(f"{PURPLE} {vim['mode']}{RESET}")
    if agent:
        parts2.append(f"{ORANGE}{agent['name']}{RESET}")

    if parts2:
        sys.stdout.write("\n" + SEP.join(parts2))

    # === LINE 3: beads task (if active) ===
    bt = beads_task(cwd, sid)
    if bt:
        sys.stdout.write(f"\n{YELLOW} {bt}{RESET}")


if __name__ == "__main__":
    main()
