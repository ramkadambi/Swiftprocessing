"""
Ledger Service for managing account balances and transaction posting.

Maintains a JSON-based ledger file that tracks:
- Account balances (opening and current)
- Processed transactions (to prevent double posting)
- Transaction history

Thread-safe file operations for concurrent access.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from satellites.payment_posting import PostingEntry


# Default ledger file path
DEFAULT_LEDGER_PATH = Path("data/test_ledger.json")

# Thread lock for file operations
_ledger_lock = threading.RLock()


def _ensure_data_directory() -> None:
    """Ensure data directory exists."""
    data_dir = DEFAULT_LEDGER_PATH.parent
    data_dir.mkdir(parents=True, exist_ok=True)


def _read_ledger_file(ledger_path: Path) -> dict[str, Any]:
    """Read ledger from JSON file."""
    if not ledger_path.exists():
        return {
            "accounts": {},
            "processed_transactions": {},
            "metadata": {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "version": "1.0",
            },
        }
    
    with open(ledger_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    # Convert string amounts to Decimal for accounts
    if "accounts" in data:
        for account_id, account_data in data["accounts"].items():
            if "opening_balance" in account_data:
                account_data["opening_balance"] = Decimal(str(account_data["opening_balance"]))
            if "current_balance" in account_data:
                account_data["current_balance"] = Decimal(str(account_data["current_balance"]))
    
    return data


def _write_ledger_file(ledger_path: Path, data: dict[str, Any]) -> None:
    """Write ledger to JSON file."""
    _ensure_data_directory()
    
    # Convert Decimal to string for JSON serialization
    data_copy = json.loads(json.dumps(data, default=str))
    
    with open(ledger_path, "w", encoding="utf-8") as f:
        json.dump(data_copy, f, indent=2, ensure_ascii=False)


def get_account_balance(account_id: str, ledger_path: Path = DEFAULT_LEDGER_PATH) -> Optional[Decimal]:
    """
    Get current balance for an account.
    
    Args:
        account_id: Account identifier (e.g., "WF-VOSTRO-SBI-USD-001")
        ledger_path: Path to ledger JSON file
    
    Returns:
        Current balance as Decimal, or None if account doesn't exist
    """
    with _ledger_lock:
        ledger = _read_ledger_file(ledger_path)
        account = ledger.get("accounts", {}).get(account_id)
        if account:
            return Decimal(str(account.get("current_balance", 0)))
        return None


def has_sufficient_balance(account_id: str, amount: Decimal, ledger_path: Path = DEFAULT_LEDGER_PATH) -> bool:
    """
    Check if account has sufficient balance for a debit.
    
    Args:
        account_id: Account identifier
        amount: Amount to debit
        ledger_path: Path to ledger JSON file
    
    Returns:
        True if account exists and has sufficient balance, False otherwise
    """
    balance = get_account_balance(account_id, ledger_path)
    if balance is None:
        return False
    return balance >= amount


def is_transaction_processed(end_to_end_id: str, ledger_path: Path = DEFAULT_LEDGER_PATH) -> bool:
    """
    Check if a transaction has already been processed (double posting detection).
    
    Args:
        end_to_end_id: End-to-end transaction identifier
        ledger_path: Path to ledger JSON file
    
    Returns:
        True if transaction already processed, False otherwise
    """
    with _ledger_lock:
        ledger = _read_ledger_file(ledger_path)
        return end_to_end_id in ledger.get("processed_transactions", {})


def post_transaction(
    entries: list["PostingEntry"],
    end_to_end_id: str,
    ledger_path: Path = DEFAULT_LEDGER_PATH,
) -> tuple[bool, Optional[str]]:
    """
    Post debit and credit entries to ledger.
    
    Args:
        entries: List of PostingEntry objects (should have DEBIT and CREDIT)
        end_to_end_id: End-to-end transaction identifier
        ledger_path: Path to ledger JSON file
    
    Returns:
        Tuple of (success: bool, error_message: Optional[str])
        - success=True: Transaction posted successfully
        - success=False: Error occurred (error_message contains reason)
    """
    with _ledger_lock:
        # Check for double posting
        if is_transaction_processed(end_to_end_id, ledger_path):
            return False, f"Transaction {end_to_end_id} already processed (double posting detected)"
        
        # Read current ledger
        ledger = _read_ledger_file(ledger_path)
        accounts = ledger.setdefault("accounts", {})
        processed = ledger.setdefault("processed_transactions", {})
        
        # Find debit and credit entries
        debit_entry: Optional[PostingEntry] = None
        credit_entry: Optional[PostingEntry] = None
        
        for entry in entries:
            if entry.side.value == "DEBIT":
                debit_entry = entry
            elif entry.side.value == "CREDIT":
                credit_entry = entry
        
        if not debit_entry or not credit_entry:
            return False, "Missing DEBIT or CREDIT entry"
        
        debit_account_id = debit_entry.settlement_account
        credit_account_id = credit_entry.settlement_account
        
        if not debit_account_id or not credit_account_id:
            return False, "Missing settlement account in entries"
        
        # Validate accounts exist
        if debit_account_id not in accounts:
            return False, f"Debit account not found: {debit_account_id}"
        
        if credit_account_id not in accounts:
            return False, f"Credit account not found: {credit_account_id}"
        
        # Get current balances
        debit_account = accounts[debit_account_id]
        credit_account = accounts[credit_account_id]
        
        debit_balance = Decimal(str(debit_account.get("current_balance", 0)))
        credit_balance = Decimal(str(credit_account.get("current_balance", 0)))
        amount = debit_entry.amount
        
        # Validate sufficient funds (should have been checked by balance_check, but double-check)
        if debit_balance < amount:
            return False, f"Insufficient balance in {debit_account_id}: {debit_balance} < {amount}"
        
        # Execute posting: Debit (reduce balance), Credit (increase balance)
        new_debit_balance = debit_balance - amount
        new_credit_balance = credit_balance + amount
        
        # Update balances
        debit_account["current_balance"] = float(new_debit_balance)
        credit_account["current_balance"] = float(new_credit_balance)
        
        # Record transaction timestamp
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Mark transaction as processed
        processed[end_to_end_id] = {
            "timestamp": timestamp,
            "status": "POSTED",
            "debit_account": debit_account_id,
            "credit_account": credit_account_id,
            "amount": float(amount),
            "currency": debit_entry.currency,
        }
        
        # Persist to file
        try:
            _write_ledger_file(ledger_path, ledger)
            print(
                f"[Ledger] Posted transaction {end_to_end_id}: "
                f"Debit {debit_account_id}: {debit_balance} -> {new_debit_balance}, "
                f"Credit {credit_account_id}: {credit_balance} -> {new_credit_balance}"
            )
            return True, None
        except Exception as e:
            return False, f"Failed to write ledger: {e}"


def initialize_account(
    account_id: str,
    opening_balance: Decimal,
    currency: str = "USD",
    account_type: Optional[str] = None,
    ledger_path: Path = DEFAULT_LEDGER_PATH,
) -> None:
    """
    Initialize an account in the ledger with opening balance.
    
    Args:
        account_id: Account identifier
        opening_balance: Opening balance for the account
        currency: Currency code (default: USD)
        account_type: Type of account (VOSTRO, NOSTRO, FED, etc.)
        ledger_path: Path to ledger JSON file
    """
    with _ledger_lock:
        ledger = _read_ledger_file(ledger_path)
        accounts = ledger.setdefault("accounts", {})
        
        if account_id not in accounts:
            accounts[account_id] = {
                "opening_balance": float(opening_balance),
                "current_balance": float(opening_balance),
                "currency": currency,
                "account_type": account_type,
            }
            _write_ledger_file(ledger_path, ledger)
            print(f"[Ledger] Initialized account {account_id} with opening balance {opening_balance} {currency}")


def get_ledger_summary(ledger_path: Path = DEFAULT_LEDGER_PATH) -> dict[str, Any]:
    """
    Get summary of ledger state.
    
    Returns:
        Dictionary with account counts, total processed transactions, etc.
    """
    with _ledger_lock:
        ledger = _read_ledger_file(ledger_path)
        accounts = ledger.get("accounts", {})
        processed = ledger.get("processed_transactions", {})
        
        return {
            "total_accounts": len(accounts),
            "total_processed_transactions": len(processed),
            "accounts": {
                acc_id: {
                    "current_balance": float(acc_data.get("current_balance", 0)),
                    "currency": acc_data.get("currency", "USD"),
                    "account_type": acc_data.get("account_type"),
                }
                for acc_id, acc_data in accounts.items()
            },
        }

