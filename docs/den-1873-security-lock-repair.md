# DEN-1873 audited security-lock repair receipt

This receipt records the Cargo-owned patch updates produced for
`agent-pontifex/ai-agent-bridge.rs#7`.

- Branch: `fix/den-1873-ci-baseline`
- Generator workflow run: `33550218978`
- Cargo-generated commit: `06b6aacb01a4839116ae02ed1ea0fe4884b34534`
- Generator result: success
- Updated vulnerable/yanked entries: `h2 0.4.15` to `0.4.16` and
  `chacha20 0.10.1` to `0.10.2`

Before committing, the generator required:

- locked metadata resolution;
- formatting;
- warnings-denied Clippy for every target and feature;
- every locked test for every target and feature;
- every locked build target and feature;
- absence of the old h2 and chacha20 versions from compiled dependency trees;
- absence of `rkyv 0.7.46` from both default and PostgreSQL compiled graphs;
- RustSec success with only the unreachable rkyv lock-metadata advisory narrowly
  ignored after that graph proof;
- a staged diff containing only Cargo's generated `Cargo.lock` and deletion of
  the one-shot carrier workflow.

The generator removed itself from the resulting branch. GitHub marked the
bot-authored commit's ordinary workflows as `action_required`; this
human-authored receipt exists to trigger the complete normal exact-head pull
request suite without changing runtime code or generated dependency bytes.
