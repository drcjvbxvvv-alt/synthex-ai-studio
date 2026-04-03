##### [繁體中文](./README.md) | English

# Project Brain

> **Engineering memory infrastructure for AI Agents.**
> Every conversation picks up where the last one left off — decisions, rules, and hard-won lessons included.

[![Version](https://img.shields.io/badge/version-v0.2.0-blue.svg)](https://github.com/your-org/project-brain/releases)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![MCP Compatible](https://img.shields.io/badge/MCP-compatible-purple.svg)](https://modelcontextprotocol.io/)
[![Zero Dependencies](https://img.shields.io/badge/runtime_deps-flask_only-brightgreen.svg)]()

---

## The Problem

Every time you open a new AI conversation, the Agent knows nothing about your project.

Six months ago you hit the Stripe Webhook idempotency bug, fixed it, wrote a commit — but the next time an Agent helps you implement a refund, it doesn't know. It will step on exactly the same landmine, in exactly the same way.

This isn't the Agent being unintelligent. It simply has no memory.

Project Brain solves this: it builds a long-term knowledge store inside your project that Agents can query, turning pitfalls, architectural decisions, and engineering rules into knowledge that is available at the start of every conversation.

```
You say: "Help me implement the payment refund feature"
         ↓
Agent queries Brain: any payment-related pitfalls?
         ↓
Brain returns: Stripe Webhook fires twice — must use idempotency_key (confidence=0.9)
         ↓
Agent writes the code with that knowledge, avoiding the mistake
```

---

## The Honest Case: Why Project Brain When LLMs Keep Getting Stronger?

> This is not a sales pitch. It's a direct answer to a fair question.

### The Real Question: LLMs are increasingly capable — do I still need this?

**Yes. But not for the reason you might expect.**

Claude Opus 4, GPT-4o, Gemini Ultra — their reasoning, comprehension, and code generation are genuinely remarkable. The problem has never been that LLMs aren't smart enough.

The problem is: **they know nothing about your project.**

```
You say: "Help me fix this refund bug"
LLM: "Sure, let me look at this code..."

What it doesn't know:
  × Your team already hit this exact issue six months ago
  × Your Stripe integration has a non-standard idempotency_key convention
  × payment_service has different transaction boundaries than other services
  × The last engineer who touched this left an implicit assumption in place

None of this is in any training data. It lives in your git history and your colleagues' heads.
```

### 5W1H: Let's be specific

---

**Who — Who should use this?**

A good fit:
- **Teams using AI Coding Agents (Claude Code, Cursor, Copilot) for real development work**
- Codebases 6+ months old with accumulated architectural decisions and hard-won lessons
- Multi-person teams where knowledge is scattered across individual heads
- Engineers who find themselves re-explaining context every time they open a new AI conversation

Not a good fit:
- Brand-new projects with no history yet (cold-start period has low value)
- Purely exploratory, one-off AI conversations
- Anyone expecting "install and it works" without being willing to do `brain add`

---

**What — What problem does it actually solve?**

**Problem 1: LLM context is ephemeral.**

Even with a 200k-token context window, you can't fit six months of decision history. The deeper problem: you don't know which 3 rules are relevant to today's task. Brain's job is to compress 6 months into "the 2,000 tokens relevant to what you're doing right now."

**Problem 2: Project-specific knowledge isn't in any LLM's training data.**

An LLM knows general Stripe best practices. It does not know that your team uses `X-Idempotency-Key` instead of `Idempotency-Key` because a specific version of your SDK had a bug. That knowledge lives only in commit e3f2a19.

**Problem 3: AI Agents make decisions — and then forget them.**

An Agent helps you refactor your database access layer, explains the rationale in the PR — then the conversation ends. Next month you open a new session, it faces the same decision, and may make a completely different call. Brain records those decisions automatically every time an Agent commits.

**What Brain does NOT solve (honestly):**
- It doesn't make the LLM smarter
- It doesn't replace your own architectural thinking
- It cannot capture tacit knowledge — if you never wrote it down, Brain can't know it
- Cold-start period (first 2–4 weeks) delivers limited value while the knowledge base is being built

---

**When — When is the benefit most visible?**

The payoff grows **non-linearly** over time:

```
Week 1:    Almost no benefit (knowledge base is empty)
Month 1:   Relevant rules start appearing in context
Month 3:   Agent automatically avoids pitfalls your team has already hit
Month 6:   New Agents (and new team members) can understand project context quickly
```

Scenarios where it makes a clear difference:
- "How did we do this last time?" type queries
- Knowledge continuity across LLM conversation boundaries
- Onboarding (letting Agent play the role of the "senior engineer who knows everything")
- Technical debt review (which decisions were intentional vs. historical accidents)

---

**Where — Where in the workflow does it have an effect?**

```
You describe the task → Agent queries Brain first → Agent responds with project context
                                                          ↑
                                                  These 2 seconds are the difference
```

Not inside LLM reasoning — but in **context injection before reasoning begins**. Brain doesn't reason; it provides material so the LLM can reason more accurately.

---

**Why — Why not use other approaches?**

| Approach | Problem |
|----------|---------|
| Dump all docs into context | Doesn't fit; you don't know what's relevant; requires manual curation every time |
| Notion / Confluence | Agent won't query it proactively; requires manual maintenance |
| Rely on git log | Unstructured; LLM re-parses it from scratch each time, expensive |
| General memory tools (Mem0 etc.) | No engineering-specialized schema; no version-based decay; external service dependency |
| Do nothing | Depends on individual memory; knowledge walks out the door with people |

Brain's position: **structured long-term memory for engineering codebases, zero external dependencies, natively integrated with git workflows.**

---

**How — How does it actually work? How do you measure it?**

Workflow:
```
1. brain setup        (5 minutes, one time)
2. Every git commit   automatically recorded (zero friction)
3. Important decision brain add              (30 seconds)
4. Every Agent task   automatically queried  (transparent to Agent)
```

Honest ways to measure whether it's working:
- How often does "Agent referenced a decision I made before" happen?
- How many times does "we already hit this — Agent avoided it this time" occur?
- When a new team member asks "why is it done this way?", what fraction can `brain ask` answer?

**What it cannot guarantee:**
- Recall ceiling is approximately 75% — 25% of relevant knowledge may not be retrieved
- Quality depends entirely on how well the knowledge base is maintained
- Auto-extracted knowledge needs human review to reach high-confidence status

---

### One-sentence summary

**LLMs solve "how to do it." Project Brain solves "in this project, how did we decide to do it." They don't compete — Brain gives the LLM the project context it needs to reason accurately.**

---

## Why the AI Era Needs This

### AI Agent commits are better raw material than human commits

Traditional knowledge-management tools assume "humans write commits, humans record decisions" — commit message quality is inconsistent and knowledge extraction is noisy.

The AI era inverts that assumption:

|             | Human commit                       | AI Agent commit                                                 |
| ----------- | ---------------------------------- | --------------------------------------------------------------- |
| Format      | Arbitrary ("fix bug", "wip", "ok") | Structured (Conventional Commits: `feat:`, `fix:`, `refactor:`) |
| Intent      | Often implicit or omitted          | Explicit and complete, drawn directly from the task description |
| Consistency | Varies by developer                | Stable, governed by the prompt's style                          |
| Frequency   | Human-driven, sporadic             | Committed on task completion — high-frequency and systematic    |

**Conclusion:** AI Agent commits are first-class knowledge material. Brain's git hook creates a positive feedback loop that runs naturally inside an AI coding workflow:

```
Agent completes task → structured commit
                              ↓
                   Brain extracts decisions & pitfalls
                              ↓
                   Next Agent session already knows
                              ↓
                   Agent avoids repeat mistakes, writes better commits
```

This loop is high-friction and hard to sustain with purely human collaboration; in an Agent workflow **it runs on its own, at no extra cost**.

---

## Design Philosophy

### Memory is engineering team infrastructure

Code is an asset, tests are a safety net, and memory is the soil that keeps both effective.

A development process without memory means every AI Agent you bring in is like a new hire on their first day — sharp, but knowing nothing about this project. Project Brain's goal is to let Agents start every conversation with the perspective of a seasoned team member.

### Fight forgetting, not ignorance

Project Brain doesn't try to remember everything — it remembers **what's worth remembering**:

- Pitfalls — prevent repeating the same mistakes
- Decisions — understand why things are the way they are
- Rules — let Agents automatically follow implicit conventions
- ADRs (Architecture Decision Records) — preserve context around major choices

What it does _not_ store: scratch notes, one-off tasks, completed TODOs.

### Honest about its limits

Any system that claims to be perfect is a lab toy. Project Brain is clear about its own boundaries by design:

- Semantic recall ceiling is roughly 75% (ontology is a research problem, not an engineering one)
- It can only record what humans have already noticed is worth recording
- It has no power over tacit knowledge — things you take for granted and never write down

Acknowledging these limits is the beginning of building something genuinely useful.

---

## Engineering Philosophy

### 1. Zero Dependencies by Default

Core functionality depends only on the Python standard library and SQLite. No Docker, no Redis, no vector database — install and go.

Advanced features (vector semantic search, MCP Server, local LLM) are provided as optional dependencies, installed on demand.

```
brain setup   ← one command, no external services required
```

### 2. Single File, Backup is a Copy

All memory lives in `.brain/brain.db` — one standard SQLite file.

Backup: `cp .brain/brain.db .brain/brain.db.bak`
Migration: copy the file to a new machine
Version control: optionally git-track it, or add it to `.gitignore`

No backup scripts. No export/import tooling. No admin intervention.

### 3. Graceful Degradation

| Scenario             | Brain's behavior                                    |
| -------------------- | --------------------------------------------------- |
| No API key           | Skip LLM extraction; still record basic commit info |
| No vector index      | Fall back to FTS5 keyword search                    |
| MCP connection fails | CLAUDE.md prompt guides Agent to query manually     |
| Empty knowledge base | Return empty string; don't block Agent operation    |

Brain's failure mode is "silent fallback", not "block the pipeline".

### 4. Confidence Spectrum, Not Binary Truth

Knowledge isn't "right" or "wrong" — it has degrees of reliability:

| Source                           | Confidence | Meaning                           |
| -------------------------------- | ---------- | --------------------------------- |
| Manually verified (KRB approval) | 0.9        | Confirmed correct                 |
| Manually added directly          | 0.8        | Trusted but unverified            |
| Auto-discovered by Agent         | 0.6        | Probably correct                  |
| Extracted from git commit        | 0.5        | Standard quality                  |
| fix/wip commit                   | 0.2        | Low quality, candidate for expiry |

Confidence decays over time; nodes that are queried more often decay more slowly (because usage signals continued relevance).

### 5. Human-in-the-Loop, Not Full Automation

Automation lowers friction but doesn't replace judgment.

`brain sync` (git hook) automatically captures every commit, providing raw material. Knowledge that is genuinely valuable still requires an engineer to confirm and augment it with `brain add`. This isn't a design flaw — it's a deliberate choice. Fully automated extraction isn't reliable enough to trust directly.

---

## Engineering Concepts

### The Atkinson-Shiffrin Memory Model

Project Brain's architecture maps directly to the cognitive science multi-store memory model:

```
L1a  Working Memory
     ↳ Immediate attention for the current task
     ↳ Cleared automatically when the conversation ends
     ↳ Stores: today's notes, current task context

L2   Episodic Memory
     ↳ "When did that JWT incident happen?"
     ↳ Corresponds to: git commit history, event sequences
     ↳ Supports time-machine queries (temporal_query)

L3   Semantic Memory
     ↳ "JWT must use RS256" — not an event, a pattern
     ↳ Refined from L2 into long-term knowledge
     ↳ Supports knowledge-graph relationships (PREVENTS / CAUSES / REQUIRES)
```

Each layer has its own role; `get_context` reads all three and merges the output.

### Multi-Factor Knowledge Decay Model

Knowledge doesn't stay valid forever. Brain uses seven factors to compute a dynamic confidence score for each knowledge node:

| Factor                         | Effect                                                                   |
| ------------------------------ | ------------------------------------------------------------------------ |
| F1 Time decay                  | Older knowledge receives lower confidence (base daily decay rate: 0.003) |
| F2 Technology version gap      | Knowledge mentions React 16, current version is React 18 → penalty       |
| F3 Code activity signal        | Related files modified in the last 30 days → bonus                       |
| F4 Contradiction detection     | Two pieces of knowledge contradict each other → both penalized           |
| F5 Code reference confirmation | Classes mentioned in the knowledge still exist in the codebase → bonus   |
| F7 Query frequency             | The more often the Agent queries a node → the slower it decays           |

Nodes whose confidence falls below 0.20 are automatically marked stale. Decay reduces visibility; it does not delete knowledge.

### Spatial Scope Isolation

Knowledge from different modules should not interfere with each other:

```bash
brain add "Transaction Lock rule" --scope payment_service
brain add "React Hook rule"       --scope user_profile
```

Queries are automatically filtered: an Agent operating in the `user_profile` context will not see rules scoped to `payment_service`. Knowledge with no explicit scope belongs to `global` and is visible to all queries.

---

## Architecture Overview

```
.brain/
├── brain.db              Primary memory store (SQLite)
│   ├── nodes             L3 semantic memory (Rule/Decision/Pitfall/ADR)
│   ├── edges             Causal relationship edges (PREVENTS/CAUSES/REQUIRES)
│   ├── episodes          L2 episodic memory (git commits)
│   ├── temporal_edges    Temporal relationships (time-machine queries)
│   └── sessions          L1a working memory (current task)
├── review_board.db       KRB staging area (auto-extracted candidate knowledge)
└── config.json           Brain configuration
```

```
┌──────────────────────────────────────────────────┐
│                   AI Agent                        │
│          (Claude / Cursor / any MCP tool)         │
└──────────────┬───────────────────────────────────┘
               │  MCP / REST API / Python SDK
┌──────────────▼───────────────────────────────────┐
│              Project Brain                        │
│                                                   │
│  ┌──────────┐  ┌──────────┐  ┌─────────────────┐ │
│  │ L1a      │  │ L2       │  │ L3              │ │
│  │ Working  │  │ Episodic │  │ Semantic        │ │
│  │ Memory   │  │ Memory   │  │ Memory          │ │
│  └──────────┘  └──────────┘  └─────────────────┘ │
│                      ↑                            │
│              DecayEngine (every 7 days)           │
└──────────────────────────────────────────────────┘
               ↑
    git hook (automatic) + brain add (manual)
```

---

## Quick Start

### Installation

```bash
pip install project-brain
```

**Advanced installation (with MCP Server and semantic search):**

```bash
pip install "project-brain[mcp]"
```

### Initialization

```bash
cd /your/project
brain setup
```

`brain setup` does the following automatically:

1. Creates `.brain/brain.db`
2. Installs a git `post-commit` hook (learns from every commit)
3. Detects Claude Code / Cursor and prints sample MCP configuration

### Step 1: Add Knowledge

```bash
# Quick form
brain add "JWT must use RS256 — HS256 will fail token validation behind a load balancer"

# Full form
brain add \
  --title "Stripe Webhook Idempotency" \
  --content "Must use idempotency_key on duplicate triggers, otherwise double charges occur" \
  --kind Pitfall \
  --scope payment_service \
  --confidence 0.9
```

### Step 2: Verify It's Queryable

```bash
brain ask "JWT configuration"
brain ask "payment refund"
```

### Step 3: Connect Your Agent (Claude Code)

```json
// .claude/settings.json
{
  "mcpServers": {
    "project-brain": {
      "command": "python",
      "args": ["-m", "project_brain.mcp_server"],
      "env": {
        "BRAIN_WORKDIR": "/your/project"
      }
    }
  }
}
```

Add the following to `.claude/CLAUDE.md`:

```markdown
At the start of every task, call the `get_context` MCP tool with the task description.
If Brain returns nudges or warnings, treat them as hard constraints.
```

---

## CLI Reference

| Command             | Description                  | Example                            |
| ------------------- | ---------------------------- | ---------------------------------- |
| `brain setup`       | One-command initialization   | `brain setup`                      |
| `brain add`         | Add knowledge (manual)       | `brain add "rule" --kind Rule`     |
| `brain ask`         | Query knowledge              | `brain ask "how to configure JWT"` |
| `brain status`      | Memory store status          | `brain status`                     |
| `brain sync`        | Learn from the latest commit | `brain sync --quiet`               |
| `brain scan`        | Scan git history for knowledge | `brain scan --all`               |
| `brain review`      | Review KRB staging area      | `brain review list`                |
| `brain serve`       | Start REST API               | `brain serve --port 7891`          |
| `brain serve --mcp` | Start MCP Server             | `brain serve --mcp`                |
| `brain webui`       | D3.js visualization          | `brain webui --port 7890`          |
| `brain index`       | Build vector index (with progress bar) | `brain index`          |
| `brain optimize`    | VACUUM + ANALYZE + FTS5 rebuild | `brain optimize`              |
| `brain clear`       | Clear session working memory | `brain clear`                      |
| `brain export`      | Export knowledge store       | `brain export --format json`       |
| `brain import`      | Import knowledge store       | `brain import backup.json`         |
| `brain analytics`   | Usage analytics              | `brain analytics --export csv`     |
| `brain deprecate`   | Deprecate a knowledge node   | `brain deprecate <id>`             |
| `brain lifecycle`   | Node lifecycle history       | `brain lifecycle <id>`             |
| `brain counterfactual` | Counterfactual impact analysis | `brain counterfactual "replace PostgreSQL"` |
| `brain health-report` | Health report (Markdown)  | `brain health-report`              |
| `brain doctor`      | Environment diagnostics & fix | `brain doctor --fix`              |

### Knowledge Types (--kind)

| Type       | Meaning                      | When to Use                                 |
| ---------- | ---------------------------- | ------------------------------------------- |
| `Pitfall`  | Trap record                  | Mistakes made before, hidden landmines      |
| `Decision` | Architectural decision       | Why A was chosen over B                     |
| `Rule`     | Engineering rule             | Technical conventions that must be followed |
| `ADR`      | Architecture Decision Record | Formal architectural decision document      |
| `Note`     | General note                 | Other information worth remembering         |

---

## Agent Integration

### MCP (Recommended — works with Claude Code / Cursor)

```bash
brain serve --mcp
```

Available MCP tools:

| Tool                                                     | Description                                                               |
| -------------------------------------------------------- | ------------------------------------------------------------------------- |
| `get_context(task, current_file, scope)`                 | Retrieve task-relevant knowledge (with causal chain + proactive warnings) |
| `add_knowledge(title, content, kind, scope, confidence)` | Agent writes new knowledge                                                |
| `search_knowledge(query)`                                | Direct semantic search                                                    |
| `temporal_query(at_time, git_branch)`                    | Time-machine — read knowledge state at a given point in time              |
| `brain_status()`                                         | Memory store statistics                                                   |

### Python SDK

```python
from project_brain import Brain

b = Brain("/your/project")

# Structured query (recommended)
result = b.query("JWT authentication issue", scope="auth")
if result:
    print(f"Found {result.source_count} entries, confidence {result.confidence:.2f}")
    prompt = result.to_prompt() + "\n\nUser task: ..."

# Backwards-compatible (returns string)
ctx = b.get_context("JWT authentication issue")
```

### REST API

```bash
brain serve --port 7891
```

```http
GET  /v1/context?q=JWT&scope=auth
POST /v1/add
     {"title": "JWT rule", "content": "...", "kind": "Rule", "scope": "auth"}
GET  /v1/stats
GET  /health
```

---

## Auto-Learning (Git Hook)

`brain setup` installs a `post-commit` hook that automatically records every commit:

```bash
git commit -m "fix: validate JWT exp field to prevent token hijacking"
# → Brain records automatically (confidence=0.5)
# → Next time an Agent queries JWT, this entry appears
```

**AI Agent commits are far higher quality than casual human submissions.** Conventional Commits format (`feat:`, `fix:`, `refactor:`) combined with complete task descriptions lets Brain's LLM extractor accurately identify decision types with almost no manual correction.

**Confidence scoring:**

- `fix:` / `feat:` / `refactor:` prefix → confidence 0.5
- `wip` / no prefix → confidence 0.2
- Manual `brain add` → confidence 0.8 (default)
- Manual KRB review approval → confidence 0.9

**Confidence semantic labels (v0.2.0):**

Output confidence values carry semantic markers so Agents can immediately judge reliability:

| Label | Range | Meaning |
|-------|-------|---------|
| `⚠ speculative` | 0.0–0.3 | Low-quality commit origin; use with caution |
| `~ inferred` | 0.3–0.6 | Auto-extracted; probably correct |
| `✓ verified` | 0.6–0.8 | Manually added or confirmed by repeated queries |
| `✓✓ authoritative` | 0.8–1.0 | KRB-approved or high-confidence manual entry |

---

## Memory Synthesizer (Advanced)

By default, `get_context` returns a concatenation of raw data from all three layers. With Memory Synthesizer enabled, an LLM fuses the three layers into a concise "tactical brief":

```bash
export BRAIN_SYNTHESIZE=1
```

**Without (default):**

```
## L2 Episodic
- 3 months ago: switched JWT from HS256 to RS256

## L3 Semantic Rules
- JWT must use RS256
```

**With Memory Synthesizer:**

```
## 🧠 Brain Tactical Brief
• [WARNING] JWT must use RS256 — previously used HS256 in testing (corrected 3mo ago)
• [RULE] Validate exp field in every token handler
```

Cost: approximately one LLM call per `get_context` invocation (haiku ~$0.0002, Ollama free).

---

## Environment Variables

| Variable             | Default                     | Description                                |
| -------------------- | --------------------------- | ------------------------------------------ |
| `BRAIN_WORKDIR`      | Current directory           | Project directory (omits `--workdir` flag) |
| `ANTHROPIC_API_KEY`  | —                           | Anthropic API (AI extraction features)     |
| `BRAIN_LLM_PROVIDER` | `anthropic`                 | Use `openai` for Ollama / LM Studio        |
| `BRAIN_LLM_BASE_URL` | `http://localhost:11434/v1` | Local LLM endpoint                         |
| `BRAIN_LLM_MODEL`    | `claude-haiku-4-5-20251001` | Model name                                 |
| `BRAIN_SYNTHESIZE`   | `0`                         | Set to `1` to enable Memory Synthesizer    |
| `BRAIN_API_KEY`      | —                           | API authentication for `brain serve`       |
| `BRAIN_MAX_TOKENS`   | `6000`                      | Maximum context token budget               |
| `BRAIN_EXPAND_LIMIT` | `15`                        | Query expansion term limit (reduces noise) |
| `BRAIN_DEDUP_THRESHOLD` | `0.85`                   | Semantic dedup cosine threshold            |
| `BRAIN_RATE_LIMIT_RPM` | `60`                      | MCP calls per minute limit                 |
| `BRAIN_EMBED_PROVIDER` | auto-detected             | `none` = disable vectors, FTS5 only        |

### Local LLM (Ollama)

```bash
export BRAIN_LLM_PROVIDER=openai
export BRAIN_LLM_BASE_URL=http://localhost:11434/v1
export BRAIN_LLM_MODEL=llama3.2:3b
```

---

## Multi-Project Support

`brain` automatically walks up from the current directory to locate `.brain/`, mirroring git's `.git/` detection logic:

```bash
cd ~/projects/payment-service
brain ask "refund logic"   # ← uses payment-service/.brain/

cd ~/projects/auth-service
brain ask "JWT config"     # ← uses auth-service/.brain/
```

Each project has its own isolated memory store; they do not interfere with each other.

---

## Academic Context & Research Comparison

### Theoretical Foundations

Project Brain's three-layer architecture maps directly to the **Atkinson-Shiffrin multi-store memory model** (1968) and draws on the systematic classification framework for AI Agent memory in **CoALA: Cognitive Architectures for Language Agents** (arXiv:2309.02427, TMLR 2024).

### Comparison with Contemporary Research

In early 2026, "automatically extracting structured knowledge from engineering history" became an active research direction:

| Paper                                            | Core Contribution                                                | Project Brain's Distinction                                                                         |
| ------------------------------------------------ | ---------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| **Lore** (arXiv:2603.15566, 2026/03)             | Redesigns git commit messages as a structured knowledge protocol | Lore changes how you write; Brain extracts from existing commits, no workflow changes required      |
| **MemCoder** (arXiv:2603.13258, 2026/03)         | Extracts intent-to-code mappings from commit history             | MemCoder doesn't classify; Brain classifies into Pitfall/Decision/Rule with decay management        |
| **MemGovern** (arXiv:2601.06789, 2026/01)        | Extracts governed experience cards from GitHub Issues            | MemGovern's quality gate is the closest analog to KRB; Brain adds KG persistence and decay          |
| **Codified Context** (arXiv:2602.20478, 2026/02) | Hierarchical Agent context architecture for complex codebases    | Codified Context is static documentation; Brain is a dynamic knowledge graph with decay and updates |

### Core Technical Differentiators

The following three technical combinations have **no direct precedent** in existing papers or open-source systems:

**1. Engineering-Specialized Knowledge Graph Schema**

```
Node types: Pitfall / Decision / Rule / ADR / Note
Edge types: PREVENTS / CAUSES / REQUIRES / BLOCKS
```

Existing systems (GraphRAG, Zep Graphiti) use generic entities and relations. Project Brain's schema is purpose-built for engineering decision knowledge; edge semantics (PREVENTS) map directly to causal reasoning, letting Agents arrive at pre-derived conclusions before a task even begins.

**2. Six-Factor Git-Grounded Decay Formula**

```
Confidence = F1(time decay) × F2(version gap) × F3(git activity) × F4(contradiction penalty) × F5(code reference) + F7(query frequency)
```

- **F2 (version gap):** Knowledge references React 16, current version is React 18 → automatic score reduction. No equivalent mechanism exists in MemOS, MemoryBank, or SAGE.
- **F3 (git activity anti-decay):** Code related to the knowledge has been committed in the last 30 days → score increase. Knowledge validity is determined by git history, not AI self-assessment.
- **F5 (code reference confirmation):** grep confirms that classes mentioned in the knowledge still exist in the codebase → score increase.

This is the design philosophy of "git history as the ground truth for knowledge validity" — unseen in existing AI memory research.

**3. Complete Pipeline: Auto-Extraction → Review Gate → Knowledge Graph → Decay Management**

```
git commit (written by Agent)
      ↓ [post-commit hook]
 KnowledgeExtractor (LLM classification)
      ↓
 KnowledgeReviewBoard (staging)
      ↓ [brain review approve]
 L3 KnowledgeGraph
      ↓ [weekly]
 DecayEngine (six-factor recalculation)
```

MemGovern has a quality gate; MemCoder has commit extraction — but no existing system completes this entire closed-loop pipeline.

### Competitive Feature Matrix

| Feature                             | Project Brain |    Mem0    |   Zep/Graphiti    | MemGPT/Letta | MemCoder | MemGovern |
| ----------------------------------- | :-----------: | :--------: | :---------------: | :----------: | :------: | :-------: |
| Engineering-specialized KG schema   |       ✓       |     ✗      |         ✗         |      ✗       |    ✗     |     ✗     |
| Multi-factor knowledge decay (6+)   |       ✓       | Single-dim |         ✗         |      ✗       |    ✗     |     ✗     |
| Version gap decay (F2)              |       ✓       |     ✗      |         ✗         |      ✗       |    ✗     |     ✗     |
| Git activity anti-decay (F3)        |       ✓       |     ✗      |         ✗         |      ✗       |    ✗     |     ✗     |
| Code reference confirmation (F5)    |       ✓       |     ✗      |         ✗         |      ✗       |    ✗     |     ✗     |
| git commit knowledge extraction     |       ✓       |     ✗      |         ✗         |      ✗       |    ✓     |     ✗     |
| Human review gate                   |     ✓ KRB     |     ✗      |         ✗         |      ✗       |    ✓     |     ✓     |
| Proactive risk nudges (NudgeEngine) |  ✓ Zero-cost  |     ✗      |         ✗         |      ✗       |    ✗     |     ✗     |
| Conditional invalidation monitoring |       ✓       |     ✗      |         ✗         |      ✗       |    ✗     |     ✗     |
| Zero external dependencies          | ✓ Pure SQLite |     ✗      |  Requires Redis   |      ✗       |    ✗     |     ✗     |
| Temporal Query                      |       ✓       |     ✗      | ✓ (more complete) |      ✗       |    ✗     |     ✗     |

---

## Known Limitations and Design Boundaries

Honestly listing the boundaries of this version is a basic form of respect for users.

| Limitation                              | Description                                                                                                     | Plan                                          |
| --------------------------------------- | --------------------------------------------------------------------------------------------------------------- | --------------------------------------------- |
| Semantic recall ~75%                    | FTS5 keyword search struggles with semantically similar but differently worded queries                          | Phase 1: vector semantic search               |
| Possible duplicate output across layers | L2 episode and L3 node may describe the same thing                                                              | Phase 4: auto-build DERIVES_FROM edges        |
| Scope must be specified manually        | Forgetting `--scope` causes knowledge to pollute the global namespace                                           | Phase 5: infer scope from directory structure |
| Cannot capture tacit knowledge          | Only records decisions that humans have consciously noticed; "goes without saying" conventions are out of reach | Design boundary — won't fix                   |

---

## Directory Structure

```
project-brain/
├── project_brain/          Core package
│   ├── brain_db.py         Unified database entry point (BrainDB)
│   ├── graph.py            L3 knowledge graph (KnowledgeGraph)
│   ├── context.py          Context assembly engine
│   ├── engine.py           ProjectBrain main engine
│   ├── extractor.py        LLM knowledge extraction
│   ├── decay_engine.py     Multi-factor knowledge decay
│   ├── consolidation.py    L1a → L3 memory consolidation
│   ├── memory_synthesizer.py  Three-layer fusion (opt-in)
│   ├── review_board.py     KRB human review committee
│   ├── nudge_engine.py     Proactive warning engine
│   ├── session_store.py    L1a working memory
│   ├── mcp_server.py       MCP Server
│   ├── api_server.py       REST API (Flask)
│   └── cli.py              CLI entry point
├── docs/
│   ├── BRAIN_MASTER.md     Master design document (single source of truth)
│   └── BRAIN_INTEGRATION.md  Integration guide
├── tests/
│   ├── unit/               Unit tests
│   ├── integration/        Integration tests
│   └── chaos/              Stress tests
└── pyproject.toml
```

---

## Installation Options

```bash
# Standard installation (includes vector semantic search)
pip install project-brain

# With MCP Server (Claude Code / Cursor)
pip install "project-brain[mcp]"

# With Anthropic SDK (AI knowledge extraction)
pip install "project-brain[anthropic]"

# Full installation
pip install "project-brain[all]"
```

**Core dependencies:** `flask`, `flask-cors`, `sqlite-vec` (vector search C extension — pre-compiled wheels available on PyPI)

**System requirements:** Python 3.10+, no external services required

### Verifying sqlite-vec Works Correctly

`pip install sqlite-vec` is only the first step. sqlite-vec requires Python to have been compiled with SQLite extension support enabled. Use `brain doctor` for a three-layer verification:

```bash
brain doctor
```

```
Vector Search Engine
────────────────────────────────────────────
✓  Layer 1  Package installed  (sqlite-vec 0.1.9)
✓  Layer 2  SQLite C extension loaded        ← This is the critical layer
✓  Layer 3  vec_distance_cosine computed correctly  (dist=0.0000)
✓  Search path  C extension accelerated  (FTS5 × 0.4 + Vector × 0.6)
```

If Layer 2 shows `✗` (common with pyenv's default Python build):

```bash
# pyenv fix: recompile Python with extension support enabled
PYTHON_CONFIGURE_OPTS='--enable-loadable-sqlite-extensions' \
  pyenv install --force $(pyenv version-name)

# Or use Homebrew Python (ships with support built in)
brew install python@3.12
```

When Layer 2 fails the system automatically falls back to pure-Python cosine similarity — fully functional but slower.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

Before filing an issue, please include:

1. Output of `brain status`
2. Python version (`python --version`)
3. Reproduction steps

For core design questions and architecture discussions, please open a Discussion.

---

## Design Documents

| Document                                               | Description                                                |
| ------------------------------------------------------ | ---------------------------------------------------------- |
| [docs/BRAIN_MASTER.md](docs/BRAIN_MASTER.md)           | Master design document: architecture, defect list, roadmap |
| [docs/BRAIN_INTEGRATION.md](docs/BRAIN_INTEGRATION.md) | Integration guide (SDK / API / MCP details)                |
| [INSTALL.md](INSTALL.md)                               | Installation and verification steps                        |

---

## License

MIT License — see [LICENSE](LICENSE) for details

---

_v0.1.0 · Project Brain · Engineering memory infrastructure for AI Agents_

_Related academic literature: CoALA (arXiv:2309.02427) · MemCoder (arXiv:2603.13258) · MemGovern (arXiv:2601.06789) · Lore (arXiv:2603.15566)_
