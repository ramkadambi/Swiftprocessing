"""
Script to initialize the test ledger with opening balances for all accounts.

This script creates the ledger JSON file and initializes all test accounts
with opening balances based on settlement account lookup data.
"""

import sys
from decimal import Decimal
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from satellites.ledger_service import initialize_account

# Ledger file path
LEDGER_PATH = Path("data/test_ledger.json")


def initialize_all_accounts() -> None:
    """Initialize all test accounts with opening balances."""
    print("Initializing test ledger with opening balances...")
    
    # Initialize FED account
    initialize_account(
        "WF-FED-SETTLE-001",
        opening_balance=Decimal("50000000.00"),  # $50M
        currency="USD",
        account_type="FED",
        ledger_path=LEDGER_PATH,
    )
    
    # Initialize Vostro accounts (foreign bank accounts at Wells Fargo)
    vostro_accounts = {
        "WF-VOSTRO-SBI-USD-001": Decimal("1000000.00"),  # $1M
        "WF-VOSTRO-DEUT-USD-001": Decimal("2000000.00"),  # $2M
        "WF-VOSTRO-HSBC-USD-001": Decimal("1500000.00"),  # $1.5M
        "WF-VOSTRO-BANAMEX-USD-001": Decimal("800000.00"),  # $800K
        "WF-VOSTRO-SCBL-USD-001": Decimal("1200000.00"),  # $1.2M
    }
    
    for account_id, balance in vostro_accounts.items():
        initialize_account(
            account_id,
            opening_balance=balance,
            currency="USD",
            account_type="VOSTRO",
            ledger_path=LEDGER_PATH,
        )
    
    # Initialize CHIPS nostro accounts
    chips_nostro_accounts = {
        "WF-CHIPS-NOSTRO-CHASE-001": Decimal("10000000.00"),  # $10M
        "WF-CHIPS-NOSTRO-BOFA-001": Decimal("10000000.00"),  # $10M
        "WF-CHIPS-NOSTRO-CITI-001": Decimal("8000000.00"),  # $8M
        "WF-CHIPS-NOSTRO-DEUT-001": Decimal("5000000.00"),  # $5M
        "WF-CHIPS-NOSTRO-HSBC-001": Decimal("5000000.00"),  # $5M
    }
    
    for account_id, balance in chips_nostro_accounts.items():
        initialize_account(
            account_id,
            opening_balance=balance,
            currency="USD",
            account_type="CHIPS_NOSTRO",
            ledger_path=LEDGER_PATH,
        )
    
    # Initialize SWIFT out nostro accounts
    swift_nostro_accounts = {
        "WF-SWIFT-NOSTRO-BANAMEX-001": Decimal("3000000.00"),  # $3M
        "WF-SWIFT-NOSTRO-SBI-001": Decimal("2000000.00"),  # $2M
        "WF-SWIFT-NOSTRO-DEUT-001": Decimal("4000000.00"),  # $4M
        "WF-SWIFT-NOSTRO-HSBC-001": Decimal("3500000.00"),  # $3.5M
        "WF-SWIFT-NOSTRO-SCBL-001": Decimal("2500000.00"),  # $2.5M
    }
    
    for account_id, balance in swift_nostro_accounts.items():
        initialize_account(
            account_id,
            opening_balance=balance,
            currency="USD",
            account_type="SWIFT_NOSTRO",
            ledger_path=LEDGER_PATH,
        )
    
    # Initialize some customer/internal accounts for testing
    customer_accounts = {
        "WFBIUS6S": Decimal("50000.00"),  # Wells Fargo customer account
        "CHASUS33": Decimal("100000.00"),  # Chase (for internal transfers)
        "BOFAUS3N": Decimal("100000.00"),  # Bank of America
        "CITIUS33": Decimal("100000.00"),  # Citibank
        "USBKUS44": Decimal("100000.00"),  # US Bank (for R4 FED-only scenario)
        "DEUTDEFF": Decimal("200000.00"),  # Deutsche Bank (for CHIPS scenarios)
        "HSBCGB2L": Decimal("150000.00"),  # HSBC (for CHIPS scenarios)
        "BAMXMXMM": Decimal("100000.00"),  # Banamex (for SWIFT scenarios)
        "SBININBB": Decimal("100000.00"),  # SBI (for inbound scenarios)
    }
    
    for account_id, balance in customer_accounts.items():
        initialize_account(
            account_id,
            opening_balance=balance,
            currency="USD",
            account_type="CUSTOMER",
            ledger_path=LEDGER_PATH,
        )
    
    print(f"\nLedger initialized successfully at: {LEDGER_PATH}")
    print("All test accounts have been created with opening balances.")


if __name__ == "__main__":
    initialize_all_accounts()

