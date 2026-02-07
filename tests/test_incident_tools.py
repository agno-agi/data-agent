"""Tests for incident timeline reconstruction tools (Phase 5.3).

These tests mock SQLAlchemy engine/connection to verify that the incident
tools correctly build queries, format results, and handle errors.
No real database is needed.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Import incidents module directly to avoid dash/__init__.py Postgres connection.
_module_path = Path(__file__).resolve().parent.parent / "dash" / "tools" / "incidents.py"
_spec = importlib.util.spec_from_file_location("dash.tools.incidents", _module_path)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["dash.tools.incidents"] = _mod
_spec.loader.exec_module(_mod)
create_incident_tools = _mod.create_incident_tools


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DB_URL = "postgresql+psycopg://ai:ai@localhost:5432/ai"


@pytest.fixture
def tools():
    """Create the incident tool set with a test DB URL."""
    mock_engine = MagicMock()
    with patch.object(_mod, "create_engine", return_value=mock_engine):
        return create_incident_tools(DB_URL), mock_engine


@pytest.fixture
def tool_map(tools):
    """Map tool entrypoint functions by name."""
    tool_list, engine = tools
    return {fn.name: fn.entrypoint for fn in tool_list}, engine


# ---------------------------------------------------------------------------
# Test: Tool creation
# ---------------------------------------------------------------------------


class TestToolCreation:
    def test_returns_four_tools(self, tools):
        tool_list, _ = tools
        assert len(tool_list) == 4

    def test_tool_names(self, tool_map):
        tmap, _ = tool_map
        expected = {
            "reconstruct_timeline",
            "create_incident_marker",
            "resolve_incident",
            "find_similar_incidents",
        }
        assert set(tmap.keys()) == expected


# ---------------------------------------------------------------------------
# Test: reconstruct_timeline
# ---------------------------------------------------------------------------


class TestReconstructTimeline:
    def test_timeline_with_events(self, tool_map):
        tmap, engine = tool_map
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            (datetime(2025, 1, 15, 3, 0), "deploy", "deploy_started", "ghost-blog", "prod", {}),
            (datetime(2025, 1, 15, 3, 2), "docker", "die", "ghost_web_1", "prod", {"exit_code": 137}),
            (datetime(2025, 1, 15, 3, 5), "deploy", "deploy_failed", "ghost-blog", "prod", {}),
        ]
        mock_result.keys.return_value = ["occurred_at", "source", "event_type", "entity", "environment", "details"]
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value = mock_result
        engine.connect.return_value = mock_conn

        result = tmap["reconstruct_timeline"](
            start_time="2025-01-15T03:00:00Z",
            end_time="2025-01-15T04:00:00Z",
        )

        assert "3 events" in result
        assert "ghost-blog" in result
        assert "deploy_started" in result
        assert "die" in result
        assert "[D]" in result  # deploy icon
        assert "[C]" in result  # docker/container icon

    def test_timeline_no_events(self, tool_map):
        tmap, engine = tool_map
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value = mock_result
        engine.connect.return_value = mock_conn

        result = tmap["reconstruct_timeline"](
            start_time="2025-01-15T03:00:00Z",
            end_time="2025-01-15T04:00:00Z",
        )

        assert "No events found" in result

    def test_timeline_with_entity_filter(self, tool_map):
        tmap, engine = tool_map
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            (datetime(2025, 1, 15, 3, 0), "deploy", "deploy_started", "ghost-blog", "prod", {}),
        ]
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value = mock_result
        engine.connect.return_value = mock_conn

        result = tmap["reconstruct_timeline"](
            start_time="2025-01-15T03:00:00Z",
            end_time="2025-01-15T04:00:00Z",
            entity_filter="ghost",
        )

        assert "1 events" in result
        # Verify the query used ILIKE pattern
        call_args = mock_conn.execute.call_args
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
        assert params.get("pattern") == "%ghost%"


# ---------------------------------------------------------------------------
# Test: create_incident_marker
# ---------------------------------------------------------------------------


class TestCreateIncidentMarker:
    def test_create_success(self, tool_map):
        tmap, engine = tool_map
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 42
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value = mock_result
        engine.connect.return_value = mock_conn

        result = tmap["create_incident_marker"](
            title="Ghost OOM crash loop",
            severity="critical",
            started_at="2025-01-15T03:00:00Z",
            affected_services="ghost-blog,ghost-db",
        )

        assert "#42" in result
        assert "Ghost OOM crash loop" in result
        assert "critical" in result
        assert "ghost-blog" in result
        assert "ghost-db" in result
        mock_conn.commit.assert_called_once()

    def test_invalid_severity(self, tool_map):
        tmap, _ = tool_map
        result = tmap["create_incident_marker"](
            title="Test",
            severity="urgent",
            started_at="2025-01-15T03:00:00Z",
            affected_services="test",
        )
        assert "Error" in result
        assert "severity" in result

    def test_empty_services(self, tool_map):
        tmap, _ = tool_map
        result = tmap["create_incident_marker"](
            title="Test",
            severity="warning",
            started_at="2025-01-15T03:00:00Z",
            affected_services="",
        )
        assert "Error" in result
        assert "service" in result.lower()


# ---------------------------------------------------------------------------
# Test: resolve_incident
# ---------------------------------------------------------------------------


class TestResolveIncident:
    def test_resolve_success(self, tool_map):
        tmap, engine = tool_map
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (42, "Ghost OOM crash loop", "2025-01-15T03:00:00Z")
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value = mock_result
        engine.connect.return_value = mock_conn

        result = tmap["resolve_incident"](
            incident_id=42,
            root_cause="Memory limit too low for Ghost 5.x",
            resolution="Increased container memory from 256MB to 512MB",
        )

        assert "#42" in result
        assert "Ghost OOM crash loop" in result
        assert "Resolved" in result
        mock_conn.commit.assert_called_once()

    def test_resolve_with_knowledge_pack(self, tool_map):
        tmap, engine = tool_map
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (42, "Ghost OOM", "2025-01-15T03:00:00Z")
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value = mock_result
        engine.connect.return_value = mock_conn

        kp = json.dumps({"gotchas": ["Ghost 5.x needs 512MB minimum"]})
        result = tmap["resolve_incident"](
            incident_id=42,
            root_cause="Memory limit",
            resolution="Increased memory",
            knowledge_pack=kp,
        )

        assert "stored" in result.lower()

    def test_resolve_not_found(self, tool_map):
        tmap, engine = tool_map
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value = mock_result
        engine.connect.return_value = mock_conn

        result = tmap["resolve_incident"](
            incident_id=999,
            root_cause="Test",
            resolution="Test",
        )

        assert "Error" in result
        assert "not found" in result.lower()

    def test_resolve_invalid_json(self, tool_map):
        tmap, _ = tool_map
        result = tmap["resolve_incident"](
            incident_id=1,
            root_cause="Test",
            resolution="Test",
            knowledge_pack="not-json{",
        )
        assert "Error" in result
        assert "Invalid JSON" in result


# ---------------------------------------------------------------------------
# Test: find_similar_incidents
# ---------------------------------------------------------------------------


class TestFindSimilarIncidents:
    def test_search_by_services(self, tool_map):
        tmap, engine = tool_map
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            (
                1,
                "Ghost OOM",
                "critical",
                "2025-01-10T03:00:00Z",
                "2025-01-10T04:00:00Z",
                ["ghost-blog", "ghost-db"],
                "Memory limit",
                "Increased memory",
                True,
            ),
        ]
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value = mock_result
        engine.connect.return_value = mock_conn

        result = tmap["find_similar_incidents"](services="ghost-blog")

        assert "Ghost OOM" in result
        assert "Memory limit" in result
        assert "resolved" in result
        assert "[+]" in result  # has knowledge pack

    def test_search_by_keywords(self, tool_map):
        tmap, engine = tool_map
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            (
                2,
                "Traefik cert failure",
                "warning",
                "2025-01-12T10:00:00Z",
                None,
                ["traefik"],
                "ACME rate limit",
                None,
                False,
            ),
        ]
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value = mock_result
        engine.connect.return_value = mock_conn

        result = tmap["find_similar_incidents"](keywords="cert")

        assert "Traefik cert failure" in result
        assert "ONGOING" in result
        assert "[-]" in result  # no knowledge pack

    def test_search_no_params(self, tool_map):
        tmap, _ = tool_map
        result = tmap["find_similar_incidents"]()
        assert "Error" in result
        assert "services or keywords" in result

    def test_search_no_results(self, tool_map):
        tmap, engine = tool_map
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value = mock_result
        engine.connect.return_value = mock_conn

        result = tmap["find_similar_incidents"](keywords="nonexistent")
        assert "No matching incidents" in result
