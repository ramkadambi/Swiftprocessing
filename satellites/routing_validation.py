from __future__ import annotations

import json
import os
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Optional, Union

from canonical import (
    Agent,
    PaymentEvent,
    RoutingDecision,
    RoutingNetwork,
    ServiceResult,
    ServiceResultStatus,
    Urgency,
)
from ingress.mx_receiver import payment_event_to_json_bytes
from kafka_bus import KafkaConsumerWrapper, KafkaProducerWrapper
from orchestrator import topics
from satellites import aba_lookup, bic_lookup, chips_lookup


SERVICE_NAME = "routing_validation"
DEFAULT_INPUT_TOPIC = topics.TOPIC_ROUTING_VALIDATION_IN
DEFAULT_RESULT_TOPIC = topics.TOPIC_ROUTING_VALIDATION_OUT
DEFAULT_ERROR_TOPIC = topics.TOPIC_ROUTING_VALIDATION_ERR


def _service_result_to_json_bytes(result: ServiceResult) -> bytes:
    d = asdict(result)
    st = d.get("status")
    if hasattr(st, "value"):
        d["status"] = st.value
    return json.dumps(d, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _load_routing_rules(config_path: str | Path) -> list[dict[str, Any]]:
    """Load routing rules from JSON config file."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Routing rules config not found: {config_path}")
    
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    # Support both "routing_rules" and "rules" keys
    rules = data.get("routing_rules", data.get("rules", []))
    # Sort by priority (lower number = higher priority)
    rules.sort(key=lambda r: r.get("priority", 999))
    return rules


def _build_routing_context(event: PaymentEvent) -> dict[str, Any]:
    """Build routing context from PaymentEvent for rule matching."""
    # Use BIC lookup to enrich context
    creditor_bic = event.creditor_agent.id_value or ""
    bic_data = bic_lookup.lookup_bic(creditor_bic) if creditor_bic else None
    
    creditor_country = event.creditor_agent.country
    if not creditor_country and bic_data:
        creditor_country = bic_data.get("country")
    
    # Get intermediary bank info if present
    intermediary_bic = None
    intermediary_bic_data = None
    if event.agent_chain and len(event.agent_chain) > 0:
        intermediary_bic = event.agent_chain[0].id_value or ""
        if intermediary_bic:
            intermediary_bic_data = bic_lookup.lookup_bic(intermediary_bic)
    
    # Determine "next bank" - the bank we're routing to (creditor or intermediary)
    next_bank_bic = intermediary_bic or creditor_bic
    next_bank_data = intermediary_bic_data or bic_data
    
    ctx: dict[str, Any] = {
        "currency": event.currency,
        "amount": float(event.amount),
        "sender_country": event.debtor_agent.country or "UNKNOWN",
        "creditor_country": creditor_country or "UNKNOWN",
        "ultimate_creditor_country": creditor_country or "UNKNOWN",  # For routing_rulesV2.json
    }
    
    # Add MT103-style fields for routing_rulesV2.json compatibility
    ctx["mt103"] = {
        "credit_agent_bic": creditor_bic,
        "intermediary_bic": intermediary_bic,
        "debtor_agent_bic": event.debtor_agent.id_value or "",
    }
    
    # Add BIC lookup data
    if bic_data:
        ctx["bic_lookup"] = {
            "bank_name": bic_data.get("bank_name"),
            "country": bic_data.get("country"),
            "fed_member": bic_data.get("fed_member", False),
            "chips_member": bic_data.get("chips_member", False),
            "aba_routing": bic_data.get("aba_routing"),
            "chips_uid": bic_data.get("chips_uid"),
        }
    
    # Add "next_bank" data for routing_rulesV2.json
    if next_bank_data:
        ctx["next_bank"] = {
            "chips_id_exists": bool(next_bank_data.get("chips_uid")),
            "aba_exists": bool(next_bank_data.get("aba_routing")),
            "bic": next_bank_bic,
            "country": next_bank_data.get("country"),
        }
    else:
        ctx["next_bank"] = {
            "chips_id_exists": False,
            "aba_exists": False,
            "bic": next_bank_bic,
            "country": None,
        }
    
    if event.account_validation:
        av = event.account_validation
        ctx["account_validation"] = {
            "creditor_type": av.creditor_type.value,
            "fed_member": av.fed_member,
            "chips_member": av.chips_member,
            "nostro_with_us": av.nostro_with_us,
            "vostro_with_us": av.vostro_with_us,
            "preferred_correspondent": av.preferred_correspondent,
        }
    
    # Add payment ecosystem context (for R5 decision_matrix)
    # In production, this would come from external services
    ctx["payment_ecosystem"] = {
        "chips_cutoff_passed": False,  # Default, can be overridden in tests
        "chips_queue_depth": "NORMAL",  # NORMAL | HIGH
    }
    
    # Add routing context (for R5 decision_matrix)
    ctx["customer_preference"] = None  # FED | CHIPS | NONE
    ctx["payment_urgency"] = "NORMAL"  # NORMAL | HIGH
    
    return ctx


def _match_rule_conditions(ctx: dict[str, Any], conditions: dict[str, Any]) -> bool:
    """Check if routing context matches rule conditions."""
    # Currency match
    if "currency" in conditions:
        if ctx.get("currency") != conditions["currency"]:
            return False
    
    # Amount thresholds
    if "amount_threshold" in conditions:
        if ctx.get("amount", 0) < conditions["amount_threshold"]:
            return False
    
    if "amount_threshold_max" in conditions:
        if ctx.get("amount", 0) >= conditions["amount_threshold_max"]:
            return False
    
    # Country matches
    if "sender_country" in conditions:
        if ctx.get("sender_country") != conditions["sender_country"]:
            return False
    
    if "creditor_country" in conditions:
        if ctx.get("creditor_country") != conditions["creditor_country"]:
            return False
    
    # MT103-style conditions (for routing_rulesV2.json)
    if "mt103.credit_agent_bic" in conditions:
        mt103_ctx = ctx.get("mt103", {})
        if mt103_ctx.get("credit_agent_bic", "").upper() != conditions["mt103.credit_agent_bic"].upper():
            return False
    
    if "mt103.intermediary_bic" in conditions:
        mt103_ctx = ctx.get("mt103", {})
        ctx_intermediary = mt103_ctx.get("intermediary_bic") or ""
        cond_intermediary = conditions["mt103.intermediary_bic"] or ""
        if ctx_intermediary.upper() != cond_intermediary.upper():
            return False
    
    # Ultimate creditor country (for routing_rulesV2.json)
    if "ultimate_creditor_country" in conditions:
        if ctx.get("ultimate_creditor_country") != conditions["ultimate_creditor_country"]:
            return False
    
    if "ultimate_creditor_country_not" in conditions:
        if ctx.get("ultimate_creditor_country") == conditions["ultimate_creditor_country_not"]:
            return False
    
    # Next bank conditions (for routing_rulesV2.json)
    if "next_bank.chips_id_exists" in conditions:
        next_bank = ctx.get("next_bank", {})
        if next_bank.get("chips_id_exists") != conditions["next_bank.chips_id_exists"]:
            return False
    
    if "next_bank.aba_exists" in conditions:
        next_bank = ctx.get("next_bank", {})
        if next_bank.get("aba_exists") != conditions["next_bank.aba_exists"]:
            return False
    
    # Account validation conditions
    if "account_validation" in conditions:
        av_cond = conditions["account_validation"]
        av_ctx = ctx.get("account_validation", {})
        
        for key, expected_value in av_cond.items():
            if key == "preferred_correspondent":
                if expected_value.get("exists") and not av_ctx.get("preferred_correspondent"):
                    return False
            elif av_ctx.get(key) != expected_value:
                return False
    
    return True


def _create_routing_decision(
    event: PaymentEvent, rule: dict[str, Any], ctx: dict[str, Any], selected_network: RoutingNetwork
) -> RoutingDecision:
    """Create RoutingDecision object from rule actions and context."""
    actions = rule.get("actions", {})
    
    # Get BIC lookup data
    creditor_bic = event.creditor_agent.id_value or ""
    bic_data = bic_lookup.lookup_bic(creditor_bic) if creditor_bic else None
    
    # Determine intermediary bank from agent_chain or actions
    intermediary_bank: Optional[Agent] = None
    
    # Check if we need to insert/substitute intermediary
    if "insert_intermediary" in actions:
        insert_action = actions["insert_intermediary"]
        agent_data = insert_action.get("agent", {})
        agent_id_value = agent_data.get("id_value", "")
        
        # Resolve template variables
        if agent_id_value.startswith("${") and agent_id_value.endswith("}"):
            var_path = agent_id_value[2:-1]
            parts = var_path.split(".")
            if len(parts) == 2 and parts[0] == "account_validation":
                agent_id_value = ctx.get("account_validation", {}).get(parts[1], "")
        
        # Lookup intermediary BIC data
        intermediary_bic_data = bic_lookup.lookup_bic(agent_id_value) if agent_id_value else None
        intermediary_bank = Agent(
            id_scheme=agent_data.get("id_scheme", "BIC"),
            id_value=agent_id_value,
            name=agent_data.get("name") or (intermediary_bic_data.get("bank_name") if intermediary_bic_data else None),
            country=intermediary_bic_data.get("country") if intermediary_bic_data else None,
        )
    elif "substitute_intermediary" in actions:
        sub_action = actions["substitute_intermediary"]
        agent_data = sub_action.get("agent", {})
        agent_id_value = agent_data.get("id_value", "")
        
        # Resolve template variables
        if agent_id_value.startswith("${") and agent_id_value.endswith("}"):
            var_path = agent_id_value[2:-1]
            parts = var_path.split(".")
            if len(parts) == 2 and parts[0] == "account_validation":
                agent_id_value = ctx.get("account_validation", {}).get(parts[1], "")
        
        # Lookup intermediary BIC data
        intermediary_bic_data = bic_lookup.lookup_bic(agent_id_value) if agent_id_value else None
        intermediary_bank = Agent(
            id_scheme=agent_data.get("id_scheme", "BIC"),
            id_value=agent_id_value,
            name=agent_data.get("name") or (intermediary_bic_data.get("bank_name") if intermediary_bic_data else None),
            country=intermediary_bic_data.get("country") if intermediary_bic_data else None,
        )
    
    # Build creditor bank with enriched data
    creditor_bank = Agent(
        id_scheme=event.creditor_agent.id_scheme,
        id_value=event.creditor_agent.id_value,
        name=event.creditor_agent.name or (bic_data.get("bank_name") if bic_data else None),
        country=event.creditor_agent.country or (bic_data.get("country") if bic_data else None),
    )
    
    # Build sender bank (debtor agent)
    sender_bic = event.debtor_agent.id_value or ""
    sender_bic_data = bic_lookup.lookup_bic(sender_bic) if sender_bic else None
    sender_bank = Agent(
        id_scheme=event.debtor_agent.id_scheme,
        id_value=event.debtor_agent.id_value,
        name=event.debtor_agent.name or (sender_bic_data.get("bank_name") if sender_bic_data else None),
        country=event.debtor_agent.country or (sender_bic_data.get("country") if sender_bic_data else None),
    )
    
    # Determine urgency (default to NORMAL, could be extracted from PaymentEvent in future)
    urgency = Urgency.NORMAL
    
    return RoutingDecision(
        selected_network=selected_network,
        sender_bank=sender_bank,
        creditor_bank=creditor_bank,
        intermediary_bank=intermediary_bank,
        urgency=urgency,
        customer_preference=None,  # Could be extracted from PaymentEvent in future
        routing_rule_applied=rule.get("rule_id"),
        bic_lookup_data=bic_data,
        account_validation_data=event.account_validation,
    )


def _apply_rule_actions(
    event: PaymentEvent, rule: dict[str, Any], ctx: dict[str, Any]
) -> PaymentEvent:
    """Apply routing rule actions to PaymentEvent."""
    actions = rule.get("actions", {})
    
    # Check for decision_matrix (for R5 in routing_rulesV2.json)
    selected_network = None
    if "decision_matrix" in rule:
        decision_matrix = rule["decision_matrix"]
        if_conditions = decision_matrix.get("if", [])
        
        # Evaluate if conditions in order
        for condition_block in if_conditions:
            condition_expr = condition_block.get("condition", "")
            route_value = condition_block.get("route", "")
            
            # Parse condition expression
            if "payment_ecosystem.chips_cutoff_passed == true" in condition_expr:
                if ctx.get("payment_ecosystem", {}).get("chips_cutoff_passed", False):
                    selected_network = RoutingNetwork(route_value)
                    break
            elif "payment_ecosystem.chips_queue_depth == HIGH" in condition_expr:
                if ctx.get("payment_ecosystem", {}).get("chips_queue_depth") == "HIGH":
                    selected_network = RoutingNetwork(route_value)
                    break
            elif "customer_preference == FED" in condition_expr:
                if ctx.get("customer_preference") == "FED":
                    selected_network = RoutingNetwork(route_value)
                    break
            elif "payment_urgency == HIGH" in condition_expr:
                if ctx.get("payment_urgency") == "HIGH":
                    selected_network = RoutingNetwork(route_value)
                    break
        
        # If no if condition matched, use else
        if selected_network is None:
            else_block = decision_matrix.get("else", {})
            route_value = else_block.get("route", "CHIPS")
            selected_network = RoutingNetwork(route_value)
    
    # Select network from actions (for routing_rules.json or routing_rulesV2.json)
    if selected_network is None:
        if "select_network" in actions:
            network_str = actions["select_network"]
            try:
                selected_network = RoutingNetwork(network_str)
            except ValueError:
                print(f"[RoutingValidation] WARNING: Invalid network '{network_str}', skipping")
                selected_network = RoutingNetwork.SWIFT  # Fallback
        elif "selected_network" in actions:
            network_str = actions["selected_network"]
            try:
                selected_network = RoutingNetwork(network_str)
            except ValueError:
                print(f"[RoutingValidation] WARNING: Invalid network '{network_str}', skipping")
                selected_network = RoutingNetwork.SWIFT  # Fallback
    
    if selected_network is None:
        selected_network = RoutingNetwork.SWIFT  # Default fallback
    
    # Create RoutingDecision object
    routing_decision = _create_routing_decision(event, rule, ctx, selected_network)
    
    # Build agent chain from routing decision
    agent_chain: list[Agent] = []
    if routing_decision.intermediary_bank:
        agent_chain.append(routing_decision.intermediary_bank)
    
    # Create enriched PaymentEvent with routing decision
    return PaymentEvent(
        msg_id=event.msg_id,
        end_to_end_id=event.end_to_end_id,
        amount=event.amount,
        currency=event.currency,
        debtor_agent=event.debtor_agent,
        creditor_agent=event.creditor_agent,
        status=event.status,
        account_validation=event.account_validation,
        selected_network=selected_network,
        agent_chain=agent_chain if agent_chain else None,
        routing_rule_applied=rule.get("rule_id"),
        routing_decision=routing_decision,
    )


def _apply_routing_rules(event: PaymentEvent, rules: list[dict[str, Any]]) -> PaymentEvent:
    """Apply first matching routing rule to PaymentEvent."""
    ctx = _build_routing_context(event)
    
    for rule in rules:
        conditions = rule.get("conditions", {})
        if _match_rule_conditions(ctx, conditions):
            print(
                f"[RoutingValidation] Rule matched: {rule.get('rule_id')} - {rule.get('description')}"
            )
            
            # Check if rule only invokes services (like R2) without routing
            actions = rule.get("actions", {})
            if "invoke_services" in actions and "selected_network" not in actions and "select_network" not in actions:
                # Rule only invokes services, continue to next rule
                print(f"[RoutingValidation] Rule {rule.get('rule_id')} only invokes services, continuing to next rule")
                # Note: In production, invoke_services would enrich the context
                # For R2, after invoking services, we need to update next_bank to point to creditor bank
                # (not intermediary) for subsequent rules to check creditor's CHIPS/FED capabilities
                if rule.get("rule_id") == "WF-MT103-R2-US-INTERMEDIARY-LOOKUP":
                    # Update next_bank to creditor bank (not intermediary) for subsequent rule matching
                    creditor_bic = event.creditor_agent.id_value or ""
                    creditor_bic_data = bic_lookup.lookup_bic(creditor_bic) if creditor_bic else None
                    if creditor_bic_data:
                        ctx["next_bank"] = {
                            "chips_id_exists": bool(creditor_bic_data.get("chips_uid")),
                            "aba_exists": bool(creditor_bic_data.get("aba_routing")),
                            "bic": creditor_bic,
                            "country": creditor_bic_data.get("country"),
                        }
                    print(f"[RoutingValidation] Updated next_bank to creditor bank: {creditor_bic}")
                continue
            
            return _apply_rule_actions(event, rule, ctx)
    
    # No rule matched - this should not happen if fallback rule exists
    print("[RoutingValidation] WARNING: No routing rule matched, using original event")
    return event


class RoutingValidationService:
    """
    Kafka consumer for routing validation satellite:
    - consume enriched PaymentEvent (with account_validation data)
    - apply routing rules from config
    - enrich PaymentEvent with routing decisions
    - publish to next step (sanctions_check)
    """

    def __init__(
        self,
        *,
        consumer: KafkaConsumerWrapper,
        producer: KafkaProducerWrapper,
        input_topics: Optional[list[str]] = None,
        result_topic: str = DEFAULT_RESULT_TOPIC,
        error_topic: str = DEFAULT_ERROR_TOPIC,
        service_name: str = SERVICE_NAME,
        routing_rules_path: str | Path = "config/routing_rules.json",
        key_fn: Optional[Callable[[PaymentEvent], Optional[Union[str, bytes]]]] = None,
    ) -> None:
        self._consumer = consumer
        self._producer = producer
        self._result_topic = result_topic
        self._error_topic = error_topic
        self._service_name = service_name
        self._key_fn = key_fn
        
        # Load routing rules at startup
        print(f"[RoutingValidation] Loading routing rules from: {routing_rules_path}")
        self._routing_rules = _load_routing_rules(routing_rules_path)
        print(f"[RoutingValidation] Loaded {len(self._routing_rules)} routing rules")

        topics_to_subscribe = input_topics or [DEFAULT_INPUT_TOPIC]
        print(f"[RoutingValidation] Subscribing to topics: {topics_to_subscribe}")
        self._consumer.subscribe(topics_to_subscribe)

    def _handle_event(self, event: PaymentEvent) -> Any:
        print(
            f"[RoutingValidation] Received PaymentEvent: E2E={event.end_to_end_id}, "
            f"MsgId={event.msg_id}, Amount={event.amount} {event.currency}"
        )
        
        # Check if account_validation enrichment exists
        if not event.account_validation:
            print(
                f"[RoutingValidation] ERROR: PaymentEvent missing account_validation enrichment for E2E={event.end_to_end_id}"
            )
            result = ServiceResult(
                end_to_end_id=event.end_to_end_id,
                service_name=self._service_name,
                status=ServiceResultStatus.ERROR,
            )
            payload = _service_result_to_json_bytes(result)
            key = self._key_fn(event) if self._key_fn else event.end_to_end_id
            self._producer.send_bytes(self._error_topic, key, payload)
            return result
        
        # Apply routing rules
        try:
            routed_event = _apply_routing_rules(event, self._routing_rules)
            print(
                f"[RoutingValidation] Routing applied: network={routed_event.selected_network.value if routed_event.selected_network else 'NONE'}, "
                f"rule={routed_event.routing_rule_applied}, "
                f"agent_chain_len={len(routed_event.agent_chain) if routed_event.agent_chain else 0}"
            )
            
            # Cache routed PaymentEvent internally (orchestrator will retrieve it)
            # Store it in a way orchestrator can access - publish to output topic as PaymentEvent
            # But output topic is for ServiceResult... 
            # Actually, we need to publish routed PaymentEvent somewhere orchestrator can consume it
            # Following account_validation pattern: publish routed PaymentEvent directly to next step input
            # But user wants only 3 topics... 
            # Solution: Store routed event in memory cache, orchestrator will retrieve via ServiceResult correlation
            # OR: Publish routed PaymentEvent to output topic (mixed with ServiceResult - not ideal)
            # OR: Publish routed PaymentEvent directly to next step (like account_validation does)
            
            # Following account_validation pattern: publish routed PaymentEvent directly to next step
            # But this breaks the "only 3 topics" rule...
            # Actually, account_validation publishes to routing_validation INPUT, which is routing_validation's IN topic
            # So routing_validation should publish routed PaymentEvent to sanctions_check INPUT topic
            # But that's not one of routing_validation's 3 topics - it's sanctions_check's IN topic
            
            # I think the pattern is: satellites publish enriched/routed events directly to next satellite's INPUT
            # This is not counted as one of the satellite's own topics
            routed_payload = payment_event_to_json_bytes(routed_event)
            key = self._key_fn(event) if self._key_fn else event.end_to_end_id
            
            # Publish routed PaymentEvent directly to next step (sanctions_check) - like account_validation does
            next_step_topic = topics.TOPIC_SANCTIONS_CHECK_IN
            print(f"[RoutingValidation] Publishing routed PaymentEvent to next step topic='{next_step_topic}'")
            self._producer.send_bytes(next_step_topic, key, routed_payload)
            
            # Publish ServiceResult to output topic (like all other satellites)
            result = ServiceResult(
                end_to_end_id=event.end_to_end_id,
                service_name=self._service_name,
                status=ServiceResultStatus.PASS,
            )
            result_payload = _service_result_to_json_bytes(result)
            print(f"[RoutingValidation] Publishing ServiceResult to topic='{self._result_topic}'")
            self._producer.send_bytes(self._result_topic, key, result_payload)
            
            return result
            
        except Exception as e:
            import traceback
            print(f"[RoutingValidation] ERROR processing E2E={event.end_to_end_id}: {e}")
            traceback.print_exc()
            result = ServiceResult(
                end_to_end_id=event.end_to_end_id,
                service_name=self._service_name,
                status=ServiceResultStatus.ERROR,
            )
            payload = _service_result_to_json_bytes(result)
            key = self._key_fn(event) if self._key_fn else event.end_to_end_id
            self._producer.send_bytes(self._error_topic, key, payload)
            return result

    def run(
        self,
        *,
        poll_timeout_s: float = 1.0,
        max_messages: Optional[int] = None,
        on_error: Optional[Callable[[Exception], Any]] = None,
    ) -> int:
        from kafka_bus.consumer import payment_event_from_json
        
        return self._consumer.run(
            self._handle_event,
            deserializer=payment_event_from_json,
            poll_timeout_s=poll_timeout_s,
            max_messages=max_messages,
            on_error=on_error,
        )

    def close(self) -> None:
        self._consumer.close()
        self._producer.flush()


def main():
    print("[RoutingValidation] Starting Routing Validation Service...")
    
    # Determine config path relative to project root
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    config_path = project_root / "config" / "routing_rules.json"
    
    consumer = KafkaConsumerWrapper(
        group_id="routing-validation",
        bootstrap_servers="localhost:9092",
        auto_offset_reset="earliest",
    )
    producer = KafkaProducerWrapper(
        bootstrap_servers="localhost:9092",
    )
    service = RoutingValidationService(
        consumer=consumer,
        producer=producer,
        routing_rules_path=config_path,
    )
    print("[RoutingValidation] Routing Validation Service started. Listening to Kafka...")
    service.run()


if __name__ == "__main__":
    main()

