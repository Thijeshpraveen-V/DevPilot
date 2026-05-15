"""
agent/tools/git_ops.py
──────────────────────
Git operations tools using GitPython.
Separated into GitStatusTool and GitCommitTool for surgical operations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent.tools.base import BaseTool, ToolResult, ToolSchema

if TYPE_CHECKING:
    from agent.config import Config


class GitStatusTool(BaseTool):
    """Check git status and uncommitted changes."""

    def __init__(self, config: "Config") -> None:
        self._config = config

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="git_status",
            description="View the current git branch, staged files, modified files, untracked files, and the current working tree diff.",
            parameters={
                "type": "object",
                "properties": {},
            },
            sprint="Sprint 2",
        )

    async def execute(self) -> ToolResult:  # type: ignore[override]
        try:
            import git  # type: ignore[import]
        except ImportError:
            return ToolResult("Error: GitPython not installed. Run: pip install gitpython", is_error=True)

        workdir = self._config.workdir

        try:
            repo = git.Repo(workdir, search_parent_directories=True)
            changed = [item.a_path for item in repo.index.diff(None) if item.a_path is not None]
            staged = [item.a_path for item in repo.index.diff("HEAD") if item.a_path is not None] if repo.head.is_valid() else []
            untracked = repo.untracked_files
            branch_name = repo.active_branch.name if not repo.head.is_detached else "DETACHED HEAD"
            
            diff = repo.git.diff()
            
            lines = [
                f"Branch: {branch_name}",
                f"Staged ({len(staged)}): {', '.join(staged) or 'none'}",
                f"Modified ({len(changed)}): {', '.join(changed) or 'none'}",
                f"Untracked ({len(untracked)}): {', '.join(untracked[:10]) or 'none'}",
                "\n--- Unstaged Diff ---\n" + (diff[:8000] if diff else "No unstaged changes.")
            ]
            return ToolResult("\n".join(lines), is_error=False)

        except git.InvalidGitRepositoryError:
            return ToolResult(f"Error: {workdir} is not a git repository.", is_error=True)
        except Exception as e:
            return ToolResult(f"Git error: {e}", is_error=True)


class GitCommitTool(BaseTool):
    """Stage specific files and commit."""

    def __init__(self, config: "Config") -> None:
        self._config = config

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="git_commit",
            description=(
                "Stage specific files and commit them to the repository. "
                "You must explicitly provide the paths to stage. "
                "Returns the diff of what was actually committed."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of file paths to stage (e.g., ['agent/loop.py', 'README.md']).",
                    },
                    "message": {
                        "type": "string",
                        "description": "The commit message.",
                    },
                },
                "required": ["paths", "message"],
            },
            required=["paths", "message"],
            is_destructive=True,
            sprint="Sprint 2",
        )

    async def execute(self, paths: list[str], message: str) -> ToolResult:  # type: ignore[override]
        try:
            import git  # type: ignore[import]
        except ImportError:
            return ToolResult("Error: GitPython not installed.", is_error=True)

        workdir = self._config.workdir

        try:
            repo = git.Repo(workdir, search_parent_directories=True)
            
            if not paths:
                return ToolResult("Error: 'paths' list cannot be empty. Specify which files to commit.", is_error=True)
            if not message:
                return ToolResult("Error: 'message' is required for commit.", is_error=True)

            # Stage the specific files
            repo.index.add(paths)
            
            # Capture the staged diff before committing
            # If repo has no commits yet, diff against empty tree
            try:
                if not repo.head.is_valid():
                    # Initial commit staging diff
                    staged_diff = "Initial commit: All staged files."
                else:
                    staged_diff = repo.git.diff("--staged")
            except Exception:
                staged_diff = "(Could not compute staged diff)"

            # Commit
            commit = repo.index.commit(message)
            
            res = [
                f"✓ Committed: {commit.hexsha[:8]} — {message}",
                f"\n--- Staged Diff ---\n{staged_diff[:8000]}"
            ]
            return ToolResult("\n".join(res), is_error=False)

        except git.InvalidGitRepositoryError:
            return ToolResult(f"Error: {workdir} is not a git repository.", is_error=True)
        except Exception as e:
            return ToolResult(f"Git error: {e}", is_error=True)
