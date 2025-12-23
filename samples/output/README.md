# Output Samples

This folder contains egress outputs generated from processing input payment files.

Each output file shows:
- Payment metadata (E2E ID, selected network, routing rule applied)
- Intermediary agents (if any were added during routing)
- Complete egress message in the appropriate network format

## Output Formats

- **INTERNAL**: JSON notification (no external message sent)
- **FED**: pacs.008 XML (ISO 20022 Customer Credit Transfer)
- **CHIPS**: pacs.009 XML (ISO 20022 Financial Institution Transfer)
- **SWIFT**: 
  - MT103 (direct customer credit transfer)
  - MT202 (domestic bank-to-bank transfer)
  - MT202COV (international cover payment with underlying customer details)

## Generating Outputs

Run the demo script to generate outputs:
```bash
python scripts/run_payment_demo.py
```

Outputs will be named: `{INPUT_FILE}_OUTPUT.txt`

