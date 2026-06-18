# AI Multi-Model Conversations

An engine where two or more AI agents hold a structured, multi-turn conversation toward
a goal — planning, collaborating, and producing artifacts (stories, reports, plans).
Every run is fully logged and replayable.

## Features

- **Multi-agent loop** — agents take turns with distinct system prompts and a shared
  master plan, driven by a local LLM (Ollama).
- **Session logging** — each run writes a timestamped folder under `sessions/` with both
  agents' prompts, the full conversation log, and a generated `final_report.html`.
- **Self-evolving prompts** — system prompts are versioned to a history file so they can
  be refined across runs.
- **Variants** — interactive choose-your-own-adventure (`cyoa.py`) and a multi-agent
  "agora" simulator are included.

## Stack

- Python, Ollama for local inference, JSON-based session/persona config

## Run

```bash
pip install ollama
python main.py
```
