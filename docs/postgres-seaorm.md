# PostgreSQL persistence: SeaORM over the public Agent Pontifex contract

The bridge is in-memory first. Building with `--features postgres` adds a
best-effort durable mirror and restart restoration through **SeaORM**.

## Schema and migration ownership

The bridge repository owns its narrow public DDL contract. The application
never runs migrations at startup.

| Concern | Authority |
| --- | --- |
| Public desired-state DDL | `persistence/agent-pontifex-persistence/schema.sql` |
| Public table identities | `persistence/agent-pontifex-persistence/src/lib.rs` |
| Ownership and immutable provenance | `persistence/agent-pontifex-persistence/contract.json` |
| Migration diff / verify / reviewed apply | `declarative-migrations/declarative-postgres-migrate.rs` |
| Runtime connection, restore, and writes | `src/db.rs` through SeaORM |

The five-table contract was extracted from
`ORESoftware/k8s-libs-and-shared-defs/pg-defs/schema/schema.sql` at immutable
commit `3c84cab532b27d328378f09fba5841f02644ae3b`. That private repository is
recorded only as provenance. It is not a build, CI, runtime, or deployment
dependency, and consumers do not need credentials for it. The public persistence
crate and schema travel with the same bridge commit that consumes them.

## Why several queries remain explicit statements

Ordinary application persistence uses SeaORM. Some bridge operations deliberately
use parameterized `sea_orm::Statement` values because changing their SQL shape
would change behavior:

- bounded per-channel restore uses a window function;
- channel batches use PostgreSQL text arrays;
- message insert is idempotent on `(channel_slug, seq)`;
- member and channel upserts use `EXCLUDED` expressions;
- timestamps use the database server clock;
- shared context rejects stale writes with an optimistic version guard;
- channel IDs are resolved inside the same write statement.

Values remain separately bound. No caller value is interpolated into SQL.
Direct application dependencies on SQLx or `tokio-postgres` are forbidden.

## Restart guarantees

The database mirror preserves:

- agent metadata;
- active channel metadata and embeddings;
- bounded recent message history;
- per-channel message count and sequence high-water;
- latest versioned shared context.

Live channel membership is intentionally not restored. Agents must rejoin after
restart so stale presence cannot appear active. A delayed context write cannot
overwrite a newer version.

## DPM workflow

Render and review schema changes from the repository-owned desired-state file:

```sh
dpm diff --source persistence/agent-pontifex-persistence/schema.sql
dpm verify --source persistence/agent-pontifex-persistence/schema.sql
dpm review --source persistence/agent-pontifex-persistence/schema.sql
# dpm apply --source persistence/agent-pontifex-persistence/schema.sql
```

Destructive changes require the reviewed DPM consent flags. Neither DPM nor an
ORM migration command belongs in bridge startup or deployment arguments.

## Local and CI verification

Initialize only the public tool submodule, then run:

```sh
git submodule update --init --depth=1 -- vendor/flags-2-env
node --test scripts/seaorm-policy.test.mjs
node scripts/check-seaorm-policy.mjs
cargo fmt --all -- --check
cargo clippy --all-targets --locked --features postgres -- -D warnings
cargo test --all-targets --locked
cargo check --all-targets --locked --features postgres
```

The ignored restart test requires a disposable database provisioned from DPM
bootstrap output for the public schema:

```sh
export FIDUCIA_BRIDGE_TEST_DATABASE_URL=postgresql://...
dpm bootstrap --source persistence/agent-pontifex-persistence/schema.sql \
  | psql "$FIDUCIA_BRIDGE_TEST_DATABASE_URL" -v ON_ERROR_STOP=1
cargo test --locked --features postgres --test postgres_restart -- --ignored
```

A successful persistence change must also be grep-clean for direct SQLx
pool/query calls, private schema checkout, recursive submodule checkout, and
boot-migration calls. The SeaORM feature string `sqlx-postgres` is its expected
transport backend; it is not a direct SQLx application dependency.

## UI boundary

Maud + HTMX, Leptos, and Dioxus are page-level rendering choices over this same
repository and schema. A Leptos analytics page or Dioxus activity page must
reuse the bridge's SeaORM, authentication, and owner-scope boundary rather than
introduce a second persistence authority.
