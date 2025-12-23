# Payment Routing Rules - Reference Table

This document provides a clear, easy-to-understand reference for all payment routing rules used in the Wells Fargo payment processing system.

## Overview

The routing rules determine which payment network (INTERNAL, FED, CHIPS, or SWIFT) should be used to process a payment based on various conditions such as:
- Whether the payment is internal to Wells Fargo
- Whether Wells Fargo is acting as an intermediary
- The clearing capabilities of the receiving bank (FED/CHIPS membership)
- Payment urgency and customer preferences
- Cross-border vs domestic payments

Rules are evaluated in priority order (lower number = higher priority). The first matching rule is applied.

---

## Routing Rules Table

| Rule ID | Priority | Description | When It Applies (Conditions) | What Happens (Actions) | Example Scenario |
|---------|----------|-------------|------------------------------|------------------------|------------------|
| **R1**<br/>WF-MT103-R1-INTERNAL-CREDIT | 1 | Internal Credit Transfer | • Creditor bank is Wells Fargo (`WFBIUS6SXXX`) | • Route via **INTERNAL** network<br/>• No external message sent<br/>• Internal account posting only | SBI (India) sends money to a Wells Fargo customer account. Payment is processed internally without sending to external networks. |
| **R2**<br/>WF-MT103-R2-US-INTERMEDIARY-LOOKUP | 2 | Intermediary Lookup | • Wells Fargo is the intermediary bank<br/>• Ultimate creditor is in the US | • Invoke lookup services:<br/>  - BIC to ABA lookup<br/>  - BIC to CHIPS lookup<br/>• **Continue to next rule** (R3, R4, or R5) | Foreign bank sends payment to US bank via Wells Fargo as intermediary. System looks up the US bank's clearing capabilities (FED/CHIPS) to determine best route. |
| **R3**<br/>WF-MT103-R3-CHIPS-DEFAULT | 3 | CHIPS Default Route | • Next bank has CHIPS ID available<br/>• (Cheaper option, preferred when available) | • Route via **CHIPS** network<br/>• Send ISO 20022 pacs.009 message | Payment to a CHIPS member bank (e.g., Chase, Bank of America). System routes via CHIPS as the default cheaper option. |
| **R4**<br/>WF-MT103-R4-FED-ONLY | 4 | FED-Only Route | • Next bank does **NOT** have CHIPS ID<br/>• Next bank **HAS** ABA routing number | • Route via **FED** network<br/>• Send ISO 20022 pacs.008 message | Payment to a US bank that is FED member but not CHIPS member (e.g., US Bank). System routes via FED. |
| **R5**<br/>WF-MT103-R5-CHIPS-OR-FED-OPTIMIZATION | 5 | CHIPS/FED Optimization | • Next bank has **BOTH** CHIPS ID and ABA<br/>• (Both networks available) | • Apply optimization logic:<br/>  - Route via **FED** if:<br/>    • CHIPS cutoff passed<br/>    • CHIPS queue depth is HIGH<br/>    • Customer prefers FED<br/>    • Payment urgency is HIGH<br/>  - Otherwise route via **CHIPS** (default)<br/>• Send appropriate message format | Payment to a bank with both CHIPS and FED capabilities. System applies business optimization rules to choose the best network based on operational conditions. |
| **R6**<br/>WF-MT103-R6-CROSSBORDER-OUT-SWIFT | 10 | Cross-Border SWIFT | • Ultimate creditor is **outside** the US | • Route via **SWIFT** network<br/>• Send SWIFT message:<br/>  - MT103 (direct customer transfer)<br/>  - MT202 (domestic bank-to-bank)<br/>  - MT202COV (international cover payment) | Payment to a bank outside the US (e.g., Mexico, Germany). System routes via SWIFT network for international delivery. |

---

## Rule Priority and Execution Flow

```
Priority 1: R1 (INTERNAL) - Check if Wells Fargo is creditor
    ↓ (if not matched)
Priority 2: R2 (INTERMEDIARY) - Check if Wells Fargo is intermediary
    ↓ (if matched, continues to...)
Priority 3: R3 (CHIPS) - Check if CHIPS available
    ↓ (if not matched)
Priority 4: R4 (FED) - Check if FED available
    ↓ (if not matched)
Priority 5: R5 (OPTIMIZATION) - Check if both available, apply optimization
    ↓ (if not matched)
Priority 10: R6 (SWIFT) - Cross-border fallback
```

---

## Decision Matrix for R5 (Optimization Rule)

When both CHIPS and FED are available, the system uses the following decision matrix:

| Condition | Route Selected |
|-----------|----------------|
| CHIPS cutoff time has passed | **FED** |
| CHIPS queue depth is HIGH | **FED** |
| Customer explicitly prefers FED | **FED** |
| Payment urgency is HIGH | **FED** |
| **None of the above** | **CHIPS** (default, cheaper) |

---

## Network Output Messages

Each routing network generates a specific message format:

| Network | Message Format | Description |
|---------|---------------|-------------|
| **INTERNAL** | JSON notification | Internal notification only (no external message) |
| **FED** | ISO 20022 pacs.008 | Customer Credit Transfer message |
| **CHIPS** | ISO 20022 pacs.009 | Financial Institution Transfer message |
| **SWIFT** | MT103 / MT202 / MT202COV | SWIFT message format based on payment type:<br/>• MT103: Direct customer transfer<br/>• MT202: Domestic bank-to-bank<br/>• MT202COV: International cover payment |

---

## Test Scenarios Reference

### Scenario 1: Internal Credit (R1)
- **Input**: Payment where creditor bank = `WFBIUS6SXXX`
- **Expected**: Route = INTERNAL, No external message

### Scenario 2: Intermediary with CHIPS (R2 → R3)
- **Input**: Payment with Wells Fargo as intermediary, creditor bank has CHIPS
- **Expected**: Route = CHIPS, pacs.009 message

### Scenario 3: Intermediary with FED Only (R2 → R4)
- **Input**: Payment with Wells Fargo as intermediary, creditor bank has FED but no CHIPS
- **Expected**: Route = FED, pacs.008 message

### Scenario 4: Direct CHIPS (R3)
- **Input**: Payment to CHIPS member bank (no intermediary)
- **Expected**: Route = CHIPS, pacs.009 message

### Scenario 5: Direct FED (R4)
- **Input**: Payment to FED-only member bank (no intermediary)
- **Expected**: Route = FED, pacs.008 message

### Scenario 6: Optimization - CHIPS Selected (R5)
- **Input**: Payment to bank with both CHIPS and FED, no optimization triggers
- **Expected**: Route = CHIPS (default), pacs.009 message

### Scenario 7: Optimization - FED Selected (R5)
- **Input**: Payment to bank with both CHIPS and FED, urgency = HIGH
- **Expected**: Route = FED, pacs.008 message

### Scenario 8: Cross-Border (R6)
- **Input**: Payment to non-US bank
- **Expected**: Route = SWIFT, MT103/MT202/MT202COV message

---

## Key Terms

- **Creditor Bank**: The bank receiving the payment (beneficiary bank)
- **Debtor Bank**: The bank sending the payment (originator bank)
- **Intermediary Bank**: A bank that acts as a middleman in the payment chain
- **CHIPS**: Clearing House Interbank Payments System (US dollar clearing)
- **FED**: Federal Reserve Wire Network (Fedwire)
- **SWIFT**: Society for Worldwide Interbank Financial Telecommunication
- **ABA Routing Number**: American Bankers Association routing number (for FED)
- **CHIPS UID**: CHIPS Universal Identifier (for CHIPS)
- **BIC**: Bank Identifier Code (SWIFT code)

---

## Notes for Testers

1. **Rule Priority**: Rules are evaluated in priority order. Once a rule matches, processing stops (except R2 which continues to next rule).

2. **R2 Special Behavior**: R2 only invokes lookup services and does NOT select a network. It always continues to R3, R4, or R5.

3. **R5 Decision Matrix**: R5 uses multiple conditions. Test each condition separately to ensure correct routing.

4. **Account Validation**: All rules require successful account validation. Ensure test accounts are properly configured in the account lookup service.

5. **Message Format**: The output message format depends on the selected network. Verify the correct format is generated for each scenario.

---

## Notes for Product Owners

1. **Business Logic**: The rules implement Wells Fargo's operational optimization strategy:
   - Prefer CHIPS when available (cheaper)
   - Use FED for urgency or when CHIPS is unavailable
   - Use SWIFT for international payments

2. **Extensibility**: New rules can be added by:
   - Adding a new rule object to `routing_rulesV2.json`
   - Assigning a unique priority
   - Defining conditions and actions

3. **Configuration**: Rules are JSON-based and can be updated without code changes (subject to validation).

4. **Performance**: Rule evaluation is sequential but fast. Consider rule priority when adding new rules to maintain performance.

---

*Last Updated: Based on routing_rulesV2.json*
*Version: 2.0*

