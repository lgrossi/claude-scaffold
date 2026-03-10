#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Jarvis: Auto-Fix Pipeline

Reads pending insights with action_payload from pending-insights.json,
applies mechanical file edits as atomic git commits with blast-radius tags.
Direct push for personal repos, branch+MR for work repos.

Run: uv run auto-fix.py --execute  (default is --dry-run)
Schedule: systemd timer (jarvis-auto-fix.service), after analyzer
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]

MEMORY_DIR = Path(os.environ.get("JARVIS_MEMORY_DIR", str(Path.home() / ".claude" / "memory" / "jarvis")))
INSIGHTS_FILE = MEMORY_DIR / "pending-insights.json"
ACTED_FILE = MEMORY_DIR / "acted-on-hints.json"
LOG_FILE = MEMORY_DIR / "auto-fix-log.md"
MAX_PER_RUN = 5

BLOCKED_PATHS = {
    Path.home() / ".claude" / "CLAUDE.md",
    Path.home() / ".claude" / "settings.json",
    Path.home() / ".claude" / "scripts" / "jarvis" / "daily-analyzer.py",
    Path.home() / ".claude" / "scripts" / "jarvis" / "auto-fix.py",
    Path.home() / ".claude" / "rules" / "jarvis" / "calibration.md",
}


def classify_blast(file_path: str) -> str:
    p = Path(file_path).resolve()
    if p in {b.resolve() for b in BLOCKED_PATHS}:
        return "blocked"
    parts = p.parts
    if "memory" in parts:
        return "safe"
    if "rules" in parts or "skills" in parts:
        return "moderate"
    return "risky"


def load_insights() -> list[dict]:
    if not INSIGHTS_FILE.exists():
        return []
    with INSIGHTS_FILE.open() as f:
        return json.load(f)


def filter_actionable(insights: list[dict]) -> list[dict]:
    result = []
    for i in insights:
        if not i.get("action", "").startswith("auto-fix:"):
            continue
        if i.get("surfaced_at") is not None:
            continue
        payload = i.get("action_payload")
        if not isinstance(payload, dict):
            continue
        if not all(k in payload for k in ("file", "op", "content")):
            continue
        result.append(i)
        if len(result) >= MAX_PER_RUN:
            break
    return result


def apply_payload(payload: dict, dry_run: bool) -> bool:
    file_path = Path(payload["file"])
    op = payload["op"]
    content = payload["content"]
    section = payload.get("section")

    if dry_run:
        print(f"  [dry-run] Would {op} on {file_path}")
        if section:
            print(f"            Section: ## {section}")
        return True

    file_path.parent.mkdir(parents=True, exist_ok=True)

    if op == "append":
        existing = file_path.read_text() if file_path.exists() else ""
        separator = "\n" if existing and not existing.endswith("\n") else ""
        file_path.write_text(existing + separator + content + "\n")
    elif op == "prepend":
        existing = file_path.read_text() if file_path.exists() else ""
        file_path.write_text(content + "\n" + existing)
    elif op == "replace_section":
        if not section:
            print(f"  ERROR: replace_section requires 'section' in payload")
            return False
        if not file_path.exists():
            file_path.write_text(f"## {section}\n{content}\n")
            return True
        existing = file_path.read_text()
        heading = f"## {section}"
        pattern = re.compile(
            rf"^({re.escape(heading)}\s*\n)(.*?)(?=^## |\Z)",
            re.MULTILINE | re.DOTALL,
        )
        match = pattern.search(existing)
        if match:
            replaced = existing[: match.start()] + match.group(1) + content + "\n" + existing[match.end() :]
            file_path.write_text(replaced)
        else:
            file_path.write_text(existing.rstrip() + f"\n\n{heading}\n{content}\n")
    else:
        print(f"  ERROR: Unknown op '{op}'")
        return False
    return True


def git_run(repo: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True, text=True,
    )


def get_repo_root(file_path: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(Path(file_path).parent), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def is_work_repo(repo_root: str) -> bool:
    result = git_run(repo_root, "remote", "get-url", "origin")
    if result.returncode != 0:
        return False
    gitlab_host = os.environ.get("GITLAB_HOST", "gitlab.com")
    return gitlab_host in result.stdout.strip()


def get_current_branch(repo_root: str) -> str:
    result = git_run(repo_root, "rev-parse", "--abbrev-ref", "HEAD")
    return result.stdout.strip()


def create_gitlab_mr(repo_root: str, branch: str, title: str) -> str | None:
    token = os.environ.get("GITLAB_TOKEN")
    host = os.environ.get("GITLAB_HOST", "gitlab.com")
    if not token:
        print("  WARNING: GITLAB_TOKEN not set, skipping MR creation")
        return None

    result = git_run(repo_root, "remote", "get-url", "origin")
    remote_url = result.stdout.strip()

    # Extract project path from remote URL
    # ssh: git@host:group/project.git  or  https://host/group/project.git
    if remote_url.startswith("git@"):
        path = remote_url.split(":", 1)[1]
    elif "://" in remote_url:
        path = "/".join(remote_url.split("://", 1)[1].split("/")[1:])
    else:
        print(f"  WARNING: Cannot parse remote URL: {remote_url}")
        return None
    path = path.removesuffix(".git")
    encoded_path = path.replace("/", "%2F")

    # Get default branch
    default_branch_result = git_run(repo_root, "symbolic-ref", "refs/remotes/origin/HEAD")
    target_branch = "main"
    if default_branch_result.returncode == 0:
        target_branch = default_branch_result.stdout.strip().split("/")[-1]

    result = subprocess.run(
        [
            "curl", "-sL",
            "--header", f"PRIVATE-TOKEN: {token}",
            "--header", "Content-Type: application/json",
            "--data", json.dumps({
                "source_branch": branch,
                "target_branch": target_branch,
                "title": title,
            }),
            f"https://{host}/api/v4/projects/{encoded_path}/merge_requests",
        ],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        try:
            mr_data = json.loads(result.stdout)
            iid = mr_data.get("iid")
            web_url = mr_data.get("web_url")
            if iid:
                return web_url or f"!{iid}"
        except json.JSONDecodeError:
            pass
    print(f"  WARNING: MR creation failed: {result.stdout[:200]}")
    return None


def update_tracking(insight: dict, payload: dict) -> None:
    now = datetime.now(timezone.utc).isoformat()

    # Update surfaced_at in pending-insights.json
    all_insights = load_insights()
    for i in all_insights:
        if i.get("id") == insight.get("id"):
            i["surfaced_at"] = now
            break
    with INSIGHTS_FILE.open("w") as f:
        json.dump(all_insights, f, indent=2)

    # Append to acted-on-hints.json
    acted = []
    if ACTED_FILE.exists():
        with ACTED_FILE.open() as f:
            acted = json.load(f)
    acted.append({
        "hint": insight.get("title", ""),
        "acted_at": now,
        "action": f"auto-fix applied: {payload['op']} on {payload['file']}",
    })
    with ACTED_FILE.open("w") as f:
        json.dump(acted, f, indent=2)


def append_log(direct_pushes: dict, merge_requests: dict) -> None:
    today = date.today().isoformat()
    lines = [f"\n## {today}\n"]

    if direct_pushes:
        lines.append("### Direct pushes")
        for repo, commits in direct_pushes.items():
            lines.append(f"- `{repo}` — {len(commits)} commit(s)")
            for blast, title in commits:
                lines.append(f"  - [{blast}] {title}")
        lines.append("")

    if merge_requests:
        lines.append("### Merge requests")
        for repo, (mr_url, commits) in merge_requests.items():
            mr_num = mr_url.rstrip("/").split("/")[-1] if mr_url and "/" in mr_url else ""
            mr_ref = f"[MR !{mr_num}]({mr_url})" if mr_num else mr_url
            lines.append(f"- `{repo}` — {mr_ref} — {len(commits)} commit(s)")
            for blast, title in commits:
                lines.append(f"  - [{blast}] {title}")
        lines.append("")

    if not direct_pushes and not merge_requests:
        return

    log_content = "\n".join(lines)
    if LOG_FILE.exists():
        with LOG_FILE.open("a") as f:
            f.write(log_content)
    else:
        with LOG_FILE.open("w") as f:
            f.write("# Jarvis Auto-Fix Log\n" + log_content)


def main() -> None:
    parser = argparse.ArgumentParser(description="Jarvis auto-fix pipeline")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Preview changes without applying (default)")
    parser.add_argument("--execute", action="store_true", help="Actually apply fixes")
    args = parser.parse_args()

    dry_run = not args.execute
    mode = "DRY RUN" if dry_run else "EXECUTE"
    print(f"Jarvis auto-fix [{mode}]")

    insights = load_insights()
    actionable = filter_actionable(insights)

    if not actionable:
        print("No actionable auto-fix insights found.")
        return

    print(f"Found {len(actionable)} actionable insight(s)")

    # Group by repo for batched git operations
    # Structure: {repo_root: [(insight, payload, blast), ...]}
    repo_groups: dict[str, list[tuple[dict, dict, str]]] = {}

    for insight in actionable:
        payload = insight["action_payload"]
        file_path = payload["file"]
        blast = classify_blast(file_path)

        print(f"\n  [{blast}] {insight.get('title', 'untitled')}")
        print(f"    File: {file_path}")
        print(f"    Op: {payload['op']}")

        if blast == "blocked":
            print(f"    SKIPPED: file is in blocked list")
            continue

        repo_root = get_repo_root(file_path)
        if repo_root is None:
            print(f"    SKIPPED: file not in a git repo")
            continue

        repo_groups.setdefault(repo_root, []).append((insight, payload, blast))

    if dry_run:
        print(f"\n[dry-run] Would process {sum(len(v) for v in repo_groups.values())} fix(es) across {len(repo_groups)} repo(s)")
        for repo, items in repo_groups.items():
            work = is_work_repo(repo)
            strategy = "branch + MR" if work else "direct push"
            print(f"  {repo} ({strategy}): {len(items)} fix(es)")
        return

    # Execute mode
    direct_pushes: dict[str, list[tuple[str, str]]] = {}
    merge_requests: dict[str, tuple[str, list[tuple[str, str]]]] = {}

    for repo_root, items in repo_groups.items():
        work = is_work_repo(repo_root)
        original_branch = get_current_branch(repo_root)
        branch_name = None

        if work:
            git_user = os.environ.get("GIT_USERNAME", "jarvis")
            branch_name = f"{git_user}/jarvis-autofix-{date.today().isoformat()}"
            result = git_run(repo_root, "checkout", "-b", branch_name)
            if result.returncode != 0:
                # Branch already exists (same-day re-run) — switch to it
                result = git_run(repo_root, "checkout", branch_name)
                if result.returncode != 0:
                    print(f"  ERROR: Cannot create/switch to branch {branch_name}: {result.stderr.strip()}")
                    continue

        commits_in_repo = []
        for insight, payload, blast in items:
            success = apply_payload(payload, dry_run=False)
            if not success:
                print(f"  FAILED: {insight.get('title')}")
                continue

            # Git commit
            add_result = git_run(repo_root, "add", payload["file"])
            if add_result.returncode != 0:
                print(f"  ERROR: git add failed: {add_result.stderr.strip()}")
                continue
            title = insight.get("title", "untitled")
            commit_msg = f"[{blast}] Auto-fix: {title}"
            commit_result = git_run(repo_root, "commit", "-m", commit_msg)
            if commit_result.returncode != 0:
                print(f"  ERROR: git commit failed: {commit_result.stderr.strip()}")
                continue
            commits_in_repo.append((blast, title))

            update_tracking(insight, payload)
            print(f"  Committed: {commit_msg}")

        if not commits_in_repo:
            if work and branch_name:
                git_run(repo_root, "checkout", original_branch)
                git_run(repo_root, "branch", "-d", branch_name)
            continue

        if work and branch_name:
            git_run(repo_root, "push", "-u", "origin", branch_name)
            mr_title = f"Jarvis auto-fix {date.today().isoformat()} ({len(commits_in_repo)} fixes)"
            mr_url = create_gitlab_mr(repo_root, branch_name, mr_title)
            git_run(repo_root, "checkout", original_branch)
            merge_requests[repo_root] = (mr_url or f"branch:{branch_name}", commits_in_repo)
        else:
            git_run(repo_root, "push")
            direct_pushes[repo_root] = commits_in_repo

    append_log(direct_pushes, merge_requests)

    print(f"\nDone. {sum(len(v) for v in direct_pushes.values())} direct push(es), {len(merge_requests)} MR(s)")


if __name__ == "__main__":
    main()
