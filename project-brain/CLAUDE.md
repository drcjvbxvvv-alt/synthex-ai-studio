- Think before acting. Read existing files before writing code.
- Be concise in output but thorough in reasoning.
- Prefer editing over rewriting whole files.
- Do not re-read files you have already read.
- Test your code before declaring done.
- No sycophantic openers or closing fluff.
- Keep solutions simple and direct.
- User instructions always override this file.

## Knowledge Summary Protocol

After completing any non-trivial task in this project, call the
`complete_task` MCP tool (project-brain MCP server) with:
- `task_description`: one-sentence summary of what was done
- `decisions`: architectural choices made (may be empty list)
- `lessons`: non-obvious things learned that help future work
- `pitfalls`: bugs hit or near-misses to avoid next time
- `workdir`: current working directory

If a retrieved knowledge node directly helped the task, also call
`report_knowledge_outcome(node_id=..., was_useful=True)`.
If a node was outdated or wrong, call it with `was_useful=False`.
