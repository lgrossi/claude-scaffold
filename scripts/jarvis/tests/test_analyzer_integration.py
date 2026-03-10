"""Tests for daily-analyzer build_prompt with **sensors dict pattern."""

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "daily_analyzer",
    Path(__file__).parent.parent / "daily-analyzer.py",
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def _minimal_compact() -> dict:
    return {
        "session_id": "test-1",
        "date": "2026-03-10",
        "cwd": "/tmp",
        "stats": {"user_messages": 3, "tool_calls": 5, "tool_errors": 0, "interrupts": 0},
        "tool_usage": {},
        "conversation": "[USER] test\n[CLAUDE] ok",
    }


def _build(**sensors) -> str:
    return mod.build_prompt([_minimal_compact()], [], [], **sensors)


class TestSensorsDict:
    def test_no_sensors(self):
        prompt = _build()
        assert "Calendar:" not in prompt
        assert "Slack (yesterday):" not in prompt
        assert "GitLab (yesterday):" not in prompt
        assert "Jira:" not in prompt
        assert "Confluence:" not in prompt

    def test_calendar_sensor(self):
        cal = {
            "analysis": {
                "total_events": 10,
                "avg_daily_meeting_minutes": 45,
                "deep_work_days": ["2026-03-11"],
            },
        }
        prompt = _build(calendar=cal)
        assert "Calendar: 10 events" in prompt
        assert "Deep work days" in prompt

    def test_slack_sensor(self):
        slack = {
            "summary": {
                "mentions": 5,
                "my_threads": 2,
                "unanswered_threads": 1,
                "top_channels": [{"name": "eng", "messages": 10}],
                "top_interactions": [],
            },
        }
        prompt = _build(slack=slack)
        assert "Slack (yesterday): 5 mentions" in prompt

    def test_unknown_sensor_ignored(self):
        prompt = _build(unknown_sensor={"data": 1})
        assert "unknown_sensor" not in prompt


class TestJiraInjection:
    def test_jira_data_injected(self):
        jira = {
            "summary": {
                "open_issues": 5,
                "stale_issues": 1,
                "sprint_name": "Sprint 42",
                "sprint_days_remaining": 3,
                "sprint_completion_pct": 60,
            },
        }
        prompt = _build(jira=jira)
        assert "Jira: 5 open issues, 1 stale" in prompt
        assert "Sprint: Sprint 42" in prompt
        assert "3d remaining" in prompt
        assert "60% done" in prompt

    def test_jira_none_skipped(self):
        prompt = _build()
        assert "Jira:" not in prompt

    def test_jira_no_sprint(self):
        jira = {
            "summary": {
                "open_issues": 2,
                "stale_issues": 0,
                "sprint_name": None,
                "sprint_days_remaining": None,
                "sprint_completion_pct": None,
            },
        }
        prompt = _build(jira=jira)
        assert "Jira: 2 open issues, 0 stale" in prompt
        assert "Sprint:" not in prompt


class TestConfluenceInjection:
    def test_confluence_data_injected(self):
        confluence = {
            "summary": {
                "my_pages": 3,
                "watched_pages": 2,
                "unresolved_comments": 4,
            },
        }
        prompt = _build(confluence=confluence)
        assert "Confluence: 3 owned pages, 2 watched, 4 unresolved comments" in prompt

    def test_confluence_none_skipped(self):
        prompt = _build()
        assert "Confluence:" not in prompt


class TestAllSensorsCombined:
    def test_all_sensors_present(self):
        prompt = _build(
            gitlab={"summary": {"open_mrs": 1, "stale_mrs": 0, "review_requested": 0, "recently_merged": 0},
                    "items": {"open_mrs": []}},
            gdocs={"summary": {"total_files": 1, "total_unresolved_comments": 0}, "lookback_hours": 24},
            jira={"summary": {"open_issues": 3, "stale_issues": 0, "sprint_name": None,
                              "sprint_days_remaining": None, "sprint_completion_pct": None}},
            confluence={"summary": {"my_pages": 1, "watched_pages": 0, "unresolved_comments": 0}},
        )
        assert "GitLab" in prompt
        assert "Google Docs" in prompt
        assert "Jira:" in prompt
        assert "Confluence:" in prompt


class TestWorkDiarySection:
    def test_work_diary_marker_in_prompt(self):
        prompt = _build()
        assert "<<<WORK_DIARY>>>" in prompt
        assert "<<<END_WORK_DIARY>>>" in prompt

    def test_work_diary_describes_shipped(self):
        prompt = _build()
        assert "Shipped" in prompt

    def test_work_diary_in_report_paths(self):
        assert "work_diary" in mod.REPORT_PATHS

    def test_work_diary_not_in_required(self):
        import inspect
        source = inspect.getsource(mod.main)
        # Find the required = [...] list and ensure WORK_DIARY is not in it
        import re
        match = re.search(r'required\s*=\s*\[([^\]]+)\]', source)
        assert match is not None, "required list not found in main()"
        assert "WORK_DIARY" not in match.group(1)


class TestLoadCalendarSensorRemoved:
    def test_no_load_calendar_sensor_function(self):
        assert not hasattr(mod, "load_calendar_sensor")
