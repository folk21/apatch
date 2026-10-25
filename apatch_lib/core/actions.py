"""Canonical operation identifiers shared across CLI, workflow, and presentation."""

ACTION_CODES = ("EXT", "BRN", "BAP", "APL", "CHK", "CMT", "PSH", "PR", "MRG", "SYN", "STS")


def action_number(value):
    """Resolve an operation number or mnemonic to its stable menu index."""
    key = str(value).strip().upper()
    if key.isdecimal() and 0 <= int(key) < len(ACTION_CODES):
        return int(key)
    try:
        return ACTION_CODES.index(key)
    except ValueError as exc:
        raise ValueError("Invalid action: use 0-10 or one of " + ", ".join(ACTION_CODES)) from exc
