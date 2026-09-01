//! Replay-safe live-session compatibility routes layered on the existing channel bus.
//!
//! This module does not create another queue, message store, provider executor, or
//! finalizer. Every accepted live event is an ordinary bridge message, so channel
//! sequence numbers, retained history, persistence, and SSE fan-out remain the one
//! ordering and replay authority.

use std::collections::{BTreeMap, BTreeSet};
use std::convert::Infallible;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, OnceLock};

use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    response::sse::{Event as SseEvent, KeepAlive, Sse},
    response::{IntoResponse, Response},
    routing::get,
    Json, Router,
};
use futures::{stream, StreamExt};
use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};
use sha2::{Digest, Sha256};
use tokio_stream::wrappers::BroadcastStream;

use crate::error::BridgeError;
use crate::state::AppState;
use crate::types::{Agent, AgentKind, Event, Member, MemberRole, Message, Role};

const LIVE_PROTOCOL_ID: &str = "agent-pontifex.live";
const LIVE_SCHEMA_VERSION: u16 = 1;
const LIVE_META_KEY: &str = "agent_pontifex_live";
const MAX_SAFE_SEQUENCE: u64 = 9_007_199_254_740_991;
const MAX_ID_BYTES: usize = 256;
const MAX_TEXT_BYTES: usize = 1_048_576;
const MAX_JSON_BYTES: usize = 1_048_576;
const MAX_RECIPIENTS: usize = 64;
const MAX_CAPABILITIES: usize = 256;
const MAX_EVIDENCE_REFS: usize = 128;
const MAX_EXTENSIONS: usize = 64;
const MAX_EXTENSION_BYTES: usize = 64 * 1024;
const MIN_IDEMPOTENCY_BYTES: usize = 16;
const MAX_IDEMPOTENCY_BYTES: usize = 128;

static LIVE_PUBLISH_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

pub fn router() -> Router<Arc<AppState>> {
    Router::new()
        .route("/live-sessions/{slug}", get(get_live_session))
        .route(
            "/live-sessions/{slug}/events",
            get(list_live_events).post(post_live_event),
        )
        .route(
            "/live-sessions/{slug}/stream",
            get(stream_live_session),
        )
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct PublishEvent {
    client_event_id: String,
    session_id: String,
    channel: String,
    sender: String,
    #[serde(default)]
    recipients: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    correlation_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    causation_id: Option<String>,
    idempotency_key: String,
    payload: Value,
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    extensions: BTreeMap<String, Value>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredLiveMeta {
    schema_version: u16,
    protocol: String,
    client_event_id: String,
    session_id: String,
    recipients: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    correlation_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    causation_id: Option<String>,
    idempotency_key: String,
    request_digest: String,
    payload: Value,
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    extensions: BTreeMap<String, Value>,
}

#[derive(Debug)]
struct PublishOutcome {
    message: Message,
    client_event_id: String,
    replayed: bool,
}

#[derive(Debug)]
struct LiveError {
    status: StatusCode,
    code: &'static str,
    message: String,
}

impl LiveError {
    fn bad_request(message: impl Into<String>) -> Self {
        Self::new(StatusCode::BAD_REQUEST, "live_bad_request", message)
    }

    fn conflict(code: &'static str, message: impl Into<String>) -> Self {
        Self::new(StatusCode::CONFLICT, code, message)
    }

    fn gone(code: &'static str, message: impl Into<String>) -> Self {
        Self::new(StatusCode::GONE, code, message)
    }

    fn new(status: StatusCode, code: &'static str, message: impl Into<String>) -> Self {
        Self {
            status,
            code,
            message: message.into(),
        }
    }
}

impl From<BridgeError> for LiveError {
    fn from(error: BridgeError) -> Self {
        let status =
            StatusCode::from_u16(error.http_status()).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR);
        Self::new(status, error.code(), error.to_string())
    }
}

impl IntoResponse for LiveError {
    fn into_response(self) -> Response {
        (
            self.status,
            Json(json!({
                "ok": false,
                "error": self.code,
                "message": self.message,
            })),
        )
            .into_response()
    }
}

type LiveResult<T> = Result<T, LiveError>;

#[derive(Deserialize, Default)]
struct EventsQuery {
    #[serde(default)]
    since: Option<u64>,
}

#[derive(Deserialize, Default)]
struct LiveStreamQuery {
    #[serde(default)]
    agent_key: Option<String>,
    #[serde(default)]
    after_seq: Option<u64>,
}

include!("live_sessions/api.rs");
include!("live_sessions/views.rs");
include!("live_sessions/validation.rs");

#[cfg(test)]
include!("live_sessions/tests.rs");
