"""Tests for the Telegram photo/document handler."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.channels.telegram import handle_photo_document


def _make_update(*, photo: bool = False, document: bool = False, caption: str | None = None):
    """Build a minimal mock Update with optional photo or document."""
    update = AsyncMock()
    update.effective_user.id = 12345
    update.effective_user.first_name = "Mario"

    # Default both to falsy
    update.message.photo = []
    update.message.document = None
    update.message.caption = caption

    if photo:
        photo_size = AsyncMock()
        file_mock = AsyncMock()
        file_mock.download_as_bytearray.return_value = bytearray(b"\xff\xd8fake-jpeg")
        photo_size.get_file.return_value = file_mock
        update.message.photo = [MagicMock(), photo_size]  # two sizes, last is largest

    if document:
        doc_mock = AsyncMock()
        file_mock = AsyncMock()
        file_mock.download_as_bytearray.return_value = bytearray(b"\x89PNGfake-png")
        doc_mock.get_file.return_value = file_mock
        update.message.document = doc_mock

    return update


@pytest.fixture()
def mock_engine():
    with patch("src.channels.telegram.conversation_engine") as engine:
        engine.process_message = AsyncMock(return_value="Documento ricevuto, grazie!")
        yield engine


@pytest.fixture()
def mock_db():
    with patch("src.channels.telegram.async_session_factory") as factory:
        session = AsyncMock()
        factory.return_value.__aenter__ = AsyncMock(return_value=session)
        factory.return_value.__aexit__ = AsyncMock(return_value=False)
        yield session


@pytest.mark.asyncio()
async def test_photo_downloads_largest_resolution(mock_db, mock_engine):
    """Photo handler grabs the last (largest) PhotoSize and passes bytes to engine."""
    update = _make_update(photo=True)
    context = AsyncMock()

    await handle_photo_document(update, context)

    # Should have called get_file on the *last* photo size
    update.message.photo[-1].get_file.assert_awaited_once()

    # Engine receives image bytes
    mock_engine.process_message.assert_awaited_once()
    call_kwargs = mock_engine.process_message.call_args.kwargs
    assert call_kwargs["image_bytes"] == b"\xff\xd8fake-jpeg"
    assert call_kwargs["telegram_id"] == "12345"
    assert call_kwargs["text"] == "[documento inviato]"


@pytest.mark.asyncio()
async def test_document_upload_passes_bytes(mock_db, mock_engine):
    """Document handler downloads and passes bytes to engine."""
    update = _make_update(document=True)
    context = AsyncMock()

    await handle_photo_document(update, context)

    update.message.document.get_file.assert_awaited_once()

    call_kwargs = mock_engine.process_message.call_args.kwargs
    assert call_kwargs["image_bytes"] == b"\x89PNGfake-png"


@pytest.mark.asyncio()
async def test_caption_forwarded_as_text(mock_db, mock_engine):
    """When a caption is present, it is used as the message text."""
    update = _make_update(photo=True, caption="Ecco la mia busta paga")
    context = AsyncMock()

    await handle_photo_document(update, context)

    call_kwargs = mock_engine.process_message.call_args.kwargs
    assert call_kwargs["text"] == "Ecco la mia busta paga"


@pytest.mark.asyncio()
async def test_download_failure_returns_error(mock_db, mock_engine):
    """When file download fails, user gets an Italian error message."""
    update = _make_update(photo=True)
    # Make download raise an exception
    file_mock = AsyncMock()
    file_mock.download_as_bytearray.side_effect = Exception("Network error")
    update.message.photo[-1].get_file.return_value = file_mock
    context = AsyncMock()

    await handle_photo_document(update, context)

    # Engine should NOT have been called
    mock_engine.process_message.assert_not_awaited()

    # User should get an error reply in Italian
    update.message.reply_text.assert_awaited_once()
    error_msg = update.message.reply_text.call_args.args[0]
    assert "non sono riuscito a scaricare" in error_msg


@pytest.mark.asyncio()
async def test_engine_error_returns_generic_error(mock_db, mock_engine):
    """When the engine raises, user gets the standard error message."""
    update = _make_update(photo=True)
    mock_engine.process_message.side_effect = Exception("Engine boom")
    context = AsyncMock()

    await handle_photo_document(update, context)

    error_msg = update.message.reply_text.call_args.args[0]
    assert "si è verificato un errore" in error_msg
