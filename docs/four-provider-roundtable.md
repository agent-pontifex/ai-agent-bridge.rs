# Four-provider live roundtable conformance

This lane tests four independent provider identities against the actual Rust `fiducia-ai-agent-bridge` binary:

- Grok 4.6 (`grok-4.6`)
- Gemini 3.6 Pro, resolved explicitly to the available Pro endpoint `gemini-3.1-pro-preview`
- Claude Opus 5 (`claude-opus-5`)
- ChatGPT Sol 4.6, resolved explicitly to the available Sol endpoint `gpt-5.6-sol`

The checked-in matrix is `tests/fixtures/four-provider-models.json`. Model substitutions are visible data, not silent aliases. The live workflow refuses to run until an operator explicitly authorizes the bounded provider calls/API spend and acknowledges both model substitutions.

## What the pull-request lane proves

The credential-free job builds the exact pull-request head of the Rust bridge, starts it on loopback, registers and joins all four agents, and opens four independent SSE subscribers before any turn is published. It then runs two phases through the same provider adapter code used by the manual live lane:

1. each adapter publishes one observable introduction;
2. each adapter receives all four introductions, invokes its provider-shaped adapter with the shared transcript, and publishes a peer-aware acknowledgement.

The job requires eight contiguous server-assigned sequences, four complete SSE views, complete directed pairwise visibility, replay parity, exact idempotent retry, and conflicting-idempotency rejection. It uploads metadata-only evidence containing identifiers, sequence numbers, hashes, byte counts, and propagation measurements. It does not persist prompts, provider responses, credentials, private traces, or hidden reasoning.

This is **turn-level real-time communication**. A completed provider response is published immediately over SSE. It is not token-by-token upstream streaming.

## Manual live lane

`Live four-provider roundtable` is a manual workflow protected by the `live-provider-smoke` GitHub environment. Configure required reviewers and these environment secrets:

- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `GEMINI_API_KEY`
- `XAI_API_KEY`

A dispatch must set both `authorize_live_provider_calls` and `acknowledge_model_substitutions` to true. The command also requires the internal `AGENT_PONTIFEX_ALLOW_LIVE_PROVIDER_CALLS=1` gate. All four provider credentials are preflighted before bridge access or any provider call, so an incomplete secret set fails without partial API spend.

The adapter only permits the fixed official HTTPS destinations encoded in `scripts/agent_pontifex_roundtable/providers.py`, rejects redirects, bounds provider response bytes and text, redacts live provider HTTP error bodies, uses one request per agent per phase, and never passes provider keys to the Rust bridge. The workflow explicitly removes provider credentials from the Rust bridge process environment. A live pass requires eight successful provider calls and the same replay/SSE/pairwise assertions as the credential-free lane.

## Local credential-free run

```sh
cargo build --locked --bin fiducia-ai-agent-bridge
state_dir="$(mktemp -d)"
export AGENT_PONTIFEX_BRIDGE_BEARER=local-only
HOST=127.0.0.1 HTTP_PORT=18142 TCP_PORT=0 \
API_AUTH_BEARER="$AGENT_PONTIFEX_BRIDGE_BEARER" \
AI_AGENT_BRIDGE_DIR="$state_dir" \
target/debug/fiducia-ai-agent-bridge &
bridge_pid=$!

python3 scripts/four_provider_roundtable.py \
  --mode mock \
  --bridge-url http://127.0.0.1:18142 \
  --evidence-out artifacts/four-provider-roundtable.json

kill "$bridge_pid"
```

The bearer and provider keys are accepted only through environment variables, never command-line arguments. GitHub and Linear remain the durable human-visible ledgers. The live room transports externally observable coordination; it does not confer tool authority or permission for irreversible writes.
