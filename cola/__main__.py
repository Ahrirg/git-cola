"""Run cola as a Python module.

Usage: python -m cola
"""
import sys

from cola import main
from cola.server import run as serverrun


def run() -> None:
    """Start the command-line interface."""
    main.main()


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'server':
        serverrun()
    else:
        run()
