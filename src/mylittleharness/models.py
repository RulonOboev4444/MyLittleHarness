from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    message: str
    source: str | None = None
    line: int | None = None
    route_id: str | None = None
    mutates: bool = False
    requires_human_gate: bool = False
    gate_class: str = ""
    human_gate_reason: str = ""
    allowed_decisions: tuple[str, ...] = ()
    advisory: bool = True

    def render(self) -> str:
        location = ""
        if self.source:
            location = self.source
            if self.line:
                location = f"{location}:{self.line}"
            location = f" ({location})"
        return f"[{self.severity.upper()}] {self.code}: {self.message}{location}"

    def to_dict(self) -> dict[str, object]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "source": self.source,
            "line": self.line,
            "route_id": self.route_id,
            "mutates": self.mutates,
            "requires_human_gate": self.requires_human_gate,
            "gate_class": self.gate_class,
            "human_gate_reason": self.human_gate_reason,
            "allowed_decisions": list(self.allowed_decisions),
            "advisory": self.advisory,
        }
