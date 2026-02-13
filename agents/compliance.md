# Agent: Compliance

## Domain
GDPR implementation, AI Act transparency, consent management, field-level encryption, data retention enforcement, right to erasure, audit logging, regulatory disclaimers.

## Context
BrokerBot operates under EU AI Act, GDPR, Italian Privacy Code, and Italian financial intermediation law (D.Lgs. 141/2010). The architecture is designed to enable compliance: all processing is local (no cloud LLMs), data is encrypted, every action is logged, and human oversight is built in. This agent handles the technical implementation of these requirements.

**Important:** Full legal compliance requires qualified legal counsel. This agent implements the technical controls; the legal texts (privacy policy, informativa, DPIA) are a separate workstream.

## Key Decisions

### Consent Management (`security/consent.py`)

Four consent types (matching Primo Network's own structure):

```python
class ConsentType(str, Enum):
    CONTRACTUAL = "finalita_contrattuali"       # Required to proceed
    SENSITIVE_DATA = "dati_sensibili"            # Required to proceed
    MARKETING_PN = "marketing_primo_network"     # Optional
    MARKETING_THIRD = "marketing_terzi"          # Optional

REQUIRED_CONSENTS = {ConsentType.CONTRACTUAL, ConsentType.SENSITIVE_DATA}
```

Consent is collected in the CONSENT state. Must be:
- **Unambiguous:** explicit "sì" or button press (no pre-checked boxes)
- **Specific:** each consent type explained separately
- **Informed:** link to full privacy policy
- **Revocable:** `/elimina_dati` at any time

Stored in `ConsentRecord` table: user_id, consent_type, granted, timestamp, method (message/button).

### AI Act Transparency

Implemented in conversation prompts (conversation agent), but compliance agent defines the requirements:

```python
AI_DISCLOSURE = (
    "🤖 Sta parlando con un assistente basato su intelligenza artificiale. "
    "Le valutazioni finali sono sempre confermate da un consulente qualificato "
    "di Primo Network."
)

ELIGIBILITY_DISCLAIMER = (
    "Questa è una verifica preliminare basata sui dati forniti. "
    "L'idoneità definitiva sarà confermata dal consulente Primo Network "
    "dopo un'analisi approfondita."
)

PRODUCT_DISCLAIMER = (
    "I tassi e le condizioni indicate sono a titolo orientativo e possono variare. "
    "Per le condizioni contrattuali definitive si rimanda alla documentazione "
    "fornita dagli istituti eroganti."
)

LEGAL_FOOTER = (
    "Servizio offerto da Primo Network Srl, mediatore creditizio iscritto all'OAM "
    "al n. M94. Via Vandalino 49, 10142 Torino. P.IVA 08154920014."
)
```

These are injected by the conversation engine at the right states (CONSENT, RESULT, PRODUCT_MATCHING).

### Field-Level Encryption (`security/encryption.py`)

PII fields are encrypted at the application level before DB storage:

```python
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import os, base64

class FieldEncryptor:
    def __init__(self, key: bytes):  # 32-byte AES-256 key
        self.aesgcm = AESGCM(key)

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a string field. Returns base64(nonce + ciphertext)."""
        nonce = os.urandom(12)
        ct = self.aesgcm.encrypt(nonce, plaintext.encode(), None)
        return base64.b64encode(nonce + ct).decode()

    def decrypt(self, token: str) -> str:
        """Decrypt a base64-encoded encrypted field."""
        data = base64.b64decode(token)
        nonce, ct = data[:12], data[12:]
        return self.aesgcm.decrypt(nonce, ct, None).decode()

# Fields that MUST be encrypted at rest:
ENCRYPTED_FIELDS = {
    "codice_fiscale",
    "partita_iva",
    "phone_number",
    "net_salary",
    "gross_salary",
    "net_pension",
    "gross_pension",
    "reddito_imponibile",
    "monthly_installment",
    "residual_amount",
}
```

### Right to Erasure (`security/erasure.py`)

`/elimina_dati` triggers a multi-step process:

```python
async def process_erasure_request(user_id: int, db: AsyncSession) -> ErasureResult:
    """
    GDPR Art. 17 — Right to erasure.
    1. Find all sessions for user
    2. Delete all documents (secure wipe: overwrite + unlink)
    3. Delete all extracted data
    4. Anonymize conversation transcripts (replace PII with [REDATTO])
    5. Anonymize user record (keep for audit, but scrub PII)
    6. Cancel any pending appointments
    7. Log erasure event (anonymized) in audit trail
    8. Notify admin via Telegram
    9. Send confirmation to user
    """
```

**Secure file deletion:**
```python
async def secure_delete_file(path: Path):
    """Overwrite file with random data, then delete."""
    if path.exists():
        size = path.stat().st_size
        with open(path, "wb") as f:
            f.write(os.urandom(size))
        path.unlink()
```

### Data Retention Enforcement

Cron job (or APScheduler) runs daily:

```python
async def enforce_data_retention():
    """
    - Documents older than 30 days → secure delete
    - Extracted data older than 12 months → hard delete from DB
    - Audit logs older than 24 months → archive then delete
    - Consent records: keep for duration of relationship + 5 years
    """
```

### Audit Logging (`security/audit.py`)

Every system event is persisted in the `AuditLog` table:

```python
class AuditLogSubscriber(EventSubscriber):
    async def on_event(self, event: SystemEvent):
        """Write event to audit log. Redact PII from event data."""
        sanitized = redact_pii(event.data)
        await self.db.execute(insert(AuditLog).values(
            event_type=event.event_type,
            session_id=event.session_id,
            actor_id=event.actor_id,
            actor_role=event.actor_role,
            data=sanitized,
            timestamp=event.timestamp,
        ))
```

**PII redaction in audit logs:**
CF, phone, email → hashed or masked. Financial amounts → kept (needed for audit). Names → kept in audit log (it's access-controlled), but redacted in anonymized exports.

### Admin Access Logging

Every admin action (view session, download dossier, search, intervene) is logged:

```python
async def log_admin_access(admin_id: int, action: str, target_entity: str, target_id: int):
    await db.execute(insert(AdminAccess).values(
        admin_id=admin_id,
        action=action,
        target_entity=target_entity,
        target_id=target_id,
        timestamp=datetime.utcnow(),
    ))
```

### Data Breach Detection

Basic breach indicators (to be expanded in Phase 2):
- Multiple failed admin auth attempts → alert
- Unusual data access patterns → alert
- Mass data export → alert
- Database connection from unexpected IP → alert

Breach response:
1. Alert admin immediately
2. Log incident with full details
3. Admin assesses severity
4. If personal data compromised: notify Garante within 72h, notify affected users if high risk

## Dependencies
- `foundation` agent: DB models, event system, config
- `conversation` agent: consumes disclaimer text, consent prompts
- `admin` agent: erasure notifications, audit log viewer

## Task Checklist
- [ ] `src/security/encryption.py` — AES-256-GCM field encryptor with encrypt/decrypt
- [ ] `src/security/consent.py` — ConsentManager: record, check, revoke, export
- [ ] `src/security/erasure.py` — ErasureProcessor: full /elimina_dati workflow
- [ ] `src/security/audit.py` — AuditLogSubscriber + PII redaction
- [ ] `src/security/retention.py` — Data retention cron job (documents, data, logs)
- [ ] Compliance text constants: AI_DISCLOSURE, disclaimers, LEGAL_FOOTER
- [ ] Admin access logging middleware
- [ ] Breach detection (basic indicators)
- [ ] Tests: encryption round-trip, erasure workflow (mock DB), consent checks, PII redaction
