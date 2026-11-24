"""Immutable producer results and source discovery suggestions."""

from dataclasses import asdict, dataclass
import shlex


@dataclass(frozen=True)
class PreflightResult:
    """Evidence for the exact worktree inspected before external ZIP packaging."""

    repository: str
    branch: str
    head: str
    changed_paths: tuple[str, ...]
    worktree_sha256: str
    prepared: bool
    format_commands_run: int
    check_commands_run: int

    def to_dict(self) -> dict:
        return {"status": "passed", **asdict(self)}


@dataclass(frozen=True)
class PackagingResult:
    """Archive identity and the verified Git snapshot used to build it."""

    output: str
    zip_sha256: str
    size_bytes: int
    source: PreflightResult
    files: tuple[str, ...]
    deleted_paths: tuple[str, ...]

    def to_dict(self) -> dict:
        return {"status": "passed", **asdict(self)}


@dataclass(frozen=True)
class SourceCandidates:
    """Read-only explicit inclusion suggestions, never an authorization to pack."""

    repository: str
    branch: str
    head: str
    include: tuple[str, ...]
    delete: tuple[str, ...]
    untracked: tuple[str, ...]

    def to_dict(self) -> dict:
        return {"status": "candidates", **asdict(self)}

    def suggested_flags(self) -> str:
        def flag(name: str, path: str) -> str:
            if path.startswith("-"):
                return f"--{name}={shlex.quote(path)}"
            return f"--{name} {shlex.quote(path)}"

        items = [flag("include", path) for path in self.include]
        items += [flag("delete", path) for path in self.delete]
        return " ".join(items)
