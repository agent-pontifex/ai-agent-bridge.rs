const REQUIRED_STATEMENT_FRAGMENTS = [
  "row_number() over (partition by m.channel_slug order by m.seq desc)",
  "where m.channel_slug = any($1::text[])",
  "on conflict (agent_key) do update",
  "on conflict (slug) do update",
  "on conflict (channel_slug, seq) do nothing",
  "on conflict (channel_slug, agent_key) do update",
  "version < excluded.version",
  "updated_at = now()",
];

const TABLES = [
  "agents",
  "channels",
  "channel_members",
  "messages",
  "shared_context",
];

export class SeaOrmPolicyError extends Error {
  constructor(errors) {
    super(`ai-agent-bridge SeaORM policy failed:\n- ${errors.join("\n- ")}`);
    this.name = "SeaOrmPolicyError";
    this.errors = errors;
  }
}

function require(condition, message, errors) {
  if (!condition) errors.push(message);
}

function dependency(manifest, name) {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&");
  const pattern = new RegExp(`^\\s*${escaped}\\s*=`, "mu");
  return pattern.test(manifest);
}

export function validateSeaOrmPolicy({
  manifest,
  databaseSource,
  restartTest,
  gitmodules,
  persistenceManifest,
  persistenceSource,
  persistenceContract,
  persistenceSchema,
  persistenceSchemaSha256,
}) {
  const errors = [];

  if (typeof manifest !== "string") {
    errors.push("Cargo.toml must be text");
  } else {
    require(dependency(manifest, "sea-orm"), "Cargo.toml must depend on SeaORM", errors);
    require(
      dependency(manifest, "agent-pontifex-persistence"),
      "Cargo.toml must consume the public Agent Pontifex persistence crate",
      errors,
    );
    require(!dependency(manifest, "sqlx"), "Cargo.toml must not directly depend on SQLx", errors);
    require(
      !dependency(manifest, "tokio-postgres"),
      "Cargo.toml must not directly depend on tokio-postgres",
      errors,
    );
    require(
      manifest.includes(
        'postgres = ["dep:sea-orm", "dep:agent-pontifex-persistence"]',
      ),
      "the postgres feature must enable only public SeaORM persistence dependencies",
      errors,
    );
    require(
      manifest.includes(
        'path = "persistence/agent-pontifex-persistence"',
      ),
      "the public persistence crate must be consumed from its repository-owned path",
      errors,
    );
    require(
      !manifest.includes("vendor/k8s-libs-and-shared-defs"),
      "Cargo.toml must not depend on the private fleet schema checkout",
      errors,
    );
  }

  if (typeof databaseSource !== "string") {
    errors.push("src/db.rs must be text");
  } else {
    for (const forbidden of [
      /\buse\s+sqlx\b/u,
      /\bsqlx::(?:query|query_as|query_scalar|raw_sql|migrate!)/u,
      /\bPgPool(?:Options)?\b/u,
      /\btokio_postgres\b/u,
      /\bMigrator::(?:up|down)\b/u,
      /create\s+(?:schema|table)\b/iu,
    ]) {
      require(!forbidden.test(databaseSource), `src/db.rs contains forbidden path ${forbidden}`, errors);
    }
    for (const required of [
      "DatabaseConnection",
      "ConnectOptions",
      "FromQueryResult",
      "Statement::from_sql_and_values",
      "Value::Array",
      "agent_pontifex_persistence",
      "verify_public_entity_contract",
      "on conflict (channel_slug, ctx_key) do update",
      'const SHARED_CONTEXT_TABLE: &str = "ai_agent_bridge.shared_context"',
    ]) {
      require(databaseSource.includes(required), `src/db.rs is missing ${JSON.stringify(required)}`, errors);
    }
    for (const fragment of REQUIRED_STATEMENT_FRAGMENTS) {
      require(
        databaseSource.includes(fragment),
        `src/db.rs lost PostgreSQL semantic fragment ${JSON.stringify(fragment)}`,
        errors,
      );
    }
    require(
      databaseSource.includes("[text_array(channel_slugs)]") &&
        databaseSource.includes("[advisory_key.into()]") === false,
      "channel slug arrays must remain bound SeaORM values",
      errors,
    );
    require(
      databaseSource.includes(".sqlx_logging(false)"),
      "SeaORM SQL logging policy must remain explicit",
      errors,
    );
  }

  if (typeof restartTest !== "string") {
    errors.push("tests/postgres_restart.rs must be text");
  } else {
    require(!/sqlx::|PgPool|raw_sql/u.test(restartTest), "restart test must not use direct SQLx", errors);
    require(
      !/create\s+(?:schema|table)\b/iu.test(restartTest),
      "restart test must not duplicate the public schema",
      errors,
    );
    require(
      restartTest.includes("public Agent Pontifex persistence schema.sql"),
      "restart test must require public schema provisioning",
      errors,
    );
    require(
      restartTest.includes("late stale context write is harmless") &&
        restartTest.includes("sequence must resume above the durable high-water") &&
        restartTest.includes("presence must be live, not durable"),
      "restart durability invariants must remain covered",
      errors,
    );
  }

  if (typeof gitmodules !== "string") {
    errors.push(".gitmodules must be text");
  } else {
    require(
      gitmodules.includes('[submodule "vendor/flags-2-env"]') &&
        gitmodules.includes("https://github.com/ORESoftware/flags-2-env.git"),
      "the public flags2env submodule is missing",
      errors,
    );
    require(
      !gitmodules.includes("k8s-libs-and-shared-defs"),
      "the private fleet schema must not remain a Git submodule",
      errors,
    );
  }

  if (typeof persistenceManifest !== "string") {
    errors.push("public persistence Cargo.toml must be text");
  } else {
    require(
      /^name\s*=\s*"agent-pontifex-persistence"$/mu.test(persistenceManifest),
      "public persistence package name drifted",
      errors,
    );
    require(
      dependency(persistenceManifest, "sea-orm"),
      "public persistence crate must expose SeaORM table identities",
      errors,
    );
  }

  if (typeof persistenceSource !== "string") {
    errors.push("public persistence src/lib.rs must be text");
  } else {
    for (const entity of [
      "AgentsEntity",
      "ChannelsEntity",
      "ChannelMembersEntity",
      "MessagesEntity",
      "SharedContextEntity",
    ]) {
      require(
        persistenceSource.includes(entity),
        `public persistence crate is missing ${entity}`,
        errors,
      );
    }
    require(
      persistenceSource.includes('Some("ai_agent_bridge")'),
      "public entities must remain scoped to ai_agent_bridge",
      errors,
    );
  }

  if (
    persistenceContract === null ||
    typeof persistenceContract !== "object" ||
    Array.isArray(persistenceContract)
  ) {
    errors.push("public persistence contract must be an object");
  } else {
    require(
      persistenceContract.schemaAuthority?.repository ===
        "agent-pontifex/ai-agent-bridge.rs" &&
        persistenceContract.schemaAuthority?.path ===
          "persistence/agent-pontifex-persistence/schema.sql",
      "public schema authority drifted",
      errors,
    );
    require(
      persistenceContract.schemaAuthority?.sha256 === persistenceSchemaSha256,
      "public schema digest does not match contract.json",
      errors,
    );
    require(
      persistenceContract.upstreamProvenance?.repository ===
        "ORESoftware/k8s-libs-and-shared-defs" &&
        persistenceContract.upstreamProvenance?.path ===
          "pg-defs/schema/schema.sql" &&
        persistenceContract.upstreamProvenance?.commit ===
          "3c84cab532b27d328378f09fba5841f02644ae3b",
      "immutable upstream provenance drifted",
      errors,
    );
    require(
      persistenceContract.upstreamProvenance?.privateCheckoutRequired === false,
      "public consumers must not require the private upstream checkout",
      errors,
    );
    require(
      persistenceContract.rust?.applicationOrm === "SeaORM",
      "public contract must require SeaORM",
      errors,
    );
    require(
      persistenceContract.rust?.directSqlxDependency === "forbidden",
      "public contract must forbid direct SQLx",
      errors,
    );
    require(
      persistenceContract.schemaAuthority?.serviceBootMigrations === false,
      "public contract must forbid boot migrations",
      errors,
    );
    require(
      persistenceContract.migration?.tool === "dpm" &&
        persistenceContract.migration?.repository ===
          "declarative-migrations/declarative-postgres-migrate.rs",
      "public migration authority drifted",
      errors,
    );
  }

  if (typeof persistenceSchema !== "string") {
    errors.push("public persistence schema.sql must be text");
  } else {
    require(
      persistenceSchema.includes("create schema if not exists ai_agent_bridge"),
      "public schema must own ai_agent_bridge",
      errors,
    );
    for (const table of TABLES) {
      require(
        persistenceSchema.includes(
          `create table if not exists ai_agent_bridge.${table}`,
        ),
        `public schema is missing table ${table}`,
        errors,
      );
    }
    require(
      !/create\s+schema\s+if\s+not\s+exists\s+(?!ai_agent_bridge\b)/iu.test(
        persistenceSchema,
      ),
      "public bridge schema must not absorb unrelated fleet schemas",
      errors,
    );
  }

  if (errors.length > 0) throw new SeaOrmPolicyError(errors);
  return {
    valid: true,
    service: "agent-pontifex-ai-agent-bridge",
    applicationOrm: "SeaORM",
    schemaAuthority: "agent-pontifex/ai-agent-bridge.rs",
    upstreamCommit:
      persistenceContract.upstreamProvenance.commit,
    statementSemantics: REQUIRED_STATEMENT_FRAGMENTS.length,
    publicTables: TABLES.length,
    directSqlx: false,
    bootMigrations: false,
    privateCheckoutRequired: false,
  };
}
