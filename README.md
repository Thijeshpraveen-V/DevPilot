# DevPilot 🚀

[![PyPI](https://img.shields.io/pypi/v/devpilot-agentic-cli)](https://pypi.org/project/devpilot-agentic-cli/)
[![Python](https://img.shields.io/pypi/pyversions/devpilot-agentic-cli)](https://pypi.org/project/devpilot-agentic-cli/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**An autonomous AI coding agent for your terminal.** DevPilot gives Claude, GPT-4o, Groq, Mistral, or any local model a full suite of tools — file read/write, bash execution, code search, git, MCP, and more — orchestrated into a self-healing agentic loop inside a rich Textual TUI.

```
┌─ DevPilot ──────────────────────────────────────────────────────┐
│  ✦ claude-opus-4-5  │  agent/tools/fs.py  │  iteration 2/50    │
├─────────────────────────────────────────────────────────────────┤
│  You › Add input validation to the write_file tool              │
│                                                                 │
│  ● Calling read_file   agent/tools/fs.py                        │
│  ● Calling edit_file   agent/tools/fs.py                        │
│    ✓ Edited agent/tools/fs.py successfully.                     │
│                                                                 │
│  Done — added a size cap and path-escape guard. The diff is     │
│  above. Want me to run the tests?                               │
└─────────────────────────────────────────────────────────────────┘
```

---

## Features

| Category | Capability |
|---|---|
| **File ops** | `read_file`, `write_file`, `edit_file` (surgical replace), `list_files` |
| **Shell** | `run_bash` with timeout, blocked-command guard, and auto-heal loop |
| **Code search** | Regex `search_code` |
| **Pre-flight linting** | Syntax-checks Python (`ast.parse`) and JS/TS (`node --check`) before writing |
| **Git** | `git_status`, `git_commit` with surgical file staging |
| **Documentation** | `doc_gen` (markdown), `diagram` (Mermaid) |
| **Web search** | `web_search` via Tavily (optional) |
| **MCP** | Connect any MCP server via `mcp_servers.json` |
| **A2A** | Agent-to-agent task delegation over HTTP |
| **Providers** | Anthropic, OpenAI, Groq, Together AI, Mistral, Ollama, any OpenAI-compatible endpoint |

---

## Quickstart

**Requires Python ≥ 3.11.**

```bash
pip install devpilot-agentic-cli
devpilot
```

That's it. On first run DevPilot launches a setup wizard — pick your provider, enter your API key, choose a model. It saves everything to a `.env` file and opens the TUI. Every subsequent run starts immediately.

### Optional Features

**PDF Documentation Generation**
Enable the `generate_docs` tool to export PDFs:
```bash
pip install devpilot-agentic-cli[pdf]
```
*Note: You also need to install the [wkhtmltopdf](https://wkhtmltopdf.org/downloads.html) system binary.*

---

## Providers

DevPilot works with any of these out of the box — the setup wizard walks you through each one:

| Provider | Models | Get API key |
|---|---|---|
| **Anthropic** | claude-opus-4-5, claude-sonnet-4-5, claude-haiku-4-5 | [console.anthropic.com](https://console.anthropic.com/) |
| **OpenAI** | gpt-4o, gpt-4o-mini, o3, o4-mini | [platform.openai.com](https://platform.openai.com/api-keys) |
| **Groq** | llama-3.3-70b, mixtral-8x7b, gemma2-9b | [console.groq.com](https://console.groq.com/keys) |
| **Together AI** | Llama 3, Mixtral, and more | [api.together.xyz](https://api.together.xyz/settings/api-keys) |
| **Mistral AI** | mistral-large, codestral | [console.mistral.ai](https://console.mistral.ai/api-keys/) |
| **Ollama** | Any local model — no API key needed | [ollama.com](https://ollama.com/library) |
| **Other** | Any OpenAI-compatible endpoint | — |

---

## Configuration

All settings live in a `.env` file in your project directory. The setup wizard creates this on first run. You can edit it manually anytime — or re-run the wizard with `devpilot --setup`.

### Full settings reference

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | API key for Anthropic provider |
| `OPENAI_API_KEY` | — | API key for OpenAI / Groq / Together / Mistral / Ollama |
| `DEVPILOT_PROVIDER` | `anthropic` | `anthropic` or `openai` |
| `DEVPILOT_MODEL` | `claude-opus-4-5` | Model name |
| `DEVPILOT_BASE_URL` | — | Custom endpoint, e.g. `http://localhost:11434/v1` for Ollama |
| `DEVPILOT_NO_CONFIRM` | `false` | Skip confirmation prompts (useful for CI) |
| `DEVPILOT_MAX_ITERATIONS` | `50` | Max tool-use iterations before loop aborts |
| `DEVPILOT_WORKDIR` | `cwd` | Root directory for file operations |
| `DEVPILOT_SESSIONS_DIR` | `.devpilot_sessions` | Where session JSON files are saved |
| `DEVPILOT_THINKING` | `false` | Enable extended thinking (Claude only) |
| `DEVPILOT_THINKING_BUDGET` | `10000` | Token budget for extended thinking |

### Override priority

```
CLI flags  →  env vars  →  .env file  →  defaults
```

Per-run override example:
```bash
DEVPILOT_MODEL=claude-haiku-4-5-20251101 devpilot --task "fix typos"
```

---

## CLI Reference

```
devpilot [OPTIONS]

Options:
  --provider {anthropic,openai}   Model provider
  --model MODEL                   Model name
  --base-url URL                  OpenAI-compatible base URL (e.g. Ollama)
  --no-confirm                    Skip confirmation prompts
  --thinking                      Enable extended thinking (Claude only)
  --thinking-budget N             Token budget for extended thinking (default: 10000)
  --workdir PATH                  Working directory for file operations
  --task TASK                     Run a single task and exit (CI mode)
  --resume SESSION_ID             Resume a previous session
  --a2a-port PORT                 A2A server port (default: 8000)
  --no-a2a                        Disable A2A server
  --no-web-search                 Disable Tavily web search
  --setup                         Re-run the setup wizard
```

### CI / single-task mode

```bash
devpilot --task "Run the test suite and fix any failures" --no-confirm
```

---

## Using Ollama (Local Models)

```bash
# Pull and serve a model
ollama pull qwen2.5-coder:7b
ollama serve

# Run devpilot and pick Ollama in the setup wizard
devpilot --setup
```

Or set env vars directly:
```bash
DEVPILOT_PROVIDER=openai \
DEVPILOT_BASE_URL=http://localhost:11434/v1 \
DEVPILOT_MODEL=qwen2.5-coder:7b \
devpilot
```

---

## MCP Integration

DevPilot connects to any [Model Context Protocol](https://modelcontextprotocol.io/) server. Edit `mcp_servers.json` in your project root:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]
    }
  }
}
```

Tools from connected MCP servers are automatically available to the agent on startup.

---

## Architecture

```
agent/
├── cli.py                Entry point — args, setup wizard, wires everything
├── setup_wizard.py       First-run interactive configuration wizard
├── loop.py               Core agentic loop (plan → act → verify → heal)
├── config.py             Config dataclass — all settings from env vars
├── context.py            RepoContext — file awareness, AST project map
├── history.py            Conversation history + smart context pruning
├── providers/
│   ├── anthropic_provider.py
│   ├── openai_provider.py
│   ├── system_prompt.py  PLAN→ACT→VERIFY prompt, platform-aware shell rules
│   └── factory.py
├── tools/
│   ├── fs.py             read_file, write_file (pre-flight lint), edit_file, list_files
│   ├── shell.py          run_bash
│   ├── search_code.py    regex search
│   ├── git_ops.py        git_status, git_commit
│   ├── doc_gen.py        doc_gen
│   ├── diagram.py        diagram (Mermaid)
│   ├── web_search.py     web_search (Tavily)
│   ├── a2a.py            A2A delegation
│   └── registry.py       ToolRegistry + PermissionGuard
└── tui/
    └── app.py            Textual TUI — chat log, project map, tool drawer
```

---

## Running Tests

```bash
pip install devpilot-agentic-cli[dev]
pytest
```

48 tests — unit tests for every tool plus end-to-end integration tests with a mocked provider.

---

## Development / Contributing

```bash
git clone https://github.com/Thijeshpraveen-V/DevPilot
cd DevPilot
pip install -e ".[dev]"
devpilot --setup
```

PR checklist:
- `pytest` passes (48 tests, 0 failures)
- No new hard dependencies without discussion
- New tools follow the `BaseTool` pattern in `agent/tools/base.py`

---

## License

MIT © Thijesh Praveen V
