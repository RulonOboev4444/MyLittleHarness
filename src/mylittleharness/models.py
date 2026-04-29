from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    message: str
    source: str | None = None
    line: int | None = None

    def render(self) -> str:
        location = ""
        if self.source:
            location = self.source
            if self.line:
                location = f"{location}:{self.line}"
            location = f" ({location})"
        return f"[{self.severity.upper()}] {self.code}: {self.message}{location}"

