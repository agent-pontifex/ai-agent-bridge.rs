mod tests {
    use super::*;

    fn proposal() -> PublishEvent {
        PublishEvent {
            client_event_id: "client-event-0001".to_string(),
            session_id: "den-1873-live".to_string(),
            channel: "den-1873-live".to_string(),
            sender: "claude".to_string(),
            recipients: vec!["chatgpt".to_string(), "grok".to_string()],
            correlation_id: Some("review-round-1".to_string()),
            causation_id: None,
            idempotency_key: "claude-review-round-0001".to_string(),
            payload: json!({
                "kind": "proposal",
                "proposal_id": "proposal-0001",
                "summary": "Keep GitHub and Linear as the durable delivery ledgers."
            }),
            extensions: BTreeMap::new(),
        }
    }

    #[test]
    fn validates_and_hashes_provider_neutral_proposal() {
        let event = proposal();
        validate_publish_event("den-1873-live", &event).unwrap();
        let first = event_digest(&event).unwrap();
        let second = event_digest(&event).unwrap();
        assert_eq!(first, second);
        assert_eq!(first.len(), 64);
    }

    #[test]
    fn rejects_hidden_reasoning_even_inside_extensions() {
        let mut event = proposal();
        event.extensions.insert(
            "vendor.trace".to_string(),
            json!({"nested":{"chain_of_thought":"not allowed"}}),
        );
        assert!(validate_publish_event("den-1873-live", &event).is_err());
    }

    #[test]
    fn rejects_unknown_payload_fields_and_conflicting_route_identity() {
        let mut event = proposal();
        event.payload["surprise"] = json!(true);
        assert!(validate_publish_event("den-1873-live", &event).is_err());
        event.payload.as_object_mut().unwrap().remove("surprise");
        assert!(validate_publish_event("another-session", &event).is_err());
    }

    #[test]
    fn legacy_messages_still_fill_the_ordered_live_log() {
        let message = Message {
            id: "5f752a77-80e4-47f8-8f91-41f2a3f71352".to_string(),
            channel: "den-1873-live".to_string(),
            seq: 7,
            from: "human-reviewer".to_string(),
            role: Role::User,
            content: "Review the proposal.".to_string(),
            meta: json!({}),
            created_at: "2026-09-01T17:00:00.000Z".to_string(),
        };
        let envelope = envelope_from_message(&message);
        assert_eq!(envelope["seq"], 7);
        assert_eq!(envelope["payload"]["kind"], "message");
        assert_eq!(
            envelope["extensions"]["agent-pontifex.compat"]["legacy_bridge_message"],
            true
        );
    }

    #[test]
    fn maps_chatgpt_claude_and_grok_to_provider_namespaces() {
        let base = |kind| Agent {
            agent_key: "agent".to_string(),
            display_name: "Agent".to_string(),
            kind,
            host: None,
            meta: json!({}),
            registered_at: "2026-09-01T17:00:00.000Z".to_string(),
        };
        assert_eq!(
            provider_and_model(Some(&base(AgentKind::ChatGpt))).0,
            "openai"
        );
        assert_eq!(
            provider_and_model(Some(&base(AgentKind::Claude))).0,
            "anthropic"
        );
        assert_eq!(provider_and_model(Some(&base(AgentKind::Grok))).0, "xai");
    }
}
