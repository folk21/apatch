"""Public CLI parsing and read-only status entry points."""

from .cli_request import (CliRequest, MACRO_OPERATIONS, build_parser, normalize_arguments,
                          parse_boolean, parse_operation,
                          parse_operation_sequence, parse_request,
                          validate_progress_request, validate_repository_request)
from .cli_inspection import (select_without_handoff, show_audit_with_activity,
                             show_status_with_progress, show_unresolved_operations)

__all__ = (
    "CliRequest", "MACRO_OPERATIONS", "build_parser", "normalize_arguments", "parse_boolean",
    "parse_operation", "parse_operation_sequence", "parse_request",
    "validate_progress_request", "validate_repository_request",
    "select_without_handoff", "show_audit_with_activity",
    "show_status_with_progress", "show_unresolved_operations",
)
