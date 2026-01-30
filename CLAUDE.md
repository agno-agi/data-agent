# CLAUDE.md

## Project Overview

Data Agent ("Dash") - A self-learning data agent with 6 layers of context for grounded SQL generation. Inspired by [OpenAI's internal data agent](https://openai.com/index/how-openai-built-its-data-agent/).

## Structure

```
da/
├── agent.py              # Main agent (knowledge + LearningMachine)
├── paths.py              # Path constants
├── context/
│   ├── semantic_model.py # Layer 1: Table metadata
│   └── business_rules.py # Layer 2: Human annotations
├── tools/
│   ├── introspect.py     # Layer 6: Runtime schema
│   └── save_query.py     # Save validated queries
├── scripts/
│   ├── load_data.py      # Load F1 sample data
│   └── load_knowledge.py # Load knowledge files
└── evals/
    ├── test_cases.py     # Test cases
    └── run_evals.py      # Run evaluations

app/
├── main.py               # API entry point (AgentOS)
└── config.yaml           # Agent configuration

db/
├── session.py            # PostgreSQL session factory
└── url.py                # Database URL builder
```

## Commands

```bash
./scripts/venv_setup.sh && source .venv/bin/activate
./scripts/format.sh      # Format code
./scripts/validate.sh    # Lint + type check
python -m da             # CLI mode
python -m da.agent       # Test mode (runs sample query)

# Data & Knowledge
python -m da.scripts.load_data       # Load F1 sample data
python -m da.scripts.load_knowledge  # Load knowledge into vector DB

# Evaluations
python -m da.evals.run_evals              # Run all evals
python -m da.evals.run_evals -c basic     # Run specific category
python -m da.evals.run_evals -v           # Verbose mode
```

## Architecture

**Two Knowledge Bases:**

```python
# KNOWLEDGE: Static, curated (table schemas, validated queries)
data_agent_knowledge = Knowledge(...)

# LEARNINGS: Dynamic, discovered (error patterns, gotchas)
data_agent_learnings = Knowledge(...)

data_agent = Agent(
    knowledge=data_agent_knowledge,
    search_knowledge=True,
    learning=LearningMachine(
        knowledge=data_agent_learnings,  # separate from static knowledge
        user_profile=UserProfileConfig(mode=LearningMode.AGENTIC),
        user_memory=UserMemoryConfig(mode=LearningMode.AGENTIC),
        learned_knowledge=LearnedKnowledgeConfig(mode=LearningMode.AGENTIC),
    ),
)
```

**LearningMachine provides:**
- `search_learnings` / `save_learning` tools
- `user_profile` - structured facts about user
- `user_memory` - unstructured observations

## The 6 Layers

| Layer | Source | Code |
|-------|--------|------|
| 1. Table Metadata | `knowledge/tables/*.json` | `da/context/semantic_model.py` |
| 2. Human Annotations | `knowledge/business/*.json` | `da/context/business_rules.py` |
| 3. Query Patterns | `knowledge/queries/*.sql` | Loaded into knowledge base |
| 4. Institutional Knowledge | Exa MCP | `da/agent.py` |
| 5. Memory | LearningMachine | Separate knowledge base |
| 6. Runtime Context | `introspect_schema` | `da/tools/introspect.py` |

## Data Quality (F1 Dataset)

| Issue | Solution |
|-------|----------|
| `position` is TEXT in `drivers_championship` | Use `position = '1'` |
| `position` is INTEGER in `constructors_championship` | Use `position = 1` |
| `date` is TEXT in `race_wins` | Use `TO_DATE(date, 'DD Mon YYYY')` |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes | OpenAI API key |
| `EXA_API_KEY` | No | Exa for web research |
| `DB_*` | No | Database config |
