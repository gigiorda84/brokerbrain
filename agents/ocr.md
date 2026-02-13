# Agent: OCR

## Domain
Document processing pipeline: image preprocessing, document classification, type-specific data extraction via vision LLM, post-extraction validation, confidence scoring.

## Context
Users upload Italian financial documents (payslips, pension slips, tax returns, loan statements) via WhatsApp/Telegram. The OCR pipeline classifies the document, extracts structured data using Qwen2.5-VL 7B, validates the output, and returns a typed result with per-field confidence scores. The conversation engine calls this pipeline during DOC_PROCESSING states.

## Key Decisions

### Pipeline Steps
```
1. Image preprocessing (preprocessor.py)
   - Resize: max 1440px on long side (VLM sweet spot)
   - Auto-orient: EXIF rotation correction
   - Contrast enhancement: CLAHE if histogram is flat
   - Format: convert HEIC/WebP → JPEG

2. Document classification (classifier.py)
   - Single VLM call with short prompt
   - Returns: doc_type enum + confidence
   - If confidence < 0.80 → ask user "È una busta paga o un altro documento?"

3. Type-specific extraction (extractors/*.py)
   - Each document type has a dedicated extraction prompt
   - Prompt instructs VLM to return JSON matching a Pydantic schema
   - See PRD v1.5 Section 9 for exact prompts

4. JSON parsing + validation (validator.py)
   - Parse VLM JSON output (handle markdown fences, trailing commas)
   - Validate against Pydantic schema
   - Range checks: salary €200–€15,000, age 18–100, dates in valid range
   - CF checksum validation
   - Detect CdQ/delega deductions in payslip/cedolino

5. Confidence scoring
   - VLM returns per-field confidence in its output
   - Validator upgrades/downgrades: e.g., if CF checksum passes → confidence 1.0
   - Fields below 0.70 → flagged for user confirmation
   - Fields below 0.50 → flagged for admin alert

6. Result: OcrResult Pydantic model with all fields + confidence map
```

### Model Management
- Vision model (qwen2.5-vl:7b) is NOT always loaded
- Before OCR: call `llm_client.ensure_model("vision")` → unloads conversation model
- After OCR: call `llm_client.ensure_model("conversation")` → swaps back
- During swap (~10-15s on M2), send user a "Sto analizzando il documento..." message
- On 32GB production: both models loaded simultaneously, no swap needed

### Document Types & Extraction Schemas

**Busta Paga (Payslip):**
```python
class BustaPagaResult(BaseModel):
    employee_name: str
    codice_fiscale: str  # 16 chars, uppercase
    employer_name: str
    employer_type: EmployerCategory | None  # infer from CCNL if possible
    ccnl: str | None
    pay_period: str  # "MM/YYYY"
    hiring_date: date | None
    contract_type: ContractType  # indeterminato/determinato/apprendistato
    gross_salary: Decimal
    net_salary: Decimal
    inps_contributions: Decimal | None
    irpef_withheld: Decimal | None
    tfr_accrued: Decimal | None
    detected_deductions: DeductionSet
    net_after_deductions: Decimal | None
    confidence: dict[str, float]
```

**Cedolino Pensione:**
```python
class CedolinoPensioneResult(BaseModel):
    pensioner_name: str
    codice_fiscale: str
    pension_number: str | None
    pension_type: PensionType  # vecchiaia/anticipata/invalidita/superstiti/sociale
    pension_source: PensionSource  # inps/inpdap/altro
    payment_period: str
    gross_pension: Decimal
    net_pension: Decimal  # BEFORE CdQ deductions (this is what 1/5 is calculated on)
    irpef_withheld: Decimal | None
    detected_deductions: DeductionSet
    net_after_deductions: Decimal | None
    confidence: dict[str, float]
```

**Dichiarazione dei Redditi:**
```python
class DichiarazioneRedditiResult(BaseModel):
    taxpayer_name: str
    codice_fiscale: str
    tax_year: int
    partita_iva: str | None  # 11 digits
    ateco_code: str | None  # "XX.XX.XX"
    tax_regime: TaxRegime  # forfettario/ordinario/semplificato
    reddito_imponibile: Decimal
    compensi_ricavi: Decimal | None
    imposta_netta: Decimal | None
    inps_contributions: Decimal | None
    confidence: dict[str, float]
```

**Conteggio Estintivo / Piano Ammortamento:**
```python
class LoanDocumentResult(BaseModel):
    document_type: Literal["conteggio_estintivo", "piano_ammortamento"]
    borrower_name: str | None
    lender: str
    loan_type: LiabilityType
    residual_amount: Decimal
    monthly_installment: Decimal
    remaining_installments: int | None
    total_installments: int | None
    paid_installments: int | None
    interest_rate: Decimal | None
    maturity_date: date | None
    early_payoff_amount: Decimal | None
    confidence: dict[str, float]
```

**Shared:**
```python
class DeductionSet(BaseModel):
    cessione_del_quinto: Decimal | None = None
    delegazione: Decimal | None = None
    pignoramento: Decimal | None = None
    other: list[NamedDeduction] = []

class NamedDeduction(BaseModel):
    description: str
    amount: Decimal
```

### VLM Prompt Strategy
- System prompt: "You are an Italian financial document OCR specialist."
- User prompt: document-specific (see PRD Section 9 for exact text)
- Always end with: "Return ONLY valid JSON matching this schema. No explanation."
- Temperature: 0.1 (near-deterministic)
- Max tokens: 1000 (structured output shouldn't be longer)

### Error Handling
- VLM returns non-JSON → retry once with "Your previous response was not valid JSON. Try again."
- VLM returns JSON but fails Pydantic validation → log, return partial result with low confidence
- Image too blurry/dark → tell user "L'immagine non è leggibile. Può riprovare con una foto più chiara?"
- Wrong document type detected → "Sembra un [detected_type]. Stavo cercando una [expected_type]. Può verificare?"
- 2 consecutive failures → emit HUMAN_ESCALATION event

## Dependencies
- `foundation` agent: LLM client (model swapping), event system, models
- `calculators` agent: CF decoder called on extracted codice_fiscale

## Task Checklist
- [ ] `src/schemas/ocr.py` — All Pydantic schemas above
- [ ] `src/ocr/preprocessor.py` — Image resize, orient, contrast (Pillow)
- [ ] `src/ocr/classifier.py` — Document type classification prompt + parsing
- [ ] `src/ocr/extractors/busta_paga.py` — Payslip extraction prompt + parsing
- [ ] `src/ocr/extractors/cedolino_pensione.py` — Pension slip extraction
- [ ] `src/ocr/extractors/dichiarazione_redditi.py` — Tax return extraction
- [ ] `src/ocr/extractors/conteggio_estintivo.py` — Loan document extraction
- [ ] `src/ocr/validator.py` — Range checks, CF checksum, date validation, deduction detection
- [ ] `src/ocr/pipeline.py` — Orchestrator: preprocess → classify → extract → validate → result
- [ ] Tests: validator (known good/bad inputs), JSON parsing edge cases, confidence scoring
