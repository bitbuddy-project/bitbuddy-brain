from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DoctorStatus = Literal["pass", "warn", "fail", "skip"]


@dataclass(frozen=True)
class DoctorCheckResult:
    id: str
    section: str
    status: DoctorStatus
    title: str
    detail: str = ""
    fix_id: str | None = None


SYMBOLS = {
    "pass": "✓",
    "warn": "⚠",
    "fail": "✗",
    "skip": "-",
}


def doctor_exit_code(results: list[DoctorCheckResult]) -> int:
    return 1 if any(result.status == "fail" for result in results) else 0


def render_doctor_report(results: list[DoctorCheckResult]) -> str:
    lines = ["BitBuddy Doctor", ""]
    sections: list[str] = []
    for result in results:
        if result.section not in sections:
            sections.append(result.section)

    for section in sections:
        lines.append(section)
        for result in [item for item in results if item.section == section]:
            symbol = SYMBOLS[result.status]
            lines.append(f"  {symbol} {result.title}")
            if result.detail:
                lines.append(f"    {result.detail}")
            if result.fix_id:
                lines.append("    → suggested fix: bitbuddy doctor fix")
        lines.append("")

    if any(result.fix_id for result in results if result.status in {"fail", "warn"}):
        lines.extend(["Suggested fix:", "  Run: bitbuddy doctor fix", ""])
    return "\n".join(lines).rstrip() + "\n"
