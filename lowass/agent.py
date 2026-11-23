# lowass/agent.py
"""LOWASS agent on Strands Agents: LiteLLM (OpenAI API) model + mcphub MCP tools + a few hooks.

Strands owns the tool loop, tool schemas and the MCP connection. What stays here:
read-only guard, step limit, status lines, tool-result truncation, and the memory policy
(auto/hotkey runs and NOTHING answers are never remembered; Clear wipes everything).
"""
from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable
from datetime import datetime
from typing import Any

from strands import Agent as StrandsAgent
from strands.hooks import AfterToolCallEvent, BeforeToolCallEvent
from strands.types.exceptions import EventLoopException, MaxTokensReachedException

from .guard import check_call

log = logging.getLogger("lowass.agent")

NOTHING = "NOTHING"
LIMIT_MSG = "Tool-call limit reached. Answer now with what you have; mark anything unchecked as NEOVERENO."


class StepLimitError(RuntimeError):
    """The model kept calling tools after the limit message."""


def session_stamp() -> str:
    """Today's date for the system prompt. Computed once per session, never added to the conversation:
    a changing value in the messages would break the provider's prompt cache (Bedrock)."""
    now = datetime.now().astimezone()
    return f"\n\nToday is {now:%A, %Y-%m-%d} (local time zone {now:%Z}, UTC{now:%z}). Use it to judge dates and deadlines.\n"


def _text_msg(role: str, text: str) -> dict:
    return {"role": role, "content": [{"text": text}]}


def partial_text(messages: list) -> str:
    """The text of the last assistant message (Strands stores the cut-off answer there when max_tokens is hit)."""
    if not messages or messages[-1].get("role") != "assistant":
        return ""
    return "".join(b.get("text", "") for b in messages[-1].get("content", [])).strip()


class Agent:
    def __init__(self, model: Any, tools: list, deny: re.Pattern[str], cfg: dict, prompts: dict):
        self.deny = deny
        self.max_steps = int(cfg.get("max_steps", 8))
        self.max_chars = int(cfg.get("max_tool_chars", 12000))
        self.history_n = int(cfg.get("history_messages", 12))
        self.generation = 0  # bumped by clear(); an answer started before a clear is not remembered
        self._lock = threading.Lock()  # one request at a time
        self._steps = 0
        self._status: Callable[[str], None] = lambda _s: None
        self.ag = StrandsAgent(model=model, tools=tools, callback_handler=None,
                               system_prompt=prompts["system"] + session_stamp())  # fixed per session: cache-stable
        self.ag.hooks.add_callback(BeforeToolCallEvent, self._before_tool)
        self.ag.hooks.add_callback(AfterToolCallEvent, self._after_tool)

    @property
    def model(self) -> str:
        return str(self.ag.model.get_config().get("model_id", ""))

    def set_model(self, model_id: str) -> None:
        self.ag.model.update_config(model_id=model_id)

    @property
    def history(self) -> list:
        return self.ag.messages

    def clear(self) -> None:
        self.generation += 1
        if self._lock.acquire(blocking=False):  # idle: wipe now; a running request wipes itself when it ends
            try:
                self.ag.messages.clear()
            finally:
                self._lock.release()

    # --- hooks -----------------------------------------------------------------
    def _before_tool(self, event: BeforeToolCallEvent) -> None:
        name, args = event.tool_use["name"], event.tool_use.get("input") or {}
        self._steps += 1
        if self._steps > self.max_steps + 3:
            raise StepLimitError(f"{self._steps} tool calls in one request")
        if self._steps > self.max_steps:
            event.cancel_tool = LIMIT_MSG
            return
        if name == "call_tool":
            err = check_call(args, self.deny)
            if err:
                log.warning("guard: %s", err)
                event.cancel_tool = err
                return
        self._status(f"{name}: {str(args)[:90]}")

    def _after_tool(self, event: AfterToolCallEvent) -> None:
        for block in event.result.get("content", []):
            text = block.get("text")
            if text and len(text) > self.max_chars:
                block["text"] = text[:self.max_chars] + f"\n...[truncated, {len(text) - self.max_chars} more chars]"

    # --- run -------------------------------------------------------------------
    def run(self, user_text: str, context: str = "", on_status: Callable[[str], None] | None = None,
            remember: bool = True, image: bytes | None = None) -> str:
        """image: PNG bytes sent with this request only. The image is NOT kept in the agent's memory (it would be
        paid again with every later request); the remembered turn is the text plus a note that a screenshot was shared."""
        with self._lock:
            gen = self.generation
            base = list(self.ag.messages)
            self._steps, self._status = 0, on_status or (lambda _s: None)
            text = f"Conversation transcript (recent):\n{context}\n\n---\n{user_text}" if context else user_text
            content: Any = text if image is None else [{"text": text}, {"image": {"format": "png", "source": {"bytes": image}}}]
            try:
                answer = str(self.ag(content)).strip()
            except MaxTokensReachedException:
                answer = partial_text(self.ag.messages)  # a cut-off answer is still worth more than none (the summary!)
                if not answer:
                    raise
                log.warning("the answer hit max_tokens and was cut (%d chars kept)", len(answer))
                answer += "\n[cut: output limit reached]"
            except EventLoopException:
                if self._steps <= self.max_steps + 3:  # not our StepLimitError: a real failure
                    raise
                answer = "NEOVERENO: tool-call limit reached."
            finally:
                self.ag.messages[:] = base  # drop this turn's tool traffic; only a clean pair may be kept below
            if gen != self.generation:
                self.ag.messages.clear()  # Clear was pressed while this request ran
            elif remember and answer != NOTHING:
                note = user_text if image is None else f"{user_text}\n(a screenshot was shared with this request)"
                kept = [*base, _text_msg("user", note), _text_msg("assistant", answer)]
                self.ag.messages[:] = kept[-self.history_n * 2:]
            return answer
