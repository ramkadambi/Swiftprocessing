# Payment Processing Demo - Summary

## Overview

This demo showcases the complete payment processing flow from input to egress output, demonstrating how intermediary agents are added and how payments are formatted for different networks (FED, CHIPS, SWIFT).

## Files Created

### Input Samples (`samples/input/`)
- **R1_INTERNAL_CREDIT_pacs008.xml**: Wells Fargo as creditor → INTERNAL
- **R2_INTERMEDIARY_LOOKUP_pacs008.xml**: Wells Fargo as intermediary → CHIPS/FED lookup
- **R3_CHIPS_DEFAULT_pacs008.xml**: CHIPS member as creditor → CHIPS
- **R4_FED_ONLY_pacs008.xml**: FED-only bank → FED
- **R5_CHIPS_FED_OPTIMIZATION_pacs008.xml**: Bank with both CHIPS and FED → Optimization
- **R6_CROSSBORDER_SWIFT_pacs008.xml**: Non-US creditor → SWIFT

### Processing Script
- **scripts/run_payment_demo.py**: End-to-end processing script that:
  1. Shows all input samples first
  2. Processes each payment through the complete flow
  3. Captures egress output
  4. Saves outputs to `samples/output/`

### Output Folder
- **samples/output/**: Contains generated egress outputs for each input scenario

## Key Features Demonstrated

### 1. Intermediary Agent Addition
- Shows how Wells Fargo is added to `agent_chain` when it acts as intermediary
- Example: R2 scenario has `IntrmyAgt1` in input XML, which is extracted and added to PaymentEvent

### 2. Network-Specific Formatting
- **FED**: pacs.008 XML (ISO 20022 Customer Credit Transfer)
- **CHIPS**: pacs.009 XML (ISO 20022 Financial Institution Transfer)
- **SWIFT**: MT103, MT202, or MT202COV based on payment characteristics

### 3. SWIFT Message Type Selection
- **MT103**: Direct customer transfer (no intermediary)
- **MT202**: Domestic cover payment (US to US with intermediary)
- **MT202COV**: International cover payment (cross-border with intermediary)

### 4. Routing Rule Application
All 6 routing rules from `routing_rulesV2.json` are exercised:
- R1: INTERNAL-CREDIT
- R2: US-INTERMEDIARY-LOOKUP
- R3: CHIPS-DEFAULT
- R4: FED-ONLY
- R5: CHIPS-OR-FED-OPTIMIZATION
- R6: CROSSBORDER-OUT-SWIFT

## Running the Demo

### Prerequisites
```bash
pip install lxml
python scripts/initialize_ledger.py
```

### Execute
```bash
python scripts/run_payment_demo.py
```

## Output Format

Each output file (`{INPUT_FILE}_OUTPUT.txt`) contains:
- Payment metadata (E2E ID, selected network, routing rule)
- Intermediary agents (if any were added)
- Complete egress message in the appropriate format

## Code Changes

1. **Updated `ingress/mx_to_canonical.py`**:
   - Added `intermediary_bic` field to `Pacs008Extract`
   - Extracts `IntrmyAgt1` from pacs.008 XML
   - Builds `agent_chain` in `PaymentEvent` when intermediary is present

2. **Created egress formatters**:
   - `canonical_to_pacs009.py` (CHIPS)
   - `canonical_to_mt103.py` (SWIFT direct)
   - `canonical_to_mt202.py` (SWIFT domestic)
   - `canonical_to_mt202cov.py` (SWIFT international)

3. **Created demo script**:
   - Processes inputs through full flow
   - Captures and saves egress outputs

## Management Presentation

The outputs demonstrate:
- ✅ Correct intermediary agent addition (R2 scenario)
- ✅ Proper FED format (pacs.008) for R4 scenario
- ✅ Proper CHIPS format (pacs.009) for R3 scenario
- ✅ Proper SWIFT format (MT103/MT202/MT202COV) for R6 scenario
- ✅ All routing rules are correctly applied

