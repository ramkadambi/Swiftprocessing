# Test Payment Scripts

This directory contains scripts for sending test payments to the payment processing system.

## Prerequisites

1. **Initialize Ledger**: Before running test payments, initialize the ledger with opening balances:
   ```bash
   python scripts/initialize_ledger.py
   ```

2. **Kafka Running**: Ensure Kafka is running on `localhost:9092` (or update `--bootstrap-servers`)

3. **Services Running**: Ensure all satellite services and orchestrator are running

## Scripts

### 1. `send_test_payment_rulesV2.py`

Test payments for `config/routing_rulesV2.json` scenarios.

**Usage:**
```bash
python scripts/send_test_payment_rulesV2.py --scenario <scenario_name>
```

**Available Scenarios:**

- `r1_internal_credit` - WF-MT103-R1: Wells Fargo as final beneficiary → INTERNAL
- `r2_intermediary_lookup` - WF-MT103-R2: Wells is intermediary, lookup next US bank
- `r3_chips_default` - WF-MT103-R3: Route via CHIPS when CHIPS ID is available
- `r4_fed_only` - WF-MT103-R4: Route via FED when only ABA is available
- `r5_chips_fed_optimization` - WF-MT103-R5: Both CHIPS and FED available, apply optimization
- `r6_crossborder_swift` - WF-MT103-R6: Ultimate creditor outside US → SWIFT

**Examples:**
```bash
# Test internal credit (R1)
python scripts/send_test_payment_rulesV2.py --scenario r1_internal_credit

# Test CHIPS routing (R3)
python scripts/send_test_payment_rulesV2.py --scenario r3_chips_default

# Test with custom amount and E2E ID
python scripts/send_test_payment_rulesV2.py --scenario r1_internal_credit --amount 3000.00 --e2e-id E2E-CUSTOM-001
```

### 2. `send_test_payment.py`

General test payment script with various scenarios.

**Usage:**
```bash
python scripts/send_test_payment.py --scenario <scenario_name>
```

**Available Scenarios:**
- `happy` - Happy path (default)
- `sanctions_fail` - Triggers sanctions failure
- `balance_fail` - Triggers balance check failure
- `posting_fail` - Triggers posting failure
- `routing_usd_domestic_fed` - USD domestic → FED
- `routing_usd_crossborder_chips` - USD cross-border → CHIPS
- `routing_usd_crossborder_fed` - USD cross-border → FED
- `routing_usd_fallback_swift` - USD fallback → SWIFT
- `routing_usd_individual` - USD individual beneficiary → FED

### 3. `send_test_payment_rules2.py`

Test payments for `config/routing_rules2.json` scenarios (legacy).

## Account Balances

All test accounts are initialized with the following balances:

- **Vostro Accounts**: $800K - $2M (for inbound payments)
- **CHIPS Nostro Accounts**: $5M - $10M
- **SWIFT Nostro Accounts**: $2M - $4M
- **FED Account**: $50M
- **Customer Accounts**: $50K - $200K

## Balance Check Limits

- **Balance Check**: Fails if amount > $10,000
- **Payment Posting**: Fails if amount > $25,000

All default amounts in test scripts are set to pass these checks.

## End-to-End Testing

To test the full flow:

1. **Start Services** (in separate terminals):
   ```bash
   # Terminal 1: Orchestrator
   python -m orchestrator.orchestrator
   
   # Terminal 2: Account Validation
   python -m satellites.account_validation
   
   # Terminal 3: Routing Validation
   python -m satellites.routing_validation
   
   # Terminal 4: Sanctions Check
   python -m satellites.sanctions_check
   
   # Terminal 5: Balance Check
   python -m satellites.balance_check
   
   # Terminal 6: Payment Posting
   python -m satellites.payment_posting
   ```

2. **Send Test Payment**:
   ```bash
   python scripts/send_test_payment_rulesV2.py --scenario r1_internal_credit
   ```

3. **Monitor Topics** (optional):
   ```bash
   # Watch orchestrator input
   docker exec -it kafka kafka-console-consumer --bootstrap-server localhost:9092 --topic payments.orchestrator.in --from-beginning
   
   # Watch service results
   docker exec -it kafka kafka-console-consumer --bootstrap-server localhost:9092 --topic service.results.account_validation --from-beginning
   ```

## Validation

After sending a payment, check:

1. **Ledger File**: `data/test_ledger.json` - Verify balances updated correctly
2. **Kafka Topics**: Check service results and error topics
3. **Service Logs**: Check console output from each service

## Troubleshooting

- **"Account not found"**: Run `python scripts/initialize_ledger.py`
- **"Insufficient balance"**: Check account balances in `data/test_ledger.json`
- **"Double posting detected"**: Use a unique `--e2e-id` for each test
- **Kafka connection errors**: Ensure Kafka is running and accessible

