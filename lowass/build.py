# lowass/build.py
"""Builds one agent session: LiteLLM model + the project's mcphub MCP tools + the project's system prompt."""
from __future__ import annotations

from strands.models.openai import OpenAIModel
from strands.tools.mcp import MCPClient

from .agent import Agent
from .config import Config


def build_agent(cfg: Config, project_key: str, model_id: str, extra_tools: list | None = None) -> tuple[Agent, MCPClient]:
    """Starts the MCP connection; the caller must stop() it when the session ends.
    Raises (and leaves nothing running) if mcphub is unreachable. extra_tools = local tools (e.g. meeting search)."""
    a = cfg.section("agent")
    proj = cfg.projects()[project_key]
    model = OpenAIModel(
        client_args={"base_url": cfg.env("LITELLM_BASE_URL"), "api_key": cfg.env("LITELLM_API_KEY"),
                     "timeout": a["llm_timeout_sec"]},
        model_id=model_id, params={"max_tokens": a.get("max_tokens", 2000)})
    mcp = MCPClient(url=proj["mcphub_url"], headers={"Authorization": f"Bearer {cfg.env('MCPHUB_TOKEN')}"},
                    startup_timeout=int(a["mcp_timeout_sec"]))
    try:
        mcp.start()
        tools = list(mcp.list_tools_sync())
    except BaseException:
        mcp.stop(None, None, None)
        raise
    prompts = {**cfg.section("prompts"), "system": cfg.system_prompt(project_key)}
    return Agent(model, [*tools, *(extra_tools or [])], cfg.deny_regex(), a, prompts), mcp
