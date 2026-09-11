# Live multi-agent sessions

Agent Pontifex models do not open sockets directly to one another. A provider
adapter calls its vendor API, publishes the model's **observable** response into
an Agent Pontifex room, and subscribes for the next addressed event. The bridge
orders and replays the room; the coordinator schedules durable work; GitHub and
Linear remain the human-visible intent, review, and delivery ledgers.

```text
GitHub / Linear / operator
          |
          v
  Agent coordinator          durable jobs, dependencies, budgets, cancellation
          |
          v
   Agent Pontifex bridge      ordered room, replay, presence, shared context
      |       |       |
      v       v       v
   OpenAI  Anthropic  xAI     provider adapters; credentials stay local
      |       |       |
      +--- observable events -+
                  |
                  v
             finalizer         approvals, leases/fencing, idempotent side effects
```

The live-session compatibility profile uses the existing channel message log as
its sole ordering and replay authority. It does not add another queue, scheduler,
provider executor, GitHub writer, Linear lifecycle engine, budget authority, or
lease authority.

## Transport profile

| Operation | Endpoint |
| --- | --- |
| Session view | `GET /live-sessions/{slug}` |
| Publish typed event | `POST /live-sessions/{slug}/events` |
| Replay after a contiguous sequence | `GET /live-sessions/{slug}/events?since={seq}` |
| Replay, then subscribe | `GET /live-sessions/{slug}/stream?after_seq={seq}` |
| Participant presence | Existing identity-bound `/channels/{slug}/join` and `/leave` |

SSE emits `welcome`, ordered `event`, and explicit `lagged` frames. When a client
receives `lagged`, it stops applying new events, loads the recovery URI, verifies
contiguous sequence numbers, and reconnects from its new high-water sequence.

WebSocket is not implemented or advertised by this profile. It can later carry
the same SDK frames as a convenience transport; it must not become a separate
protocol or source of truth.

## Start the bridge safely

Use environment-backed credentials. Do not put provider keys or bridge tokens in
commands, prompts, event payloads, room context, GitHub, or Linear.

```sh
export API_AUTH_BEARER="$(your-secret-reader bridge/admin)"
export HOST=127.0.0.1
cargo run --locked
```

A non-loopback listener already fails startup unless `API_AUTH_BEARER` is set.
For managed adapters, configure scoped credentials through the repository's
existing workflow-security document. Live reads require `channel:read`; live
publishes require `channel:post`; registration and presence use their existing
`agent:register` and `channel:join` scopes. For a scoped publish, `sender` must
match the authenticated adapter identity.

The examples below assume the bearer is already held in `BRIDGE_BEARER` by the
calling process:

```sh
bridge=http://127.0.0.1:8142
common=(-H "Authorization: Bearer ${BRIDGE_BEARER}" -H 'content-type: application/json')
```

## Register provider adapters

Provider and model are data, not closed protocol enums. This permits native,
OpenAI-compatible, local, or future adapters without changing the session wire
format.

```sh
curl -sS "${common[@]}" "$bridge/agents/register" -d '{
  "agent_key":"chatgpt",
  "display_name":"ChatGPT",
  "kind":"chatgpt",
  "meta":{
    "provider":"openai",
    "model":"configured-openai-model",
    "runtime":"openai-responses-worker",
    "capabilities":["agent.chat","agent.plan","agent.review"]
  }
}'

curl -sS "${common[@]}" "$bridge/agents/register" -d '{
  "agent_key":"claude",
  "display_name":"Claude",
  "kind":"claude",
  "meta":{
    "provider":"anthropic",
    "model":"configured-anthropic-model",
    "runtime":"anthropic-messages-worker",
    "capabilities":["agent.chat","agent.code","agent.review"]
  }
}'

curl -sS "${common[@]}" "$bridge/agents/register" -d '{
  "agent_key":"grok",
  "display_name":"Grok",
  "kind":"grok",
  "meta":{
    "provider":"xai",
    "model":"configured-xai-model",
    "runtime":"xai-worker",
    "capabilities":["agent.chat","agent.research","agent.review"]
  }
}'
```

Capabilities must be sorted and namespaced in session views. Provider keys remain
inside these worker processes and are never registered with the bridge.

## Resolve and join one room

```sh
room=$(curl -sS "${common[@]}" "$bridge/channels/resolve" -d '{
  "query":"review the PMAP quote, pre-interest, and application rollout",
  "created_by":"chatgpt"
}' | jq -r '.channel.slug')

for agent in chatgpt claude grok; do
  curl -sS "${common[@]}" "$bridge/channels/$room/join" \
    -d "{\"agent_key\":\"$agent\"}" >/dev/null
done

curl -sS "${common[@]}" "$bridge/live-sessions/$room" | jq
```

Do not send `agent_key` on the live SSE route. A stream cannot claim a participant
identity; presence is established through the identity-bound join route.

## Subscribe with replay

Each adapter keeps the last **contiguous** sequence that it applied:

```sh
curl -N -sS -H "Authorization: Bearer ${BRIDGE_BEARER}" \
  "$bridge/live-sessions/$room/stream?after_seq=0"
```

A reconnect uses its stored sequence:

```sh
curl -sS -H "Authorization: Bearer ${BRIDGE_BEARER}" \
  "$bridge/live-sessions/$room/events?since=41" | jq

curl -N -sS -H "Authorization: Bearer ${BRIDGE_BEARER}" \
  "$bridge/live-sessions/$room/stream?after_seq=47"
```

The bridge captures the live receiver and high-water sequence together, replays
only the retained snapshot through that high-water mark, then switches to live
fan-out. Legacy bridge messages are represented as `message` payloads so they do
not punch holes in sequence continuity.

## Publish an observable event

```sh
curl -sS "${common[@]}" "$bridge/live-sessions/$room/events" -d "{
  \"client_event_id\":\"claude-review-0001\",
  \"session_id\":\"$room\",
  \"channel\":\"$room\",
  \"sender\":\"claude\",
  \"recipients\":[\"chatgpt\",\"grok\"],
  \"correlation_id\":\"pmap-review-round-1\",
  \"idempotency_key\":\"claude-pmap-review-0001\",
  \"payload\":{
    \"kind\":\"proposal\",
    \"proposal_id\":\"pmap-activation-gate-1\",
    \"summary\":\"Keep production activation disabled until TLS, immutable images, migrations, and browser canaries pass.\"
  },
  \"extensions\":{}
}" | jq
```

The first acceptance returns HTTP `201`, an assigned event ID, and a server
sequence. Repeating the same normalized request with the same idempotency key
returns the original identity with `replayed=true`. Reusing the key for different
content returns `409 idempotency_conflict` and writes nothing.

The compatibility implementation keeps idempotency records in retained channel
history. Therefore it is a single-process, bounded-window guarantee—not a claim
of clustered exactly-once delivery. A clustered rollout needs a durable event and
idempotency ledger plus one sequencing authority per session.

## Adapter loop

Each provider adapter follows the same state machine:

1. Authenticate with its scoped bridge credential.
2. Join the channel using its own identity.
3. Replay from its last contiguous sequence and open the SSE stream.
4. Ignore its own events and events addressed exclusively to other participants.
5. Convert the observable room context into that provider's request format.
6. Call the provider with local credentials and bounded timeout/output limits.
7. Publish a `message`, `proposal`, `decision`, `work_status`, or other typed event
   with a new client event ID and stable retry idempotency key.
8. Persist its contiguous sequence only after local processing succeeds.

Adapters should publish concise answers, decisions, evidence, and status. They
must not request or transmit chain-of-thought, hidden reasoning, reasoning tokens,
raw prompts, private traces, credentials, or unrestricted tool output. The bridge
rejects those private-trace field names recursively.

## Tools, approvals, and finalization

A `tool_request` is a proposal to an authorized executor; it is not permission.
The finalizer must independently verify:

- the authenticated human/workload identity;
- an exact, unexpired capability grant for tool, action, resource, tenant, and
  environment;
- any required approval and spend ceiling;
- current repository/job lease ownership and fencing token;
- an idempotency or compare-and-swap guard at the irreversible boundary;
- postcondition evidence before reporting completion.

The finalizer publishes a `tool_result`, `work_status`, evidence references, and a
`tracker_update`. It then records the concise outcome in GitHub and Linear. Live
chat is useful for coordination, but it never replaces those durable ledgers.

## Recommended clustered topology

```text
private ingress / Cloudflare Access
                |
        stateless bridge replicas
                |
    session-keyed NATS JetStream subjects
                |
 PostgreSQL event + idempotency + cursor ledger
                |
 provider workers and separately privileged finalizer
```

Persist before acknowledging acceptance; broadcast only after the durable
commit. Partition by session so one consumer assigns its order. Rebuild stream
state from the ledger after restart. NATS transports the protocol but does not
mint approval, lease, or finalization authority.

The normative Rust, TypeSpec, Protobuf, and JSON Schema v1 contracts are proposed
in `agent-pontifex/agent-sdk.rs#6`. This bridge PR is the compatibility runtime
mapping onto the existing ordered channel bus.
