import subprocess
from typing import Sequence


def run_command(args: Sequence[str], timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
    )
