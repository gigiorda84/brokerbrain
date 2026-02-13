"""Event emitter and subscriber system.

Async pub/sub for SystemEvents. Every action in BrokerBot emits events
that are consumed by AuditLogger, AdminBot, and AlertEngine.

Usage:
    # Emit an event from anywhere:
    from src.admin.events import emit

    await emit(SystemEvent(
        event_type=EventType.SESSION_STARTED,
        session_id=session.id,
        data={"channel": "telegram"},
    ))

    # Register a subscriber at startup:
    from src.admin.events import subscribe

    subscribe(my_handler)  # async def my_handler(event: SystemEvent) -> None
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from src.schemas.events import EventType, SystemEvent

logger = logging.getLogger(__name__)

# Type alias for event handler functions
EventHandler = Callable[[SystemEvent], Coroutine[Any, Any, None]]

# ── Internal state ───────────────────────────────────────────────────

_subscribers: list[EventHandler] = []
_type_subscribers: dict[EventType, list[EventHandler]] = {}
_queue: asyncio.Queue[SystemEvent] | None = None
_worker_task: asyncio.Task[None] | None = None


# ── Public API ───────────────────────────────────────────────────────


def subscribe(handler: EventHandler, event_types: list[EventType] | None = None) -> None:
    """Register an event handler.

    Args:
        handler: Async function that accepts a SystemEvent.
        event_types: If provided, handler only receives these event types.
                     If None, handler receives ALL events.
    """
    if event_types is None:
        _subscribers.append(handler)
        logger.info("Registered global event subscriber: %s", handler.__name__)
    else:
        for et in event_types:
            _type_subscribers.setdefault(et, []).append(handler)
        logger.info(
            "Registered event subscriber %s for types: %s",
            handler.__name__,
            [t.value for t in event_types],
        )


def unsubscribe(handler: EventHandler) -> None:
    """Remove a previously registered handler."""
    if handler in _subscribers:
        _subscribers.remove(handler)
    for handlers in _type_subscribers.values():
        if handler in handlers:
            handlers.remove(handler)


async def emit(event: SystemEvent) -> None:
    """Publish a SystemEvent to all subscribers.

    Events are placed on an async queue and processed by a background worker
    so the emitter is never blocked by slow subscribers.
    """
    global _queue
    if _queue is None:
        _queue = asyncio.Queue()
        _ensure_worker()

    await _queue.put(event)
    logger.debug("Event emitted: %s (session=%s)", event.event_type.value, event.session_id)


async def emit_nowait(event: SystemEvent) -> None:
    """Fire-and-forget emit — dispatches directly without queueing.

    Use sparingly; prefer `emit()` for production code.
    """
    await _dispatch(event)


# ── Background worker ────────────────────────────────────────────────


def _ensure_worker() -> None:
    """Start the background event worker if not already running."""
    global _worker_task
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(_event_worker())
        logger.info("Event worker started")


async def _event_worker() -> None:
    """Background task that drains the event queue and dispatches to subscribers."""
    global _queue
    if _queue is None:
        return

    while True:
        try:
            event = await _queue.get()
            await _dispatch(event)
            _queue.task_done()
        except asyncio.CancelledError:
            logger.info("Event worker shutting down")
            break
        except Exception:
            logger.exception("Error in event worker")


async def _dispatch(event: SystemEvent) -> None:
    """Dispatch a single event to all matching subscribers."""
    handlers: list[EventHandler] = list(_subscribers)

    # Add type-specific subscribers
    if event.event_type in _type_subscribers:
        handlers.extend(_type_subscribers[event.event_type])

    if not handlers:
        return

    # Run all handlers concurrently; isolate failures
    results = await asyncio.gather(
        *[_safe_call(handler, event) for handler in handlers],
        return_exceptions=True,
    )
    for result in results:
        if isinstance(result, Exception):
            logger.error("Event handler failed for %s: %s", event.event_type.value, result)


async def _safe_call(handler: EventHandler, event: SystemEvent) -> None:
    """Call a handler with error isolation."""
    try:
        await handler(event)
    except Exception:
        logger.exception("Handler %s failed for event %s", handler.__name__, event.event_type.value)
        raise


# ── Lifecycle ────────────────────────────────────────────────────────


async def start_event_system() -> None:
    """Initialize the event system. Call during FastAPI lifespan startup."""
    global _queue
    _queue = asyncio.Queue()
    _ensure_worker()
    logger.info(
        "Event system started with %d global + %d typed subscribers",
        len(_subscribers),
        sum(len(v) for v in _type_subscribers.values()),
    )


async def stop_event_system() -> None:
    """Gracefully stop the event system. Call during FastAPI lifespan shutdown."""
    global _worker_task, _queue

    if _queue is not None:
        # Drain remaining events
        await _queue.join()

    if _worker_task is not None and not _worker_task.done():
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass

    _worker_task = None
    _queue = None
    logger.info("Event system stopped")
