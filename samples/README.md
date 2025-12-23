# Payment Processing Demo Samples

This folder contains input and output samples for demonstrating the payment processing system.

## Structure

- `input/` - Input payment messages (pacs.008 XML format) for all routing scenarios
- `output/` - Generated egress outputs showing how payments are formatted for different networks

## Running the Demo

### Prerequisites

Install required dependencies:
```bash
pip install lxml
```

### Execute Demo

```bash
python scripts/run_payment_demo.py
```

The script will:
1. Display all input samples
2. Process each payment through the full flow:
   - Account Validation
   - Routing Validation (applies routing rules)
   - Sanctions Check
   - Balance Check
   - Payment Posting
   - Egress (generates network-specific output)
3. Save outputs to `output/` folder

## Input Scenarios

See `input/README.md` for detailed description of each scenario.

## Output Format

Each output file contains:
- Payment metadata (E2E ID, selected network, routing rule)
- Intermediary agents (if any)
- Complete egress message in the appropriate format:
  - **INTERNAL**: JSON notification
  - **FED**: pacs.008 XML (ISO 20022 Customer Credit Transfer)
  - **CHIPS**: pacs.009 XML (ISO 20022 Financial Institution Transfer)
  - **SWIFT**: MT103, MT202, or MT202COV (based on payment characteristics)

## Key Features Demonstrated

1. **Intermediary Agent Addition**: Shows how intermediary banks are added to the agent chain during routing validation
2. **Network-Specific Formatting**: Demonstrates correct message formats for FED, CHIPS, and SWIFT networks
3. **SWIFT Message Type Selection**: Shows MT103 vs MT202 vs MT202COV decision logic
4. **Routing Rule Application**: All 6 routing rules from `routing_rulesV2.json` are exercised

