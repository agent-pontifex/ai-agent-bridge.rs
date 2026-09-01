fn session_view(state: &AppState, slug: &str) -> LiveResult<Value> {
    validate_token(slug, "session slug", MAX_ID_BYTES)?;
    let channel = state.get_channel(slug)?;
    validate_sequence(channel.message_count, true)?;
    let mut members = state.members(slug)?;
    members.sort_by(|left, right| left.agent_key.cmp(&right.agent_key));
    if members.is_empty() {
        return Err(LiveError::conflict(
            "live_session_empty",
            "a live session requires at least one registered participant",
        ));
    }
    let member_ids: BTreeSet<&str> = members
        .iter()
        .map(|member| member.agent_key.as_str())
        .collect();
    let created_by = if member_ids.contains(channel.created_by.as_str()) {
        channel.created_by.clone()
    } else {
        members[0].agent_key.clone()
    };
    let participants: Vec<Value> = members
        .iter()
        .map(|member| participant_view(state, member))
        .collect();
    let title = if channel.topic.trim().is_empty() {
        slug.to_string()
    } else {
        channel.topic
    };

    Ok(json!({
        "schema_version": LIVE_SCHEMA_VERSION,
        "protocol": LIVE_PROTOCOL_ID,
        "session_id": slug,
        "channel": slug,
        "title": title,
        "state": "active",
        "created_by": created_by,
        "created_at": channel.created_at,
        "participants": participants,
        "tracker_links": [],
        "high_water_seq": channel.message_count,
        "extensions": {
            "agent-pontifex.compat": {
                "profile": "bridge-channel-v1",
                "ordering": "existing-channel-sequence",
                "replay": "retained-channel-history",
                "idempotency": "retained-history-window"
            }
        }
    }))
}

fn participant_view(state: &AppState, member: &Member) -> Value {
    let agent = state.get_agent(&member.agent_key);
    let (provider, model) = provider_and_model(agent.as_ref());
    let display_name = agent
        .as_ref()
        .map(|value| value.display_name.trim())
        .filter(|value| !value.is_empty())
        .unwrap_or(&member.agent_key)
        .to_string();
    let capabilities = agent_capabilities(agent.as_ref());
    let runtime = agent
        .as_ref()
        .and_then(|value| metadata_token(value, "runtime", MAX_ID_BYTES));
    let instance_id = agent
        .as_ref()
        .and_then(|value| metadata_token(value, "instance_id", MAX_ID_BYTES));
    let role = match member.role {
        MemberRole::Owner => "moderator",
        MemberRole::Member => "member",
        MemberRole::Observer => "observer",
    };
    let mut identity = json!({
        "participant_id": member.agent_key,
        "provider": provider,
        "model": model,
    });
    if let Some(runtime) = runtime {
        identity["runtime"] = Value::String(runtime);
    }
    if let Some(instance_id) = instance_id {
        identity["instance_id"] = Value::String(instance_id);
    }

    json!({
        "identity": identity,
        "display_name": display_name,
        "role": role,
        "capabilities": capabilities,
        "joined_at": member.joined_at,
    })
}

fn provider_and_model(agent: Option<&Agent>) -> (String, String) {
    let metadata_provider = agent.and_then(|value| metadata_token(value, "provider", 128));
    let metadata_model = agent.and_then(|value| metadata_token(value, "model", MAX_ID_BYTES));
    let (default_provider, default_model) = match agent.map(|value| value.kind) {
        Some(AgentKind::ChatGpt | AgentKind::Codex) => ("openai", "chatgpt"),
        Some(AgentKind::Claude) => ("anthropic", "claude"),
        Some(AgentKind::Grok) => ("xai", "grok"),
        Some(AgentKind::Gemini) => ("google", "gemini"),
        Some(AgentKind::Kimi) => ("moonshot", "kimi"),
        Some(AgentKind::Qwen) => ("alibaba", "qwen"),
        Some(AgentKind::Human) => ("human", "human"),
        Some(AgentKind::Other) | None => ("custom", "unknown"),
    };
    (
        metadata_provider.unwrap_or_else(|| default_provider.to_string()),
        metadata_model.unwrap_or_else(|| default_model.to_string()),
    )
}

fn metadata_token(agent: &Agent, key: &str, max_bytes: usize) -> Option<String> {
    let value = agent.meta.get(key)?.as_str()?.trim();
    validate_token(value, key, max_bytes).ok()?;
    Some(value.to_string())
}

fn agent_capabilities(agent: Option<&Agent>) -> Vec<String> {
    let mut capabilities: Vec<String> = agent
        .and_then(|value| value.meta.get("capabilities"))
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .map(str::trim)
        .filter(|value| validate_namespaced_identifier(value, "capability").is_ok())
        .take(MAX_CAPABILITIES)
        .map(str::to_string)
        .collect();
    capabilities.sort();
    capabilities.dedup();
    if capabilities.is_empty() {
        capabilities.push("agent.chat".to_string());
    }
    capabilities
}

fn event_digest(event: &PublishEvent) -> LiveResult<String> {
    let bytes = serde_json::to_vec(event).map_err(|_| {
        LiveError::bad_request("live event could not be serialized for idempotency")
    })?;
    let digest = Sha256::digest(bytes);
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut encoded = String::with_capacity(digest.len() * 2);
    for byte in digest {
        encoded.push(HEX[(byte >> 4) as usize] as char);
        encoded.push(HEX[(byte & 0x0f) as usize] as char);
    }
    Ok(encoded)
}

fn stored_live_meta(message: &Message) -> Option<StoredLiveMeta> {
    let stored: StoredLiveMeta =
        serde_json::from_value(message.meta.get(LIVE_META_KEY)?.clone()).ok()?;
    if stored.schema_version != LIVE_SCHEMA_VERSION || stored.protocol != LIVE_PROTOCOL_ID {
        return None;
    }
    let event = PublishEvent {
        client_event_id: stored.client_event_id.clone(),
        session_id: stored.session_id.clone(),
        channel: message.channel.clone(),
        sender: message.from.clone(),
        recipients: stored.recipients.clone(),
        correlation_id: stored.correlation_id.clone(),
        causation_id: stored.causation_id.clone(),
        idempotency_key: stored.idempotency_key.clone(),
        payload: stored.payload.clone(),
        extensions: stored.extensions.clone(),
    };
    if validate_publish_event(&message.channel, &event).is_err() {
        return None;
    }
    let digest = event_digest(&event).ok()?;
    if digest != stored.request_digest {
        return None;
    }
    Some(stored)
}

fn envelope_from_message(message: &Message) -> Value {
    if let Some(stored) = stored_live_meta(message) {
        return json!({
            "schema_version": LIVE_SCHEMA_VERSION,
            "protocol": LIVE_PROTOCOL_ID,
            "event_id": message.id,
            "session_id": stored.session_id,
            "channel": message.channel,
            "seq": message.seq,
            "sender": message.from,
            "recipients": stored.recipients,
            "correlation_id": stored.correlation_id,
            "causation_id": stored.causation_id,
            "idempotency_key": stored.idempotency_key,
            "created_at": message.created_at,
            "payload": stored.payload,
            "extensions": stored.extensions,
        });
    }

    json!({
        "schema_version": LIVE_SCHEMA_VERSION,
        "protocol": LIVE_PROTOCOL_ID,
        "event_id": message.id,
        "session_id": message.channel,
        "channel": message.channel,
        "seq": message.seq,
        "sender": message.from,
        "recipients": [],
        "idempotency_key": format!("legacy-message:{}", message.id),
        "created_at": message.created_at,
        "payload": {
            "kind": "message",
            "content": message.content,
            "content_type": "text/plain"
        },
        "extensions": {
            "agent-pontifex.compat": {
                "legacy_bridge_message": true
            }
        }
    })
}

fn role_for_payload(payload: &Value) -> Role {
    match payload.get("kind").and_then(Value::as_str) {
        Some("tool_request" | "tool_result") => Role::Tool,
        _ => Role::Assistant,
    }
}

fn payload_summary(payload: &Value, max_bytes: usize) -> String {
    let object = payload.as_object();
    let kind = object
        .and_then(|value| value.get("kind"))
        .and_then(Value::as_str)
        .unwrap_or("event");
    let summary = match kind {
        "message" => object_string(object, "content"),
        "proposal" | "approval_request" | "work_status" | "handoff" | "tracker_update" => {
            object_string(object, "summary").or_else(|| object_string(object, "subject"))
        }
        "decision" | "approval_decision" => object_string(object, "decision_basis")
            .or_else(|| object_string(object, "outcome")),
        "tool_request" => {
            object_string(object, "action").map(|action| format!("tool request: {action}"))
        }
        "tool_result" => {
            object_string(object, "outcome").map(|outcome| format!("tool result: {outcome}"))
        }
        "error" => object_string(object, "message"),
        _ => None,
    }
    .unwrap_or_else(|| kind.to_string());
    truncate_utf8(summary, max_bytes)
}

fn object_string(object: Option<&Map<String, Value>>, key: &str) -> Option<String> {
    object?
        .get(key)?
        .as_str()
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
}

fn truncate_utf8(mut value: String, max_bytes: usize) -> String {
    if value.len() <= max_bytes {
        return value;
    }
    let mut end = max_bytes;
    while end > 0 && !value.is_char_boundary(end) {
        end -= 1;
    }
    value.truncate(end);
    value
}

fn sse_frame(frame: Value, seq: Option<u64>) -> SseEvent {
    let event = SseEvent::default().event("agent-pontifex.live");
    let event = if let Some(seq) = seq {
        event.id(seq.to_string())
    } else {
        event
    };
    event.json_data(frame).unwrap_or_default()
}
