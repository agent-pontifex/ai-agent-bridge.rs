# DEN-1873 generated dependency repair receipt

This receipt records the one-shot Cargo lock repair used by
`agent-pontifex/ai-agent-bridge.rs#7`.

- Carrier branch: `fix/den-1873-ci-baseline`
- Manifest contract: `hmac = "0.12"`, `sha2 = "0.10"`
- Generator workflow run: `33548672878`
- Cargo-generated commit: `1a37f8e117f649ce763c0dc4fabfd7919f48ddb0`
- Generator result: success

The generator ran `cargo metadata`, locked metadata, formatting, strict Clippy,
all-target/all-feature tests, and all-target/all-feature builds before it was
allowed to commit. Its commit changed only `Cargo.lock` and removed the
branch-scoped generator workflow.

The compatible 0.10 digest family preserves the existing Slack HMAC source API.
The lock repair removes the unused 0.11 digest/HMAC dependency family instead of
silently migrating the signing implementation or hand-editing generated lock
bytes.

This receipt is documentation only. It does not authorize a deployment, relax a
repository policy, suppress an advisory, or replace the normal exact-head pull
request checks.
