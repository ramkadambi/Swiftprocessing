# Payment Processing Demo

This demo processes payment input files through the complete payment flow and generates egress outputs showing how payments are formatted for different networks.

## Setup

### Prerequisites

Install required dependencies:
```bash
pip install lxml
```

### Initialize Ledger

Before running the demo, initialize the test ledger with account balances:
```bash
python scripts/initialize_ledger.py
```

## Running the Demo

```bash
python scripts/run_payment_demo.py
```

## What the Demo Does

1. **Shows Input Samples**: Displays all input payment files (pacs.008 XML) before processing
2. **Processes Each Payment**: Runs through the complete flow:
   - Account Validation
   - Routing Validation (applies routing rules from `routing_rulesV2.json`)
   - Sanctions Check
   - Balance Check
   - Payment Posting
   - Egress (generates network-specific output)
3. **Saves Outputs**: Each processed payment generates an output file in `samples/output/`

## Input Scenarios

The demo includes 6 input scenarios covering all routing rules:

1. **R1_INTERNAL_CREDIT**: Wells Fargo as creditor → INTERNAL (IBT)
2. **R2_INTERMEDIARY_LOOKUP**: Wells Fargo as intermediary → CHIPS/FED lookup
3. **R3_CHIPS_DEFAULT**: CHIPS member as creditor → CHIPS
4. **R4_FED_ONLY**: FED-only bank as creditor → FED
5. **R5_CHIPS_FED_OPTIMIZATION**: Bank with both CHIPS and FED → Optimization logic
6. **R6_CROSSBORDER_SWIFT**: Non-US creditor → SWIFT

## Output Format

Each output file contains:
- Payment metadata (E2E ID, selected network, routing rule)
- Intermediary agents (if added during routing)
- Complete egress message:
  - **INTERNAL**: JSON notification
  - **FED**: pacs.008 XML
  - **CHIPS**: pacs.009 XML
  - **SWIFT**: MT103, MT202, or MT202COV

## Key Features Demonstrated

1. **Intermediary Agent Addition**: Shows how Wells Fargo is added as intermediary when routing through it
2. **Network-Specific Formatting**: Correct message formats for each network
3. **SWIFT Message Type Selection**: MT103 vs MT202 vs MT202COV decision logic
4. **Routing Rule Application**: All 6 routing rules are exercised

## Files

- `samples/input/` - Input payment files (pacs.008 XML)
- `samples/output/` - Generated egress outputs
- `scripts/run_payment_demo.py` - Demo script

