"""Read-only handoff selection, with explicit selection provenance."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Mapping, TYPE_CHECKING

from ..mo_core.api import Abort
from ..mo_configuration.api import Config
from .api import BASENAME_PATTERN, Handoff, load_handoff
from .cache.service import load_cached_handoff
from .api import HandoffCacheOperations, handoff_from_zip
if TYPE_CHECKING:
    from ..mo_cli.api import CliRequest


MAX_HANDOFF_SELECTIONS = 20


def parse_handoff_sequence(value: str):
    """Parse an explicit one-to-one list of ZIP selections for APL actions."""
    names = tuple(token.strip() for token in value.split(","))
    if not names or any(not name for name in names):
        raise ValueError("handoffSeq requires nonempty comma-separated ZIP selections")
    if len(names) > MAX_HANDOFF_SELECTIONS:
        raise ValueError(f"handoffSeq supports at most {MAX_HANDOFF_SELECTIONS} ZIPs")
    return names


def validate_multi_handoff_actions(actions: tuple[int, ...], selections: tuple[str, ...], mode: str):
    """Reject sequences that could apply multiple ZIPs on the base or publish too early."""
    apply_indices = [index for index, action in enumerate(actions) if action == 3]
    if not apply_indices or len(apply_indices) != len(selections):
        raise ValueError("handoffSeq must select exactly one distinct ZIP for each APL operation")
    if len(selections) == 1:
        return
    if mode != "loose":
        raise ValueError("Multiple ZIPs in one opSeq require LOOSE mode; STRICT/FORCE cannot accumulate them")
    if actions[:2] != (3, 1):
        raise ValueError("Multi-ZIP sequences must begin with APL,BRN before another APL")
    if 1 in actions[2:]:
        raise ValueError("Multi-ZIP sequences must transfer to the feature branch exactly once")
    if any(action in {5, 6, 7, 8, 9} for action in actions[:apply_indices[-1]]):
        raise ValueError("Apply all ZIPs before commit/push/PR/merge/sync in a multi-ZIP sequence")


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
    identifier: str | None, config: Config, root: Path,
    *, cache_ops: HandoffCacheOperations | None = None,
) -> HandoffSelection:
    """Identify ZIP, cached workflow, or legacy JSON without changing target state."""
    if identifier is None:
        return HandoffSelection(
            cache_ops.load(root) if cache_ops is not None else load_cached_handoff(root),
            ".apatch/params.json",
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


def resolve_handoffs(
    request: CliRequest, config: Config, root: Path, *,
    cache_ops: HandoffCacheOperations | None = None,
) -> HandoffSelection:
    """Resolve one or many handoffs before acquiring the writable workflow lock."""
    if request.handoff_seq is not None:
        if request.op_seq is None:
            raise Abort("handoffSeq requires opSeq; it cannot accompany op= or an interactive menu")
        names = resolve_sequence_zip_names(request.handoff_seq, config)
        try:
            validate_multi_handoff_actions(request.op_seq.actions, names, request.mode)
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

    if request.status_only and request.handoff is None:
        cached_path = root / ".apatch" / "params.json"
        if not cached_path.exists() and not cached_path.is_symlink():
            return HandoffSelection(None, "stored workflow", SelectionKind.CACHED_WORKFLOW)
        try:
            cached = cache_ops.load(root) if cache_ops is not None else load_cached_handoff(root)
        except Abort as exc:
            return HandoffSelection(None, "stored workflow", SelectionKind.CACHED_WORKFLOW,
                                    evidence=f"Cached handoff unavailable: {exc}")
        return HandoffSelection(cached, ".apatch/params.json", SelectionKind.CACHED_WORKFLOW)

    if (request.op_seq is not None
            and sum(action in {2, 3} for action in request.op_seq.actions) > 1):
        raise Abort("Multiple APL actions require explicit handoffSeq ZIP selections")
    return resolve_selected_handoff(request.handoff, config, root, cache_ops=cache_ops)
