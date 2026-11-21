# AgentShield (SafeguardAI)

A local-first privacy gateway for AI agents. **The AI asks, fixed rules decide.**

## The problem

AI agents read documents, emails and web pages. Attackers can hide instructions inside that content (prompt injection) and trick the agent into leaking private data such as phone numbers, bank details or API keys.

## The solution

AgentShield sits between the AI agent and your data. Every tool action passes a Python policy gateway before it runs. The model cannot approve its own actions.

| Decision | Meaning |
|---|---|
| ALLOW | Safe fields to an approved recipient |
| REVIEW | User approves once, for that exact recipient and data (expires in 5 minutes) |
| BLOCK | Restricted fields (bank, keys) and unknown recipients are never shared |
| REDACT | Private parts removed and a safe version offered |

## Features

- Policy gateway with deterministic rules (FastAPI + Python)
- Local AI agent: Qwen3 4B through Ollama, routed through the same gateway
- Approval requests tied to one recipient and one payload
- Audit trail in a local SQLite database
- Glass-style dashboard with a 3D shield
- 22 automated tests

## Demo

1. The agent reads an approved profile (only name and work email).
2. It reads an untrusted document that asks to export everything to `attacker@example.com`.
3. It tries to send the data. The gateway **blocks** it, nothing is executed, and a safe alternative is suggested.

All data is synthetic and no real message is ever sent.

## Run it (Mac)

1. Install [Ollama](https://ollama.com) and open it.
2. Download the model: `ollama pull qwen3:4b`
3. In this folder run: `./run.sh`
4. Open http://127.0.0.1:8000 and click **Run local agent**.

Run the tests with `./verify.sh`.

## Known limits

- Protects only actions routed through the gateway.
- Secret detection uses simple patterns.
- One scripted attack scenario so far.
- Qwen3 4B sometimes answers in prose on the final send step. In that case the app submits the same Python-built request to the gateway and labels it `structured_tool_call: false`. The block decision never depends on the model.
- The glass bending effect shows in Chromium browsers only.

## Roadmap

- More attack types and stronger private-data detection
- Custom rules
- Browser extension for ChatGPT, Claude and Gemini
- Mobile app for alerts and approvals
- Team policies and reports

## Credits

Glass effect inspired by [rdev/liquid-glass-react](https://github.com/rdev/liquid-glass-react).
