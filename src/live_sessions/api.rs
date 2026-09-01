async fn get_live_session(
    State(state): State<Arc<AppState>>,
    Path(slug): Path<String>,
) -> LiveResult<Json<Value>> {
    let session = session_view(&state, &slug)?;
    Ok(Json(json!({ "ok": true, "session": session })))
}

async fn list_live_events(
    State(state): State<Arc<AppState>>,
    Path(slug): Path<String>,
    Query(query): Query<EventsQuery>,
) -> LiveResult<Json<Value>> {
    let since = query.since.unwrap_or(0);
    validate_sequence(since, true)?;
    let channel = state.get_channel(&slug)?;
    validate_sequence(channel.message_count, true)?;
    if since > channel.message_count {
        return Err(LiveError::conflict(
            "resume_cursor_ahead",
            format!(
                "resume cursor {since} is ahead of live-session high-water sequence {}",
                channel.message_count
            ),
        ));
    }
    let retained = state.history(&slug, None)?;
    validate_replay_window(&retained, since, channel.message_count)?;
    let events: Vec<Value> = retained
        .iter()
        .filter(|message| message.seq > since)
        .map(envelope_from_message)
        .collect();
    Ok(Json(json!({
        "ok": true,
        "session_id": slug,
        "after_seq": since,
        "high_water_seq": channel.message_count,
        "retained_from_seq": retained.first().map(|message| message.seq),
        "events": events,
    })))
}

async fn post_live_event(
    State(state): State<Arc<AppState>>,
    Path(slug): Path<String>,
    Json(event): Json<PublishEvent>,
) -> LiveResult<Response> {
    let outcome = publish_event(&state, &slug, event)?;
    let status = if outcome.replayed {
        StatusCode::OK
    } else {
        StatusCode::CREATED
    };
    let envelope = envelope_from_message(&outcome.message);
    Ok((
        status,
        Json(json!({
            "ok": true,
            "accepted": {
                "type": "accepted",
                "client_event_id": outcome.client_event_id,
                "event_id": outcome.message.id,
                "seq": outcome.message.seq,
                "replayed": outcome.replayed,
            },
            "event": envelope,
        })),
    )
        .into_response())
}

async fn stream_live_session(
    State(state): State<Arc<AppState>>,
    Path(slug): Path<String>,
    Query(query): Query<LiveStreamQuery>,
) -> LiveResult<Response> {
    let after_seq = query.after_seq.unwrap_or(0);
    validate_sequence(after_seq, true)?;
    let permit = state
        .sse_connections
        .clone()
        .try_acquire_owned()
        .map_err(|_| {
            LiveError::new(
                StatusCode::TOO_MANY_REQUESTS,
                "capacity_exceeded",
                format!(
                    "capacity for live-session SSE connections reached ({})",
                    state.config.max_sse_connections
                ),
            )
        })?;

    let agent_key = query
        .agent_key
        .as_deref()
        .map(str::trim)
        .filter(|value| !value.is_empty());
    let (receiver, high_water) = state.subscribe(&slug, agent_key)?;
    validate_sequence(high_water, true)?;
    if after_seq > high_water {
        return Err(LiveError::conflict(
            "resume_cursor_ahead",
            format!(
                "resume cursor {after_seq} is ahead of live-session high-water sequence {high_water}"
            ),
        ));
    }

    let mut session = session_view(&state, &slug)?;
    session["high_water_seq"] = json!(high_water);
    let retained_snapshot: Vec<Message> = state
        .history(&slug, None)?
        .into_iter()
        .filter(|message| message.seq <= high_water)
        .collect();
    validate_replay_window(&retained_snapshot, after_seq, high_water)?;
    let replay_messages: Vec<Message> = retained_snapshot
        .into_iter()
        .filter(|message| message.seq > after_seq)
        .collect();
    let replay_from_seq = replay_messages
        .first()
        .map(|message| message.seq)
        .unwrap_or(after_seq);
    let delivered_seq = Arc::new(AtomicU64::new(
        replay_messages
            .last()
            .map(|message| message.seq)
            .unwrap_or(after_seq),
    ));

    let mut replay_frames = Vec::with_capacity(replay_messages.len().saturating_add(1));
    replay_frames.push(sse_frame(
        json!({
            "type": "welcome",
            "session": session,
            "replay_from_seq": replay_from_seq,
        }),
        None,
    ));
    replay_frames.extend(replay_messages.iter().map(|message| {
        sse_frame(
            json!({
                "type": "event",
                "event": envelope_from_message(message),
            }),
            Some(message.seq),
        )
    }));

    let replay = stream::iter(
        replay_frames
            .into_iter()
            .map(Ok::<SseEvent, Infallible>),
    );
    let live_state = state.clone();
    let live_slug = slug.clone();
    let live_delivered_seq = delivered_seq.clone();
    let live = BroadcastStream::new(receiver).filter_map(move |item| {
        let state = live_state.clone();
        let slug = live_slug.clone();
        let delivered_seq = live_delivered_seq.clone();
        async move {
            match item {
                Ok(Event::Message(message)) => {
                    delivered_seq.store(message.seq, Ordering::Relaxed);
                    Some(Ok(sse_frame(
                        json!({
                            "type": "event",
                            "event": envelope_from_message(&message),
                        }),
                        Some(message.seq),
                    )))
                }
                Ok(Event::Presence { .. }) => None,
                Err(tokio_stream::wrappers::errors::BroadcastStreamRecvError::Lagged(_)) => {
                    let expected_after_seq = delivered_seq.load(Ordering::Relaxed);
                    let high_water_seq = state
                        .get_channel(&slug)
                        .map(|channel| channel.message_count)
                        .unwrap_or(expected_after_seq)
                        .min(MAX_SAFE_SEQUENCE);
                    Some(Ok(sse_frame(
                        json!({
                            "type": "lagged",
                            "session_id": slug,
                            "expected_after_seq": expected_after_seq,
                            "high_water_seq": high_water_seq,
                            "recovery_uri": format!(
                                "/live-sessions/{}/events?since={expected_after_seq}",
                                slug
                            ),
                        }),
                        None,
                    )))
                }
            }
        }
    });
    let stream = replay.chain(live).map(move |item| {
        let _permit = &permit;
        item
    });

    Ok(Sse::new(stream)
        .keep_alive(KeepAlive::default())
        .into_response())
}

fn validate_replay_window(
    retained: &[Message],
    after_seq: u64,
    high_water_seq: u64,
) -> LiveResult<()> {
    if after_seq >= high_water_seq {
        return Ok(());
    }
    let first_retained = retained.first().map(|message| message.seq);
    if first_retained.is_none_or(|first| after_seq.saturating_add(1) < first) {
        return Err(LiveError::gone(
            "replay_window_exhausted",
            format!(
                "events after sequence {after_seq} are no longer present in retained bridge history"
            ),
        ));
    }
    Ok(())
}

fn publish_event(
    state: &AppState,
    slug: &str,
    event: PublishEvent,
) -> LiveResult<PublishOutcome> {
    validate_publish_event(slug, &event)?;
    let request_digest = event_digest(&event)?;
    let client_event_id = event.client_event_id.clone();

    let lock = LIVE_PUBLISH_LOCK.get_or_init(|| Mutex::new(()));
    let _guard = lock.lock();
    for message in state.history(slug, None)? {
        let Some(stored) = stored_live_meta(&message) else {
            continue;
        };
        if stored.session_id.as_str() != event.session_id.as_str()
            || message.from.as_str() != event.sender.as_str()
            || stored.idempotency_key.as_str() != event.idempotency_key.as_str()
        {
            continue;
        }
        if stored.request_digest == request_digest {
            return Ok(PublishOutcome {
                message,
                client_event_id,
                replayed: true,
            });
        }
        return Err(LiveError::conflict(
            "idempotency_conflict",
            "idempotency key was already accepted with a different live event",
        ));
    }

    let stored = StoredLiveMeta {
        schema_version: LIVE_SCHEMA_VERSION,
        protocol: LIVE_PROTOCOL_ID.to_string(),
        client_event_id: event.client_event_id,
        session_id: event.session_id,
        recipients: event.recipients,
        correlation_id: event.correlation_id,
        causation_id: event.causation_id,
        idempotency_key: event.idempotency_key,
        request_digest,
        payload: event.payload,
        extensions: event.extensions,
    };
    let content_limit = state.config.max_content_bytes.min(16_384).max(1);
    let content = payload_summary(&stored.payload, content_limit);
    let role = role_for_payload(&stored.payload);
    let stored_value = serde_json::to_value(stored)
        .map_err(|_| LiveError::bad_request("live event metadata could not be serialized"))?;
    let mut meta = Map::new();
    meta.insert(LIVE_META_KEY.to_string(), stored_value);
    let message = state.post_message(
        slug,
        &event.sender,
        role,
        &content,
        Value::Object(meta),
    )?;
    Ok(PublishOutcome {
        message,
        client_event_id,
        replayed: false,
    })
}
