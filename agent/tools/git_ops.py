"""
agent/tools/git_ops.py
──────────────────────
Git operations tool using GitPython.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent.tools.base import BaseTool, ToolResult, ToolSchema

if TYPE_CHECKING:
    from agent.config import Config


class GitOpsTool(BaseTool):
    """Perform git operations in the working directory."""

    def __init__(self, config: "Config") -> None:
        self._config = config

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="git_ops",
            description=(
                "Perform git operations in the project. Supports: "
                "status, diff, log, add, commit, checkout, branch, push, pull, clone."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["status", "diff", "log", "add", "commit", "checkout", "branch", "push", "pull", "clone"],
                        "description": "Git action to perform.",
                    },
                    "message": {
                        "type": "string",
                        "description": "Commit message (required for 'commit').",
                    },
                    "branch": {
                        "type": "string",
                        "description": "Branch name (used for 'checkout' and 'branch' actions).",
                    },
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Files to add (for 'add'). Defaults to all '.'.",
                    },
                    "url": {
                        "type": "string",
                        "description": "Repository URL (for 'clone').",
                    },
                    "max_commits": {
                        "type": "integer",
                        "description": "Max commits to show in 'log' (default: 10).",
                        "default": 10,
                    },
                },
                "required": ["action"],
            },
            required=["action"],
            is_destructive=True,
            sprint="Sprint 2",
        )

    async def execute(  # type: ignore[override]
        self,
        action: str,
        message: str | None = None,
        branch: str | None = None,
        files: list[str] | None = None,
        url: str | None = None,
        max_commits: int = 10,
    ) -> ToolResult:
        try:
            import git  # type: ignore[import]
        except ImportError:
            return ToolResult("Error: GitPython not installed. Run: pip install gitpython", is_error=True)

        workdir = self._config.workdir

        try:
            if action == "clone":
                if not url:
                    return ToolResult("Error: 'url' is required for clone.", is_error=True)
                repo = git.Repo.clone_from(url, workdir)
                return ToolResult(f"✓ Cloned {url} into {workdir}", is_error=False)

            repo = git.Repo(workdir, search_parent_directories=True)

            if action == "status":
                changed = [item.a_path for item in repo.index.diff(None) if item.a_path is not None]
                staged = [item.a_path for item in repo.index.diff("HEAD") if item.a_path is not None] if repo.head.is_valid() else []
                untracked = repo.untracked_files
                branch_name = repo.active_branch.name if not repo.head.is_detached else "DETACHED HEAD"
                lines = [
                    f"Branch: {branch_name}",
                    f"Staged ({len(staged)}): {', '.join(staged) or 'none'}",
                    f"Modified ({len(changed)}): {', '.join(changed) or 'none'}",
                    f"Untracked ({len(untracked)}): {', '.join(untracked[:10]) or 'none'}",
                ]
                return ToolResult("\n".join(lines), is_error=False)

            elif action == "diff":
                diff = repo.git.diff()
                if not diff:
                    return ToolResult("No changes.", is_error=False)
                return ToolResult(diff[:8000], is_error=False)

            elif action == "log":
                commits = list(repo.iter_commits(max_count=max_commits))
                lines = [f"Last {len(commits)} commits:"]
                for c in commits:
                    lines.append(f"  {c.hexsha[:8]}  {c.author.name}  {c.summary}")
                return ToolResult("\n".join(lines), is_error=False)

            elif action == "add":
                targets = files or ["."]
                repo.index.add(targets)
                return ToolResult(f"✓ Staged: {', '.join(targets)}", is_error=False)

            elif action == "commit":
                if not message:
                    return ToolResult("Error: 'message' is required for commit.", is_error=True)
                commit = repo.index.commit(message)
                return ToolResult(f"✓ Committed: {commit.hexsha[:8]} — {message}", is_error=False)

            elif action == "checkout":
                if not branch:
                    return ToolResult("Error: 'branch' is required for checkout.", is_error=True)
                repo.git.checkout(branch)
                return ToolResult(f"✓ Switched to branch: {branch}", is_error=False)

            elif action == "branch":
                if branch:
                    repo.git.checkout("-b", branch)
                    return ToolResult(f"✓ Created and switched to branch: {branch}", is_error=False)
                else:
                    branches = [b.name for b in repo.branches]
                    current = repo.active_branch.name
                    lines = [f"* {b}" if b == current else f"  {b}" for b in branches]
                    return ToolResult("Branches:\n" + "\n".join(lines), is_error=False)

            elif action == "push":
                origin = repo.remote(name="origin")
                push_info = origin.push()
                return ToolResult(f"✓ Pushed to {origin.url}", is_error=False)

            elif action == "pull":
                origin = repo.remote(name="origin")
                pull_info = origin.pull()
                return ToolResult(f"✓ Pulled from {origin.url}", is_error=False)

            else:
                return ToolResult(f"Error: Unknown action '{action}'.", is_error=True)

        except git.InvalidGitRepositoryError:
            return ToolResult(
                f"Error: {workdir} is not a git repository. Run 'git init' or 'git_ops clone'.",
                is_error=True,
            )
        except Exception as e:
            return ToolResult(f"Git error: {e}", is_error=True)
