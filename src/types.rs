use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum AgentKind {
    ChatGpt,
    Claude,
    Codex,
    Gemini,
    Grok,
    Kimi,
    Qwen,
    Human,
    #[default]
    Other,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Agent {
    pub agent_key: String,
    pub display_name: String,
    pub kind: AgentKind,
    pub host: Option<String>,
    pub meta: Value,
    pub registered_at: String,
}

#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum MemberRole {
    Owner,
    #[default]
    Member,
    Observer,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Member {
    pub agent_key: String,
    pub role: MemberRole,
    pub joined_at: String,
    pub last_seen_at: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Channel {
    pub slug: String,
    pub topic: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub topic_summary: Option<String>,
    pub created_by: String,
    pub created_at: String,
    pub member_count: usize,
    pub message_count: u64,
    pub embedding_model: String,
    #[serde(default)]
    pub meta: Value,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ScoredChannel {
    #[serde(flatten)]
    pub channel: Channel,
    pub score: f32,
}

#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum Role {
    #[default]
    User,
    Assistant,
    System,
    Tool,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Message {
    pub id: String,
    pub channel: String,
    pub seq: u64,
    pub from: String,
    pub role: Role,
    pub content: String,
    pub meta: Value,
    pub created_at: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ContextEntry {
    pub key: String,
    pub value: Value,
    pub version: u32,
    pub updated_by: String,
    pub updated_at: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct FileLease {
    pub id: String,
    pub repository: String,
    pub path: String,
    pub recursive: bool,
    pub agent_key: String,
    pub purpose: String,
    pub meta: Value,
    pub fencing_token: u64,
    pub acquired_at: String,
    pub expires_at: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct FileLeaseHolder {
    pub lease: FileLease,
    pub agent: Agent,
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PresenceKind {
    Joined,
    Left,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum Event {
    Message(Message),
    Presence {
        channel: String,
        agent_key: String,
        event: PresenceKind,
        member_count: usize,
        at: String,
    },
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct WorkflowParticipant {
    pub agent_key: String,
    pub role: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct WorkflowArtifact {
    pub artifact_id: String,
    pub name: String,
    pub repository: String,
    pub path: String,
    pub owner_agent_key: String,
    pub summary: String,
    pub expected_content_types: Vec<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct WorkflowArtifactSubmission {
    pub artifact_id: String,
    pub name: String,
    pub repository: String,
    pub path: String,
    pub owner_agent_key: String,
    pub summary: String,
    pub content_type: String,
    pub contents: String,
    pub sha256: String,
    pub byte_len: u64,
    pub submitted_at: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct WorkflowPlan {
    pub workflow_id: String,
    pub channel: String,
    pub objective: String,
    pub created_by: String,
    pub coordinator_agent_key: Option<String>,
    pub dependency_order: Vec<String>,
    pub participants: Vec<WorkflowParticipant>,
    pub artifacts: Vec<WorkflowArtifact>,
    pub created_at: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct WorkflowStatus {
    pub workflow_id: String,
    pub channel: String,
    pub artifact_total: usize,
    pub artifact_submitted: usize,
    pub pending_artifact_ids: Vec<String>,
    pub complete: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct WorkflowArtifactResponse {
    pub workflow_id: String,
    pub artifact: WorkflowArtifactSubmission,
    pub replaced: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct WorkflowArtifactContentResponse {
    pub workflow_id: String,
    pub artifact: WorkflowArtifact,
    pub submission: WorkflowArtifactSubmission,
}
