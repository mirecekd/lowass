# scripts/smoke_voice.py
"""Feeds transcript lines to the agent exactly like the app does. Usage: python scripts/smoke_voice.py auto|check "Ja: ..." ["Ja: ..."]"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lowass.build import build_agent
from lowass.config import load

mode, lines = sys.argv[1], sys.argv[2:]
cfg = load()
agent, mcp = build_agent(cfg, cfg.project()[1], cfg.models()[1])
new = "\n".join(lines)
try:
    prompt = f"{cfg.section('prompts')[mode]}\n\nNEW PART:\n{new}"
    print(f"[{mode}] ->", repr(agent.run(prompt, new, lambda s: print("   [tool]", s[:100]), remember=False)))
finally:
    mcp.stop(None, None, None)
