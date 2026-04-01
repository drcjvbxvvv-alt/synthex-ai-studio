# Project Brain — Integration Guide (v10.6)

> **v10.6 Update:** L2 memory now uses pure SQLite. No FalkorDB, no Docker.
> Setup is one command: `brain setup`

---

## Quick Start

```bash
pip install project-brain
cd /your/project
brain setup          # init + git hook + MCP auto-detect
```

That's it. Brain will learn from every git commit automatically.

---

## How AI Agents Read Brain Memory

### Method 1: MCP (recommended for Claude Code / Cursor)

`brain setup` auto-installs MCP if Claude Code or Cursor is detected.

```json
{
  "mcpServers": {
    "project-brain": {
      "command": "python",
      "args": ["-m", "project_brain.mcp_server"],
      "env": {"BRAIN_WORKDIR": "/your/project"}
    }
  }
}
```

Available MCP tools:
- `get_context(task, current_file, scope)` — get relevant knowledge + nudges
- `temporal_query(at_time, git_branch)` — time-machine read for old branches
- `get_stats()` — current memory state

### Method 2: Python SDK (for scripts and pipelines)

```python
from project_brain import Brain, ContextResult

b = Brain("/your/project")

# Structured result (recommended)
result = b.query("JWT authentication", scope="auth")

if not result.is_initialized:
    print("Run: brain setup")
elif not result:
    print("No relevant memory found")
else:
    # Inject into your LLM prompt
    prompt = result.to_prompt() + "\n\nUser task: ..."
    print(f"Found {result.source_count} nodes, confidence={result.confidence:.2f}")

# Backward compatible (returns str)
ctx = b.get_context("JWT authentication")
```

### Method 3: REST API (for any LLM tool)

```bash
brain serve --port 7891
```

```http
GET  /v1/context?q=JWT+authentication&scope=auth
POST /v1/add   {"title":"JWT rule","content":"...","kind":"Rule"}
GET  /v1/stats
GET  /health
```

---

## Memory Architecture

```
brain.db  (single file — backup = copy one file)
├── nodes          L3 semantic memory (Rules, Decisions, Pitfalls, ADRs)
├── edges          causal relationships (PREVENTS, CAUSES, REQUIRES)
├── episodes       L2 episodic memory (git commits, events)
├── temporal_edges time-scoped relationships (supersede when updated)
├── sessions       L1a working memory (current task context)
└── events         event log
```

### Three Memory Layers

| Layer | Content | How it's updated |
|-------|---------|-----------------|
| L1a Working Memory | Current task, today's notes | `brain add`, session API |
| L2 Episodic | Commit history, events | git hook (auto), `brain sync` |
| L3 Semantic | Rules, decisions, pitfalls | `brain add`, LLM extraction |

### Spatial Scope

Knowledge can be tagged with a module scope to prevent cross-module pollution:

```bash
brain add "Transaction Lock rule" --kind Rule --scope payment_service
brain add "React Hook rule"       --kind Rule --scope user_profile
```

When an Agent queries with `scope=user_profile`, payment rules are excluded.

### Temporal Query (Time Machine)

```python
# What rules were valid when working on v1.0?
result = db.temporal_query(at_time="2024-06-01T00:00:00")

# Via MCP:
temporal_query(git_branch="v1-legacy")  # auto-resolves branch timestamp
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BRAIN_WORKDIR` | current dir | Project directory |
| `ANTHROPIC_API_KEY` | — | For AI extraction (optional) |
| `BRAIN_LLM_PROVIDER` | `anthropic` | `openai` for Ollama/local |
| `BRAIN_LLM_BASE_URL` | `http://localhost:11434/v1` | Local LLM endpoint |
| `BRAIN_LLM_MODEL` | `claude-haiku-4-5-20251001` | Model name |
| `BRAIN_SYNTHESIZE` | `0` | `1` = enable Memory Synthesizer |
| `BRAIN_API_KEY` | — | API auth for `brain serve` |

---

## Memory Synthesizer (opt-in)

Set `BRAIN_SYNTHESIZE=1` to enable fusion of L1+L2+L3 into a single
"tactical brief" before returning to Agent.

**Without synthesis (default):**
```
## L1 Working Memory
- today's note: JWT HS256 test

## L2 Episodic
- 3 months ago: switched to RS256

## L3 Semantic Rules
- JWT must use RS256
```

**With synthesis (`BRAIN_SYNTHESIZE=1`):**
```
## 🧠 Brain Tactical Brief
• [WARNING] JWT must use RS256 (previously used HS256 in testing — now corrected)
• [RULE] Validate exp field in every token handler
```

Cost: ~1 LLM call per query. Use haiku or local Ollama to minimise cost.

---

## Git Hook (automatic learning)

`brain setup` installs a post-commit hook that captures every commit:

```bash
# Stored as Note with confidence=0.4 (auto-extracted, uncertain)
brain add "commit: fix JWT expiry validation | files: auth/jwt.py" \
  --kind Note --confidence 0.4
```

- No LLM required — always works
- `confidence=0.4` means "auto-extracted, not human-verified"
- Decay engine gradually archives unused low-confidence notes

---

## COMMANDS.md cross-reference

| Use case | Command |
|----------|---------|
| First setup | `brain setup` |
| Add knowledge | `brain add "note"` or `brain add --title "X" --content "..."` |
| Query | `brain ask "question"` |
| API server | `brain serve --port 7891` |
| MCP server | `brain serve --mcp` or `python -m project_brain.mcp_server` |
| Visualize | `brain webui --port 7890` |
| Status | `brain status` |
