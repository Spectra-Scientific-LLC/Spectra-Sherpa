#!/usr/bin/env python3
"""Emit per-executable Ubuntu user-namespace policy for this disposable CI checkout.

This grants Chromium its sandbox primitive, not a sandbox bypass. No global
sysctl is modified. Installation is an explicit CI sudo step.
"""

import re
import sys
from pathlib import Path


def policy(paths):
    resolved = [str(Path(value).resolve()) for value in paths]
    if not resolved or any(not re.fullmatch(r"/[A-Za-z0-9/._-]+", value) for value in resolved):
        raise ValueError("Require safe absolute executable paths")
    return (
        "abi <abi/4.0>,\ninclude <tunables/global>\n"
        + "\n".join(
            f'profile spectrasherpa-ci-{index} "{value}" flags=(unconfined) {{\n  userns,\n}}'
            for index, value in enumerate(resolved)
        )
        + "\n"
    )


if __name__ == "__main__":
    print(policy(sys.argv[1:]), end="")
