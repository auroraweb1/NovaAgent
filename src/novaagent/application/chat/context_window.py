from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from novaagent.domain.errors import ProtocolValidationError
from novaagent.domain.messages import Message

DEFAULT_CONTEXT_TURNS = 20
DEFAULT_CONTEXT_ESTIMATED_TOKEN_BUDGET = 24_000
MESSAGE_ESTIMATE_OVERHEAD = 8


@dataclass(frozen=True, slots=True)
class ContextSelection:
    messages: tuple[Message, ...]
    included_messages: int
    dropped_messages: int
    estimated_input_tokens: int


def estimate_messages(messages: Sequence[Message]) -> int:
    return sum(
        MESSAGE_ESTIMATE_OVERHEAD
        + sum(
            len(block.text.encode("utf-8")) for block in message.content if hasattr(block, "text")
        )
        for message in messages
    )


def select_context(
    *,
    system_messages: Sequence[Message],
    history: Sequence[Message],
    current_user: Message,
    max_turns: int = DEFAULT_CONTEXT_TURNS,
    budget: int = DEFAULT_CONTEXT_ESTIMATED_TOKEN_BUDGET,
) -> ContextSelection:
    if max_turns < 0 or budget <= 0:
        raise ProtocolValidationError("context limits must be positive")
    if len(history) % 2:
        raise ProtocolValidationError("history must contain complete turns", field="history")

    fixed = tuple(system_messages) + (current_user,)
    fixed_cost = estimate_messages(fixed)
    if fixed_cost > budget:
        raise ProtocolValidationError("current message exceeds the context budget", field="context")

    turns = [tuple(history[index : index + 2]) for index in range(0, len(history), 2)]
    selected: list[tuple[Message, Message]] = []
    selected_cost = fixed_cost
    for turn in reversed(turns[-max_turns:] if max_turns else []):
        turn_cost = estimate_messages(turn)
        if selected_cost + turn_cost > budget:
            break
        selected.append((turn[0], turn[1]))
        selected_cost += turn_cost
    selected.reverse()
    selected_messages = tuple(message for turn in selected for message in turn)
    return ContextSelection(
        messages=tuple(system_messages) + selected_messages + (current_user,),
        included_messages=len(selected_messages),
        dropped_messages=len(history) - len(selected_messages),
        estimated_input_tokens=selected_cost,
    )
