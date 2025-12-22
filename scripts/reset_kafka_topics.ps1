Write-Host "==============================="
Write-Host " KAFKA TOPIC RESET - STARTED"
Write-Host "==============================="

$KAFKA_CONTAINER = "kafka"
$BOOTSTRAP = "localhost:9092"

$TOPICS = @(
    # Ingress / Final
    "payments.orchestrator.in",
    "payments.final",

    # Step topics
    "payments.step.account_validation",
    "payments.step.routing_validation",
    "payments.step.sanctions_check",
    "payments.step.balance_check",
    "payments.step.payment_posting",
    "payments.step.credit_confirmation",

    # Result topics
    "service.results.account_validation",
    "service.results.routing_validation",
    "service.results.sanctions_check",
    "service.results.balance_check",
    "service.results.payment_posting",

    # Error topics
    "service.errors.account_validation",
    "service.errors.routing_validation",
    "service.errors.sanctions_check",
    "service.errors.balance_check",
    "service.errors.payment_posting"
)

# -----------------------------
# DELETE TOPICS
# -----------------------------
Write-Host "`nDeleting Kafka topics..."

foreach ($topic in $TOPICS) {
    Write-Host "Deleting topic: $topic"
    docker exec $KAFKA_CONTAINER kafka-topics `
        --bootstrap-server $BOOTSTRAP `
        --delete `
        --topic $topic 2>$null
}

Write-Host "`nWaiting for deletion to complete..."
Start-Sleep -Seconds 10

# -----------------------------
# CREATE TOPICS
# -----------------------------
Write-Host "`nRecreating Kafka topics..."

foreach ($topic in $TOPICS) {
    Write-Host "Creating topic: $topic"
    docker exec $KAFKA_CONTAINER kafka-topics `
        --bootstrap-server $BOOTSTRAP `
        --create `
        --topic $topic `
        --partitions 1 `
        --replication-factor 1
}

Write-Host "`n==============================="
Write-Host " KAFKA TOPIC RESET - COMPLETED"
Write-Host "==============================="
