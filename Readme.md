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
docker exec -it kafka kafka-broker-api-versions --bootstrap-server localhost:9092
docker exec -it kafka kafka-topics --bootstrap-server localhost:9092 --list

Check kafka is able to produce and consume messages natively
docker exec -it kafka kafka-console-consumer `
--bootstrap-server localhost:9092 `
--topic payments.orchestrator.in `
--from-beginning

docker exec -it kafka kafka-console-producer `
--broker-list localhost:9092 `
--topic payments.orchestrator.in

{"probe":"kafka-baseline"}


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
python -m satellites.routing_validation
python -m satellites.sanctions_check
python -m satellites.balance_check
python -m satellites.payment_posting

Term6
python -m scripts.send_test_payment --e2e-id E2E-1001 --scenario happy
python -m scripts.send_test_payment --e2e-id E2E-1002 --scenario sanctions_fail
python scripts\send_test_payment.py --e2e-id E2E-1003 --scenario balance_fail
python -m scripts.send_test_payment2 --e2e-id E2E-2001 --scenario r1_final_credit
python -m scripts.send_test_payment2 --e2e-id E2E-2001 --scenario r2_fed_direct
python -m scripts.send_test_payment2 --e2e-id E2E-2001 --scenario r3_chips_high_value
python -m scripts.send_test_payment2 --e2e-id E2E-2001 --scenario r4_preferred_correspondent
python -m scripts.send_test_payment2 --e2e-id E2E-2001 --scenario r5_individual_beneficiary


#r1_final_credit routing_usd_individual