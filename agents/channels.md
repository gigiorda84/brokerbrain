# Agent: Channels

## Domain
Messaging channel adapters: Telegram user bot, WhatsApp Business API. Message normalization, media handling, webhook endpoints.

## Context
BrokerBot communicates with users through WhatsApp and Telegram. Each channel has different APIs, message formats, and media handling. The channel layer normalizes everything into a common `IncomingMessage` schema that the conversation engine consumes, and converts `OutgoingMessage` into channel-specific formats.

## Key Decisions

### Abstract Channel Interface
```python
class ChannelAdapter(ABC):
    @abstractmethod
    async def send_message(self, user_id: str, message: OutgoingMessage) -> None: ...
    @abstractmethod
    async def send_media(self, user_id: str, media: MediaContent) -> None: ...
    @abstractmethod
    def parse_incoming(self, raw: dict) -> IncomingMessage: ...

class IncomingMessage(BaseModel):
    channel: Literal["telegram", "whatsapp"]
    user_id: str              # channel-specific user ID
    phone: str | None         # phone number (WhatsApp always has it; Telegram optional)
    text: str | None
    media_type: Literal["image", "document", "audio"] | None
    media_url: str | None     # URL or file_id to download
    media_bytes: bytes | None # downloaded content (populated by handler)
    timestamp: datetime
    raw: dict                 # original webhook payload for debugging

class OutgoingMessage(BaseModel):
    text: str
    reply_markup: dict | None = None  # buttons/quick replies
    media: MediaContent | None = None
```

### Telegram User Bot (`channels/telegram.py`)
- Uses `python-telegram-bot` v20+ (async)
- Runs alongside FastAPI via `Application.run_webhook()` or long-polling for dev
- Handles: text messages, photo uploads, document uploads
- Quick reply buttons via InlineKeyboard for structured choices (employment type, track choice, etc.)
- Commands: `/start`, `/elimina_dati`, `/i_miei_dati`, `/aiuto`, `/operatore`
- Phone number: not available by default on Telegram. Ask user during conversation, or request via contact sharing button.

```python
# Telegram sends photos as file_id → must download to get bytes
async def download_media(bot: Bot, file_id: str) -> bytes:
    file = await bot.get_file(file_id)
    bio = BytesIO()
    await file.download_to_memory(bio)
    return bio.getvalue()
```

### WhatsApp Business API (`channels/whatsapp.py`)
- Uses WhatsApp Business Cloud API (Meta) or on-premise API
- Webhook receives messages at `/webhook/whatsapp`
- Phone number always available (it's the user ID)
- Media: WhatsApp sends media_id → download via API → bytes
- Interactive messages: buttons (max 3), list messages (max 10 items)
- Session window: 24 hours after last user message (then need template message to re-engage)
- Template messages needed for: appointment reminders, follow-ups

```python
# WhatsApp webhook verification (GET request)
@app.get("/webhook/whatsapp")
async def verify_whatsapp(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    if mode == "subscribe" and token == settings.WHATSAPP_VERIFY_TOKEN:
        return Response(content=challenge, media_type="text/plain")
    raise HTTPException(403)
```

### Media Handling
- Images from WhatsApp/Telegram are downloaded to a temp directory
- Stored encrypted in `data/uploads/{session_id}/{uuid}.jpg`
- Passed to OCR pipeline as bytes
- Deleted after `DOCUMENT_RETENTION_DAYS` (30 days)
- Max file size: 10MB (reject larger with friendly message)
- Supported formats: JPEG, PNG, PDF, HEIC, WebP

### Message Flow
```
[Telegram/WhatsApp Webhook]
    → parse_incoming() → IncomingMessage
    → download media if present
    → conversation_engine.process_message(incoming)
    → OutgoingMessage
    → channel_adapter.send_message()
    → event emitted at each step
```

### Rate Limiting (per user)
- Max 60 messages per session per hour
- Max 8 document uploads per session
- Max 3 new sessions per phone per day
- Flood detection: > 10 messages/minute → "Sta inviando messaggi troppo rapidamente..."

## Dependencies
- `foundation` agent: event system, models, config
- `conversation` agent: process_message() is the main consumer

## Task Checklist
- [ ] `src/schemas/messages.py` — IncomingMessage, OutgoingMessage, MediaContent
- [ ] `src/channels/base.py` — Abstract ChannelAdapter
- [ ] `src/channels/telegram.py` — Telegram adapter: webhook/polling, send, receive, media download
- [ ] `src/channels/whatsapp.py` — WhatsApp adapter: webhook verification, send, receive, media download
- [ ] `src/main.py` — FastAPI app with webhook endpoints for both channels
- [ ] Rate limiting middleware
- [ ] Media storage: encrypted temp directory, cleanup job
- [ ] Tests: message parsing (Telegram format, WhatsApp format), media download mock
