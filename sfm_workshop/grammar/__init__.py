"""Generated from TeamDman/SuperFactoryManager SFML.g4 (4.34.0 projection).

Generated parser files are used for local L0 syntax validation.
Grammar source: MPL-2.0; see NOTICE.md.
"""
from __future__ import annotations


def parse_sfml(source: str) -> list[str]:
    """Return syntax errors as ``line:column message`` strings (empty = ok)."""
    import sys
    from pathlib import Path

    # The generated modules use absolute imports (SFMLLexer/SFMLParser), so
    # make this directory importable for the duration of the call.
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    from antlr4 import CommonTokenStream, InputStream
    from antlr4.error.ErrorListener import ErrorListener
    from SFMLLexer import SFMLLexer
    from SFMLParser import SFMLParser

    class Collect(ErrorListener):
        def __init__(self) -> None:
            super().__init__()
            self.errors: list[str] = []

        def syntaxError(self, recognizer, symbol, line, col, msg, e):  # noqa: N802
            self.errors.append(f"{line}:{col} {msg}")

    listener = Collect()
    lexer = SFMLLexer(InputStream(source))
    lexer.removeErrorListeners()
    lexer.addErrorListener(listener)
    parser = SFMLParser(CommonTokenStream(lexer))
    parser.removeErrorListeners()
    parser.addErrorListener(listener)
    parser.program()
    return listener.errors
