# Data Agent

A self-learning data agent inspired by [OpenAI's internal data agent](https://openai.com/index/how-openai-built-its-data-agent/).

## The 6 Layers of Context

| Layer | Purpose | Implementation |
|-------|---------|----------------|
| **1. Table Metadata** | Schema, columns, types | `knowledge/tables/*.json` |
| **2. Human Annotations** | Business rules, gotchas | `knowledge/business/*.json` |
| **3. Query Patterns** | Validated SQL | `knowledge/queries/*.sql` |
| **4. Institutional Knowledge** | External context | MCP (optional) |
| **5. Learnings** | Discovered patterns | Custom tools + Knowledge base |
| **6. Runtime Context** | Live schema inspection | `introspect_schema` tool |

Plus **agentic memory** for user preferences.

## Quick Start

```sh
# Clone and configure
git clone https://github.com/agno-agi/data-agent.git
cd data-agent
cp example.env .env  # Add OPENAI_API_KEY

# Start
docker compose up -d --build

# Load sample F1 data
docker exec -it data-agent-api python -m da.scripts.load_data
```

- **API**: http://localhost:8000
- **Docs**: http://localhost:8000/docs
- **Control Plane**: [os.agno.com](https://os.agno.com) → Add OS → Local → `http://localhost:8000`

## Try It

```
Who has won the most F1 World Championships?
How many races has Lewis Hamilton won?
Compare Ferrari vs Mercedes points 2015-2020
```

## Deploy to Railway

```sh
railway login
./scripts/railway_up.sh
```

## Add Your Own Data

### 1. Table metadata (`knowledge/tables/my_table.json`)

```json
{
  "table_name": "users",
  "table_description": "User accounts",
  "use_cases": ["User lookup", "Activity analysis"],
  "data_quality_notes": ["Email stored lowercase"]
}
```

### 2. Business rules (`knowledge/business/my_rules.json`)

```json
{
  "metrics": [{"name": "Active User", "definition": "Login in last 30 days"}],
  "common_gotchas": [{"issue": "Timezones", "solution": "All timestamps UTC"}]
}
```

### 3. Load data

```sh
docker exec -it data-agent-api python -c "
import pandas as pd
from sqlalchemy import create_engine
from db import db_url
df = pd.read_csv('/path/to/data.csv')
df.to_sql('my_table', create_engine(db_url), if_exists='replace', index=False)
"
```

## Local Development

```sh
./scripts/venv_setup.sh
source .venv/bin/activate
docker compose up -d data-agent-db  # PostgreSQL
python -m da.scripts.load_data
python -m da  # CLI mode
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes | OpenAI API key |
| `EXA_API_KEY` | No | Exa API for web research |
| `DB_HOST/PORT/USER/PASS/DATABASE` | No | Database config (defaults to localhost) |

## Links

- [OpenAI Data Agent Article](https://openai.com/index/how-openai-built-its-data-agent/)
- [Agno Docs](https://docs.agno.com)
- [Discord](https://agno.com/discord)
