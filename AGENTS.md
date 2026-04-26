# Project Brain

Project Brain is installed at `/Users/ahern/Documents/AI-tools/files/synthex-release/project-brain`.

## Memory System Instructions

At the start of every task, call the `get_context` MCP tool
with the task description, current file path, and **current working directory**
(the directory Codex is currently operating in).

Always pass `workdir` = the primary working directory of the current session.
Brain will automatically walk up from that path to find the nearest `.brain/`.

If Brain returns nudges or warnings, treat them as **hard constraints**.

When you discover any of the following, call `add_knowledge` immediately
— do not wait until the end of the task:

- A bug and the reason it happened (kind: Pitfall)
- An architectural decision and why (kind: Decision)
- A rule that must always be followed (kind: Rule)
- Something that does not work as expected (kind: Pitfall)

Always pass `workdir` to `add_knowledge` and `brain_status` as well.

Use confidence=0.9 for verified facts, 0.7 for reasonable inferences.

## Task Start Protocol

Before beginning **any** task:

1. Call `get_context` with the task description and current file path.
2. If the result contains **Pitfall** entries, read each one carefully and
   explicitly state how you will avoid that mistake before writing code.
3. If the result contains **Rule** entries, those rules are mandatory for
   this task — do not deviate from them.
4. If the result contains **Decision** entries, treat them as established
   architecture — do not reverse them without discussion.

## Task Complete Protocol

After completing **any** non-trivial task:

1. Call `complete_task` with:
   - `task_description`: one-sentence summary of what was done
   - `decisions`: list of architectural or design choices made (can be empty)
   - `lessons`: list of things learned that would help future work (can be empty)
   - `pitfalls`: list of mistakes encountered or near-misses (can be empty)
2. If a **new bug pattern** was discovered during the task, also call
   `add_knowledge(kind="Pitfall", ...)` immediately — do not rely solely on
   `complete_task` for Pitfall recording.
3. If an **important architectural decision** was made, call
   `add_knowledge(kind="Decision", ...)` as well.

## Knowledge Feedback Protocol

After a task that used knowledge retrieved from Brain:

- If a retrieved knowledge node **directly helped** complete the task correctly,
  call `report_knowledge_outcome(node_id=..., was_useful=True)`.
- If a retrieved knowledge node was **outdated, incorrect, or irrelevant**,
  call `report_knowledge_outcome(node_id=..., was_useful=False, notes="reason")`.

This feedback loop keeps confidence scores accurate and prevents stale knowledge
from surfacing in future queries.
