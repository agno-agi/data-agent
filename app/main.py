"""
Dash API
========

Production deployment entry point for Dash.

Run:
    python -m app.main
"""

from os import getenv
from pathlib import Path

from agno.os import AgentOS

from dash.agents import dash, dash_knowledge, reasoning_dash
from dash.agents_ops import ops_dash, ops_knowledge, reasoning_ops_dash
from db import get_postgres_db

# ============================================================================
# Create AgentOS
# ============================================================================
agent_os = AgentOS(
    name="Dash",
    tracing=True,
    db=get_postgres_db(),
    agents=[dash, reasoning_dash, ops_dash, reasoning_ops_dash],
    knowledge=[dash_knowledge, ops_knowledge],
    config=str(Path(__file__).parent / "config.yaml"),
)

app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(
        app="main:app",
        reload=getenv("RUNTIME_ENV", "prd") == "dev",
    )
