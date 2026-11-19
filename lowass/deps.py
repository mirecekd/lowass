# lowass/deps.py
"""Missing-package check with a message a person can act on (instead of a bare "No module named 'x'")."""
from __future__ import annotations

import importlib.util

# import name -> pip name
BASE = {"numpy": "numpy", "scipy": "scipy", "requests": "requests", "dotenv": "python-dotenv", "strands": "strands-agents[openai]",
        "boto3": "boto3", "mss": "mss", "PIL": "pillow"}
TRANSCRIBE = {"amazon_transcribe": "amazon-transcribe", "awscrt": "awscrt"}
WINDOWS_AUDIO = {"pyaudiowpatch": "pyaudiowpatch"}


def missing(provider: str = "transcribe", audio: bool = True) -> list[str]:
    """pip names of the packages that cannot be imported for this configuration."""
    need = dict(BASE)
    if provider == "transcribe":
        need.update(TRANSCRIBE)
    if audio:
        need.update(WINDOWS_AUDIO)
    return [pip for mod, pip in need.items() if importlib.util.find_spec(mod) is None]


def install_hint(packages: list[str]) -> str:
    return ("Missing Python packages: " + ", ".join(packages) + ".\n"
            "Install them with:  python -m pip install -r requirements.txt   (run it in the folder of lowass.toml,\n"
            "with the same Python that starts the app; run.bat does this for its own .venv).")


def describe(exc: BaseException) -> str:
    """One readable line for the window: a missing module names the package and the fix."""
    if isinstance(exc, ModuleNotFoundError) and exc.name:
        top = exc.name.split(".")[0]
        pip = {**BASE, **TRANSCRIBE, **WINDOWS_AUDIO}.get(top, top)
        return f"Missing package '{pip}': run  python -m pip install -r requirements.txt  (then start LOWASS again)."
    return f"{type(exc).__name__}: {exc}"
