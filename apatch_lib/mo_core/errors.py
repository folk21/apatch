"""Domain-neutral precondition error shared by public boundaries."""


class Abort(RuntimeError):
    """A precondition failed; no further workflow step is safe."""

