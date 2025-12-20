# ISO 20022 SWIFT MX POC

Flow:
1. Receive SWIFT MX pacs.008 / camt.054
2. Convert MX → canonical ISO 20022
3. Publish canonical event to Kafka
4. Async satellite processing
5. Aggregate results
6. Convert canonical → MX if forwarded

Running
docker-compose up -d
docker ps

Term1
.\venv\Scripts\activate
python -m orchestrator.orchestrator

Expected output
[Orchestrator] Subscribing ingress consumer to: ['payments.orchestrator.in']
[Orchestrator] Subscribing results consumer to: [...]
Payment Orchestrator started. Listening to Kafka...
[KafkaConsumerWrapper] Polling topics=['payments.orchestrator.in']

Term2 - 5
python -m satellites.account_validation
python -m satellites.sanctions_check
python -m satellites.balance_check
python -m satellites.payment_posting

Term6
python scripts\send_test_payment.py --e2e-id E2E-1001 --scenario happy
python scripts\send_test_payment.py --e2e-id E2E-1002 --scenario sanctions_fail
python scripts\send_test_payment.py --e2e-id E2E-1003 --scenario balance_fail
