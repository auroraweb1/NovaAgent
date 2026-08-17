from collections.abc import Mapping
from typing import Protocol


class HealthPort(Protocol):
    def check(self) -> Mapping[str, object]: ...
