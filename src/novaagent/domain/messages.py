from dataclasses import dataclass


@dataclass(frozen=True)
class Message:
    """Minimal message contract reserved for later chat stages."""

    role: str
    text: str
