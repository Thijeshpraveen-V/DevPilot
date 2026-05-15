"""
agent/tools/doc_gen.py
──────────────────────
Documentation generation tool — Markdown + PDF output.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent.tools.base import BaseTool, ToolResult, ToolSchema
from agent.tools.fs import _safe_path

if TYPE_CHECKING:
    from agent.config import Config


class DocGenTool(BaseTool):
    """Generate Markdown and PDF documentation from provided content."""

    def __init__(self, config: "Config") -> None:
        self._config = config

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="generate_docs",
            description=(
                "Generate documentation files. Converts Markdown to a polished PDF "
                "or writes a Markdown file. Use to create README files, "
                "API docs, reports, or any structured text document."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "Markdown content to write.",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Output file path (e.g. 'docs/README.md' or 'docs/report.pdf').",
                    },
                    "format": {
                        "type": "string",
                        "enum": ["markdown", "pdf", "both"],
                        "description": "Output format: 'markdown', 'pdf', or 'both'. Default: 'markdown'.",
                        "default": "markdown",
                    },
                    "title": {
                        "type": "string",
                        "description": "Document title for PDF header.",
                    },
                },
                "required": ["content", "output_path"],
            },
            required=["content", "output_path"],
            is_destructive=True,
            sprint="Sprint 2",
        )

    async def execute(  # type: ignore[override]
        self,
        content: str,
        output_path: str,
        format: str = "markdown",
        title: str | None = None,
    ) -> ToolResult:
        results: list[str] = []

        # Write Markdown
        if format in ("markdown", "both"):
            md_path = output_path if output_path.endswith(".md") else output_path.rstrip(".pdf") + ".md"
            try:
                safe_p = _safe_path(self._config.workdir, md_path)
                safe_p.parent.mkdir(parents=True, exist_ok=True)
                safe_p.write_text(content, encoding="utf-8")
                results.append(f"✓ Markdown written to {md_path}")
            except Exception as e:
                return ToolResult(f"Error writing Markdown: {e}", is_error=True)

        # Write PDF
        if format in ("pdf", "both"):
            pdf_path = output_path if output_path.endswith(".pdf") else output_path.rstrip(".md") + ".pdf"
            try:
                html_content = _markdown_to_html(content, title=title)
                safe_pdf = _safe_path(self._config.workdir, pdf_path)
                safe_pdf.parent.mkdir(parents=True, exist_ok=True)
                _html_to_pdf(html_content, str(safe_pdf))
                results.append(f"✓ PDF written to {pdf_path}")
            except PdfGenerationError as e:
                results.append(f"⚠ PDF generation failed: {e}")
            except Exception as e:
                results.append(f"⚠ PDF error: {e}")

        if not results:
            return ToolResult("Error: No output was generated.", is_error=True)

        return ToolResult("\n".join(results), is_error=False)


class PdfGenerationError(Exception):
    pass


def _markdown_to_html(md_content: str, title: str | None = None) -> str:
    """Convert markdown to an HTML string with basic styling."""
    try:
        from markdown_it import MarkdownIt  # type: ignore[import]
        md = MarkdownIt()
        body = md.render(md_content)
    except ImportError:
        # Minimal fallback: wrap in <pre>
        body = f"<pre>{md_content}</pre>"

    doc_title = title or "Document"
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>{doc_title}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            max-width: 860px; margin: 40px auto; line-height: 1.6; color: #1a1a1a; }}
    h1, h2, h3 {{ border-bottom: 1px solid #e0e0e0; padding-bottom: 4px; }}
    code {{ background: #f4f4f4; padding: 2px 5px; border-radius: 3px; font-size: 0.9em; }}
    pre code {{ display: block; padding: 12px; overflow-x: auto; }}
    blockquote {{ border-left: 4px solid #ccc; margin: 0; padding: 8px 16px; color: #555; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
    th {{ background: #f0f0f0; }}
  </style>
</head>
<body>
{f'<h1>{doc_title}</h1>' if title else ''}
{body}
</body>
</html>"""


def _html_to_pdf(html_content: str, output_path: str) -> None:
    """Convert HTML string to PDF file using pdfkit (requires wkhtmltopdf)."""
    try:
        import pdfkit  # type: ignore[import]
        options = {
            "page-size": "A4",
            "margin-top": "20mm",
            "margin-bottom": "20mm",
            "margin-left": "20mm",
            "margin-right": "20mm",
            "encoding": "UTF-8",
            "quiet": "",
        }
        pdfkit.from_string(html_content, output_path, options=options)
    except ImportError:
        raise PdfGenerationError("pdfkit not installed. Run: pip install pdfkit")
    except OSError as e:
        if "wkhtmltopdf" in str(e).lower():
            raise PdfGenerationError(
                "wkhtmltopdf binary not found. Download from: https://wkhtmltopdf.org/downloads.html"
            )
        raise PdfGenerationError(str(e))
