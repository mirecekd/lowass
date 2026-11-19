# scripts/smoke_live.py
"""Live check of LiteLLM + mcphub + Strands agent (no audio, no UI). Run: python scripts/smoke_live.py "question" ..."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lowass.build import build_agent
from lowass.config import load

cfg = load()
miss = cfg.missing_env(("LITELLM_BASE_URL", "LITELLM_API_KEY", "MCPHUB_URL", "MCPHUB_TOKEN"))
if miss:
    sys.exit(f"missing in .env: {miss}")
agent, mcp = build_agent(cfg, cfg.project()[1], cfg.models()[1])
try:
    print("model:", agent.model)
    for q in sys.argv[1:] or ["Najdi na webu, jaka je aktualni LTS verze Node.js, a uved zdroj."]:
        print(">>", q)
        print(agent.run(q, "", lambda s: print("   [tool]", s[:140]), remember=False), "\n")
finally:
    mcp.stop(None, None, None)
