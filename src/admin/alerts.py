"""Alert engine — evaluates events against rules and pushes notifications to admins.

Decoupled from the admin bot via `set_send_fn()`. The alert engine defines
rules (which events trigger alerts, under what conditions) and formats
Italian alert messages. The actual delivery is delegated to whatever send
function is injected — typically the admin bot's `send_to_admin`.

Never raises — failures are logged but never propagate to the event system.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from src.config import settings
from src.schemas.events import EventType, SystemEvent

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AlertRule:
    """A single alert rule that maps event conditions to notifications."""

    name: str
    event_types: list[EventType]
    condition: Callable[[SystemEvent], bool]
    template: str  # format string using event.data keys
    level: str  # "info", "warning", "critical"


# ── MVP alert rules ──────────────────────────────────────────────────

ALERT_RULES: list[AlertRule] = [
    AlertRule(
        name="Nuovo lead qualificato",
        event_types=[EventType.ELIGIBILITY_CHECKED],
        condition=lambda e: e.data.get("eligible_count", 0) > 0,
        template=(
            "\u2705 <b>Nuovo lead qualificato</b>\n"
            "Prodotti idonei: {eligible_count}\n"
            "Sessione: <code>{session_id}</code>"
        ),
        level="info",
    ),
    AlertRule(
        name="OCR bassa confidenza",
        event_types=[EventType.OCR_COMPLETED],
        condition=lambda e: e.data.get("overall_confidence", 1.0) < 0.70,
        template=(
            "\u26a0\ufe0f <b>OCR bassa confidenza</b>\n"
            "Confidenza: {overall_confidence:.0%}\n"
            "Tipo doc: {doc_type}\n"
            "Sessione: <code>{session_id}</code>"
        ),
        level="warning",
    ),
    AlertRule(
        name="OCR fallito",
        event_types=[EventType.OCR_FAILED],
        condition=lambda _: True,
        template=(
            "\u274c <b>OCR fallito</b>\n"
            "Errore: {error}\n"
            "Sessione: <code>{session_id}</code>"
        ),
        level="critical",
    ),
    AlertRule(
        name="LLM timeout",
        event_types=[EventType.LLM_ERROR],
        condition=lambda e: "timeout" in str(e.data.get("error", "")),
        template=(
            "\u23f1 <b>LLM timeout</b>\n"
            "Modello: {model}\n"
            "Latenza: {latency_ms}ms"
        ),
        level="critical",
    ),
    AlertRule(
        name="Escalation umana",
        event_types=[EventType.SESSION_ESCALATED],
        condition=lambda _: True,
        template=(
            "\U0001f6a8 <b>Escalation umana richiesta</b>\n"
            "Sessione: <code>{session_id}</code>"
        ),
        level="critical",
    ),
    AlertRule(
        name="Errore di sistema",
        event_types=[EventType.SYSTEM_ERROR],
        condition=lambda _: True,
        template=(
            "\U0001f4a5 <b>Errore di sistema</b>\n"
            "Errore: {error}\n"
            "Modulo: {source_module}"
        ),
        level="critical",
    ),
    AlertRule(
        name="Richiesta eliminazione dati",
        event_types=[EventType.DELETION_REQUESTED],
        condition=lambda _: True,
        template=(
            "\U0001f5d1 <b>Richiesta eliminazione dati (GDPR)</b>\n"
            "Sessione: <code>{session_id}</code>"
        ),
        level="critical",
    ),
]


class AlertEngine:
    """Evaluates events against alert rules and pushes matching alerts."""

    def __init__(self) -> None:
        self._send_fn: Callable[[int, str], Coroutine[Any, Any, None]] | None = None

    @property
    def watched_types(self) -> list[EventType]:
        """Event types this engine cares about — for targeted subscription."""
        types: set[EventType] = set()
        for rule in ALERT_RULES:
            types.update(rule.event_types)
        return list(types)

    def set_send_fn(self, fn: Callable[[int, str], Coroutine[Any, Any, None]]) -> None:
        """Inject the send function (typically admin bot's send_to_admin)."""
        self._send_fn = fn

    async def on_event(self, event: SystemEvent) -> None:
        """Evaluate event against all rules and push matching alerts.

        Never raises — failures are logged and swallowed.
        """
        if self._send_fn is None:
            return

        for rule in ALERT_RULES:
            if event.event_type not in rule.event_types:
                continue
            try:
                if not rule.condition(event):
                    continue
            except Exception:
                logger.exception("Alert rule condition failed: %s", rule.name)
                continue

            # Build template context from event data + top-level fields
            ctx: dict[str, Any] = {**event.data}
            if event.session_id is not None:
                ctx.setdefault("session_id", str(event.session_id)[:8])
            if event.source_module is not None:
                ctx.setdefault("source_module", event.source_module)

            try:
                message = rule.template.format(**ctx)
            except KeyError:
                # Missing keys in template — send what we can
                message = f"{rule.template}\n\n(dati parziali: {ctx})"

            await self._push_alert(message)

    async def _push_alert(self, message: str) -> None:
        """Send alert message to all admin IDs."""
        if self._send_fn is None:
            return

        for admin_id in settings.telegram.admin_ids:
            try:
                await self._send_fn(admin_id, message)
            except Exception:
                logger.exception("Failed to send alert to admin %d", admin_id)


# Module-level singleton
alert_engine = AlertEngine()
