"""
Kafka topic naming conventions for the POC.

Goal:
- Satellites are unaware of predecessors/successors.
- Each satellite reads from ONE input topic and publishes to ONE output topic.
- FAIL/ERROR outcomes also go to a per-service error topic.
- Orchestrator routes sequentially based on ServiceResult.
"""

# Orchestrator ingress (canonical PaymentEvent from ingress)
TOPIC_CANONICAL_INGRESS = "payments.orchestrator.in"

# Per-step payment event topics (input to satellites)
TOPIC_ACCOUNT_VALIDATION_IN = "payments.step.account_validation"
TOPIC_ROUTING_VALIDATION_IN = "payments.step.routing_validation"
TOPIC_SANCTIONS_CHECK_IN = "payments.step.sanctions_check"
TOPIC_BALANCE_CHECK_IN = "payments.step.balance_check"
TOPIC_PAYMENT_POSTING_IN = "payments.step.payment_posting"

# Per-service results topics (output from satellites - ServiceResult only)
TOPIC_ACCOUNT_VALIDATION_OUT = "service.results.account_validation"
TOPIC_ROUTING_VALIDATION_OUT = "service.results.routing_validation"
TOPIC_SANCTIONS_CHECK_OUT = "service.results.sanctions_check"
TOPIC_BALANCE_CHECK_OUT = "service.results.balance_check"
TOPIC_PAYMENT_POSTING_OUT = "service.results.payment_posting"

# Per-service error topics (output from satellites and/or orchestrator)
TOPIC_ACCOUNT_VALIDATION_ERR = "service.errors.account_validation"
TOPIC_ROUTING_VALIDATION_ERR = "service.errors.routing_validation"
TOPIC_SANCTIONS_CHECK_ERR = "service.errors.sanctions_check"
TOPIC_BALANCE_CHECK_ERR = "service.errors.balance_check"
TOPIC_PAYMENT_POSTING_ERR = "service.errors.payment_posting"

# Final status topic (emitted when all services succeed)
TOPIC_FINAL_STATUS = "payments.final"


