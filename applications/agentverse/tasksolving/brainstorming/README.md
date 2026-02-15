# Brainstorming (MASFactory Port)

This task reproduces AgentVerse's brainstorming-style task solving. Multiple expert critics discuss a topic, a summarizer consolidates the discussion, and an evaluator scores the ideas and provides advice for the next iteration.

## Files

```
applications/agentverse/tasksolving/brainstorming/
├── run.py              # CLI entry point
├── workflow/main.py    # graph builder (`create_brainstorming_graph`)
└── README.md
```

## Run

From the repo root:

```bash
uv run python applications/agentverse/tasksolving/brainstorming/run.py \
  --task "How to improve retrieval quality in long-context RAG?" \
  --model "gpt-4o-mini" \
  --max-turn 3 \
  --max-inner-turns 0 \
  --num-critics 4
```

## Upstream Reference

- Upstream implementation: `agentverse/tasks/tasksolving/brainstorming`
- MASFactory wrapper: `applications/agentverse/components/agentverse_brainstorming_decision.py`
