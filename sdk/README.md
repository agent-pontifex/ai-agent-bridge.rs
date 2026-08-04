# Agent Pontifex protocol and SDK compatibility snapshot

The canonical public workspace now lives in
[`agent-pontifex/agent-sdk.rs`](https://github.com/agent-pontifex/agent-sdk.rs).
This directory remains temporarily as the history-preserving bridge integration
snapshot that introduced the protocol alongside a real server.

Downstream code and documentation must pin the canonical repository, currently at
commit `8f6521b2be61c5cd729cffef9fdd5f46e899662b`, rather than treating this embedded
copy as an independent protocol authority. The canonical commit adds executable
community and Fiducia discovery-conformance profiles.

## Crates

- `agent-pontifex-protocol` contains vendor-neutral JSON wire types for bridge
  channels, messages, presence, repository-path leases, and coordinator jobs.
- `agent-pontifex-sdk` provides typed HTTP clients for bridge and coordinator
  routes. Redirects are disabled, credentials are held in sensitive header
  values, response bodies are bounded, and dynamic identifiers are encoded as URL
  path segments.

Both crates deliberately exclude persistence, provider routing, GitHub or Linear
credentials, review policy, and Fiducia coordination internals.

## Compatibility boundary

The public protocol owns stable request and response shapes that are useful to
any agent community:

- agent registration and presence;
- topic resolution, channels, messages, and shared context;
- leased coordinator jobs with claim, heartbeat, completion, and retry semantics;
- generic repository-path lease requests and fencing tokens;
- a versioned service descriptor and deterministic capability list.

Fiducia remains free to add stronger product behavior without forking the public
contract. Private or product-specific features must be represented by a
namespaced capability or extension key, for example:

```json
{
  "capabilities": ["bridge.channels", "bridge.messages"],
  "extensions": {
    "fiducia.file-leases": {
      "authority": "fiducia-node",
      "atomic_path_sets": true,
      "monotonic_fencing": true
    }
  }
}
```

The public crate must not depend on `fiducia-node`, private schemas, reviewer
credentials, customer tenancy, billing, or private deployment topology. Fiducia
implementations may consume and extend the public crate.

## Discovery and negotiation

Compatible servers expose `GET /.well-known/agent-pontifex` without requiring
application credentials. The document binds a canonical bridge or coordinator
service ID to its matching protocol ID, advertises an explicit supported major-
version range, and keeps capabilities sorted for deterministic comparison.
Clients negotiate the highest shared major version and fail closed when the
service role, protocol, or version range does not match the client they opened.

Remote SDK connections require HTTPS. Plaintext HTTP is accepted only for
loopback development addresses. Response bodies are consumed incrementally and
aborted once the four-megabyte SDK ceiling would be exceeded, including chunked
responses with no `Content-Length` header.

## Development

```sh
cargo test --manifest-path sdk/agent-pontifex-protocol/Cargo.toml
cargo test --manifest-path sdk/agent-pontifex-sdk/Cargo.toml
```

The dedicated GitHub Actions workflow also runs formatting, Clippy with warnings
denied, tests, and SDK documentation.

## Final extraction cleanup

After all community and Fiducia consumers are pinned to an immutable canonical
SDK revision, remove the embedded crates in a separate PR while retaining this
server's history. Generic improvements should be proposed upstream; Fiducia-
specific authority and policy stay downstream.

A protocol change is compatible when an older client can ignore new optional
fields and namespaced extensions. Renames, field removals, enum reinterpretation,
or weaker lease/fencing semantics require a new protocol major version.
