"""
agent/setup_wizard.py
──────────────────────
First-run setup wizard for DevPilot.

Runs when no API key is detected. Guides the user through:
  1. Choosing a provider (Anthropic, OpenAI, or custom compatible)
  2. Entering their API key
  3. Optionally choosing a model
  4. Saving everything to a .env file in the current directory

Completely non-interactive when running in CI (no TTY).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

console = Console()


def _prompt_secret(prompt_text: str) -> str:
    """
    Prompt for a secret (API key) showing '*' for each character typed.
    Works on Windows (CMD / PowerShell) where rich's password=True renders
    completely blank and provides no visual feedback to the user.
    Falls back to rich Prompt (password=True) on non-TTY / CI environments.
    """
    import sys
    if not sys.stdin.isatty():
        return Prompt.ask(prompt_text, password=True).strip()

    import platform
    if platform.system() == "Windows":
        import msvcrt
        console.print(f"{prompt_text}: ", end="")
        chars: list[str] = []
        while True:
            ch = msvcrt.getwch()  # read one char without echo
            if ch in ("\r", "\n"):   # Enter key
                console.print()       # move to next line
                break
            elif ch == "\x03":        # Ctrl+C
                raise KeyboardInterrupt
            elif ch in ("\x08", "\x7f"):  # Backspace
                if chars:
                    chars.pop()
                    # erase last asterisk: backspace + space + backspace
                    console.print("\b \b", end="")
            elif ch == "\x00" or ch == "\xe0":  # special key prefix — skip next byte
                msvcrt.getwch()
            else:
                chars.append(ch)
                console.print("*", end="")
        return "".join(chars).strip()
    else:
        # Unix: getpass already hides input cleanly
        import getpass
        return getpass.getpass(f"{prompt_text}: ").strip()


# ── Model lists (verified against live APIs) ──────────────────────────────────
# Last verified: May 2026

_ANTHROPIC_MODELS = [
    # Verified via GET https://api.anthropic.com/v1/models
    ("claude-opus-4-7",            "Newest — most capable Claude (latest)"),
    ("claude-opus-4-5-20251101",   "Claude Opus 4.5 — powerful & reliable"),
    ("claude-sonnet-4-5-20250929", "Claude Sonnet 4.5 — balanced speed & quality"),
    ("claude-haiku-4-5-20251001",  "Claude Haiku 4.5 — fastest, most affordable"),
]

_OPENAI_MODELS = [
    # Verified via platform.openai.com/docs/models (May 2026)
    # Note: gpt-4o, o3, o4-mini are retired as of early 2026
    ("gpt-5.5",      "Flagship — best reasoning & coding"),
    ("gpt-5.4",      "Primary model — coding & professional work"),
    ("gpt-5.4-mini", "Fast & cost-efficient"),
    ("gpt-5.4-nano", "Fastest — high-volume low-latency tasks"),
]

# OpenAI-compatible third-party providers
# (display_name, key_url, key_env_var, base_url, models)
_COMPATIBLE_PROVIDERS = {
    "1": (
        "Groq",
        "https://console.groq.com/keys",
        "GROQ_API_KEY",
        "https://api.groq.com/openai/v1",
        [
            # Verified via GET https://api.groq.com/openai/v1/models
            ("llama-3.3-70b-versatile",                "Llama 3.3 70B — best quality (131k ctx)"),
            ("meta-llama/llama-4-scout-17b-16e-instruct","Llama 4 Scout 17B — latest & fast"),
            ("qwen/qwen3-32b",                         "Qwen3 32B — strong reasoning"),
            ("llama-3.1-8b-instant",                   "Llama 3.1 8B — ultra-fast"),
            ("groq/compound",                          "Groq Compound — agentic tasks"),
        ],
    ),
    "2": (
        "Together AI",
        "https://api.together.xyz/settings/api-keys",
        "TOGETHER_API_KEY",
        "https://api.together.xyz/v1",
        [
            # Verified via Together AI docs (May 2026)
            ("meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8", "Llama 4 Maverick — best quality"),
            ("meta-llama/Llama-4-Scout-17B-16E-Instruct-FP8",     "Llama 4 Scout — fast MoE"),
            ("meta-llama/Llama-3.3-70B-Instruct-Turbo",           "Llama 3.3 70B Turbo — reliable"),
            ("meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo",     "Llama 3.1 405B — most capable"),
            ("meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",       "Llama 3.1 8B — very fast"),
        ],
    ),
    "3": (
        "Mistral AI",
        "https://console.mistral.ai/api-keys/",
        "MISTRAL_API_KEY",
        "https://api.mistral.ai/v1",
        [
            # Verified via Mistral docs — latest aliases always point to newest stable
            ("mistral-large-latest",  "Most capable Mistral model"),
            ("mistral-small-latest",  "Fast and affordable"),
            ("codestral-latest",      "Optimised for code generation"),
        ],
    ),
    "4": (
        "Ollama (local)",
        "https://ollama.com/library",
        "OLLAMA_API_KEY",   # Ollama doesn't need a real key
        "http://localhost:11434/v1",
        [
            # Run: ollama pull <model> before using
            ("qwen2.5-coder:7b",    "Qwen2.5-Coder 7B — best local coding (8GB VRAM)"),
            ("qwen2.5-coder:32b",   "Qwen2.5-Coder 32B — benchmark king (24GB VRAM)"),
            ("deepseek-coder-v2:16b","DeepSeek-Coder-V2 16B — strong coding (16GB VRAM)"),
            ("llama3.3:70b",        "Llama 3.3 70B — general purpose"),
        ],
    ),
    "5": (
        "Other (custom)",
        "",
        "",
        "",
        [],
    ),
}



# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _write_env_file(
    path: Path,
    updates: dict[str, str],
) -> None:
    """Write or update .env file preserving existing entries."""
    existing: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                existing[k.strip()] = v.strip()

    existing.update(updates)

    lines = [
        "# DevPilot configuration — generated by setup wizard",
        "# Add this file to .gitignore — never commit API keys!\n",
    ]
    for k, v in existing.items():
        lines.append(f"{k}={v}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _pick_model(models: list[tuple[str, str]], allow_custom: bool = False) -> str:
    """Show a model selection table and return the chosen model string."""
    table = Table(show_header=False, box=None, padding=(0, 2))
    for i, (name, desc) in enumerate(models, 1):
        table.add_row(
            f"[cyan]{i}[/cyan]",
            f"[bold]{name}[/bold]",
            f"[dim]{desc}[/dim]",
        )
    if allow_custom:
        table.add_row(
            f"[cyan]{len(models)+1}[/cyan]",
            "[bold]Other[/bold]",
            "[dim]Enter a custom model name[/dim]",
        )
    console.print(table)

    choices = [str(i) for i in range(1, len(models) + (2 if allow_custom else 1))]
    choice = Prompt.ask("\nModel", choices=choices, default="1")

    if allow_custom and choice == str(len(models) + 1):
        return Prompt.ask("Enter model name").strip()

    return models[int(choice) - 1][0]


# ── Main wizard ───────────────────────────────────────────────────────────────

def run_setup_wizard(env_path: Path | None = None) -> bool:
    """
    Run the interactive first-run setup wizard.
    Saves configuration to ~/.devpilot/.env so settings persist
    regardless of which directory `devpilot` is run from.
    Returns True if setup completed, False if skipped/failed.
    """
    if not _is_interactive():
        return False

    # Always save to the persistent user config directory
    user_config_dir = Path.home() / ".devpilot"
    user_config_dir.mkdir(parents=True, exist_ok=True)
    env_path = env_path or (user_config_dir / ".env")

    console.print(Panel(
        "[bold cyan]Welcome to DevPilot! 🚀[/bold cyan]\n\n"
        "No API key was found. Let's set up your configuration.\n"
        "This will create a [bold].env[/bold] file in your current directory.",
        border_style="cyan",
        expand=False,
    ))

    # ── Step 1: Choose provider ───────────────────────────────────────────────
    console.print("\n[bold]Step 1 of 3 — Choose your AI provider[/bold]\n")
    console.print("  [cyan]1[/cyan]  Anthropic      (Claude Opus 4.7, Sonnet 4.5, Haiku 4.5)")
    console.print("  [cyan]2[/cyan]  OpenAI         (GPT-5.5, GPT-5.4, GPT-5.4-mini)")
    console.print("  [cyan]3[/cyan]  Groq           (Llama 4 Scout, Llama 3.3 70B — very fast, free tier)")
    console.print("  [cyan]4[/cyan]  Together AI    (Llama 4 Maverick/Scout, Llama 3.3 70B)")
    console.print("  [cyan]5[/cyan]  Mistral AI     (Mistral Large, Codestral)")
    console.print("  [cyan]6[/cyan]  Ollama         (local models — Qwen2.5-Coder, DeepSeek, Llama)")
    console.print("  [cyan]7[/cyan]  Other          (any OpenAI-compatible endpoint)")

    choice = Prompt.ask("\nProvider", choices=["1","2","3","4","5","6","7"], default="1")

    env_updates: dict[str, str] = {}

    # ── Anthropic ─────────────────────────────────────────────────────────────
    if choice == "1":
        console.print("\n[bold]Step 2 of 3 — Enter your Anthropic API key[/bold]")
        console.print("  Get one at: [link=https://console.anthropic.com/]https://console.anthropic.com/[/link]")
        api_key = _prompt_secret("ANTHROPIC_API_KEY")
        if not api_key:
            console.print("[red]API key cannot be empty.[/red]")
            return False
        if not api_key.startswith("sk-ant-"):
            console.print("[yellow]⚠  Key doesn't look like a typical Anthropic key (sk-ant-...). Saving anyway.[/yellow]")

        console.print("\n[bold]Step 3 of 3 — Choose a model[/bold]\n")
        model = _pick_model(_ANTHROPIC_MODELS)

        env_updates = {
            "ANTHROPIC_API_KEY":  api_key,
            "DEVPILOT_PROVIDER":  "anthropic",
            "DEVPILOT_MODEL":     model,
        }

    # ── OpenAI ────────────────────────────────────────────────────────────────
    elif choice == "2":
        console.print("\n[bold]Step 2 of 3 — Enter your OpenAI API key[/bold]")
        console.print("  Get one at: [link=https://platform.openai.com/api-keys]https://platform.openai.com/api-keys[/link]")
        api_key = _prompt_secret("OPENAI_API_KEY")
        if not api_key:
            console.print("[red]API key cannot be empty.[/red]")
            return False
        if not api_key.startswith("sk-"):
            console.print("[yellow]⚠  Key doesn't look like a typical OpenAI key (sk-...). Saving anyway.[/yellow]")

        console.print("\n[bold]Step 3 of 3 — Choose a model[/bold]\n")
        model = _pick_model(_OPENAI_MODELS, allow_custom=True)

        env_updates = {
            "OPENAI_API_KEY":    api_key,
            "DEVPILOT_PROVIDER": "openai",
            "DEVPILOT_MODEL":    model,
        }

    # ── Compatible providers (Groq, Together, Mistral, Ollama) ───────────────
    elif choice in ("3", "4", "5", "6"):
        compat_key = str(int(choice) - 2)  # maps 3→1, 4→2, 5→3, 6→4
        name, key_url, key_env, base_url, models = _COMPATIBLE_PROVIDERS[compat_key]

        console.print(f"\n[bold]Step 2 of 3 — Enter your {name} API key[/bold]")

        if choice == "6":  # Ollama — no real key needed
            console.print("  [dim]Ollama runs locally — no API key required.[/dim]")
            console.print("  Make sure Ollama is running: [bold]ollama serve[/bold]")
            api_key = "ollama"
        else:
            console.print(f"  Get one at: [link={key_url}]{key_url}[/link]")
            api_key = _prompt_secret(key_env)
            if not api_key:
                console.print("[red]API key cannot be empty.[/red]")
                return False

        console.print(f"\n[bold]Step 3 of 3 — Choose a model[/bold]\n")
        model = _pick_model(models, allow_custom=True)

        env_updates = {
            key_env:                api_key,
            "OPENAI_API_KEY":       api_key,  # DevPilot reads OPENAI_API_KEY for openai provider
            "DEVPILOT_PROVIDER":    "openai",
            "DEVPILOT_MODEL":       model,
            "DEVPILOT_BASE_URL":    base_url,
        }

    # ── Custom endpoint ───────────────────────────────────────────────────────
    elif choice == "7":
        console.print("\n[bold]Step 2 of 3 — Custom OpenAI-compatible endpoint[/bold]")
        base_url  = Prompt.ask("Base URL (e.g. https://api.example.com/v1)").strip()
        api_key   = _prompt_secret("API key")
        model     = Prompt.ask("Model name (e.g. llama-3-70b)").strip()

        if not base_url or not model:
            console.print("[red]Base URL and model name are required.[/red]")
            return False

        env_updates = {
            "OPENAI_API_KEY":    api_key or "none",
            "DEVPILOT_PROVIDER": "openai",
            "DEVPILOT_MODEL":    model,
            "DEVPILOT_BASE_URL": base_url,
        }

    # ── Save .env ─────────────────────────────────────────────────────────────
    try:
        _write_env_file(env_path, env_updates)
    except OSError as e:
        console.print(f"[red]Failed to write .env file: {e}[/red]")
        return False

    # Inject into current process immediately
    for k, v in env_updates.items():
        os.environ[k] = v

    provider_display = env_updates.get("DEVPILOT_PROVIDER", "openai")
    model_display    = env_updates.get("DEVPILOT_MODEL", "")
    base_url_display = env_updates.get("DEVPILOT_BASE_URL", "")

    summary = (
        f"[bold green]✓ Setup complete![/bold green]\n\n"
        f"  Provider : [cyan]{provider_display}[/cyan]\n"
        f"  Model    : [cyan]{model_display}[/cyan]\n"
    )
    if base_url_display:
        summary += f"  Base URL : [cyan]{base_url_display}[/cyan]\n"
    summary += (
        f"  Saved to : [cyan]{env_path.resolve()}[/cyan]\n\n"
        "[dim]Add .env to your .gitignore — never commit API keys![/dim]"
    )

    console.print(Panel(summary, border_style="green", expand=False))
    return True
