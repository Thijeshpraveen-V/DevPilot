# DevPilot 🚀

**DevPilot** is an advanced, AI-powered terminal coding agent designed to execute natural-language tasks autonomously. It reads files, writes code, executes shell commands, and delegates to specialist agents through a powerful iterative agentic loop.

Inspired by tools like Claude Code and Aider, DevPilot extends the standard agent paradigm by seamlessly integrating two open protocols:
1. **Model Context Protocol (MCP)** for dynamic tool discovery.
2. **Agent-to-Agent Protocol (A2A)** for peer-agent delegation and workflows.

---

## ✨ Key Features

- **Multi-Provider Support**: Completely model-agnostic. Switch seamlessly between Anthropic (Claude), OpenAI (GPT-4), Groq, and local offline models (Ollama) by simply updating your `.env` file.
- **MCP Integration**: Connects to any conforming MCP server at startup, exposing external tools (like GitHub, file systems, etc.) to the model automatically without hardcoded logic.
- **A2A Dual-Role Architecture**: 
  - *As an Orchestrator*: Delegates specialized sub-tasks to external peer agents and streams results back into its own loop.
  - *As a Worker*: Exposes a FastAPI endpoint to accept tasks from external orchestrators.
- **Secure by Default**: Built-in permission guard blocks destructive operations (like file writes or bash commands) without explicit human confirmation (unless running in CI mode).
- **Session Persistence**: Complete conversation histories are saved locally in `.devpilot_sessions/` so you can pause, restart, and resume your workflow.
- **Rich Terminal UI**: Beautiful, syntax-highlighted diffs, collapsible tool execution traces, and color-coded status indicators powered by the `Rich` library.

---

## 🛠 Installation & Setup

**Requirements:** Python 3.11+

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Thijeshpraveen-V/DevPilot.git
   cd DevPilot
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure the environment:**
   Copy the example environment file and fill in your API keys.
   ```bash
   cp .env.example .env
   ```
   *Note: If you plan to use local models via Ollama, point `DEVPILOT_BASE_URL` to `http://localhost:11434/v1` and set the provider to `openai`.*

4. **Configure MCP Servers (Optional):**
   Edit `mcp_servers.json` to define which external Model Context Protocol servers DevPilot should connect to on startup.

---

## 🚀 Usage

Launch DevPilot in interactive mode:
```bash
devpilot
```
Once inside the REPL, simply type your natural language prompt:
> *"Can you analyze my tests directory and add a new pytest file for the MCP tool proxy?"*

### CI & Automation Mode
Run a one-shot task without human intervention:
```bash
devpilot --task "Fix the linter errors in agent/loop.py" --no-confirm
```

### Resuming Sessions
Resume a previous session using its unique ID:
```bash
devpilot --resume 20260515_151609
```

---

## 🏗 System Architecture

DevPilot follows a clean 4-layer architecture:
1. **Interface Layer**: Handles the terminal REPL, Rich output rendering, and the FastAPI A2A Task Receiver endpoint.
2. **Orchestration Layer**: Manages the agentic loop, token context windows, session history, and A2A client delegations.
3. **MCP Tool Layer**: Manages the tool registry, executing Python-native tools or proxying requests to connected MCP servers over stdio/SSE.
4. **Provider Layer**: Normalizes Anthropic and OpenAI API responses into a common agent block format.

## 🤝 Contributing
Contributions are welcome! Please ensure that any new features are thoroughly unit-tested (`pytest`) and linted (`ruff`, `mypy`) before submitting a Pull Request.

---
*Developed for Academic and Portfolio Use.*
