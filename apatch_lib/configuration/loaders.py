"""Bounded global and project configuration loading with unchanged policy."""

import configparser
import re
import shlex
from dataclasses import replace
from pathlib import Path

from ..core.api import Abort
from ..review.api import ReviewProvider, ScannerPolicy
from .models import Config
from .validators import (validate_base_branch, validate_log_subdirectory,
                         validate_runtime_filename)


def load_config(script_dir: Path) -> Config:
    parser = configparser.ConfigParser(interpolation=None)
    config_path = script_dir / "apatch.conf"
    try:
        loaded = parser.read(config_path, encoding="utf-8")
    except configparser.Error as exc:
        raise Abort(f"Invalid global configuration: {exc}") from exc
    if loaded != [str(config_path)]:
        raise Abort(f"Missing configuration: {config_path}")
    section = parser["apatch"]
    state = validate_runtime_filename(section.get("state_file", "apply_patch.state.json"))
    log_directory = validate_log_subdirectory(section.get("log_directory", "logs"))
    applied_patches = validate_runtime_filename(
        section.get("applied_patches_file", "applied_patches.txt"))
    remote = section.get("remote", "origin")
    base = validate_base_branch(section.get("base_branch", "main"), source="global")
    method = section.get("merge_method", "merge")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", remote):
        raise Abort("Invalid remote")
    if method not in {"merge", "squash", "rebase"}:
        raise Abort("merge_method must be merge, squash or rebase")
    try:
        github_timeout_seconds = section.getint("github_timeout_seconds", 30)
    except ValueError as exc:
        raise Abort("github_timeout_seconds must be an integer from 5 to 300") from exc
    if not 5 <= github_timeout_seconds <= 300:
        raise Abort("github_timeout_seconds must be an integer from 5 to 300")
    try:
        github_ci_wait_seconds = section.getint("github_ci_wait_seconds", 300)
    except ValueError as exc:
        raise Abort("github_ci_wait_seconds must be an integer from 0 to 1800") from exc
    if not 0 <= github_ci_wait_seconds <= 1800:
        raise Abort("github_ci_wait_seconds must be an integer from 0 to 1800")
    try:
        check_timeout_seconds = section.getint("check_timeout_seconds", 900)
    except ValueError as exc:
        raise Abort("check_timeout_seconds must be an integer from 1 to 3600") from exc
    if not 1 <= check_timeout_seconds <= 3600:
        raise Abort("check_timeout_seconds must be an integer from 1 to 3600")
    try:
        check_idle_timeout_seconds = section.getint("check_idle_timeout_seconds", 30)
    except ValueError as exc:
        raise Abort("check_idle_timeout_seconds must be an integer from 1 to 3600") from exc
    if not 1 <= check_idle_timeout_seconds <= 3600:
        raise Abort("check_idle_timeout_seconds must be an integer from 1 to 3600")
    progress_limits = (("progress_global_limit", 8, 100),
                       ("progress_project_limit", 3, 50))
    validated_limits = {}
    for name, default, maximum in progress_limits:
        try:
            value = section.getint(name, default)
        except ValueError as exc:
            raise Abort(f"{name} must be an integer from 1 to {maximum}") from exc
        if not 1 <= value <= maximum:
            raise Abort(f"{name} must be an integer from 1 to {maximum}")
        validated_limits[name] = value
    return Config(
        downloads=Path(section.get("downloads_dir", "~/Downloads")).expanduser().resolve(),
        state_path=state,
        log_directory=log_directory,
        applied_patches_path=applied_patches,
        remote=remote,
        base=base,
        checks=(),
        require_approval=section.getboolean("require_review_approval", True),
        require_checks=section.getboolean("require_required_checks", True),
        merge_method=method,
        max_bytes=section.getint("max_uncompressed_patch_bytes", 52428800),
        require_patch_feature_branch=section.getboolean("require_patch_feature_branch", False),
        github_timeout_seconds=github_timeout_seconds,
        github_ci_wait_seconds=github_ci_wait_seconds,
        check_timeout_seconds=check_timeout_seconds,
        check_idle_timeout_seconds=check_idle_timeout_seconds,
        **validated_limits,
    )


def load_project_config(root: Path, global_config: Config) -> Config:
    config_dir = root / ".apatch"
    config_path = config_dir / "config.yaml"
    if config_dir.is_symlink() or config_path.is_symlink():
        raise Abort(f"Project config must not be a symlink: {config_path}")
    if not config_path.is_file():
        raise Abort(f"Missing project checks config: {config_path}")
    try:
        if config_path.stat().st_size > 65536:
            raise Abort("Project checks config exceeds 64 KiB")
        import yaml
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except ImportError as exc:
        raise Abort("PyYAML is required; install apatch/requirements.txt") from exc
    except (OSError, UnicodeError) as exc:
        raise Abort(f"Cannot read project checks config: {exc}") from exc
    except yaml.YAMLError as exc:
        raise Abort(f"Invalid project checks YAML: {exc}") from exc

    required = {"schema_version", "checks"}
    allowed = required | {"log_directory", "state_file", "applied_patches_file", "base_branch",
                          "require_review_approval", "require_required_checks", "check_timeout_seconds",
                          "check_idle_timeout_seconds", "prepare_checks", "check_worktree_policy",
                          "format_commands", "github_ci_wait_seconds", "reviewers",
                          "review_required", "review_timeout_seconds", "review_max_bytes",
                          "review_artifacts_enabled", "review_artifact_max_bytes",
                          "review_context_max_bytes", "review_context_external_consent",
                          "review_context_include_messages", "review_context_include_diff",
                          "review_retention_enabled", "review_retention_max_runs",
                          "review_retention_max_bytes", "review_retention_max_age_days"}
    if not isinstance(data, dict) or not required <= set(data) or set(data) - allowed:
        raise Abort("Project config must contain schema_version and checks, with supported optional settings")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise Abort("Unsupported project checks schema_version")
    base_source = "project" if "base_branch" in data else "global"
    base = (validate_base_branch(data["base_branch"], source="project")
            if base_source == "project" else global_config.base)
    commands = data["checks"]
    approval_source = "project" if "require_review_approval" in data else "global"
    require_approval = data.get("require_review_approval", global_config.require_approval)
    if type(require_approval) is not bool:
        raise Abort("Project require_review_approval must be a YAML boolean (true or false)")
    checks_source = "project" if "require_required_checks" in data else "global"
    require_checks = data.get("require_required_checks", global_config.require_checks)
    if type(require_checks) is not bool:
        raise Abort("Project require_required_checks must be a YAML boolean (true or false)")
    if not isinstance(commands, list) or not commands:
        raise Abort("Project checks must be a non-empty list")
    check_timeout_seconds = data.get("check_timeout_seconds", global_config.check_timeout_seconds)
    if type(check_timeout_seconds) is not int or not 1 <= check_timeout_seconds <= 3600:
        raise Abort("Project check_timeout_seconds must be an integer from 1 to 3600")
    idle_timeout = data.get("check_idle_timeout_seconds", global_config.check_idle_timeout_seconds)
    if type(idle_timeout) is not int or not 1 <= idle_timeout <= 3600:
        raise Abort("Project check_idle_timeout_seconds must be an integer from 1 to 3600")
    ci_wait = data.get("github_ci_wait_seconds", global_config.github_ci_wait_seconds)
    if type(ci_wait) is not int or not 0 <= ci_wait <= 1800:
        raise Abort("Project github_ci_wait_seconds must be an integer from 0 to 1800")
    parsed = []
    for index, command in enumerate(commands, start=1):
        if isinstance(command, str):
            try:
                argv = shlex.split(command)
            except ValueError as exc:
                raise Abort(f"Invalid quoting in project check {index}") from exc
        elif isinstance(command, list):
            argv = command
        else:
            raise Abort(f"Project check {index} must be a command string or argv list")
        if not argv or any(not isinstance(arg, str) or not arg or "\x00" in arg for arg in argv):
            raise Abort(f"Project check {index} contains invalid arguments")
        parsed.append(tuple(argv))
    prepare = data.get("prepare_checks", [])
    if not isinstance(prepare, list) or len(prepare) > 20:
        raise Abort("Project prepare_checks must be a list of at most 20 argv commands")
    prepared = []
    for index, command in enumerate(prepare, start=1):
        if (not isinstance(command, list) or not command or len(command) > 128
                or any(type(arg) is not str or not arg or "\x00" in arg
                       for arg in command)):
            raise Abort(f"Project prepare_checks command {index} must be a non-empty argv list")
        prepared.append(tuple(command))
    formatting = data.get("format_commands", [])
    if not isinstance(formatting, list) or len(formatting) > 20:
        raise Abort("Project format_commands must be a list of at most 20 argv commands")
    format_commands = []
    for index, command in enumerate(formatting, start=1):
        if (not isinstance(command, list) or not command or len(command) > 128
                or any(type(arg) is not str or not arg or "\x00" in arg
                       for arg in command)):
            raise Abort(f"Project format_commands command {index} must be a non-empty argv list")
        format_commands.append(tuple(command))
    review_required = data.get("review_required", False)
    if type(review_required) is not bool:
        raise Abort("Project review_required must be a YAML boolean")
    review_timeout = data.get("review_timeout_seconds", 180)
    if type(review_timeout) is not int or not 1 <= review_timeout <= 1800:
        raise Abort("Project review_timeout_seconds must be an integer from 1 to 1800")
    review_max_bytes = data.get("review_max_bytes", 131072)
    if type(review_max_bytes) is not int or not 1024 <= review_max_bytes <= 1048576:
        raise Abort("Project review_max_bytes must be an integer from 1024 to 1048576")
    artifacts_enabled = data.get("review_artifacts_enabled", False)
    if type(artifacts_enabled) is not bool:
        raise Abort("Project review_artifacts_enabled must be a YAML boolean")
    artifact_max_bytes = data.get("review_artifact_max_bytes", 8388608)
    if type(artifact_max_bytes) is not int or not 65536 <= artifact_max_bytes <= 67108864:
        raise Abort("Project review_artifact_max_bytes must be an integer from 65536 to 67108864")
    context_max_bytes = data.get("review_context_max_bytes", 32768)
    if type(context_max_bytes) is not int or not 4096 <= context_max_bytes <= 65536:
        raise Abort("Project review_context_max_bytes must be an integer from 4096 to 65536")
    context_options = {}
    for key in ("review_context_external_consent", "review_context_include_messages",
                "review_context_include_diff"):
        value = data.get(key, False)
        if type(value) is not bool:
            raise Abort(f"Project {key} must be a YAML boolean")
        context_options[key] = value
    if ((context_options["review_context_include_messages"] or
         context_options["review_context_include_diff"])
            and not context_options["review_context_external_consent"]):
        raise Abort("Review context source text requires review_context_external_consent=true")
    retention_enabled = data.get("review_retention_enabled", False)
    if type(retention_enabled) is not bool:
        raise Abort("Project review_retention_enabled must be a YAML boolean")
    retention_limits = {}
    for key, default, minimum, maximum in (
        ("review_retention_max_runs", 100, 1, 10000),
        ("review_retention_max_bytes", 536870912, 1048576, 10737418240),
        ("review_retention_max_age_days", 30, 1, 3650),
    ):
        value = data.get(key, default)
        if type(value) is not int or not minimum <= value <= maximum:
            raise Abort(f"Project {key} must be an integer from {minimum} to {maximum}")
        retention_limits[key] = value
    configured_reviewers = data.get("reviewers", [])
    if not isinstance(configured_reviewers, list) or len(configured_reviewers) > 8:
        raise Abort("Project reviewers must be a list of at most 8 providers")
    reviewers = []
    names = set()
    for item in configured_reviewers:
        if not isinstance(item, dict) or set(item) - {"id", "kind", "command", "model", "report_format", "scanners", "input_mode"}:
            raise Abort("Each reviewer must contain id, kind and command, with optional model")
        name, kind, command, model = (item.get("id"), item.get("kind"),
                                     item.get("command"), item.get("model", ""))
        if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", name)
                or name in names):
            raise Abort("Reviewer IDs must be unique ASCII identifiers")
        if kind not in {"llm", "script"}:
            raise Abort(f"Reviewer {name} kind must be llm or script")
        if (not isinstance(command, list) or not 1 <= len(command) <= 128
                or any(type(arg) is not str or not arg or "\x00" in arg
                       or "\n" in arg or "\r" in arg for arg in command)):
            raise Abort(f"Reviewer {name} command must be a nonempty argv list")
        if (type(model) is not str or len(model) > 100
                or "\x00" in model or "\n" in model or "\r" in model):
            raise Abort(f"Reviewer {name} model must be a short string")
        report_format = item.get("report_format", "")
        scanner_items = item.get("scanners", [])
        if type(report_format) is not str or report_format not in {"", "apatch-json-v1"}:
            raise Abort(f"Reviewer {name} report_format must be apatch-json-v1")
        if (report_format and (kind != "script" or not artifacts_enabled)
                or not report_format and "scanners" in item):
            raise Abort(f"Reviewer {name} structured reports require script and review_artifacts_enabled")
        if type(scanner_items) is not list or len(scanner_items) > 16 or (report_format and not scanner_items):
            raise Abort(f"Reviewer {name} scanners must be a nonempty list of at most 16")
        input_mode = item.get("input_mode", "diff")
        if (type(input_mode) is not str or input_mode not in {"diff", "structured-summary"}
                or (input_mode == "structured-summary" and
                    (kind != "llm" or not artifacts_enabled or
                     not context_options["review_context_external_consent"]))):
            raise Abort(f"Reviewer {name} structured-summary requires llm, capture and explicit consent")
        scanners = []
        scanner_names = set()
        for entry in scanner_items:
            if (type(entry) is not dict or set(entry) != {"id", "format", "required"}
                    or type(entry.get("id")) is not str
                    or not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", entry["id"])
                    or entry["id"] in scanner_names
                    or type(entry.get("format")) is not str
                    or entry["format"] not in {"ruff-json", "bandit-json", "semgrep-json", "sarif-2.1.0"}
                    or type(entry.get("required")) is not bool):
                raise Abort(f"Reviewer {name} has invalid scanner policy")
            scanner_names.add(entry["id"])
            scanners.append(ScannerPolicy(entry["id"], entry["format"], entry["required"]))
        names.add(name)
        reviewers.append(ReviewProvider(name, kind, tuple(command), model,
                                        report_format, tuple(scanners), input_mode))
    if review_required and not reviewers:
        raise Abort("review_required=true requires at least one configured reviewer")
    policy = data.get("check_worktree_policy", "stop")
    if type(policy) is not str or policy not in {"stop", "recheck_once"}:
        raise Abort("Project check_worktree_policy must be stop or recheck_once")
    subdirectory = validate_log_subdirectory(data.get("log_directory", str(global_config.log_directory)))
    state = validate_runtime_filename(data.get("state_file", str(global_config.state_path)))
    history = validate_runtime_filename(data.get("applied_patches_file", str(global_config.applied_patches_path)))
    if (state == history or state.name + ".lock" == history.name
            or history.name + ".lock" == state.name):
        raise Abort("State and applied-patch history must have separate filenames")
    location = config_dir / subdirectory
    for segment in (config_dir, *[config_dir.joinpath(*subdirectory.parts[:i]) for i in range(1, len(subdirectory.parts) + 1)]):
        if segment.is_symlink():
            raise Abort(f"Log directory must not contain symlinks: {segment}")
    for path in (config_dir / state, config_dir / (state.name + ".lock"), config_dir / history,
                 config_dir / (history.name + ".lock")):
        if path.is_symlink():
            raise Abort(f"Runtime state and history files must not be symlinks: {path}")
    return replace(global_config, checks=tuple(parsed), log_directory=location,
                   state_path=config_dir / state, applied_patches_path=config_dir / history,
                   check_timeout_seconds=check_timeout_seconds,
                   check_idle_timeout_seconds=idle_timeout,
                   base=base, base_branch_source=base_source,
                   require_approval=require_approval, review_approval_source=approval_source,
                   require_checks=require_checks, required_checks_source=checks_source,
                   prepare_checks=tuple(prepared), check_worktree_policy=policy,
                   format_commands=tuple(format_commands), github_ci_wait_seconds=ci_wait,
                   reviewers=tuple(reviewers), review_required=review_required,
                   review_timeout_seconds=review_timeout, review_max_bytes=review_max_bytes,
                   review_artifacts_enabled=artifacts_enabled,
                   review_artifact_max_bytes=artifact_max_bytes,
                   review_context_max_bytes=context_max_bytes,
                   review_retention_enabled=retention_enabled,
                   **retention_limits, **context_options)

