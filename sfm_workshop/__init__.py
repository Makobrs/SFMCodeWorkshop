"""SFM代码生成工坊 (SFM Code Workshop) — MVP."""
__version__ = "0.2.0"


def main() -> int:
    from .entry import main as entry_main

    return entry_main()
