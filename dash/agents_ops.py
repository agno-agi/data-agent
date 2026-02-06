"""
Ops Dash Agent
==============

Ops-flavored Dash variant that queries the platform operations warehouse.
Points SQLTools at the ops warehouse tables (desired_services, actual_services,
drift_observations, etc.) and uses ops-specific semantic models and business rules.

Test: python -m dash.agents_ops
"""

from os import getenv
from pathlib import Path

from agno.agent import Agent
from agno.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.learn import (
    LearnedKnowledgeConfig,
    LearningMachine,
    LearningMode,
    UserMemoryConfig,
    UserProfileConfig,
)
from agno.models.openai import OpenAIResponses
from agno.tools.reasoning import ReasoningTools
from agno.tools.sql import SQLTools
from agno.vectordb.pgvector import PgVector, SearchType

from dash.context.business_rules import build_business_context
from dash.context.semantic_model import build_semantic_model, format_semantic_model
from dash.tools import create_introspect_schema_tool, create_save_validated_query_tool
from db import get_postgres_db

# ============================================================================
# Ops-specific paths
# ============================================================================

_OPS_KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"
_OPS_TABLES_DIR = _OPS_KNOWLEDGE_DIR / "tables"
_OPS_BUSINESS_DIR = _OPS_KNOWLEDGE_DIR / "business"

# ============================================================================
# Database
# ============================================================================

# Ops warehouse connection — uses OPS_DB_* env vars if set, otherwise falls
# back to the default DB_* vars (same Postgres instance, same database).
_ops_db_url = (
    f"{getenv('OPS_DB_DRIVER', getenv('DB_DRIVER', 'postgresql+psycopg'))}://"
    f"{getenv('OPS_DB_USER', getenv('DB_USER', 'ai'))}:"
    f"{getenv('OPS_DB_PASS', getenv('DB_PASS', 'ai'))}@"
    f"{getenv('OPS_DB_HOST', getenv('DB_HOST', 'localhost'))}:"
    f"{getenv('OPS_DB_PORT', getenv('DB_PORT', '5432'))}/"
    f"{getenv('OPS_DB_DATABASE', getenv('DB_DATABASE', 'ai'))}"
)

agent_db = get_postgres_db()

# ============================================================================
# Knowledge (ops-specific pgvector tables)
# ============================================================================

ops_knowledge = Knowledge(
    name="Ops Knowledge",
    vector_db=PgVector(
        db_url=_ops_db_url,
        table_name="ops_dash_knowledge",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
    contents_db=get_postgres_db(contents_table="ops_dash_knowledge_contents"),
)

ops_learnings = Knowledge(
    name="Ops Learnings",
    vector_db=PgVector(
        db_url=_ops_db_url,
        table_name="ops_dash_learnings",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
    contents_db=get_postgres_db(contents_table="ops_dash_learnings_contents"),
)

# ============================================================================
# Ops Semantic Model & Business Context
# ============================================================================

# Only load ops_* table definitions (filter by prefix)
_ops_semantic_model = build_semantic_model(_OPS_TABLES_DIR)
_ops_semantic_str = format_semantic_model(_ops_semantic_model)
_ops_business_context = build_business_context(_OPS_BUSINESS_DIR)

# ============================================================================
# Tools
# ============================================================================

save_validated_query = create_save_validated_query_tool(ops_knowledge)
introspect_schema = create_introspect_schema_tool(_ops_db_url)

ops_base_tools: list = [
    SQLTools(db_url=_ops_db_url),
    save_validated_query,
    introspect_schema,
    # No Exa MCP — ops-only context, no web search needed
]

# ============================================================================
# Instructions
# ============================================================================

OPS_INSTRUCTIONS = f"""\
You are Ops Dash, a self-learning infrastructure analyst that provides **operational insights** \
from the platform's operational data warehouse.

## Your Purpose

You are the platform operator's data analyst — one that knows every service, every deploy, \
every drift item, and every incident. You turn operational exhaust into actionable intelligence.

You don't just fetch data. You interpret it through the lens of operational risk, correlate \
events across systems, and explain what the data means for platform reliability.

## Two Knowledge Systems

**Knowledge** (static, curated):
- Ops warehouse table schemas, validated queries, business rules
- Searched automatically before each response
- Add successful queries here with `save_validated_query`

**Learnings** (dynamic, discovered):
- Patterns YOU discover through errors and fixes
- Incident signatures, schema quirks, correlation patterns
- Search with `search_learnings`, save with `save_learning`

## Workflow

1. Always start with `search_knowledge_base` and `search_learnings` for table info, patterns, gotchas
2. Write SQL (LIMIT 50, no SELECT *, ORDER BY for rankings)
3. If error → `introspect_schema` → fix → `save_learning`
4. Provide **operational insights**, not just data
5. Offer `save_validated_query` if the query is reusable

## Key Concepts

**Drift Debt Score**: Risk-weighted sum of unresolved drift items.
Formula: severity_weight × blast_radius × age_days × exposure_multiplier
Where exposure_multiplier: 3.0 (public Traefik), 2.0 (platform-core), 1.5 (prod), 1.0 (test)

**Priority Tiers**: P0 (Traefik/edge), P1 (monitoring), P2 (automation), P3 (apps), P4 (datastores)
Updates are applied in reverse order: P4 first (lowest risk), P0 last.

**Platform Hosts**: platform-core (control plane), prod (production workloads)

## Insights, Not Just Data

| Bad | Good |
|-----|------|
| "3 drift items found" | "3 drift items, but Traefik's is 60% of total risk due to public exposure × 12-day age" |
| "5 deploys this week" | "5 deploys, 80% success rate — the Ghost failure correlates with the MySQL OOM at 03:12" |

## SQL Rules

- LIMIT 50 by default
- Never SELECT * — specify columns
- ORDER BY for top-N queries
- No DROP, DELETE, UPDATE, INSERT
- Use JSONB operators (->> , ?) for traefik_labels and details columns
- Use ANY() for TEXT[] array membership checks

---

## SEMANTIC MODEL

{_ops_semantic_str}
---

{_ops_business_context}\
"""

# ============================================================================
# Create Agent
# ============================================================================

ops_dash = Agent(
    name="Ops Dash",
    model=OpenAIResponses(id="gpt-5.2"),
    db=agent_db,
    instructions=OPS_INSTRUCTIONS,
    knowledge=ops_knowledge,
    search_knowledge=True,
    learning=LearningMachine(
        knowledge=ops_learnings,
        user_profile=UserProfileConfig(mode=LearningMode.AGENTIC),
        user_memory=UserMemoryConfig(mode=LearningMode.AGENTIC),
        learned_knowledge=LearnedKnowledgeConfig(mode=LearningMode.AGENTIC),
    ),
    tools=ops_base_tools,
    add_datetime_to_context=True,
    add_history_to_context=True,
    read_chat_history=True,
    num_history_runs=5,
    markdown=True,
)

reasoning_ops_dash = ops_dash.deep_copy(
    update={
        "name": "Reasoning Ops Dash",
        "tools": ops_base_tools + [ReasoningTools(add_instructions=True)],
    }
)

if __name__ == "__main__":
    ops_dash.print_response("What services are running on platform-core?", stream=True)
