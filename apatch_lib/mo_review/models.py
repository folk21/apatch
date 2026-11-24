"""Immutable review-provider and scanner configuration value objects."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ReviewProvider:
    id: str
    kind: str
    command: tuple[str, ...]
    model: str = ""
    report_format: str = ""
    scanners: tuple["ScannerPolicy", ...] = ()
    input_mode: str = "diff"


@dataclass(frozen=True)
class ScannerPolicy:
    id: str
    format: str
    required: bool = True

