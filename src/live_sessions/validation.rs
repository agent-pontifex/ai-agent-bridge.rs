fn validate_publish_event(slug: &str, event: &PublishEvent) -> LiveResult<()> {
    validate_token(slug, "session slug", MAX_ID_BYTES)?;
    validate_token(
        &event.client_event_id,
        "client_event_id",
        MAX_ID_BYTES,
    )?;
    validate_token(&event.session_id, "session_id", MAX_ID_BYTES)?;
    validate_token(&event.channel, "channel", MAX_ID_BYTES)?;
    validate_token(&event.sender, "sender", MAX_ID_BYTES)?;
    if event.session_id != slug || event.channel != slug {
        return Err(LiveError::bad_request(
            "the compatibility profile requires session_id and channel to equal the route slug",
        ));
    }
    validate_recipients(&event.recipients)?;
    validate_optional_token(&event.correlation_id, "correlation_id", MAX_ID_BYTES)?;
    validate_optional_token(&event.causation_id, "causation_id", MAX_ID_BYTES)?;
    validate_idempotency_key(&event.idempotency_key)?;
    validate_payload(&event.payload)?;
    validate_extensions(&event.extensions)
}

fn validate_payload(payload: &Value) -> LiveResult<()> {
    let bytes = serde_json::to_vec(payload)
        .map_err(|_| LiveError::bad_request("payload is not serializable"))?;
    if bytes.len() > MAX_JSON_BYTES {
        return Err(LiveError::new(
            StatusCode::PAYLOAD_TOO_LARGE,
            "payload_too_large",
            format!("live payload exceeds {MAX_JSON_BYTES} bytes"),
        ));
    }
    reject_private_trace_fields(payload)?;
    let object = payload
        .as_object()
        .ok_or_else(|| LiveError::bad_request("payload must be a JSON object"))?;
    let kind = required_string(object, "kind")?;
    match kind {
        "message" => {
            ensure_allowed_fields(object, &["kind", "content", "content_type"])?;
            validate_text(
                required_string(object, "content")?,
                "message content",
                MAX_TEXT_BYTES,
            )?;
            validate_optional_object_token(object, "content_type", 128)
        }
        "proposal" => {
            ensure_allowed_fields(object, &["kind", "proposal_id", "summary", "details"])?;
            validate_token(
                required_string(object, "proposal_id")?,
                "proposal_id",
                MAX_ID_BYTES,
            )?;
            validate_text(
                required_string(object, "summary")?,
                "proposal summary",
                16_384,
            )?;
            validate_optional_object_text(object, "details", MAX_TEXT_BYTES)
        }
        "decision" => {
            ensure_allowed_fields(
                object,
                &["kind", "proposal_id", "outcome", "decision_basis"],
            )?;
            validate_token(
                required_string(object, "proposal_id")?,
                "proposal_id",
                MAX_ID_BYTES,
            )?;
            validate_enum(
                object,
                "outcome",
                &["accepted", "rejected", "deferred", "superseded"],
            )?;
            validate_optional_object_text(object, "decision_basis", 16_384)
        }
        "tool_request" => {
            ensure_allowed_fields(
                object,
                &[
                    "kind",
                    "request_id",
                    "tool",
                    "action",
                    "capability",
                    "arguments",
                    "requires_approval",
                ],
            )?;
            validate_token(
                required_string(object, "request_id")?,
                "request_id",
                MAX_ID_BYTES,
            )?;
            validate_namespaced_identifier(required_string(object, "tool")?, "tool")?;
            validate_token(
                required_string(object, "action")?,
                "action",
                MAX_ID_BYTES,
            )?;
            validate_namespaced_identifier(
                required_string(object, "capability")?,
                "capability",
            )?;
            validate_optional_bool(object, "requires_approval")
        }
        "tool_result" => {
            ensure_allowed_fields(
                object,
                &[
                    "kind",
                    "request_id",
                    "outcome",
                    "result",
                    "error",
                    "evidence",
                ],
            )?;
            validate_token(
                required_string(object, "request_id")?,
                "request_id",
                MAX_ID_BYTES,
            )?;
            let outcome = validate_enum(
                object,
                "outcome",
                &["succeeded", "failed", "denied", "cancelled"],
            )?;
            validate_optional_object_text(object, "error", 16_384)?;
            if outcome == "failed" && object.get("error").and_then(Value::as_str).is_none() {
                return Err(LiveError::bad_request(
                    "failed tool results require a bounded error",
                ));
            }
            validate_evidence(object.get("evidence"))
        }
        "approval_request" => {
            ensure_allowed_fields(
                object,
                &[
                    "kind",
                    "approval_id",
                    "subject",
                    "requested_capabilities",
                    "expires_at",
                ],
            )?;
            validate_token(
                required_string(object, "approval_id")?,
                "approval_id",
                MAX_ID_BYTES,
            )?;
            validate_text(
                required_string(object, "subject")?,
                "approval subject",
                16_384,
            )?;
            validate_capabilities(object.get("requested_capabilities"), true)?;
            validate_timestamp(required_string(object, "expires_at")?, "expires_at")
        }
        "approval_decision" => {
            ensure_allowed_fields(
                object,
                &[
                    "kind",
                    "approval_id",
                    "outcome",
                    "decided_by",
                    "decision_basis",
                ],
            )?;
            validate_token(
                required_string(object, "approval_id")?,
                "approval_id",
                MAX_ID_BYTES,
            )?;
            validate_enum(
                object,
                "outcome",
                &["approved", "denied", "expired", "revoked"],
            )?;
            validate_token(
                required_string(object, "decided_by")?,
                "decided_by",
                MAX_ID_BYTES,
            )?;
            validate_optional_object_text(object, "decision_basis", 16_384)
        }
        "work_status" => {
            ensure_allowed_fields(
                object,
                &[
                    "kind",
                    "work_id",
                    "state",
                    "summary",
                    "progress_bps",
                    "evidence",
                ],
            )?;
            validate_token(
                required_string(object, "work_id")?,
                "work_id",
                MAX_ID_BYTES,
            )?;
            validate_enum(
                object,
                "state",
                &[
                    "planned",
                    "claimed",
                    "running",
                    "blocked",
                    "awaiting_review",
                    "completed",
                    "failed",
                    "cancelled",
                ],
            )?;
            validate_text(
                required_string(object, "summary")?,
                "work summary",
                16_384,
            )?;
            if let Some(progress) = object.get("progress_bps") {
                if progress.as_u64().is_none_or(|value| value > 10_000) {
                    return Err(LiveError::bad_request(
                        "progress_bps must be an integer between 0 and 10000",
                    ));
                }
            }
            validate_evidence(object.get("evidence"))
        }
        "handoff" => {
            ensure_allowed_fields(
                object,
                &["kind", "work_id", "to", "summary", "context_refs"],
            )?;
            validate_token(
                required_string(object, "work_id")?,
                "work_id",
                MAX_ID_BYTES,
            )?;
            validate_token(
                required_string(object, "to")?,
                "handoff recipient",
                MAX_ID_BYTES,
            )?;
            validate_text(
                required_string(object, "summary")?,
                "handoff summary",
                16_384,
            )?;
            validate_token_array(object.get("context_refs"), "context_refs", 128, false)
        }
        "tracker_update" => {
            ensure_allowed_fields(object, &["kind", "link", "summary"])?;
            validate_tracker_link(object.get("link"))?;
            validate_text(
                required_string(object, "summary")?,
                "tracker summary",
                16_384,
            )
        }
        "error" => {
            ensure_allowed_fields(object, &["kind", "code", "message", "retryable"])?;
            validate_namespaced_identifier(required_string(object, "code")?, "error code")?;
            validate_text(
                required_string(object, "message")?,
                "error message",
                16_384,
            )?;
            validate_optional_bool(object, "retryable")
        }
        _ => Err(LiveError::bad_request(format!(
            "unknown live payload kind '{kind}'"
        ))),
    }
}

fn validate_tracker_link(value: Option<&Value>) -> LiveResult<()> {
    let object = value
        .and_then(Value::as_object)
        .ok_or_else(|| LiveError::bad_request("tracker link must be an object"))?;
    ensure_allowed_fields(object, &["kind", "reference", "url", "relation"])?;
    validate_namespaced_identifier(required_string(object, "kind")?, "tracker kind")?;
    validate_text(
        required_string(object, "reference")?,
        "tracker reference",
        MAX_ID_BYTES,
    )?;
    validate_https_url(required_string(object, "url")?, "tracker url")?;
    validate_optional_object_token(object, "relation", 128)
}

fn validate_evidence(value: Option<&Value>) -> LiveResult<()> {
    let Some(value) = value else {
        return Ok(());
    };
    let entries = value
        .as_array()
        .ok_or_else(|| LiveError::bad_request("evidence must be an array"))?;
    if entries.len() > MAX_EVIDENCE_REFS {
        return Err(LiveError::bad_request("too many evidence references"));
    }
    for entry in entries {
        let object = entry
            .as_object()
            .ok_or_else(|| LiveError::bad_request("evidence entry must be an object"))?;
        ensure_allowed_fields(object, &["kind", "uri", "digest", "summary"])?;
        validate_namespaced_identifier(required_string(object, "kind")?, "evidence kind")?;
        validate_text(
            required_string(object, "uri")?,
            "evidence uri",
            2_048,
        )?;
        validate_optional_object_token(object, "digest", MAX_ID_BYTES)?;
        validate_optional_object_text(object, "summary", 4_096)?;
    }
    Ok(())
}

fn validate_extensions(extensions: &BTreeMap<String, Value>) -> LiveResult<()> {
    if extensions.len() > MAX_EXTENSIONS {
        return Err(LiveError::bad_request("too many live event extensions"));
    }
    for (name, value) in extensions {
        validate_namespaced_identifier(name, "extension")?;
        reject_private_trace_fields(value)?;
        let bytes = serde_json::to_vec(value)
            .map_err(|_| LiveError::bad_request("extension is not serializable"))?;
        if bytes.len() > MAX_EXTENSION_BYTES {
            return Err(LiveError::new(
                StatusCode::PAYLOAD_TOO_LARGE,
                "payload_too_large",
                format!("extension '{name}' exceeds {MAX_EXTENSION_BYTES} bytes"),
            ));
        }
    }
    Ok(())
}

fn reject_private_trace_fields(value: &Value) -> LiveResult<()> {
    match value {
        Value::Object(object) => {
            for (key, child) in object {
                let normalized = key.to_ascii_lowercase().replace('-', "_");
                if matches!(
                    normalized.as_str(),
                    "chain_of_thought"
                        | "hidden_reasoning"
                        | "reasoning_tokens"
                        | "raw_prompt"
                        | "private_trace"
                ) {
                    return Err(LiveError::bad_request(format!(
                        "private model trace field '{key}' is not part of the live protocol"
                    )));
                }
                reject_private_trace_fields(child)?;
            }
        }
        Value::Array(values) => {
            for child in values {
                reject_private_trace_fields(child)?;
            }
        }
        _ => {}
    }
    Ok(())
}

fn required_string<'a>(object: &'a Map<String, Value>, field: &str) -> LiveResult<&'a str> {
    object
        .get(field)
        .and_then(Value::as_str)
        .ok_or_else(|| LiveError::bad_request(format!("'{field}' must be a string")))
}

fn ensure_allowed_fields(object: &Map<String, Value>, allowed: &[&str]) -> LiveResult<()> {
    for key in object.keys() {
        if !allowed.contains(&key.as_str()) {
            return Err(LiveError::bad_request(format!(
                "unknown field '{key}' in live payload"
            )));
        }
    }
    Ok(())
}

fn validate_enum<'a>(
    object: &'a Map<String, Value>,
    field: &str,
    allowed: &[&str],
) -> LiveResult<&'a str> {
    let value = required_string(object, field)?;
    if !allowed.contains(&value) {
        return Err(LiveError::bad_request(format!(
            "'{field}' has unsupported value '{value}'"
        )));
    }
    Ok(value)
}

fn validate_optional_bool(object: &Map<String, Value>, field: &str) -> LiveResult<()> {
    if object.get(field).is_some_and(|value| !value.is_boolean()) {
        return Err(LiveError::bad_request(format!(
            "'{field}' must be a boolean"
        )));
    }
    Ok(())
}

fn validate_optional_object_token(
    object: &Map<String, Value>,
    field: &str,
    max_bytes: usize,
) -> LiveResult<()> {
    if let Some(value) = object.get(field) {
        let value = value
            .as_str()
            .ok_or_else(|| LiveError::bad_request(format!("'{field}' must be a string")))?;
        validate_token(value, field, max_bytes)?;
    }
    Ok(())
}

fn validate_optional_object_text(
    object: &Map<String, Value>,
    field: &str,
    max_bytes: usize,
) -> LiveResult<()> {
    if let Some(value) = object.get(field) {
        let value = value
            .as_str()
            .ok_or_else(|| LiveError::bad_request(format!("'{field}' must be a string")))?;
        validate_text(value, field, max_bytes)?;
    }
    Ok(())
}

fn validate_recipients(recipients: &[String]) -> LiveResult<()> {
    if recipients.len() > MAX_RECIPIENTS {
        return Err(LiveError::bad_request("too many live event recipients"));
    }
    let mut seen = BTreeSet::new();
    for recipient in recipients {
        validate_token(recipient, "recipient", MAX_ID_BYTES)?;
        if !seen.insert(recipient.as_str()) {
            return Err(LiveError::bad_request("duplicate live event recipient"));
        }
    }
    Ok(())
}

fn validate_capabilities(value: Option<&Value>, required: bool) -> LiveResult<()> {
    let Some(value) = value else {
        if required {
            return Err(LiveError::bad_request(
                "requested_capabilities is required",
            ));
        }
        return Ok(());
    };
    let values = value
        .as_array()
        .ok_or_else(|| LiveError::bad_request("capabilities must be an array"))?;
    if required && values.is_empty() {
        return Err(LiveError::bad_request(
            "at least one requested capability is required",
        ));
    }
    if values.len() > MAX_CAPABILITIES {
        return Err(LiveError::bad_request("too many capabilities"));
    }
    let mut previous: Option<&str> = None;
    for value in values {
        let capability = value
            .as_str()
            .ok_or_else(|| LiveError::bad_request("capability must be a string"))?;
        validate_namespaced_identifier(capability, "capability")?;
        if previous.is_some_and(|value| value >= capability) {
            return Err(LiveError::bad_request(
                "capabilities must be sorted and unique",
            ));
        }
        previous = Some(capability);
    }
    Ok(())
}

fn validate_token_array(
    value: Option<&Value>,
    field: &str,
    max_items: usize,
    required: bool,
) -> LiveResult<()> {
    let Some(value) = value else {
        if required {
            return Err(LiveError::bad_request(format!("'{field}' is required")));
        }
        return Ok(());
    };
    let values = value
        .as_array()
        .ok_or_else(|| LiveError::bad_request(format!("'{field}' must be an array")))?;
    if required && values.is_empty() {
        return Err(LiveError::bad_request(format!(
            "'{field}' must not be empty"
        )));
    }
    if values.len() > max_items {
        return Err(LiveError::bad_request(format!(
            "'{field}' contains too many entries"
        )));
    }
    let mut seen = BTreeSet::new();
    for value in values {
        let token = value.as_str().ok_or_else(|| {
            LiveError::bad_request(format!("'{field}' entries must be strings"))
        })?;
        validate_token(token, field, MAX_ID_BYTES)?;
        if !seen.insert(token) {
            return Err(LiveError::bad_request(format!(
                "'{field}' contains duplicate entries"
            )));
        }
    }
    Ok(())
}

fn validate_optional_token(
    value: &Option<String>,
    field: &str,
    max_bytes: usize,
) -> LiveResult<()> {
    if let Some(value) = value {
        validate_token(value, field, max_bytes)?;
    }
    Ok(())
}

fn validate_token(value: &str, field: &str, max_bytes: usize) -> LiveResult<()> {
    if value.is_empty() || value.len() > max_bytes {
        return Err(LiveError::bad_request(format!(
            "{field} must contain 1 to {max_bytes} bytes"
        )));
    }
    if !value.bytes().all(is_token_byte) {
        return Err(LiveError::bad_request(format!(
            "{field} contains unsupported characters"
        )));
    }
    Ok(())
}

fn validate_namespaced_identifier(value: &str, field: &str) -> LiveResult<()> {
    validate_token(value, field, MAX_ID_BYTES)?;
    if !value.contains('.') {
        return Err(LiveError::bad_request(format!(
            "{field} must use a namespace"
        )));
    }
    Ok(())
}

fn is_token_byte(byte: u8) -> bool {
    byte.is_ascii_alphanumeric() || b"-_.:/@+".contains(&byte)
}

fn validate_text(value: &str, field: &str, max_bytes: usize) -> LiveResult<()> {
    if value.trim().is_empty() || value.len() > max_bytes {
        return Err(LiveError::bad_request(format!(
            "{field} must contain 1 to {max_bytes} bytes"
        )));
    }
    Ok(())
}

fn validate_timestamp(value: &str, field: &str) -> LiveResult<()> {
    validate_text(value, field, 64)?;
    if !value.contains('T') || !value.ends_with('Z') {
        return Err(LiveError::bad_request(format!(
            "{field} must be an RFC 3339 UTC timestamp"
        )));
    }
    Ok(())
}

fn validate_idempotency_key(value: &str) -> LiveResult<()> {
    if value.len() < MIN_IDEMPOTENCY_BYTES || value.len() > MAX_IDEMPOTENCY_BYTES {
        return Err(LiveError::bad_request(format!(
            "idempotency_key must contain {MIN_IDEMPOTENCY_BYTES} to {MAX_IDEMPOTENCY_BYTES} bytes"
        )));
    }
    if !value.bytes().all(is_token_byte) {
        return Err(LiveError::bad_request(
            "idempotency_key contains unsupported characters",
        ));
    }
    Ok(())
}

fn validate_sequence(value: u64, allow_zero: bool) -> LiveResult<()> {
    if (!allow_zero && value == 0) || value > MAX_SAFE_SEQUENCE {
        return Err(LiveError::bad_request(
            "sequence must be a JSON-safe integer in the permitted range",
        ));
    }
    Ok(())
}

fn validate_https_url(value: &str, field: &str) -> LiveResult<()> {
    validate_text(value, field, 2_048)?;
    if !value.starts_with("https://") || value.contains('@') {
        return Err(LiveError::bad_request(format!(
            "{field} must be an HTTPS URL without user information"
        )));
    }
    Ok(())
}
