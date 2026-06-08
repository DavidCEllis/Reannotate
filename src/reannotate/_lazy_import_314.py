# Hack lazy import for Python 3.14
import sys

TYPE_CHECKING = False
if TYPE_CHECKING:
    import typing
else:
    # Hack lazy import for 3.14
    typing = sys.modules.get("typing")
    # fmt: off
    if typing is None:  # pragma: no cover
        class _LazyTyping:
            def __getattr__(self, name):
                global t
                import typing

                t = typing
                return getattr(t, name)
        typing = _LazyTyping()
        del _LazyTyping
    # fmt: on
