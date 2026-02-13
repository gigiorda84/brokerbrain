# Agent: Calculators

## Domain
Codice fiscale decoder, CdQ rata/capacity/renewal calculator, DTI calculator, income normalization, ATECO→forfettario coefficient lookup, eligibility engine, product matching.

## Context
These are the deterministic core of BrokerBot — pure functions with zero LLM dependency. Every financial calculation must be provably correct. Use `Decimal` everywhere, write exhaustive unit tests, and keep the logic separate from the conversation layer.

## Key Decisions

### All Financial Math Uses Decimal
```python
from decimal import Decimal, ROUND_HALF_UP

# NEVER: 1750.0 / 5 = 350.00000000000006
# ALWAYS: Decimal("1750") / 5 = Decimal("350")

def to_euro(value: Decimal) -> Decimal:
    """Round to 2 decimal places, Italian banking convention."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
```

### Codice Fiscale Decoder (`decoders/codice_fiscale.py`)

Input: 16-char string. Output: `CfResult(birthdate, age, gender, birthplace_code, birthplace_name, valid)`.

```python
MONTH_MAP = {'A':1,'B':2,'C':3,'D':4,'E':5,'H':6,
             'L':7,'M':8,'P':9,'R':10,'S':11,'T':12}

# Checksum algorithm (odd/even position values)
ODD_VALUES = {'0':1,'1':0,'2':5,'3':7,'4':9,'5':13,'6':15,'7':17,'8':19,'9':21,
              'A':1,'B':0,'C':5,'D':7,'E':9,'F':13,'G':15,'H':17,'I':19,'J':21,
              'K':2,'L':4,'M':18,'N':20,'O':11,'P':3,'Q':6,'R':8,'S':12,'T':14,
              'U':16,'V':10,'W':22,'X':25,'Y':24,'Z':23}
EVEN_VALUES = {c:i for i,c in enumerate('0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ') if c.isalnum()}
# Simplified: digits map to their value, letters A=0, B=1, ...

def validate_cf_checksum(cf: str) -> bool:
    """Validate the check character (position 16)."""
    cf = cf.upper()
    total = sum(ODD_VALUES[cf[i]] if i % 2 == 0 else EVEN_VALUES.get(cf[i], 0) for i in range(15))
    expected = chr(65 + (total % 26))
    return cf[15] == expected

def decode_cf(cf: str) -> CfResult:
    """Decode Italian codice fiscale → personal data."""
    # ... (see PRD Section 10 for full implementation)
```

Load `data/cadastral_codes.json` for birthplace_code → municipality name mapping. This is a ~8,000-entry dict (Italian comuni).

### CdQ Calculator (`calculators/cdq.py`)

Three functions:

```python
def calculate_cdq_capacity(
    net_income: Decimal,
    existing_cdq: Decimal = Decimal("0"),
    existing_delega: Decimal = Decimal("0"),
) -> CdqCapacity:
    """
    Calculate CdQ and Delega capacity for a given net income.
    Max CdQ = net_income / 5
    Max Delega = net_income / 5 (separate from CdQ)
    Total max = 2/5 of net (for dipendenti only; pensionati get only CdQ)
    """

def check_cdq_renewal(
    total_installments: int,
    paid_installments: int,
    is_first_cdq: bool = False,
    original_duration: int | None = None,
) -> CdqRenewalResult:
    """
    Check CdQ renewal eligibility per DPR 180/1950.
    Rule: must have paid ≥ 40% of installments.
    Exception: first-time CdQ at 60 months → can renegotiate to 120.
    """

def calculate_max_age_at_maturity(
    current_age: int,
    duration_months: int,
) -> int:
    """Age at loan maturity. For CdQ pensionati: max 85."""
    return current_age + (duration_months // 12)
```

### DTI Calculator (`calculators/dti.py`)

```python
def calculate_dti(
    net_monthly_income: Decimal,
    existing_obligations: list[Liability],
    proposed_installment: Decimal = Decimal("0"),
) -> DtiResult:
    """
    DTI = (total monthly obligations + proposed) / net income × 100

    Thresholds (from PRD):
    ≤ 30% → GREEN (all products)
    31-35% → YELLOW (most products)
    36-40% → ORANGE (CdQ still ok, mutuo limited)
    41-50% → RED (consolidamento suggested)
    > 50% → CRITICAL
    """
    total = sum(l.monthly_installment for l in existing_obligations)
    current_dti = (total / net_monthly_income * 100) if net_monthly_income > 0 else Decimal("999")
    projected_dti = ((total + proposed_installment) / net_monthly_income * 100) if net_monthly_income > 0 else Decimal("999")
    ...
```

### Income Normalization (`calculators/income.py`)

Different employment types report income differently. Normalize to monthly equivalent:

```python
def monthly_equivalent(
    employment_type: EmploymentType,
    raw_value: Decimal,
    mensilita: int = 13,  # 13 or 14 depending on CCNL
    tax_regime: TaxRegime | None = None,
    ateco_code: str | None = None,
) -> Decimal:
    """
    Dipendente: net_salary (already monthly). Note: CdQ rata based on monthly net.
    P.IVA forfettario: (revenue × coefficient) / 12
    P.IVA ordinario: reddito_imponibile / 12
    Pensionato: net_pension (already monthly)
    Disoccupato: NASpI amount (already monthly)
    """
```

### ATECO → Forfettario Coefficients (`decoders/ateco.py`)

Load from `data/ateco_coefficients.json`:
```json
{
  "10-43": {"description": "Manifattura", "coefficient": 0.86},
  "45": {"description": "Commercio veicoli", "coefficient": 0.40},
  "46-47": {"description": "Commercio", "coefficient": 0.40},
  "55-63": {"description": "Ospitalità/ristorazione", "coefficient": 0.40},
  "64-66": {"description": "Finanza/assicurazioni", "coefficient": 0.78},
  "69-75": {"description": "Servizi professionali", "coefficient": 0.78},
  "85": {"description": "Istruzione", "coefficient": 0.78},
  "86-88": {"description": "Sanità/assistenza", "coefficient": 0.78},
  "default": {"description": "Altre attività", "coefficient": 0.67}
}
```

Lookup: extract first 2 digits of ATECO → find matching range → return coefficient.

### Eligibility Engine (`eligibility/engine.py`)

Evaluates all 9 Primo Network products against user profile:

```python
def match_products(profile: UserProfile) -> list[ProductMatch]:
    """
    Evaluate eligibility for each Primo Network product.
    Returns ranked list with: product, sub_type, eligible (bool),
    conditions (list[str]), estimated_terms, rank.
    """
```

Rules are loaded from `data/eligibility_rules.xlsx` or a YAML file — operator-editable without code changes.

**Product-specific rules (from PRD Section 11):**

| Product | Key Rules |
|---|---|
| CdQ Stipendio | employer_category known, contract indeterminato or public, CdQ capacity > 0, employer ≥ 16 employees (private) |
| CdQ Pensione | pension_source known, CdQ capacity > 0, age_at_maturity ≤ 85 |
| Delega | same as CdQ Stipendio, plus: check if employer allows delega |
| Prestito Personale | net_income ≥ €800, DTI ≤ 40% |
| Mutuo Acquisto | net_income ≥ €1,000, DTI ≤ 30-35%, employment ≥ 24 months |
| Mutuo Surroga | has existing mortgage, net_income sufficient |
| Mutuo Consolidamento | ≥ 2 liabilities, DTI > 30% |
| Anticipo TFS | pensionato + ex_public_state = true |
| Credito Assicurativo | cross-sell when any other product matched |

### Smart Suggestions (`eligibility/suggestions.py`)

Proactive product suggestions based on detected patterns:
- High DTI + multiple debts → "Consolidamento debiti"
- Existing CdQ, renewable → "Rinnovo CdQ"
- Dipendente pubblico → "CdQ offers best terms for public sector"
- Pensionato ex-INPDAP → "Consider Anticipo TFS alongside CdQ"
- Credit issues → "CdQ is available even with credit problems"

## Dependencies
- `foundation` agent: Decimal types, model enums, DB storage
- No LLM dependency — all pure Python

## Task Checklist
- [ ] `src/decoders/codice_fiscale.py` — Full CF decoder with checksum validation
- [ ] `data/cadastral_codes.json` — Birthplace code mapping (source: Agenzia delle Entrate)
- [ ] `src/decoders/ateco.py` — ATECO → coefficient lookup
- [ ] `data/ateco_coefficients.json` — Coefficient table
- [ ] `src/calculators/cdq.py` — Capacity, renewal, max rata, age check
- [ ] `src/calculators/dti.py` — DTI current + projected, threshold classification
- [ ] `src/calculators/income.py` — Monthly income normalization across types
- [ ] `src/eligibility/products.py` — Primo Network product definitions (9 products, 10 CdQ sub-types)
- [ ] `src/eligibility/engine.py` — Product matching logic
- [ ] `src/eligibility/rules.py` — Rule loader from YAML/Excel
- [ ] `src/eligibility/suggestions.py` — Smart suggestions engine
- [ ] `src/schemas/eligibility.py` — UserProfile, ProductMatch, CdqCapacity, DtiResult Pydantic models
- [ ] Tests: CF decoder (known valid/invalid), CdQ calculator (edge cases: 40% rule, first CdQ exception), DTI (all thresholds), ATECO lookup, eligibility (one scenario per employment type)
