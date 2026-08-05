-- Public desired-state PostgreSQL contract for the Agent Pontifex bridge.
-- Services never apply this file at boot. DPM renders reviewable bootstrap or
-- migration SQL from this source, and a human approves production changes.

create schema if not exists ai_agent_bridge;

create table if not exists ai_agent_bridge.agents (
  id uuid primary key default gen_random_uuid(),
  agent_key varchar(120) not null,
  display_name varchar(200) default '' not null,
  kind varchar(32) default 'other' not null,
  host varchar(255),
  meta_data jsonb default '{}'::jsonb not null,
  created_at timestamptz default now() not null,
  updated_at timestamptz default now() not null,
  constraint ai_agent_bridge_agents_key_size_chk
    check (octet_length(agent_key) between 1 and 120),
  constraint ai_agent_bridge_agents_display_name_size_chk
    check (octet_length(display_name) <= 200),
  constraint ai_agent_bridge_agents_meta_object_chk
    check (jsonb_typeof(meta_data) = 'object')
);

create unique index if not exists ai_agent_bridge_agents_key_uq
  on ai_agent_bridge.agents (agent_key);

create table if not exists ai_agent_bridge.channels (
  id uuid primary key default gen_random_uuid(),
  slug varchar(160) not null,
  topic text not null,
  embedding_model varchar(160) default '' not null,
  embedding jsonb default '[]'::jsonb not null,
  embedding_dimensions integer default 0 not null,
  created_by varchar(120) default '' not null,
  status varchar(32) default 'active' not null,
  meta_data jsonb default '{}'::jsonb not null,
  created_at timestamptz default now() not null,
  updated_at timestamptz default now() not null,
  constraint ai_agent_bridge_channels_slug_format_chk
    check (slug ~ '^[A-Za-z0-9._:/-]{1,160}$'),
  constraint ai_agent_bridge_channels_topic_size_chk
    check (octet_length(topic) between 1 and 32768),
  constraint ai_agent_bridge_channels_embedding_array_chk
    check (jsonb_typeof(embedding) = 'array'),
  constraint ai_agent_bridge_channels_embedding_dimensions_chk
    check (embedding_dimensions between 0 and 65536),
  constraint ai_agent_bridge_channels_status_chk
    check (status in ('active', 'paused', 'archived')),
  constraint ai_agent_bridge_channels_meta_object_chk
    check (jsonb_typeof(meta_data) = 'object')
);

create unique index if not exists ai_agent_bridge_channels_slug_uq
  on ai_agent_bridge.channels (slug);

create index if not exists ai_agent_bridge_channels_status_created_at_idx
  on ai_agent_bridge.channels (status, created_at);

create table if not exists ai_agent_bridge.channel_members (
  id uuid primary key default gen_random_uuid(),
  channel_slug varchar(160) not null,
  channel_id uuid references ai_agent_bridge.channels(id) on delete cascade,
  agent_key varchar(120) not null,
  role varchar(32) default 'member' not null,
  joined_at timestamptz default now() not null,
  last_seen_at timestamptz default now() not null,
  constraint ai_agent_bridge_channel_members_agent_key_size_chk
    check (octet_length(agent_key) between 1 and 120)
);

create unique index if not exists ai_agent_bridge_channel_members_identity_uq
  on ai_agent_bridge.channel_members (channel_slug, agent_key);

create index if not exists ai_agent_bridge_channel_members_channel_id_idx
  on ai_agent_bridge.channel_members (channel_id)
  where channel_id is not null;

create table if not exists ai_agent_bridge.messages (
  id uuid primary key,
  channel_slug varchar(160) not null,
  channel_id uuid references ai_agent_bridge.channels(id) on delete cascade,
  seq bigint not null,
  from_agent_key varchar(120) not null,
  role varchar(32) not null,
  content text not null,
  meta_data jsonb default '{}'::jsonb not null,
  created_at timestamptz default now() not null,
  constraint ai_agent_bridge_messages_seq_chk
    check (seq >= 0),
  constraint ai_agent_bridge_messages_sender_size_chk
    check (octet_length(from_agent_key) between 1 and 120),
  constraint ai_agent_bridge_messages_content_size_chk
    check (octet_length(content) between 1 and 1048576),
  constraint ai_agent_bridge_messages_meta_object_chk
    check (jsonb_typeof(meta_data) = 'object')
);

create unique index if not exists ai_agent_bridge_messages_channel_seq_uq
  on ai_agent_bridge.messages (channel_slug, seq);

create index if not exists ai_agent_bridge_messages_channel_created_at_idx
  on ai_agent_bridge.messages (channel_slug, created_at);

create index if not exists ai_agent_bridge_messages_channel_id_idx
  on ai_agent_bridge.messages (channel_id)
  where channel_id is not null;

create table if not exists ai_agent_bridge.shared_context (
  id uuid primary key default gen_random_uuid(),
  channel_slug varchar(160) not null,
  channel_id uuid references ai_agent_bridge.channels(id) on delete cascade,
  ctx_key varchar(200) not null,
  value jsonb not null,
  version integer default 0 not null,
  updated_by varchar(120) not null,
  updated_at timestamptz default now() not null,
  constraint ai_agent_bridge_shared_context_key_size_chk
    check (octet_length(ctx_key) between 1 and 200),
  constraint ai_agent_bridge_shared_context_version_chk
    check (version >= 0),
  constraint ai_agent_bridge_shared_context_updated_by_size_chk
    check (octet_length(updated_by) between 1 and 120)
);

create unique index if not exists ai_agent_bridge_shared_context_identity_uq
  on ai_agent_bridge.shared_context (channel_slug, ctx_key);

create index if not exists ai_agent_bridge_shared_context_channel_id_idx
  on ai_agent_bridge.shared_context (channel_id)
  where channel_id is not null;
