# Agent Pontifex persistence contract

This directory is the public persistence boundary for the Agent Pontifex bridge.

- `schema.sql` is the desired-state DDL for the `ai_agent_bridge` schema.
- `contract.json` records ownership, immutable upstream provenance, SeaORM rules,
  and the human-reviewed DPM migration boundary.
- `src/lib.rs` exposes the five table identities used by the bridge's
  parameterized SeaORM statements.

The bridge never applies DDL at service startup. CI uses DPM to bootstrap an
isolated PostgreSQL database and runs the restart durability test against it.
Production changes are rendered as reviewable DPM output and require human
approval.

The contract was extracted from the `ai_agent_bridge` portion of
`ORESoftware/k8s-libs-and-shared-defs` at commit
`3c84cab532b27d328378f09fba5841f02644ae3b`. That private repository remains
documented provenance, not a build-time or CI dependency.
