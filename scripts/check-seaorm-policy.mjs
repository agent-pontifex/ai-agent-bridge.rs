import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { validateSeaOrmPolicy } from "./seaorm-policy.mjs";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(scriptDirectory, "..");

async function text(relativePath) {
  return readFile(path.join(repositoryRoot, relativePath), "utf8");
}

const [
  manifest,
  databaseSource,
  restartTest,
  gitmodules,
  persistenceManifest,
  persistenceSource,
  persistenceContractText,
  persistenceSchema,
] = await Promise.all([
  text("Cargo.toml"),
  text("src/db.rs"),
  text("tests/postgres_restart.rs"),
  text(".gitmodules"),
  text("persistence/agent-pontifex-persistence/Cargo.toml"),
  text("persistence/agent-pontifex-persistence/src/lib.rs"),
  text("persistence/agent-pontifex-persistence/contract.json"),
  text("persistence/agent-pontifex-persistence/schema.sql"),
]);

const result = validateSeaOrmPolicy({
  manifest,
  databaseSource,
  restartTest,
  gitmodules,
  persistenceManifest,
  persistenceSource,
  persistenceContract: JSON.parse(persistenceContractText),
  persistenceSchema,
  persistenceSchemaSha256: createHash("sha256")
    .update(persistenceSchema)
    .digest("hex"),
});

process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
