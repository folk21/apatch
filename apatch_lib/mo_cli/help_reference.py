"""Load packaged CLI help and apply optional terminal-only presentation."""

from importlib.resources import files
import re

from ..mo_core.actions import ACTION_CODES
from ..mo_presentation.console import terminal_style


_RESOURCE_PACKAGE = "apatch_lib.mo_cli.resources"
_SECTION = re.compile(r"^[A-Z][A-Z0-9 ()/,:.+-]*$")
_ACTION = re.compile(r"^(  )(EXT|BRN|BAP|APL|CHK|REV|FMT|BLD|CMT|PSH|PR|MRG|SYN|STS|AUD)(  +)")


def _read_resource(name: str) -> str:
    """Read an immutable package resource, independent of the working directory."""
    return files(_RESOURCE_PACKAGE).joinpath(name).read_text(encoding="utf-8")


def render_help(text: str) -> str:
    """Color semantic headings and action identifiers only on capable terminals."""
    rendered = []
    for line in text.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        suffix = line[len(content):]
        if content and _SECTION.fullmatch(content):
            content = terminal_style(content, "1;36")
        else:
            content = _ACTION.sub(
                lambda m: m.group(1) + terminal_style(m.group(2), "1;32") + m.group(3),
                content, count=1,
            )
        rendered.append(content + suffix)
    return "".join(rendered)


HELP_EPILOG = _read_resource("consumer.txt").replace(
    "{{ACTION_CODES}}", ", ".join(
        f"{number}={name}" for number, name in enumerate(ACTION_CODES)))
PACK_HELP_EPILOG = _read_resource("producer.txt").rstrip("\n")
PREFLIGHT_HELP_EPILOG = _read_resource("preflight.txt").rstrip("\n")
