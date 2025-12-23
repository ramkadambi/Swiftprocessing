# Test Suite

Comprehensive test suite for the payment processing system that validates the entire flow from ingress to egress without requiring a running Kafka instance.

## Test Structure

### `test_mocks.py`
Mock Kafka producer and consumer implementations that store messages in memory, allowing tests to run without real Kafka.

### `test_satellites.py`
Unit tests for each satellite service:
- **Account Validation**: Tests validation logic and enrichment
- **Sanctions Check**: Tests sanctions screening
- **Balance Check**: Tests funds availability
- **Payment Posting**: Tests posting with debit/credit entries

### `test_integration.py`
End-to-end integration tests that validate the complete payment processing flow:
- Happy path: All satellites PASS
- Failure scenarios: Individual satellite failures

### `test_routing_scenarios.py`
Tests for routing validation scenarios:
- USD domestic FED direct
- USD cross-border CHIPS high-value
- USD individual beneficiary
- USD fallback to SWIFT
- Routing decision object creation

## Running Tests

### Run all tests:
```bash
python tests/run_all_tests.py
```

### Run with verbose output:
```bash
python tests/run_all_tests.py -v
```

### Run specific test file:
```bash
python tests/run_all_tests.py tests/test_satellites.py
```

### Run specific test class:
```bash
python tests/run_all_tests.py tests/test_satellites.py::TestAccountValidation
```

### Run specific test:
```bash
python tests/run_all_tests.py tests/test_satellites.py::TestAccountValidation::test_simulate_account_validation_pass
```

### Using pytest directly:
```bash
pytest tests/ -v
pytest tests/test_satellites.py -v
pytest tests/test_integration.py::TestFullPaymentFlow::test_happy_path_full_flow -v
```

## Test Coverage

The test suite covers:

1. **Unit Tests**: Each satellite's core logic
2. **Integration Tests**: Full flow from ingress through all satellites
3. **Routing Tests**: All routing scenarios from routing_rules.json
4. **Error Handling**: Failure scenarios and error propagation
5. **Data Validation**: PaymentEvent enrichment and RoutingDecision creation

## Mock Kafka Components

The mock components (`MockKafkaProducer`, `MockKafkaConsumer`) simulate Kafka behavior:
- Messages are stored in memory dictionaries keyed by topic
- Consumers can subscribe to topics and process messages
- Producers send messages to in-memory queues
- No network or external dependencies required

## Example Test Output

```
tests/test_satellites.py::TestAccountValidation::test_simulate_account_validation_pass PASSED
tests/test_satellites.py::TestAccountValidation::test_account_validation_service_pass PASSED
tests/test_integration.py::TestFullPaymentFlow::test_happy_path_full_flow PASSED
tests/test_routing_scenarios.py::TestRoutingScenarios::test_usd_domestic_fed_direct PASSED
```

## Adding New Tests

1. Create test functions in the appropriate test file
2. Use `create_test_payment_event()` helper for PaymentEvent creation
3. Use `MockKafkaConsumerWrapper` and `MockKafkaProducerWrapper` for Kafka mocks
4. Verify message flow by checking producer message queues
5. Assert expected outcomes (ServiceResult status, routing decisions, etc.)

## Dependencies

- `pytest` (optional): Test framework for advanced test features
- All project dependencies (canonical, satellites, orchestrator, etc.)

### Install pytest (recommended):
```bash
pip install pytest
```

### Or use the simple test runner (no pytest required):
```bash
python tests/run_tests_simple.py
```

The simple test runner runs basic unit tests without requiring pytest, but pytest provides better output and more features.

