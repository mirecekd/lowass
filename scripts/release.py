# scripts/release.py
"""Next version YYYYMMDD.X (X = next free number of today, from the git tags), written to lowass/__init__.py.

  python scripts/release.py          print the next version
  python scripts/release.py --write  write it into lowass/__init__.py and commit-ready tag it afterwards by hand:
                                     git commit -am "chore: release <v>" && git tag <v>
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

INIT = Path(__file__).resolve().parent.parent / "lowass" / "__init__.py"


def next_version(tags: list[str], today: str) -> str:
    used = [int(m.group(1)) for t in tags if (m := re.fullmatch(re.escape(today) + r"\.(\d+)", t.strip()))]
    return f"{today}.{max(used, default=0) + 1}"


def main() -> int:
    tags = subprocess.run(["git", "tag", "-l", "2*"], capture_output=True, text=True, check=False).stdout.split()
    version = next_version(tags, time.strftime("%Y%m%d"))
    if "--write" in sys.argv:
        text = INIT.read_text(encoding="utf-8")
        INIT.write_text(re.sub(r'__version__ = "[^"]*"', f'__version__ = "{version}"', text), encoding="utf-8")
    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
