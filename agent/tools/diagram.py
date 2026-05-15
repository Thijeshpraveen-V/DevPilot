"""
agent/tools/diagram.py
──────────────────────
Mermaid diagram generation tool.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent.tools.base import BaseTool, ToolResult, ToolSchema
from agent.tools.fs import _safe_path

if TYPE_CHECKING:
    from agent.config import Config


_MERMAID_TEMPLATE = """flowchart TD
    A[Start] --> B[Process]
    B --> C[End]
"""


class DiagramTool(BaseTool):
    """Generate Mermaid diagrams and save them as SVG or PNG files."""

    def __init__(self, config: "Config") -> None:
        self._config = config

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="generate_diagram",
            description=(
                "Generate a diagram from Mermaid syntax. "
                "Saves as SVG (default) or PNG using mermaid-cli (mmdc). "
                "Also writes the source .mmd file. "
                "Use for flowcharts, sequence diagrams, ER diagrams, class diagrams, etc. "
                "Mermaid docs: https://mermaid.js.org/"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "mermaid_code": {
                        "type": "string",
                        "description": "Valid Mermaid diagram definition.",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Output file path without extension (e.g. 'docs/architecture').",
                    },
                    "format": {
                        "type": "string",
                        "enum": ["svg", "png", "mmd"],
                        "description": "Output format. 'mmd' saves source only. Default: svg.",
                        "default": "svg",
                    },
                    "theme": {
                        "type": "string",
                        "enum": ["default", "dark", "neutral", "forest"],
                        "description": "Mermaid theme. Default: default.",
                        "default": "default",
                    },
                },
                "required": ["mermaid_code", "output_path"],
            },
            required=["mermaid_code", "output_path"],
            is_destructive=True,
            sprint="Sprint 2",
        )

    async def execute(  # type: ignore[override]
        self,
        mermaid_code: str,
        output_path: str,
        format: str = "svg",
        theme: str = "default",
    ) -> ToolResult:
        results: list[str] = []

        # Always write the .mmd source file
        mmd_path = _safe_path(self._config.workdir, output_path + ".mmd")
        try:
            mmd_path.parent.mkdir(parents=True, exist_ok=True)
            mmd_path.write_text(mermaid_code, encoding="utf-8")
            results.append(f"✓ Mermaid source written to {output_path}.mmd")
        except Exception as e:
            return ToolResult(f"Error writing .mmd file: {e}", is_error=True)

        if format == "mmd":
            return ToolResult("\n".join(results), is_error=False)

        # Try to render via mmdc (mermaid-cli)
        output_file = _safe_path(self._config.workdir, f"{output_path}.{format}")
        try:
            proc = subprocess.run(
                [
                    "mmdc",
                    "-i", str(mmd_path),
                    "-o", str(output_file),
                    "-t", theme,
                    "--backgroundColor", "transparent",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode == 0:
                results.append(f"✓ Diagram rendered to {output_path}.{format}")
            else:
                err = proc.stderr.strip() or proc.stdout.strip()
                results.append(
                    f"⚠ mmdc rendering failed: {err}\n"
                    f"  The .mmd source file was saved — render it manually with:\n"
                    f"  npx @mermaid-js/mermaid-cli -i {output_path}.mmd -o {output_path}.{format}"
                )
        except FileNotFoundError:
            results.append(
                f"⚠ mmdc (mermaid-cli) not found. The .mmd source was saved.\n"
                f"  Install with: npm install -g @mermaid-js/mermaid-cli\n"
                f"  Then render: mmdc -i {output_path}.mmd -o {output_path}.{format}"
            )
        except subprocess.TimeoutExpired:
            results.append(f"⚠ mmdc timed out after 30s. The .mmd source was saved.")
        except Exception as e:
            results.append(f"⚠ Rendering error: {e}. The .mmd source was saved.")

        return ToolResult("\n".join(results), is_error=False)
