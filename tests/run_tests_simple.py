"""
Simple test runner that doesn't require pytest.

Usage:
    python tests/run_tests_simple.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from tests.test_satellites import (
    TestAccountValidation,
    TestBalanceCheck,
    TestPaymentPosting,
    TestSanctionsCheck,
    create_test_payment_event,
)
from tests.test_routing_scenarios import TestRoutingScenarios, create_payment_with_enrichment


def run_test(test_name: str, test_func) -> bool:
    """Run a single test and return True if it passes."""
    try:
        test_func()
        print(f"✓ {test_name}")
        return True
    except Exception as e:
        print(f"✗ {test_name}: {e}")
        import traceback
        traceback.print_exc()
        return False


def main() -> None:
    """Run all tests."""
    print("Running test suite...\n")
    
    passed = 0
    failed = 0
    
    # Test Account Validation
    print("Testing Account Validation:")
    test_account = TestAccountValidation()
    if run_test("simulate_account_validation_pass", test_account.test_simulate_account_validation_pass):
        passed += 1
    else:
        failed += 1
    
    if run_test("simulate_account_validation_fail", test_account.test_simulate_account_validation_fail):
        passed += 1
    else:
        failed += 1
    
    # Test Sanctions Check
    print("\nTesting Sanctions Check:")
    test_sanctions = TestSanctionsCheck()
    if run_test("simulate_sanctions_check_pass", test_sanctions.test_simulate_sanctions_check_pass):
        passed += 1
    else:
        failed += 1
    
    if run_test("simulate_sanctions_check_fail", test_sanctions.test_simulate_sanctions_check_fail):
        passed += 1
    else:
        failed += 1
    
    # Test Balance Check
    print("\nTesting Balance Check:")
    test_balance = TestBalanceCheck()
    if run_test("simulate_balance_check_pass", test_balance.test_simulate_balance_check_pass):
        passed += 1
    else:
        failed += 1
    
    if run_test("simulate_balance_check_fail_amount", test_balance.test_simulate_balance_check_fail_amount):
        passed += 1
    else:
        failed += 1
    
    # Test Payment Posting
    print("\nTesting Payment Posting:")
    test_posting = TestPaymentPosting()
    if run_test("simulate_payment_posting_pass", test_posting.test_simulate_payment_posting_pass):
        passed += 1
    else:
        failed += 1
    
    # Summary
    print(f"\n{'='*50}")
    print(f"Tests passed: {passed}")
    print(f"Tests failed: {failed}")
    print(f"Total: {passed + failed}")
    print(f"{'='*50}")
    
    if failed > 0:
        sys.exit(1)
    else:
        print("\nAll tests passed! ✓")


if __name__ == "__main__":
    main()

