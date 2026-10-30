"""Parse and validate the historical apatch CLI without Git or filesystem writes."""

import argparse
import sys
from dataclasses import dataclass
from typing import Sequence

from .core.actions import ACTION_CODES, action_number
from .model import Abort, BASENAME_PATTERN, BRANCH_PATTERN
from .sequence import OperationSequence


MACRO_OPERATIONS = frozenset({"APPLY_PATCH", "APPLY_PATCH_CHECK", "MERGE", "RUN_ALL"})


@dataclass(frozen=True)
class CliRequest:
    """Validated syntax and immutable user intent, before repository resolution."""

    handoff: str | None
    mode: str
    op: str | None
    op_seq: OperationSequence | None
    info: str | None
    handoff_seq: str | None
    followup: bool
    patch: str | None
    verify_remote: bool
    skip_approves: bool
    normalized_arguments: tuple[str, ...]
    goal: str | None = None
    intent: str | None = None
    plan_only: bool = False
    feature_branch: str | None = None

    @property
    def audit_only(self) -> bool:
        return self.op in {"AUD", "11"} or (
            self.op_seq is not None and self.op_seq.actions == (11,))

    @property
    def status_only(self) -> bool:
        return self.op in {"STS", "10"} or (
            self.op_seq is not None and self.op_seq.actions == (10,))

    def with_action(self, code: str) -> "CliRequest":
        """Resolve an interactive menu choice without mutating original intent."""
        from dataclasses import replace

        return replace(self, op=code)


def parse_boolean(value: str) -> bool:
    normalized = value.lower()
    if normalized not in {"true", "false"}:
        raise argparse.ArgumentTypeError("expected true or false")
    return normalized == "true"


def normalize_arguments(arguments: Sequence[str]) -> list[str]:
    """Support key=value spellings without altering positional handoff paths."""
    aliases = {
        "op=": "--op=", "opSeq=": "--op-seq=", "handoffSeq=": "--handoff-seq=",
        "followup=": "--followup=", "patch=": "--patch=",
        "skipApproves=": "--skip-approves=", "info=": "--info=",
        "verifyRemote=": "--verify-remote=",
        "goal=": "--goal=", "intent=": "--intent=",
        "planOnly=": "--plan-only=",
        "featureBranch=": "--feature-branch=",
    }
    normalized: list[str] = []
    for argument in arguments:
        replacement = next((flag + argument[len(alias):]
                            for alias, flag in aliases.items()
                            if argument.startswith(alias)), None)
        normalized.append(replacement if replacement is not None else argument)
    return normalized


def parse_operation(value: str) -> str:
    if value.upper() in MACRO_OPERATIONS:
        return value.upper()
    try:
        action_number(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return value.upper()


def parse_operation_sequence(value: str) -> OperationSequence:
    try:
        return OperationSequence.parse(value, allow_multiple_apl=True)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=("Manage project patches. LOOSE is the default mode; STRICT enforces "
                     "workflow phases; FORCE recovers from manual changes."),
        epilog=("Examples:\n"
                "  apatch.sh apatch-PATCH-2026-10-24-00-42-example op=APL skipApproves=true\n"
                "  apatch.sh apatch-PATCH-2026-10-24-00-42-example op=3\n"
                "  apatch.sh op=BRN\n"
                "  apatch.sh op=BRN featureBranch=feature/new-name skipApproves=true\n"
                "  apatch.sh op=CHK\n"
                "  apatch.sh op=FMT\n"
                "  apatch.sh some-new-zip opSeq=APL,BRN,FMT,CHK,CMT,PSH,PR,MRG,SYN,STS skipApproves=true\n"
                "  apatch.sh apatch-PATCH-2026-10-24-00-42-example opSeq=APL,BRN,CHK,CMT,PSH skipApproves=true\n"
                "  apatch.sh opSeq=APL,BRN,APL,CHK,CMT handoffSeq=first.zip,second.zip skipApproves=true\n"
                "  apatch.sh repair-patch followup=true opSeq=APL,CHK,CMT skipApproves=true\n"
                "  apatch.sh op=STS\n"
                "  apatch.sh some-new-zip goal=CHECKED planOnly=true\n"
                "  apatch.sh some-new-zip goal=COMMITTED skipApproves=true\n"
                "  apatch.sh goal=PR_CREATED planOnly=true\n"
                "  apatch.sh goal=MERGED skipApproves=true\n"
                "  apatch.sh some-new-zip op=APPLY_PATCH skipApproves=true\n"
                "  apatch.sh some-new-zip op=APPLY_PATCH_CHECK skipApproves=true\n"
                "  apatch.sh op=MERGE skipApproves=true\n"
                "  apatch.sh some-new-zip op=RUN_ALL skipApproves=true\n"
                "  apatch.sh op=AUD\n"
                "  apatch.sh op=11 verifyRemote=true\n"
                "  apatch.sh info=PROGRESS\n"
                "  apatch.sh strict op=CHK\n"
                "  apatch.sh force op=CMT\n"
                "  apatch.sh /path/legacy.json op=STS\n"
                "Action codes: " + ", ".join(f"{i}={code}" for i, code in enumerate(ACTION_CODES)) + "\n"
                "Select an exact ZIP stem for initial APL, or omit it for cached continuation. "
                "Explicit legacy .json paths remain supported. "
                "Without op=NUMBER, op=CODE, op=MACRO, or opSeq=CODE,CODE, "
                "the action menu is displayed. "
                "skipApproves defaults to false and only skips confirmation prompts; "
                "Git/archive safety checks remain active."),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("handoff", nargs="?", metavar="ZIP_STEM|PATH.json",
                        help="ZIP stem/basename for new APL, legacy JSON, or omit to use .apatch/params.json")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--loose", action="store_const", const="loose", dest="mode",
                       help="LOOSE (default): manual edits, shared branches, separate commit and push")
    modes.add_argument("--strict", action="store_const", const="strict", dest="mode",
                       help="STRICT: enforce workflow phases and the expected Git state")
    modes.add_argument("--force", action="store_const", const="force", dest="mode",
                       help="FORCE: reconcile manual Git operations without skipping safety checks")
    parser.set_defaults(mode="loose")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--op", type=parse_operation, metavar="NUMBER|CODE|MACRO",
                         help="Run one action (0-12, APL/STS/AUD/FMT) or a named workflow macro")
    actions.add_argument("--op-seq", "--opSeq", type=parse_operation_sequence,
                         metavar="CODE,CODE,...",
                         help="Run sequential actions; stop after any error or no-op; pair with skipApproves=true for unattended use")
    actions.add_argument("--info", choices=("PROGRESS",), metavar="PROGRESS",
                         help="Read-only global progress overview; no handoff or Git repository required")
    actions.add_argument("--goal", choices=("CHECKED", "COMMITTED", "PUSHED",
                                             "PR_CREATED", "MERGED"),
                         metavar="{CHECKED,COMMITTED,PUSHED,PR_CREATED,MERGED}",
                         help="Plan a guarded LOOSE workflow, including explicit remote publication")
    parser.add_argument("--intent", choices=("auto", "new", "continue"),
                        metavar="{auto,new,continue}",
                        help="Goal-only session selection (default: auto)")
    parser.add_argument("--plan-only", "--planOnly", type=parse_boolean,
                        default=False, metavar="{true,false}",
                        help="Show a read-only local goal plan; no state, refs or cache writes")
    parser.add_argument("--handoff-seq", "--handoffSeq", metavar="ZIP1,ZIP2,...",
                        help="Explicit ZIP per APL in opSeq; multi-ZIP accumulation requires LOOSE")
    parser.add_argument("--followup", type=parse_boolean, default=False, metavar="{true,false}",
                        help="Explicitly apply a new ZIP to a matching unfinished LOOSE feature branch")
    parser.add_argument("--feature-branch", "--featureBranch", metavar="feature/NAME",
                        help="Reassign a pending, already applied ZIP to a new feature branch during BRN")
    parser.add_argument("--patch", metavar="NAME.zip",
                        help="Filter read-only STS by ZIP basename")
    parser.add_argument("--verify-remote", type=parse_boolean, default=False,
                        metavar="{true,false}",
                        help="Opt into bounded GitHub reads during 11 [AUD] (default: false)")
    parser.add_argument("--skip-approves", "--skipApproves", type=parse_boolean,
                        default=False, metavar="{true,false}",
                        help="Skip interactive confirmations (default: false); does not bypass safety checks")
    return parser


def parse_request(argv: Sequence[str] | None = None) -> CliRequest:
    normalized = normalize_arguments(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(normalized)
    return CliRequest(
        handoff=args.handoff, mode=args.mode, op=args.op, op_seq=args.op_seq,
        info=args.info, handoff_seq=args.handoff_seq, followup=args.followup,
        patch=args.patch, verify_remote=args.verify_remote,
        skip_approves=args.skip_approves, normalized_arguments=tuple(normalized),
        goal=args.goal, intent=args.intent, plan_only=args.plan_only,
        feature_branch=args.feature_branch)


def validate_progress_request(request: CliRequest) -> None:
    """Keep global read-only progress free from lifecycle intent."""
    lifecycle_flags = {"--loose", "--strict", "--force", "--skip-approves",
                       "--followup", "--verify-remote", "--intent", "--plan-only",
                       "--feature-branch"}
    if (request.handoff is not None or request.handoff_seq is not None
            or request.patch is not None
            or any(token.split("=", 1)[0] in lifecycle_flags
                   for token in request.normalized_arguments)):
        raise Abort("info=PROGRESS cannot be combined with a handoff, operation, or lifecycle options")


def validate_repository_request(request: CliRequest) -> None:
    """Validate option combinations without touching Git or persisted state."""
    if request.feature_branch is not None:
        target = request.feature_branch
        if (not BRANCH_PATTERN.fullmatch(target) or ".." in target
                or target.endswith("/") or target.endswith(".lock")):
            raise Abort("featureBranch must be a valid feature/NAME Git branch")
        if (request.mode == "force" or request.handoff_seq is not None
                or request.followup or request.goal is not None
                or request.op in MACRO_OPERATIONS
                or not ((request.op in {"BRN", "1"}) or
                        (request.op_seq is not None and request.op_seq.actions[0] == 1))):
            raise Abort("featureBranch is only supported with op=BRN or opSeq starting with BRN "
                        "in LOOSE/STRICT (no FORCE, goal, macro or new ZIP application)")
    if request.op in MACRO_OPERATIONS and (
            request.handoff_seq is not None or request.followup
            or request.patch is not None or request.verify_remote):
        raise Abort("Macros cannot be combined with handoffSeq, followup, patch or verifyRemote")
    if request.goal is not None:
        if request.mode != "loose":
            raise Abort("goal requires LOOSE mode; use explicit op/opSeq in STRICT or FORCE")
        if (request.handoff_seq is not None or request.followup
                or request.patch is not None or request.verify_remote):
            raise Abort("goal cannot be combined with handoffSeq, followup, patch or verifyRemote")
        if request.handoff is not None and request.handoff.endswith(".json"):
            raise Abort("goal requires a self-contained ZIP, not legacy JSON")
    elif request.intent is not None or request.plan_only:
        raise Abort("intent and planOnly require goal")
    if request.patch is not None and not BASENAME_PATTERN.fullmatch(request.patch):
        raise Abort("--patch must be an ASCII-safe ZIP basename")
    if request.verify_remote and not request.audit_only:
        raise Abort("verifyRemote=true is only supported by op=AUD or opSeq=AUD")
    if request.op_seq is not None and 11 in request.op_seq.actions and not request.audit_only:
        raise Abort("AUD must run separately; use op=AUD or opSeq=AUD")
    if request.audit_only and (request.handoff is not None
                               or request.handoff_seq is not None
                               or request.patch is not None or request.followup):
        raise Abort("AUD examines the entire repository; omit handoff, handoffSeq, patch and followup")
    if request.patch is not None and not request.status_only:
        raise Abort("--patch is only supported for op=STS or opSeq=STS")
    if request.followup:
        if request.mode != "loose":
            raise Abort("followup=true requires LOOSE mode")
        if request.handoff_seq is not None:
            raise Abort("followup=true is separate from handoffSeq; select only the new ZIP")
        if (request.handoff is None or
                not ((request.op is not None and action_number(request.op) == 3) or
                     (request.op_seq is not None and request.op_seq.actions[0] == 3))):
            raise Abort("followup=true is only for applying a new ZIP: provide the ZIP "
                        "and start with APL. To resume an already applied patch, use "
                        "opSeq=CHK,STS without the ZIP or followup=true")
