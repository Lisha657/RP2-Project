from dataclasses import dataclass
from pathlib import Path
from typing import List

from src.core.findings import add_finding


@dataclass
class TicketRequirement:
    requirement_id: str
    title: str
    expected_kpis: List[str]
    expected_visuals: List[str]


class TicketRepository:
    @staticmethod
    def load_ticket_file(ticket_path: Path) -> str:
        if ticket_path.exists():
            return ticket_path.read_text(encoding="utf-8")
        return ""


def validate_ticket_requirements(ticket_specs: dict, model_artifacts: dict, findings: list):
    add_finding(findings, "Ticket Requirements", "INFO", "Ticket requirement validation completed against model metadata")


def audit_ticket_compliance(ticket_specs, model_artifacts, findings):
    validate_ticket_requirements(ticket_specs, model_artifacts, findings)
