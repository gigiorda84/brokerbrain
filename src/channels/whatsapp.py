"""WhatsApp Business API adapter — receives webhooks from Meta Cloud API.

Handles:
- GET  /webhook/whatsapp  → Meta verification handshake
- POST /webhook/whatsapp  → Incoming messages (text, interactive, image, document)

Sends responses via the WhatsApp Cloud API (graph.facebook.com).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging

import httpx
from fastapi import APIRouter, Query, Request, Response

from src.config import settings
from src.conversation.engine import conversation_engine
from src.db.engine import async_session_factory
from src.models.enums import ConversationState, SessionOutcome
from src.models.session import Session
from src.models.user import User

from sqlalchemy import select

logger = logging.getLogger(__name__)

whatsapp_router = APIRouter(prefix="/webhook", tags=["whatsapp"])

# ── Helpers ──────────────────────────────────────────────────────────


def _is_configured() -> bool:
    """Check if WhatsApp settings are present."""
    wa = settings.whatsapp
    return bool(wa.whatsapp_api_url and wa.whatsapp_api_token and wa.whatsapp_verify_token)


def _verify_signature(payload: bytes, signature_header: str) -> bool:
    """Verify X-Hub-Signature-256 from Meta.

    If whatsapp_app_secret is not configured (dev mode), skip verification.
    """
    app_secret = settings.whatsapp.whatsapp_app_secret
    if not app_secret:
        return True  # Dev mode — no secret configured

    if not signature_header.startswith("sha256="):
        return False

    expected = hmac.new(
        app_secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    received = signature_header[7:]  # Strip "sha256=" prefix
    return hmac.compare_digest(expected, received)


def _auth_headers() -> dict[str, str]:
    """Build Authorization header for WhatsApp Cloud API calls."""
    return {
        "Authorization": f"Bearer {settings.whatsapp.whatsapp_api_token}",
        "Content-Type": "application/json",
    }


# ── Webhook endpoints ────────────────────────────────────────────────


@whatsapp_router.get("/whatsapp")
async def verify_webhook(
    response: Response,
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
) -> Response:
    """Meta webhook verification handshake (GET).

    Meta sends hub.mode=subscribe, hub.verify_token, hub.challenge.
    We return the challenge if the token matches.
    """
    if not _is_configured():
        return Response(content="WhatsApp not configured", status_code=503)

    if (
        hub_mode == "subscribe"
        and hub_verify_token == settings.whatsapp.whatsapp_verify_token
        and hub_challenge is not None
    ):
        logger.info("WhatsApp webhook verified successfully")
        return Response(content=hub_challenge, media_type="text/plain")

    logger.warning("WhatsApp webhook verification failed: mode=%s", hub_mode)
    return Response(content="Verification failed", status_code=403)


@whatsapp_router.post("/whatsapp")
async def receive_webhook(request: Request) -> dict[str, str]:
    """Receive incoming WhatsApp messages (POST).

    Meta sends a nested JSON payload. We extract messages and process
    them asynchronously to return 200 quickly (Meta retries on timeout).
    """
    if not _is_configured():
        return {"status": "not_configured"}

    # Verify signature
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not _verify_signature(body, signature):
        logger.warning("WhatsApp webhook signature verification failed")
        return {"status": "invalid_signature"}

    payload = await request.json()

    # Extract messages from Meta's nested structure
    # payload.object == "whatsapp_business_account"
    # payload.entry[].changes[].value.messages[]
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            messages = value.get("messages", [])
            contacts = value.get("contacts", [])

            # Build a contact name lookup
            contact_names: dict[str, str] = {}
            for contact in contacts:
                wa_id = contact.get("wa_id", "")
                profile = contact.get("profile", {})
                contact_names[wa_id] = profile.get("name", "")

            for message in messages:
                asyncio.create_task(
                    _handle_whatsapp_message(message, contact_names)
                )

    return {"status": "ok"}


# ── Message handling ─────────────────────────────────────────────────


async def _handle_whatsapp_message(
    message: dict,
    contact_names: dict[str, str],
) -> None:
    """Route a single WhatsApp message to the conversation engine."""
    wa_id = message.get("from", "")
    msg_type = message.get("type", "")
    first_name = contact_names.get(wa_id, "")

    text = ""
    image_bytes: bytes | None = None

    if msg_type == "text":
        text = message.get("text", {}).get("body", "")
    elif msg_type == "interactive":
        interactive = message.get("interactive", {})
        interactive_type = interactive.get("type", "")
        if interactive_type == "button_reply":
            text = interactive.get("button_reply", {}).get("title", "")
        elif interactive_type == "list_reply":
            text = interactive.get("list_reply", {}).get("title", "")
    elif msg_type == "image":
        media_id = message.get("image", {}).get("id", "")
        text = message.get("image", {}).get("caption", "[documento inviato]")
        if media_id:
            image_bytes = await _download_whatsapp_media(media_id)
    elif msg_type == "document":
        media_id = message.get("document", {}).get("id", "")
        text = message.get("document", {}).get("caption", "[documento inviato]")
        if media_id:
            image_bytes = await _download_whatsapp_media(media_id)
    else:
        # Unsupported message type — send a helpful fallback
        await send_whatsapp_message(
            wa_id,
            "Mi scusi, al momento posso ricevere solo messaggi di testo, immagini e documenti. "
            "Può riscrivere il suo messaggio?",
        )
        return

    if not text and image_bytes is None:
        return

    # Map WhatsApp keyword "commands" (no /commands on WhatsApp)
    text_lower = text.strip().lower()
    if text_lower == "nuova":
        await _close_active_whatsapp_session(wa_id)
        text = "/start"
    elif text_lower == "operatore":
        await send_whatsapp_message(
            wa_id,
            "La metto in contatto con un consulente di Primo Network.\n\n"
            "Può chiamare il numero verde 800.99.00.90 (lun-ven 9-18)\n"
            "oppure scrivere a info@primonetwork.it.\n\n"
            "Un operatore la ricontatterà al più presto.",
        )
        return
    elif text_lower == "elimina dati":
        await send_whatsapp_message(
            wa_id,
            "Per richiedere la cancellazione dei suoi dati personali (GDPR Art. 17), "
            "scriva a privacy@primonetwork.it indicando il suo numero di telefono.\n\n"
            "La richiesta sarà elaborata entro 30 giorni.",
        )
        return

    # Process through conversation engine
    try:
        async with async_session_factory() as db:
            response = await conversation_engine.process_message(
                db=db,
                channel_user_id=wa_id,
                text=text or "",
                first_name=first_name or None,
                image_bytes=image_bytes,
                channel="whatsapp",
            )
            await db.commit()
    except Exception:
        logger.exception("Error processing WhatsApp message from %s", wa_id)
        response = (
            "Mi scusi, si è verificato un errore. "
            "Riprovi tra qualche istante o chiami il 800.99.00.90."
        )

    await send_whatsapp_message(wa_id, response)


# ── Media download ───────────────────────────────────────────────────


async def _download_whatsapp_media(media_id: str) -> bytes | None:
    """Download media from WhatsApp Cloud API (two-step: metadata → bytes).

    Step 1: GET /{media_id} → returns JSON with {"url": "..."}
    Step 2: GET url → returns raw bytes
    """
    base_url = settings.whatsapp.whatsapp_api_url.rstrip("/")
    # The media endpoint is on graph.facebook.com, not the phone-number-scoped URL
    # Extract the base: https://graph.facebook.com/v18.0
    parts = base_url.split("/")
    # e.g. ['https:', '', 'graph.facebook.com', 'v18.0', 'YOUR_PHONE_ID']
    graph_base = "/".join(parts[:4]) if len(parts) >= 4 else base_url

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Step 1: Get media URL
            meta_resp = await client.get(
                f"{graph_base}/{media_id}",
                headers=_auth_headers(),
            )
            meta_resp.raise_for_status()
            media_url = meta_resp.json().get("url", "")
            if not media_url:
                logger.warning("No URL in media metadata for %s", media_id)
                return None

            # Step 2: Download actual bytes
            data_resp = await client.get(
                media_url,
                headers=_auth_headers(),
            )
            data_resp.raise_for_status()
            return data_resp.content
    except Exception:
        logger.exception("Failed to download WhatsApp media %s", media_id)
        return None


# ── Message sending ──────────────────────────────────────────────────


async def send_whatsapp_message(to: str, text: str) -> bool:
    """Send a plain text message via WhatsApp Cloud API.

    Returns True on success, False on failure.
    """
    url = f"{settings.whatsapp.whatsapp_api_url.rstrip('/')}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload, headers=_auth_headers())
            resp.raise_for_status()
            return True
    except Exception:
        logger.exception("Failed to send WhatsApp message to %s", to)
        return False


async def send_whatsapp_interactive(
    to: str,
    body_text: str,
    buttons: list[dict[str, str]],
) -> bool:
    """Send an interactive button message via WhatsApp Cloud API.

    Args:
        to: Recipient WhatsApp ID.
        body_text: Message body text.
        buttons: List of dicts with "id" and "title" keys (max 3).

    Returns True on success, False on failure.
    """
    url = f"{settings.whatsapp.whatsapp_api_url.rstrip('/')}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {"id": btn["id"], "title": btn["title"]},
                    }
                    for btn in buttons[:3]  # WhatsApp max 3 buttons
                ],
            },
        },
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload, headers=_auth_headers())
            resp.raise_for_status()
            return True
    except Exception:
        logger.exception("Failed to send WhatsApp interactive to %s", to)
        return False


# ── Session management ───────────────────────────────────────────────


async def _close_active_whatsapp_session(wa_id: str) -> bool:
    """Mark the user's active session as ABANDONED and clear its Redis cache.

    Returns True if a session was closed, False if none was active.
    """
    from src.db.engine import redis_client

    async with async_session_factory() as db:
        result = await db.execute(
            select(Session)
            .join(User, Session.user_id == User.id)
            .where(User.whatsapp_id == wa_id)
            .where(Session.current_state.notin_([
                ConversationState.COMPLETED.value,
                ConversationState.ABANDONED.value,
                ConversationState.HUMAN_ESCALATION.value,
            ]))
            .order_by(Session.created_at.desc())
            .limit(1)
        )
        session = result.scalar_one_or_none()
        if session is None:
            return False

        session.current_state = ConversationState.ABANDONED.value
        session.outcome = SessionOutcome.ABANDONED.value
        await db.commit()

        try:
            await redis_client.delete(f"session:{session.id}:messages")
        except Exception:
            pass

        logger.info("Closed WhatsApp session %s for user %s", session.id, wa_id)
        return True
