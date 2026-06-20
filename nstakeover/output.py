import sys


GREEN = "\033[32m"
DEFAULT = "\033[0m"
RED = "\033[91m"
YELLOW = "\033[93m"


def colorize(message: str, color: str) -> str:
    if sys.stdout.isatty():
        return f"{color}{message}{DEFAULT}"
    return message


def emit(message: str = "") -> None:
    print(message, flush=True)
