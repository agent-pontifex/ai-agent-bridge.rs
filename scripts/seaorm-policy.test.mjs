import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";

import {
  SeaOrmPolicyError,
  validateSeaOrmPolicy,
} from "./seaorm-policy.mjs";

const persistenceSchema = `
create schema if not exists ai_agent_bridge;
create table if not exists ai_agent_bridge.agents (id uuid);
create table if not exists ai_agent_bridge.channels (id uuid);
create table if not exists ai_agent_bridge.channel_members (id uuid);
create table if not exists ai_agent_bridge.messages (id uuid);
create table if not exists ai_agent_bridge.shared_context (id uuid);
`;
const persistenceSchemaSha256 = createHash("sha256")
  .update(persistenceSchema)
  .digest("hex");

const valid = {
  manifest: `
[dependencies]
sea-orm = { version = "1.1.20" }
agent-pontifex-persistence = { path = "persistence/agent-pontifex-persistence" }
[features]
postgres = ["dep:sea-orm", "dep:agent-pontifex-persistence"]
`,
  databaseSource: `
use sea_orm::{ConnectOptions, DatabaseConnection, FromQueryResult, Statement, Value};
fn verify_public_entity_contract() { let _ = agent_pontifex_persistence::AgentsEntity; }
fn statements(channel_slugs: &[String]) {
  options.sqlx_logging(false);
  let _ = Statement::from_sql_and_values(DbBackend::Postgres, "sql", [text_array(channel_slugs)]);
  let _ = Value::Array(ArrayType::String, None);
}
const SQL: &str = "row_number() over (partition by m.channel_slug order by m.seq desc)
where m.channel_slug = any($1::text[])
on conflict (agent_key) do update
on conflict (slug) do update
on conflict (channel_slug, seq) do nothing
on conflict (channel_slug, agent_key) do update
where ai_agent_bridge.shared_context.version < excluded.version
updated_at = now()
on conflict (channel_slug, ctx_key) do update";
`,
  restartTest: `
#[ignore = "requires FIDUCIA_BRIDGE_TEST_DATABASE_URL provisioned from public Agent Pontifex persistence schema.sql"]
fn invariants() {
  let _ = "late stale context write is harmless";
  let _ = "sequence must resume above the durable high-water";
  let _ = "presence must be live, not durable";
}
`,
  gitmodules: `[submodule "vendor/flags-2-env"]
path = vendor/flags-2-env
url = https://github.com/ORESoftware/flags-2-env.git
`,
  persistenceManifest: `
[package]
name = "agent-pontifex-persistence"
version = "0.1.0"
[dependencies]
sea-orm = "1"
`,
  persistenceSource: `
pub struct AgentsEntity;
pub struct ChannelsEntity;
pub struct ChannelMembersEntity;
pub struct MessagesEntity;
pub struct SharedContextEntity;
fn schema() -> Option<&'static str> { Some("ai_agent_bridge") }
`,
  persistenceContract: {
    schemaAuthority: {
      repository: "agent-pontifex/ai-agent-bridge.rs",
      path: "persistence/agent-pontifex-persistence/schema.sql",
      sha256: persistenceSchemaSha256,
      serviceBootMigrations: false,
    },
    upstreamProvenance: {
      repository: "ORESoftware/k8s-libs-and-shared-defs",
      path: "pg-defs/schema/schema.sql",
      commit: "3c84cab532b27d328378f09fba5841f02644ae3b",
      privateCheckoutRequired: false,
    },
    rust: {
      applicationOrm: "SeaORM",
      directSqlxDependency: "forbidden",
    },
    migration: {
      tool: "dpm",
      repository: "declarative-migrations/declarative-postgres-migrate.rs",
    },
  },
  persistenceSchema,
  persistenceSchemaSha256,
};

function clone(value) {
  return structuredClone(value);
}

function expectInvalid(input, pattern) {
  assert.throws(
    () => validateSeaOrmPolicy(input),
    (error) => {
      assert.ok(error instanceof SeaOrmPolicyError);
      assert.match(error.message, pattern);
      return true;
    },
  );
}

test("the public fixture preserves SeaORM and immutable upstream provenance", () => {
  assert.deepEqual(validateSeaOrmPolicy(valid), {
    valid: true,
    service: "agent-pontifex-ai-agent-bridge",
    applicationOrm: "SeaORM",
    schemaAuthority: "agent-pontifex/ai-agent-bridge.rs",
    upstreamCommit: "3c84cab532b27d328378f09fba5841f02644ae3b",
    statementSemantics: 8,
    publicTables: 5,
    directSqlx: false,
    bootMigrations: false,
    privateCheckoutRequired: false,
  });
});

test("direct SQLx, PgPool, and raw tokio-postgres fail closed", () => {
  const dependency = clone(valid);
  dependency.manifest += '\nsqlx = { version = "0.8" }\n';
  expectInvalid(dependency, /must not directly depend on SQLx/);

  const pool = clone(valid);
  pool.databaseSource += "\nlet pool: PgPool;\n";
  expectInvalid(pool, /forbidden path/);

  const query = clone(valid);
  query.databaseSource += '\nlet _ = sqlx::query("select 1");\n';
  expectInvalid(query, /forbidden path/);

  const raw = clone(valid);
  raw.manifest += '\ntokio-postgres = "0.7"\n';
  expectInvalid(raw, /must not directly depend on tokio-postgres/);
});

test("complex PostgreSQL restore and upsert semantics cannot be simplified away", () => {
  for (const fragment of [
    "row_number() over (partition by m.channel_slug order by m.seq desc)",
    "on conflict (channel_slug, seq) do nothing",
    "where ai_agent_bridge.shared_context.version < excluded.version",
    "updated_at = now()",
  ]) {
    const input = clone(valid);
    input.databaseSource = input.databaseSource.replace(fragment, "removed");
    expectInvalid(input, /lost PostgreSQL semantic fragment/);
  }

  const array = clone(valid);
  array.databaseSource = array.databaseSource.replace(
    "[text_array(channel_slugs)]",
    "[]",
  );
  expectInvalid(array, /channel slug arrays must remain bound/);
});

test("tests cannot duplicate schema DDL or bypass SeaORM", () => {
  const sqlxTest = clone(valid);
  sqlxTest.restartTest += "\nlet _ = sqlx::raw_sql(TEST_SCHEMA);\n";
  expectInvalid(sqlxTest, /restart test must not use direct SQLx/);

  const copiedSchema = clone(valid);
  copiedSchema.restartTest += "\ncreate table ai_agent_bridge.agents(id uuid);\n";
  expectInvalid(copiedSchema, /must not duplicate the public schema/);

  const invariant = clone(valid);
  invariant.restartTest = invariant.restartTest.replace(
    "presence must be live, not durable",
    "presence can persist",
  );
  expectInvalid(invariant, /restart durability invariants must remain covered/);
});

test("private checkout, schema drift, and mutable provenance fail closed", () => {
  const privateSubmodule = clone(valid);
  privateSubmodule.gitmodules += `
[submodule "vendor/k8s-libs-and-shared-defs"]
path = vendor/k8s-libs-and-shared-defs
url = https://github.com/ORESoftware/k8s-libs-and-shared-defs.git
`;
  expectInvalid(privateSubmodule, /private fleet schema must not remain/);

  const privatePath = clone(valid);
  privatePath.manifest = privatePath.manifest.replace(
    "persistence/agent-pontifex-persistence",
    "vendor/k8s-libs-and-shared-defs",
  );
  expectInvalid(privatePath, /repository-owned path|private fleet schema checkout/);

  const mutable = clone(valid);
  mutable.persistenceContract.upstreamProvenance.commit = "main";
  expectInvalid(mutable, /immutable upstream provenance drifted/);

  const digest = clone(valid);
  digest.persistenceContract.schemaAuthority.sha256 = "0".repeat(64);
  expectInvalid(digest, /schema digest/);

  const extraSchema = clone(valid);
  extraSchema.persistenceSchema +=
    "\ncreate schema if not exists unrelated_product;\n";
  expectInvalid(extraSchema, /must not absorb unrelated fleet schemas/);
});
