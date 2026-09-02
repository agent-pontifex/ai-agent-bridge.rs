# Bridge repository lineage and canonicalization gate

`agent-pontifex/ai-agent-bridge.rs` and `ORESoftware/ai-agent-bridge.rs` are
currently active, divergent repositories. The Pontifex line contains the
four-provider roundtable, replay-safe live-session, Slack-ingress, and
Agent-Pontifex persistence work. The ORESoftware line contains bounded
activation-canary and fleet-runtime work. Neither line is presently a truthful
superset of the other.

The current Cargo package and repository metadata still use the historical
`fiducia-*` identity. That is recorded in `repository-lineage.json` as
`unresolved-legacy`; it is not evidence that a third repository is canonical.
Renaming packages or images without a complete consumer/deployment inventory can
break running manifests and make process names unreliable as provenance.

For those reasons, deprecation is default-deny. A future consolidation must, in
one reviewed program:

1. inventory every active deployment, release workflow, image, package, CLI,
   service unit, Git submodule, and downstream dependency;
2. compare divergent commits and public contracts from both lines;
3. choose final crate, binary, image, and repository identities;
4. preserve every capability listed in the machine-readable lineage record with
   cross-repository tests;
5. update all consumers before retiring an old identity;
6. prove cutover, rollback, and the absence of a dual-writer window; and
7. disable release/deployment authority in the retired line before adding a
   deprecation notice.

`scripts/validate_repository_lineage.py` prevents an agent or ordinary PR from
publishing a false deprecation notice, dropping a preservation gate, drifting
Cargo identity without a decision, or restoring the incorrect ORESoftware scope
to this repository's agent instructions.
