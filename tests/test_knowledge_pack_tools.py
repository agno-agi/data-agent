"""Tests for knowledge pack pipeline tools (Phase 5.4).

These tests mock SQLAlchemy engine/connection and Knowledge instances to verify
that the knowledge pack tools correctly read incidents, generate artifacts,
and persist them to the knowledge and learnings stores.
No real database or vector DB is needed.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Import module directly to avoid dash/__init__.py Postgres connection.
_module_path = Path(__file__).resolve().parent.parent / "dash" / "tools" / "knowledge_pack.py"
_spec = importlib.util.spec_from_file_location("dash.tools.knowledge_pack", _module_path)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["dash.tools.knowledge_pack"] = _mod
_spec.loader.exec_module(_mod)
create_knowledge_pack_tools = _mod.create_knowledge_pack_tools


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DB_URL = "postgresql+psycopg://ai:ai@localhost:5432/ai"


def _make_incident_row(
    incident_id=1,
    title="Ghost OOM crash loop",
    severity="critical",
    started_at=datetime(2025, 1, 15, 3, 0, tzinfo=timezone.utc),
    resolved_at=datetime(2025, 1, 15, 4, 30, tzinfo=timezone.utc),
    services=None,
    root_cause="Memory limit too low for Ghost 5.x",
    resolution="Increased container memory from 256MB to 512MB",
    timeline_query="SELECT * FROM ops_unified_timeline WHERE ...",
    knowledge_pack=None,
):
    """Build a mock incident_markers row tuple."""
    if services is None:
        services = ["ghost-blog", "ghost-db"]
    return (
        incident_id,
        title,
        severity,
        started_at,
        resolved_at,
        services,
        root_cause,
        resolution,
        timeline_query,
        knowledge_pack or {},
    )


@pytest.fixture
def deps():
    """Create mock dependencies for knowledge pack tools."""
    mock_engine = MagicMock()
    mock_knowledge = MagicMock(spec=["insert"])
    mock_learnings = MagicMock(spec=["insert"])
    with patch.object(_mod, "create_engine", return_value=mock_engine):
        tools = create_knowledge_pack_tools(DB_URL, mock_knowledge, mock_learnings)
    return tools, mock_engine, mock_knowledge, mock_learnings


@pytest.fixture
def tool_map(deps):
    """Map tool entrypoint functions by name."""
    tools, engine, knowledge, learnings = deps
    tmap = {fn.name: fn.entrypoint for fn in tools}
    return tmap, engine, knowledge, learnings


def _setup_conn(engine, row):
    """Wire up the mock engine → connection → result chain."""
    mock_conn = MagicMock()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = row
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.execute.return_value = mock_result
    engine.connect.return_value = mock_conn
    return mock_conn


# ---------------------------------------------------------------------------
# Test: Tool creation
# ---------------------------------------------------------------------------


class TestToolCreation:
    def test_returns_two_tools(self, deps):
        tools, *_ = deps
        assert len(tools) == 2

    def test_tool_names(self, tool_map):
        tmap, *_ = tool_map
        expected = {"generate_knowledge_pack", "get_incident_knowledge_pack"}
        assert set(tmap.keys()) == expected


# ---------------------------------------------------------------------------
# Test: generate_knowledge_pack
# ---------------------------------------------------------------------------


class TestGenerateKnowledgePack:
    def test_generate_success(self, tool_map):
        tmap, engine, knowledge, learnings = tool_map
        row = _make_incident_row()
        _setup_conn(engine, row)

        result = tmap["generate_knowledge_pack"](incident_id=1)

        assert "Knowledge Pack Generated" in result
        assert "#1" in result
        assert "Ghost OOM crash loop" in result
        assert "Validated query" in result
        assert "Incident signature" in result
        assert "Runbook Suggestion" in result
        # Knowledge insert was called (validated query)
        knowledge.insert.assert_called_once()
        # Learnings insert was called (incident signature)
        learnings.insert.assert_called_once()

    def test_generate_saves_correct_query_name(self, tool_map):
        tmap, engine, knowledge, learnings = tool_map
        row = _make_incident_row(incident_id=42)
        _setup_conn(engine, row)

        tmap["generate_knowledge_pack"](incident_id=42)

        # Verify the name passed to knowledge.insert
        call_args = knowledge.insert.call_args
        assert call_args.kwargs["name"] == "incident_42_timeline"

    def test_generate_saves_incident_signature(self, tool_map):
        tmap, engine, knowledge, learnings = tool_map
        row = _make_incident_row(incident_id=7)
        _setup_conn(engine, row)

        tmap["generate_knowledge_pack"](incident_id=7)

        call_args = learnings.insert.call_args
        name = call_args.kwargs["name"]
        assert name.startswith("incident_sig_7_")
        # Parse the saved JSON to verify structure
        text_content = call_args.kwargs["text_content"]
        sig = json.loads(text_content)
        assert sig["type"] == "incident_signature"
        assert sig["incident_id"] == 7
        assert "ghost-blog" in sig["affected_services"]
        assert sig["root_cause"] == "Memory limit too low for Ghost 5.x"
        assert "Out of memory / OOM kill" in sig["symptoms"]

    def test_generate_not_found(self, tool_map):
        tmap, engine, *_ = tool_map
        _setup_conn(engine, None)

        result = tmap["generate_knowledge_pack"](incident_id=999)

        assert "Error" in result
        assert "not found" in result.lower()

    def test_generate_unresolved(self, tool_map):
        tmap, engine, *_ = tool_map
        row = _make_incident_row(resolved_at=None)
        _setup_conn(engine, row)

        result = tmap["generate_knowledge_pack"](incident_id=1)

        assert "Error" in result
        assert "not yet resolved" in result.lower()

    def test_generate_missing_root_cause(self, tool_map):
        tmap, engine, *_ = tool_map
        row = _make_incident_row(root_cause=None)
        _setup_conn(engine, row)

        result = tmap["generate_knowledge_pack"](incident_id=1)

        assert "Error" in result
        assert "root_cause" in result

    def test_generate_with_gotchas(self, tool_map):
        tmap, engine, knowledge, learnings = tool_map
        kp = {"gotchas": ["Ghost 5.x needs 512MB minimum"]}
        row = _make_incident_row(knowledge_pack=kp)
        _setup_conn(engine, row)

        result = tmap["generate_knowledge_pack"](incident_id=1)

        # Gotchas should appear in the runbook suggestion
        assert "512MB" in result
        # And in the incident signature
        text_content = learnings.insert.call_args.kwargs["text_content"]
        sig = json.loads(text_content)
        assert "Ghost 5.x needs 512MB minimum" in sig["gotchas"]

    def test_generate_updates_knowledge_pack_metadata(self, tool_map):
        tmap, engine, knowledge, learnings = tool_map
        row = _make_incident_row()
        mock_conn = _setup_conn(engine, row)

        tmap["generate_knowledge_pack"](incident_id=1)

        # The UPDATE call is the second execute call (after SELECT)
        calls = mock_conn.execute.call_args_list
        assert len(calls) >= 2
        # commit should be called for the UPDATE
        mock_conn.commit.assert_called()

    def test_runbook_contains_services(self, tool_map):
        tmap, engine, *_ = tool_map
        row = _make_incident_row(services=["traefik", "grafana"])
        _setup_conn(engine, row)

        result = tmap["generate_knowledge_pack"](incident_id=1)

        assert "traefik" in result
        assert "grafana" in result

    def test_no_timeline_query_skips_validated_query(self, tool_map):
        tmap, engine, knowledge, learnings = tool_map
        row = _make_incident_row(timeline_query=None)
        _setup_conn(engine, row)

        tmap["generate_knowledge_pack"](incident_id=1)

        # Knowledge insert should NOT be called (no query to save)
        knowledge.insert.assert_not_called()
        # But learnings should still be saved
        learnings.insert.assert_called_once()


# ---------------------------------------------------------------------------
# Test: get_incident_knowledge_pack
# ---------------------------------------------------------------------------


class TestGetIncidentKnowledgePack:
    def _make_kp_row(self, kp=None):
        """Build a row for the get_incident_knowledge_pack query."""
        return (
            1,
            "Ghost OOM crash loop",
            "critical",
            "Memory limit too low",
            "Increased memory",
            ["ghost-blog"],
            kp or {},
            datetime(2025, 1, 15, 4, 30, tzinfo=timezone.utc),
        )

    def test_get_with_knowledge_pack(self, tool_map):
        tmap, engine, *_ = tool_map
        kp = {
            "gotchas": ["Ghost 5.x needs 512MB minimum"],
            "artifacts": {
                "validated_query": "incident_1_timeline",
                "learning": "incident_sig_1_ghost_oom",
            },
            "generated_at": "2025-01-15T04:35:00+00:00",
        }
        _setup_conn(engine, self._make_kp_row(kp))

        result = tmap["get_incident_knowledge_pack"](incident_id=1)

        assert "Knowledge Pack" in result
        assert "#1" in result
        assert "Ghost OOM crash loop" in result
        assert "512MB" in result
        assert "incident_1_timeline" in result
        assert "incident_sig_1_ghost_oom" in result
        assert "Resolved" in result

    def test_get_without_knowledge_pack(self, tool_map):
        tmap, engine, *_ = tool_map
        _setup_conn(engine, self._make_kp_row({}))

        result = tmap["get_incident_knowledge_pack"](incident_id=1)

        assert "No knowledge pack generated yet" in result

    def test_get_not_found(self, tool_map):
        tmap, engine, *_ = tool_map
        _setup_conn(engine, None)

        result = tmap["get_incident_knowledge_pack"](incident_id=999)

        assert "Error" in result
        assert "not found" in result.lower()

    def test_get_ongoing_incident(self, tool_map):
        tmap, engine, *_ = tool_map
        row = (
            2,
            "Traefik cert failure",
            "warning",
            "ACME rate limit",
            None,
            ["traefik"],
            {},
            None,  # not resolved
        )
        _setup_conn(engine, row)

        result = tmap["get_incident_knowledge_pack"](incident_id=2)

        assert "ONGOING" in result


# ---------------------------------------------------------------------------
# Test: Helper functions
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_slugify(self):
        assert _mod._slugify("Ghost OOM crash loop") == "ghost_oom_crash_loop"
        assert _mod._slugify("Traefik Cert-Issue!") == "traefik_certissue"
        assert len(_mod._slugify("a" * 100)) <= 40

    def test_extract_symptoms_oom(self):
        symptoms = _mod._extract_symptoms("Ghost OOM crash", "memory limit exceeded", None)
        assert "Out of memory / OOM kill" in symptoms
        assert "Memory pressure" in symptoms

    def test_extract_symptoms_cert(self):
        symptoms = _mod._extract_symptoms("Traefik cert failure", "ACME rate limit", None)
        assert "TLS certificate issue" in symptoms

    def test_extract_symptoms_with_kp(self):
        kp = {"symptoms": ["Custom symptom"]}
        symptoms = _mod._extract_symptoms("test", "test", kp)
        assert "Custom symptom" in symptoms

    def test_extract_symptoms_deduplicates(self):
        kp = {"symptoms": ["Out of memory / OOM kill"]}
        symptoms = _mod._extract_symptoms("OOM issue", "oom detected", kp)
        assert symptoms.count("Out of memory / OOM kill") == 1

    def test_compute_duration(self):
        start = datetime(2025, 1, 15, 3, 0, tzinfo=timezone.utc)
        end = datetime(2025, 1, 15, 4, 30, tzinfo=timezone.utc)
        assert _mod._compute_duration(start, end) == 90

    def test_compute_duration_from_strings(self):
        assert _mod._compute_duration("2025-01-15T03:00:00+00:00", "2025-01-15T04:30:00+00:00") == 90

    def test_compute_duration_none(self):
        assert _mod._compute_duration(None, None) is None
