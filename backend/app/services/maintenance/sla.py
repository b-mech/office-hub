from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.models.maintenance import MaintPriority


@dataclass(frozen=True)
class SlaTargets:
    emergency: timedelta = timedelta(hours=2)
    urgent: timedelta = timedelta(hours=24)
    routine: timedelta = timedelta(days=7)
    low: timedelta = timedelta(days=14)

    def for_priority(self, priority: MaintPriority) -> timedelta:
        return getattr(self, priority.value)


DEFAULT_SLA_TARGETS = SlaTargets()


def sla_due_at(started_at: datetime, priority: MaintPriority, targets: SlaTargets = DEFAULT_SLA_TARGETS) -> datetime:
    return started_at + targets.for_priority(priority)


def sla_warning_at(started_at: datetime, due_at: datetime) -> datetime:
    return started_at + ((due_at - started_at) * 0.75)
