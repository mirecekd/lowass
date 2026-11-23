# tests/fakes.py
"""Scripted Strands model + fake MCP tools for offline agent tests."""
from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any, cast

from strands.models.model import Model
from strands.tools.decorator import tool
from strands.types.streaming import StreamEvent


class ScriptedModel(Model):
    """Each turn is either ("text", "answer") or ("tool", name, input_dict)."""

    def __init__(self, turns: list[tuple]):
        self.turns: list[tuple] = list(turns)
        self.calls: list[dict] = []
        self.config: dict[str, Any] = {"model_id": "m"}

    def update_config(self, **model_config: Any) -> None:
        self.config.update(model_config)

    def get_config(self) -> Any:
        return self.config

    async def structured_output(self, output_model: Any, prompt: Any, system_prompt: Any = None,
                                **kwargs: Any) -> AsyncGenerator[Any, None]:
        raise NotImplementedError
        yield  # pragma: no cover

    async def stream(self, messages: Any, tool_specs: Any = None, system_prompt: Any = None,
                     **kwargs: Any) -> AsyncGenerator[StreamEvent, None]:
        self.calls.append({"model_id": self.config["model_id"], "system": system_prompt, "messages": list(messages)})
        turn: tuple = self.turns.pop(0) if self.turns else ("text", "(script exhausted)")
        events: list[dict] = [{"messageStart": {"role": "assistant"}}]
        if turn[0] == "tool":
            events += [
                {"contentBlockStart": {"start": {"toolUse": {"toolUseId": f"t{len(self.calls)}", "name": turn[1]}}}},
                {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(turn[2])}}}},
                {"contentBlockStop": {}},
                {"messageStop": {"stopReason": "tool_use"}},
            ]
        else:
            stop = "max_tokens" if turn[0] == "cut" else "end_turn"  # ("cut", text): the output limit hit mid-answer
            events += [
                {"contentBlockDelta": {"delta": {"text": turn[1]}}},
                {"contentBlockStop": {}},
                {"messageStop": {"stopReason": stop}},
            ]
        for ev in events:
            yield cast(StreamEvent, ev)


def fake_tools(log: list) -> list:
    @tool
    def search_tools(query: str) -> str:
        """Search tools."""
        log.append(("search_tools", {"query": query}))
        return "FOUND"

    @tool
    def call_tool(toolName: str, arguments: dict | None = None) -> str:  # mirrors the mcphub schema
        """Call a tool."""
        log.append(("call_tool", {"toolName": toolName, "arguments": arguments}))
        return "X" * 50000 if toolName == "big-tool" else "RESULT"

    return [search_tools, call_tool]
