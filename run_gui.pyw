"""Compatibility entry point for existing source-checkout login shortcuts.

Install the project with ``python -m pip install -e .`` before using this file.
The application implementation lives in src/openbroadcast.
"""
from openbroadcast.launcher import main


if __name__ == "__main__":
    raise SystemExit(main())
