"""Read-only handoff selection, with explicit selection provenance."""

import re
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Mapping

from .cli_request import CliRequest
from .model import (Abort, BASENAME_PATTERN, Config, Handoff,
                    load_handoff)
from .params_cache import load_cached_handoff
from .patch import handoff_from_zip
from .sequence import parse_handoff_sequence, validate_multi_handoff_actions


class SelectionKind(str, Enum):
    NEW_ZIP = "NEW_ZIP"
    APPLIED_ZIP = "APPLIED_ZIP"
    CACHED_WORKFLOW = "CACHED_WORKFLOW"
    LEGACY_JSON = "LEGACY_JSON"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True)
class HandoffSelection:
    handoff: Handoff | None
    source_label: str
    kind: SelectionKind
    sequence: tuple[Handoff, ...] = ()
    evidence: str | None = None
    required_next_step: str | None = None

    @property
    def zip_selected(self) -> bool:
        return self.kind in {SelectionKind.NEW_ZIP, SelectionKind.APPLIED_ZIP}

    def with_existing_record(self, record: Mapping[str, object]) -> "HandoffSelection":
        """Classify recorded ZIPs without interpreting history as mutation permission."""
        if not self.zip_selected or self.handoff is None or not record:
            return self
        recorded_digest = record.get("archive_sha256")
        if (recorded_digest is not None and self.handoff.patch_sha256 is not None
                and recorded_digest != self.handoff.patch_sha256):
            return replace(self, kind=SelectionKind.CONFLICT,
                           evidence="Recorded workflow archive digest differs from selected ZIP",
                           required_next_step="STS")
        if record.get("phase") not in {None, "new", "applying"}:
            return replace(self, kind=SelectionKind.APPLIED_ZIP,
                           evidence="An existing workflow checkpoint was located")
        return self

    def with_conflict(self, reason: str, *, next_step: str = "STS") -> "HandoffSelection":
        return replace(self, kind=SelectionKind.CONFLICT,
                       evidence=reason, required_next_step=next_step)


def resolve_handoff_path(identifier: str, downloads_dir: Path) -> Path:
    """Resolve a required handoff stem under downloads, or keep an explicit path."""
    if not identifier.strip() or identifier in {".", ".."}:
        raise Abort("A handoff JSON name is required")
    candidate = Path(identifier).expanduser()
    if not candidate.name:
        raise Abort("Handoff must name a JSON file, not a directory")
    if not candidate.name.endswith(".json"):
        candidate = candidate.with_name(candidate.name + ".json")
    if candidate.parent == Path(".") and not identifier.startswith("./"):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*\.json", candidate.name):
            raise Abort("Handoff name must be a safe JSON filename")
        return downloads_dir / candidate.name
    return candidate


def resolve_selected_handoff(
    identifier: str | None, config: Config, root: Path
) -> HandoffSelection:
    """Identify ZIP, cached workflow, or legacy JSON without changing target state."""
    if identifier is None:
        return HandoffSelection(load_cached_handoff(root), ".apatch/params.json",
                                SelectionKind.CACHED_WORKFLOW)
    if identifier.endswith(".json") or "/" in identifier or "\\" in identifier:
        path = resolve_handoff_path(identifier, config.downloads)
        return HandoffSelection(load_handoff(path), str(path), SelectionKind.LEGACY_JSON)
    name = identifier if identifier.endswith(".zip") else identifier + ".zip"
    if not BASENAME_PATTERN.fullmatch(name):
        raise Abort("Specify an ASCII-safe ZIP stem/basename or an explicit JSON handoff path")
    legacy = config.downloads / (identifier + ".json")
    if not identifier.endswith(".zip") and legacy.is_file() and not legacy.is_symlink():
        return HandoffSelection(load_handoff(legacy), str(legacy), SelectionKind.LEGACY_JSON)
    handoff = handoff_from_zip(config, root, name)
    return HandoffSelection(handoff, str(config.downloads / name), SelectionKind.NEW_ZIP,
                            evidence="Selected ZIP and embedded handoff validated",
                            required_next_step="APL")


def resolve_sequence_zip_names(raw: str, config: Config) -> tuple[str, ...]:
    """Select explicit ZIPs only from the configured download directory."""
    try:
        selections = parse_handoff_sequence(raw)
    except ValueError as exc:
        raise Abort(str(exc)) from exc
    names: list[str] = []
    for selection in selections:
        selected = Path(selection).expanduser()
        if selected.parent != Path("."):
            if selected.suffix != ".zip" or selected.parent.resolve() != config.downloads:
                raise Abort("handoffSeq ZIP paths must resolve within configured downloads_dir")
            name = selected.name
        else:
            name = selection if selection.endswith(".zip") else selection + ".zip"
        if not BASENAME_PATTERN.fullmatch(name):
            raise Abort(f"Unsafe handoffSeq ZIP filename: {selection}")
        if name in names:
            raise Abort(f"handoffSeq repeats the same ZIP: {name}")
        names.append(name)
    return tuple(names)


def resolve_handoffs(request: CliRequest, config: Config, root: Path) -> HandoffSelection:
    """Resolve one or many handoffs before acquiring the writable workflow lock."""
    if request.handoff_seq is not None:
        if request.op_seq is None:
            raise Abort("handoffSeq requires opSeq; it cannot accompany op= or an interactive menu")
        names = resolve_sequence_zip_names(request.handoff_seq, config)
        try:
            validate_multi_handoff_actions(request.op_seq, names, request.mode)
        except ValueError as exc:
            raise Abort(str(exc)) from exc
        if request.op_seq.actions[0] != 3:
            raise Abort("handoffSeq requires APL as the first operation")
        if request.handoff is not None:
            positional = resolve_sequence_zip_names(request.handoff, config)
            if positional != names[:1]:
                raise Abort("Positional ZIP selection must equal the first handoffSeq ZIP")
        handoffs = tuple(handoff_from_zip(config, root, name) for name in names)
        if len({handoff.branch for handoff in handoffs}) != 1:
            raise Abort("All handoffSeq ZIPs must target the same feature branch")
        return HandoffSelection(handoffs[0], str(config.downloads / names[0]),
                                SelectionKind.NEW_ZIP, sequence=handoffs,
                                evidence="All explicit sequence ZIPs validated",
                                required_next_step="APL")

    if (request.status_only and request.handoff is None
            and not ((root / ".apatch" / "params.json").exists()
                     or (root / ".apatch" / "params.json").is_symlink())):
        return HandoffSelection(None, "stored workflow", SelectionKind.CACHED_WORKFLOW)

    if (request.op_seq is not None
            and sum(action in {2, 3} for action in request.op_seq.actions) > 1):
        raise Abort("Multiple APL actions require explicit handoffSeq ZIP selections")
    return resolve_selected_handoff(request.handoff, config, root)
