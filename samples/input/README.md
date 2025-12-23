# Input Samples for Payment Processing Demo

This folder contains input payment messages (pacs.008 XML format) that trigger different routing rules.

## Scenarios

### R1_INTERNAL_CREDIT_pacs008.xml
- **Rule**: WF-MT103-R1-INTERNAL-CREDIT
- **Description**: Wells Fargo is final beneficiary → INTERNAL (IBT)
- **Key Fields**:
  - Creditor Agent: `WFBIUS6SXXX` (Wells Fargo)
  - Debtor Agent: `SBININBBXXX` (Foreign bank)
- **Expected Output**: INTERNAL notification (no external message)

### R2_INTERMEDIARY_LOOKUP_pacs008.xml
- **Rule**: WF-MT103-R2-US-INTERMEDIARY-LOOKUP
- **Description**: Wells Fargo is intermediary; lookup next US bank clearing capabilities
- **Key Fields**:
  - Intermediary Agent: `WFBIUS6SXXX` (Wells Fargo)
  - Creditor Agent: `CHASUS33XXX` (US bank - Chase)
  - Debtor Agent: `SBININBBXXX` (Foreign bank)
- **Expected Output**: CHIPS or FED based on lookup (typically CHIPS for Chase)

### R3_CHIPS_DEFAULT_pacs008.xml
- **Rule**: WF-MT103-R3-CHIPS-DEFAULT
- **Description**: Route via CHIPS when CHIPS ID is available
- **Key Fields**:
  - Creditor Agent: `DEUTDEFFXXX` (Deutsche Bank - CHIPS member)
  - Debtor Agent: `CHASUS33XXX` (US bank)
- **Expected Output**: pacs.009 (CHIPS Financial Institution Transfer)

### R4_FED_ONLY_pacs008.xml
- **Rule**: WF-MT103-R4-FED-ONLY
- **Description**: Route via FED when only ABA is available (no CHIPS nostro)
- **Key Fields**:
  - Creditor Agent: `USBKUS44XXX` (US Bank - FED member, no CHIPS nostro)
  - Debtor Agent: `CHASUS33XXX` (US bank)
- **Expected Output**: pacs.008 (FED Customer Credit Transfer)

### R5_CHIPS_FED_OPTIMIZATION_pacs008.xml
- **Rule**: WF-MT103-R5-CHIPS-OR-FED-OPTIMIZATION
- **Description**: When both CHIPS and FED are available, apply Wells operational optimization
- **Key Fields**:
  - Creditor Agent: `CHASUS33XXX` (Chase - has both CHIPS and FED)
  - Debtor Agent: `BOFAUS3NXXX` (Bank of America)
- **Expected Output**: CHIPS (default) or FED (if optimization conditions met)

### R6_CROSSBORDER_SWIFT_pacs008.xml
- **Rule**: WF-MT103-R6-CROSSBORDER-OUT-SWIFT
- **Description**: If ultimate creditor is outside US, forward payment via SWIFT
- **Key Fields**:
  - Creditor Agent: `BAMXMXMMXXX` (Banamex - Mexico, non-US)
  - Debtor Agent: `CHASUS33XXX` (US bank)
- **Expected Output**: MT103, MT202, or MT202COV based on payment characteristics

## Processing

Run the demo script to process all inputs:
```bash
python scripts/run_payment_demo.py
```

Outputs will be saved to `samples/output/` folder.

