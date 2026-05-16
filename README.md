# DevPilot 🚀

**DevPilot** is an advanced, fully autonomous AI software engineering agent designed to run directly in your terminal. By operating inside your local environment, DevPilot can autonomously read files, write and refactor code, execute shell commands, and even delegate specialized tasks to other agents.

Unlike traditional reactive coding assistants, DevPilot is built on a rigorous **Plan → Act → Verify** cognitive architecture. It operates as a true virtual teammate—exploring your codebase contextually, formulating explicit architectural plans, making surgical edits, and running its own tests and linters to verify its work before presenting it to you.

DevPilot seamlessly integrates two powerful open protocols:
1. **Model Context Protocol (MCP)** for dynamic, universal tool discovery.
2. **Agent-to-Agent Protocol (A2A)** for peer-agent delegation and multi-agent workflows.

---

## ✨ Core Capabilities

### 🧠 Advanced Cognitive Architecture
DevPilot is designed to outperform standard coding bots by enforcing strict engineering discipline:
- **Explore First**: Never guesses file paths or structures. It actively uses tools like `ripgrep`, `fd`, and `find` to map your repository.
- **Persistent Planning**: For complex, multi-file tasks, DevPilot writes its architectural approach to a physical `.devpilot/memory.md` file, ensuring context isn't lost across sessions or massive refactors.
- **Surgical Edits**: Rather than rewriting entire files blindly, DevPilot reads files line-by-line and performs targeted block replacements, preserving your exact indentation and formatting.
- **Self-Verification**: After editing code, DevPilot automatically runs shell commands (like `pytest`, `tsc`, or `npm run build`) to ensure it didn't break the build before confirming success.

### 🖥️ Full-Screen Terminal IDE (TUI)
Powered by the `Textual` framework, DevPilot transcends the standard command-line REPL by offering a beautiful, hardware-accelerated dashboard:
- **Project Context Map**: A live-updating sidebar that tracks your workspace directory and places visual indicators (●) next to files the agent has recently read or modified.
- **Interactive Chat Log**: Buttery-smooth, streaming Markdown rendering with native background spinners that don't block the UI thread.
- **Unobtrusive Tool Traces**: Instead of flooding your screen with raw JSON, DevPilot displays clean, single-line tool execution summaries (e.g., `🔧 Used read_file(path="main.py")`).
- **Frictionless Copying**: Press `F3` at any time to instantly copy DevPilot's most recent code block or response directly to your system clipboard.

### 🔌 Multi-Provider & Local Support
DevPilot is completely model-agnostic. By simply updating your `.env` file, you can switch between:
- **Anthropic** (Claude 3.5 Sonnet, Claude 3 Opus, Claude 3 Haiku)
- **OpenAI** (GPT-4o, GPT-4-turbo)
- **Groq** (Ultra-fast open source models)
- **Local / Offline Models**: Run entirely offline and free by pointing DevPilot to your local `Ollama` instance.

### 🤖 A2A Dual-Role Architecture
DevPilot can act as both a master orchestrator and a sub-worker:
- **As an Orchestrator**: If a task requires specialized knowledge (e.g., database administration or complex DevOps), DevPilot can delegate sub-tasks to external peer agents and stream their results back into its own loop.
- **As a Worker**: Exposes a FastAPI endpoint, allowing external systems or orchestrators to assign tasks directly to your DevPilot instance.

### 🛡️ Secure by Default
Built-in **Permission Guards** automatically intercept destructive operations (like writing files or executing arbitrary bash commands). DevPilot will always pause and request explicit human confirmation before altering your system, ensuring you remain in total control.

---

## 🛠 Installation & Setup

**Requirements:** Python 3.11+

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Thijeshpraveen-V/DevPilot.git
   cd DevPilot
   ```

2. **Install dependencies:**
   It is highly recommended to use a virtual environment.
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Configure the environment:**
   Copy the example environment file and fill in your API keys.
   ```bash
   cp .env.example .env
   ```
   *Required Keys:* Add your `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`.
   *Local Ollama Setup:* Point `DEVPILOT_BASE_URL` to `http://localhost:11434/v1` and set the provider to `openai`.

4. **Configure MCP Servers (Optional):**
   Edit `mcp_servers.json` to define which external Model Context Protocol servers DevPilot should connect to on startup (e.g., GitHub integration, specialized databases).

---

## 🚀 Usage Guide

Launch the full-screen DevPilot TUI dashboard from your project directory:
```bash
devpilot
```

### TUI Hotkeys & Controls
Once inside the IDE, you have access to several global hotkeys designed to speed up your workflow:
- **`F1`**: Shrink the Project Map sidebar.
- **`F2`**: Expand the Project Map sidebar.
- **`F3`**: **Copy Last Response**. Instantly copies DevPilot's most recent output to your system clipboard (eliminating the need to manually highlight text with the mouse).
- **`Ctrl+B`**: Toggle the Project Map visibility entirely.
- **`Shift + Click/Drag`**: Standard terminal bypass to manually highlight and copy text from the UI.

### Natural Language Workflows
Simply type your request in the bottom input bar. Try prompts like:
> *"Analyze my tests directory and add a new pytest file for the MCP tool proxy."*
> *"Find where we handle database connection timeouts and increase it to 60 seconds."*
> *"Write a script to convert all PNG images in the assets folder to WEBP, and run it to verify it works."*

### CI & Automation Mode
You can run DevPilot completely headlessly for CI/CD pipelines or one-shot automation scripts:
```bash
devpilot --task "Fix the linter errors in agent/loop.py" --no-confirm
```

### Resuming Sessions
DevPilot saves your conversation history locally. If you need to stop and pick up a complex task later, simply resume the session:
```bash
devpilot --resume 20260515_151609
```

---

## 🏗 System Architecture Deep Dive

DevPilot's codebase is strictly modularized into 4 distinct layers:

1. **Interface Layer (`agent/tui/`, `agent/cli.py`)**
   Handles user interactions. The TUI leverages the `Textual` framework for asynchronous UI rendering, managing the project map, chat history, and global state without blocking the agent's reasoning loop.

2. **Orchestration Layer (`agent/loop.py`, `agent/a2a_server.py`)**
   The core brain. It manages the iterative agentic loop (Plan -> Act -> Verify), tracks token limits, manages context windows, and coordinates Agent-to-Agent (A2A) delegations. It dynamically injects the `RepoContext` into the system prompt on every iteration so the model never loses track of what files it has already read.

3. **Tool & MCP Layer (`agent/tools/`)**
   The hands of the agent. This layer manages the Tool Registry, encompassing both native Python tools (`read_file`, `run_bash`, `search_code`) and external tools proxied dynamically via the connected Model Context Protocol servers over stdio/SSE.

4. **Provider Layer (`agent/providers/`)**
   The translation layer. Normalizes responses and tool-call schemas between different LLM providers (Anthropic, OpenAI, Groq) so the Orchestration layer can operate completely model-agnostically.

---

## 🤝 Contributing

Contributions are highly encouraged! Whether you're adding support for new MCP servers, refining the TUI, or optimizing the cognitive prompt framework:
1. Ensure your code passes all linting (`ruff`, `mypy`).
2. Add corresponding tests for any new native tools.
3. Submit a descriptive Pull Request.

---
*Developed for Academic and Portfolio Use.*
