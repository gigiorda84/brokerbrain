"""Tests for the WhatsApp channel adapter."""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.channels.whatsapp import (
    _verify_signature,
    send_whatsapp_message,
    whatsapp_router,
)


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _mock_rate_limiter():
    """Prevent real Redis calls from the rate limiter in all tests."""
    with patch("src.channels.whatsapp.rate_limiter") as rl:
        rl.check = AsyncMock(return_value=(True, 0))
        yield rl


@pytest.fixture()
def _wa_configured():
    """Patch settings so WhatsApp appears configured."""
    with patch("src.channels.whatsapp.settings") as mock_settings:
        mock_settings.whatsapp.whatsapp_api_url = "https://graph.facebook.com/v18.0/123456"
        mock_settings.whatsapp.whatsapp_api_token = "test_token"
        mock_settings.whatsapp.whatsapp_verify_token = "my_verify_token"
        mock_settings.whatsapp.whatsapp_app_secret = ""
        yield mock_settings


@pytest.fixture()
def _wa_configured_with_secret():
    """Patch settings with app secret for signature verification."""
    with patch("src.channels.whatsapp.settings") as mock_settings:
        mock_settings.whatsapp.whatsapp_api_url = "https://graph.facebook.com/v18.0/123456"
        mock_settings.whatsapp.whatsapp_api_token = "test_token"
        mock_settings.whatsapp.whatsapp_verify_token = "my_verify_token"
        mock_settings.whatsapp.whatsapp_app_secret = "test_secret"
        yield mock_settings


@pytest.fixture()
def client():
    """FastAPI test client with just the WhatsApp router."""
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(whatsapp_router)
    return TestClient(app)


def _make_wa_payload(
    wa_id: str = "393331234567",
    msg_type: str = "text",
    text: str = "Buongiorno",
    name: str = "Mario Rossi",
    interactive: dict | None = None,
    image_id: str | None = None,
    document_id: str | None = None,
) -> dict:
    """Build a minimal Meta webhook payload."""
    message: dict = {"from": wa_id, "id": "wamid.abc123", "type": msg_type, "timestamp": "1700000000"}

    if msg_type == "text":
        message["text"] = {"body": text}
    elif msg_type == "interactive" and interactive:
        message["interactive"] = interactive
    elif msg_type == "image":
        message["image"] = {"id": image_id or "img_123", "caption": text}
    elif msg_type == "document":
        message["document"] = {"id": document_id or "doc_456", "caption": text}

    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "BIZ_ACCOUNT_ID",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "15550001234", "phone_number_id": "123456"},
                    "contacts": [{"profile": {"name": name}, "wa_id": wa_id}],
                    "messages": [message],
                },
                "field": "messages",
            }],
        }],
    }


def _sign_payload(payload: dict, secret: str) -> str:
    """Compute X-Hub-Signature-256 for a payload."""
    body = json.dumps(payload).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


# ── Webhook verification tests ───────────────────────────────────────

@pytest.mark.usefixtures("_wa_configured")
class TestWebhookVerification:
    def test_verify_success(self, client):
        resp = client.get(
            "/webhook/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "my_verify_token",
                "hub.challenge": "challenge_123",
            },
        )
        assert resp.status_code == 200
        assert resp.text == "challenge_123"

    def test_verify_wrong_token(self, client):
        resp = client.get(
            "/webhook/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong_token",
                "hub.challenge": "challenge_123",
            },
        )
        assert resp.status_code == 403

    def test_verify_wrong_mode(self, client):
        resp = client.get(
            "/webhook/whatsapp",
            params={
                "hub.mode": "unsubscribe",
                "hub.verify_token": "my_verify_token",
                "hub.challenge": "challenge_123",
            },
        )
        assert resp.status_code == 403

    def test_verify_not_configured(self, client):
        """When WhatsApp is not configured, returns 503."""
        with patch("src.channels.whatsapp.settings") as mock_settings:
            mock_settings.whatsapp.whatsapp_api_url = ""
            mock_settings.whatsapp.whatsapp_api_token = ""
            mock_settings.whatsapp.whatsapp_verify_token = ""
            mock_settings.whatsapp.whatsapp_app_secret = ""

            resp = client.get(
                "/webhook/whatsapp",
                params={
                    "hub.mode": "subscribe",
                    "hub.verify_token": "my_verify_token",
                    "hub.challenge": "test",
                },
            )
            assert resp.status_code == 503


# ── Signature verification tests ─────────────────────────────────────

class TestSignatureVerification:
    def test_valid_signature(self):
        with patch("src.channels.whatsapp.settings") as mock_settings:
            mock_settings.whatsapp.whatsapp_app_secret = "my_secret"
            payload = b'{"test": true}'
            sig = "sha256=" + hmac.new(b"my_secret", payload, hashlib.sha256).hexdigest()
            assert _verify_signature(payload, sig) is True

    def test_invalid_signature(self):
        with patch("src.channels.whatsapp.settings") as mock_settings:
            mock_settings.whatsapp.whatsapp_app_secret = "my_secret"
            assert _verify_signature(b'{"test": true}', "sha256=bad") is False

    def test_missing_prefix(self):
        with patch("src.channels.whatsapp.settings") as mock_settings:
            mock_settings.whatsapp.whatsapp_app_secret = "my_secret"
            assert _verify_signature(b'{"test": true}', "nope") is False

    def test_no_secret_dev_mode(self):
        with patch("src.channels.whatsapp.settings") as mock_settings:
            mock_settings.whatsapp.whatsapp_app_secret = ""
            assert _verify_signature(b"anything", "anything") is True


# ── Message routing tests ────────────────────────────────────────────

@pytest.mark.usefixtures("_wa_configured")
class TestMessageRouting:
    @pytest.mark.asyncio()
    async def test_text_message_routes_to_engine(self, client):
        """Text message is parsed and sent to the conversation engine."""
        payload = _make_wa_payload(text="Buongiorno")

        with (
            patch("src.channels.whatsapp._handle_whatsapp_message", new_callable=AsyncMock) as mock_handler,
        ):
            resp = client.post("/webhook/whatsapp", json=payload)
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"

            # Give the asyncio.create_task a moment
            import asyncio
            await asyncio.sleep(0.1)

    def test_post_not_configured_returns_status(self, client):
        with patch("src.channels.whatsapp.settings") as mock_settings:
            mock_settings.whatsapp.whatsapp_api_url = ""
            mock_settings.whatsapp.whatsapp_api_token = ""
            mock_settings.whatsapp.whatsapp_verify_token = ""
            mock_settings.whatsapp.whatsapp_app_secret = ""

            resp = client.post("/webhook/whatsapp", json={"object": "whatsapp_business_account", "entry": []})
            assert resp.json()["status"] == "not_configured"

    def test_invalid_signature_rejected(self, client):
        with patch("src.channels.whatsapp.settings") as mock_settings:
            mock_settings.whatsapp.whatsapp_api_url = "https://graph.facebook.com/v18.0/123456"
            mock_settings.whatsapp.whatsapp_api_token = "test_token"
            mock_settings.whatsapp.whatsapp_verify_token = "my_verify_token"
            mock_settings.whatsapp.whatsapp_app_secret = "real_secret"

            payload = {"object": "whatsapp_business_account", "entry": []}
            resp = client.post(
                "/webhook/whatsapp",
                json=payload,
                headers={"X-Hub-Signature-256": "sha256=invalid"},
            )
            assert resp.json()["status"] == "invalid_signature"


# ── Message parsing tests ────────────────────────────────────────────

class TestMessageParsing:
    @pytest.mark.asyncio()
    async def test_text_message_parsed(self):
        """Plain text message is extracted correctly."""
        message = {"from": "393331234567", "type": "text", "text": {"body": "Ciao"}}

        with (
            patch("src.channels.whatsapp._is_configured", return_value=True),
            patch("src.channels.whatsapp.settings") as mock_settings,
            patch("src.channels.whatsapp.async_session_factory") as mock_factory,
            patch("src.channels.whatsapp.conversation_engine") as mock_engine,
            patch("src.channels.whatsapp.send_whatsapp_message", new_callable=AsyncMock) as mock_send,
        ):
            mock_settings.whatsapp.whatsapp_api_url = "https://graph.facebook.com/v18.0/123456"
            mock_settings.whatsapp.whatsapp_api_token = "test_token"
            mock_settings.whatsapp.whatsapp_app_secret = ""

            mock_db = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_engine.process_message = AsyncMock(return_value="Benvenuto!")

            from src.channels.whatsapp import _handle_whatsapp_message
            await _handle_whatsapp_message(message, {"393331234567": "Mario"})

            mock_engine.process_message.assert_awaited_once()
            call_kwargs = mock_engine.process_message.call_args.kwargs
            assert call_kwargs["channel_user_id"] == "393331234567"
            assert call_kwargs["channel"] == "whatsapp"
            assert call_kwargs["text"] == "Ciao"
            assert call_kwargs["first_name"] == "Mario"

            mock_send.assert_awaited_once_with("393331234567", "Benvenuto!")

    @pytest.mark.asyncio()
    async def test_interactive_button_reply(self):
        """Interactive button reply extracts the button title as text."""
        message = {
            "from": "393331234567",
            "type": "interactive",
            "interactive": {
                "type": "button_reply",
                "button_reply": {"id": "btn_1", "title": "Sì, confermo"},
            },
        }

        with (
            patch("src.channels.whatsapp.settings") as mock_settings,
            patch("src.channels.whatsapp.async_session_factory") as mock_factory,
            patch("src.channels.whatsapp.conversation_engine") as mock_engine,
            patch("src.channels.whatsapp.send_whatsapp_message", new_callable=AsyncMock),
        ):
            mock_settings.whatsapp.whatsapp_api_url = "https://graph.facebook.com/v18.0/123456"
            mock_settings.whatsapp.whatsapp_api_token = "test_token"
            mock_settings.whatsapp.whatsapp_app_secret = ""

            mock_db = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_engine.process_message = AsyncMock(return_value="Ok!")

            from src.channels.whatsapp import _handle_whatsapp_message
            await _handle_whatsapp_message(message, {})

            call_kwargs = mock_engine.process_message.call_args.kwargs
            assert call_kwargs["text"] == "Sì, confermo"

    @pytest.mark.asyncio()
    async def test_interactive_list_reply(self):
        """Interactive list reply extracts the list item title as text."""
        message = {
            "from": "393331234567",
            "type": "interactive",
            "interactive": {
                "type": "list_reply",
                "list_reply": {"id": "opt_2", "title": "Cessione del quinto"},
            },
        }

        with (
            patch("src.channels.whatsapp.settings") as mock_settings,
            patch("src.channels.whatsapp.async_session_factory") as mock_factory,
            patch("src.channels.whatsapp.conversation_engine") as mock_engine,
            patch("src.channels.whatsapp.send_whatsapp_message", new_callable=AsyncMock),
        ):
            mock_settings.whatsapp.whatsapp_api_url = "https://graph.facebook.com/v18.0/123456"
            mock_settings.whatsapp.whatsapp_api_token = "test_token"
            mock_settings.whatsapp.whatsapp_app_secret = ""

            mock_db = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_engine.process_message = AsyncMock(return_value="Ok!")

            from src.channels.whatsapp import _handle_whatsapp_message
            await _handle_whatsapp_message(message, {})

            call_kwargs = mock_engine.process_message.call_args.kwargs
            assert call_kwargs["text"] == "Cessione del quinto"

    @pytest.mark.asyncio()
    async def test_unsupported_type_sends_fallback(self):
        """Unsupported message types get a helpful Italian fallback."""
        message = {"from": "393331234567", "type": "sticker"}

        with patch("src.channels.whatsapp.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
            from src.channels.whatsapp import _handle_whatsapp_message
            await _handle_whatsapp_message(message, {})

            mock_send.assert_awaited_once()
            text = mock_send.call_args.args[1]
            assert "messaggi di testo" in text

    @pytest.mark.asyncio()
    async def test_image_message_downloads_media(self):
        """Image messages trigger media download and pass bytes to engine."""
        message = {
            "from": "393331234567",
            "type": "image",
            "image": {"id": "media_789", "caption": "Busta paga"},
        }

        with (
            patch("src.channels.whatsapp.settings") as mock_settings,
            patch("src.channels.whatsapp.async_session_factory") as mock_factory,
            patch("src.channels.whatsapp.conversation_engine") as mock_engine,
            patch("src.channels.whatsapp.send_whatsapp_message", new_callable=AsyncMock),
            patch("src.channels.whatsapp._download_whatsapp_media", new_callable=AsyncMock) as mock_dl,
        ):
            mock_settings.whatsapp.whatsapp_api_url = "https://graph.facebook.com/v18.0/123456"
            mock_settings.whatsapp.whatsapp_api_token = "test_token"
            mock_settings.whatsapp.whatsapp_app_secret = ""
            mock_settings.rate_limit.upload_rate_limit = 5
            mock_settings.rate_limit.upload_rate_window = 60
            mock_settings.rate_limit.upload_max_size_bytes = 5_242_880

            mock_db = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_engine.process_message = AsyncMock(return_value="Documento ricevuto!")
            mock_dl.return_value = b"\xff\xd8fake-jpeg"

            from src.channels.whatsapp import _handle_whatsapp_message
            await _handle_whatsapp_message(message, {})

            mock_dl.assert_awaited_once_with("media_789")
            call_kwargs = mock_engine.process_message.call_args.kwargs
            assert call_kwargs["image_bytes"] == b"\xff\xd8fake-jpeg"
            assert call_kwargs["text"] == "Busta paga"


# ── Message sending tests ────────────────────────────────────────────

class TestMessageSending:
    @pytest.mark.asyncio()
    async def test_send_text_message_payload(self):
        """send_whatsapp_message builds the correct Cloud API payload."""
        with patch("src.channels.whatsapp.settings") as mock_settings:
            mock_settings.whatsapp.whatsapp_api_url = "https://graph.facebook.com/v18.0/123456"
            mock_settings.whatsapp.whatsapp_api_token = "test_token"

            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_resp = AsyncMock()
                mock_resp.raise_for_status = lambda: None
                mock_client.post = AsyncMock(return_value=mock_resp)
                mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

                result = await send_whatsapp_message("393331234567", "Ciao!")
                assert result is True

                call_kwargs = mock_client.post.call_args
                payload = call_kwargs.kwargs["json"]
                assert payload["messaging_product"] == "whatsapp"
                assert payload["to"] == "393331234567"
                assert payload["type"] == "text"
                assert payload["text"]["body"] == "Ciao!"


# ── Keyword command tests ────────────────────────────────────────────

class TestKeywordCommands:
    @pytest.mark.asyncio()
    async def test_operatore_keyword(self):
        """'operatore' keyword sends operator info without hitting engine."""
        message = {"from": "393331234567", "type": "text", "text": {"body": "operatore"}}

        with patch("src.channels.whatsapp.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
            from src.channels.whatsapp import _handle_whatsapp_message
            await _handle_whatsapp_message(message, {})

            mock_send.assert_awaited_once()
            text = mock_send.call_args.args[1]
            assert "800.99.00.90" in text

    @pytest.mark.asyncio()
    async def test_elimina_dati_keyword(self):
        """'elimina dati' keyword sends GDPR info without hitting engine."""
        message = {"from": "393331234567", "type": "text", "text": {"body": "elimina dati"}}

        with patch("src.channels.whatsapp.send_whatsapp_message", new_callable=AsyncMock) as mock_send:
            from src.channels.whatsapp import _handle_whatsapp_message
            await _handle_whatsapp_message(message, {})

            mock_send.assert_awaited_once()
            text = mock_send.call_args.args[1]
            assert "privacy@primonetwork.it" in text

    @pytest.mark.asyncio()
    async def test_nuova_keyword_closes_session(self):
        """'nuova' keyword closes active session and sends /start."""
        message = {"from": "393331234567", "type": "text", "text": {"body": "nuova"}}

        with (
            patch("src.channels.whatsapp.settings") as mock_settings,
            patch("src.channels.whatsapp._close_active_whatsapp_session", new_callable=AsyncMock) as mock_close,
            patch("src.channels.whatsapp.async_session_factory") as mock_factory,
            patch("src.channels.whatsapp.conversation_engine") as mock_engine,
            patch("src.channels.whatsapp.send_whatsapp_message", new_callable=AsyncMock),
        ):
            mock_settings.whatsapp.whatsapp_api_url = "https://graph.facebook.com/v18.0/123456"
            mock_settings.whatsapp.whatsapp_api_token = "test_token"
            mock_settings.whatsapp.whatsapp_app_secret = ""

            mock_db = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_engine.process_message = AsyncMock(return_value="Benvenuto!")
            mock_close.return_value = True

            from src.channels.whatsapp import _handle_whatsapp_message
            await _handle_whatsapp_message(message, {})

            mock_close.assert_awaited_once_with("393331234567")
            call_kwargs = mock_engine.process_message.call_args.kwargs
            assert call_kwargs["text"] == "/start"


# ── Multi-channel user creation test ─────────────────────────────────

class TestMultiChannelEngine:
    @pytest.mark.asyncio()
    async def test_whatsapp_user_creation(self):
        """Engine creates user with whatsapp_id and phone when channel=whatsapp."""
        from src.conversation.engine import ConversationEngine

        engine = ConversationEngine()
        mock_db = AsyncMock()

        # scalar_one_or_none is synchronous on the Result object — use MagicMock
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        user = await engine.get_or_create_user(mock_db, "whatsapp", "393331234567", "Mario")

        # Verify the User was created with correct fields
        assert mock_db.add.called
        added_user = mock_db.add.call_args.args[0]
        assert added_user.whatsapp_id == "393331234567"
        assert added_user.phone == "393331234567"
        assert added_user.channel == "whatsapp"
        assert added_user.first_name == "Mario"

    @pytest.mark.asyncio()
    async def test_telegram_user_creation(self):
        """Engine creates user with telegram_id when channel=telegram."""
        from src.conversation.engine import ConversationEngine

        engine = ConversationEngine()
        mock_db = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        user = await engine.get_or_create_user(mock_db, "telegram", "12345", "Luigi")

        added_user = mock_db.add.call_args.args[0]
        assert added_user.telegram_id == "12345"
        assert added_user.channel == "telegram"
        assert added_user.first_name == "Luigi"
        assert added_user.whatsapp_id is None
