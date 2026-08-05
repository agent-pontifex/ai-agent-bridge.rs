# GitHub Actions workflows

Continuous-integration definitions for the Agent Pontifex bridge.

- `ci.yml` runs on pull requests and `main`. It validates formatting, Clippy,
  tests, the public PostgreSQL persistence contract, browser registry behavior,
  dependency advisories, and the pinned `flags-2-env` audit. Only the public
  `flags-2-env` submodule is initialized, and only in the job that consumes it.
- `seaorm-exact.yml` independently provisions PostgreSQL from
  `persistence/agent-pontifex-persistence/schema.sql` through DPM, then executes
  the ignored restart durability test with the `postgres` feature.
- `container-images.yml` builds and scans the four non-root runtime images from
  the public repository without private submodule credentials.

This folder exists so the same quality gates run identically in CI and locally.

## Security baseline

Every executable workflow uses explicit least-privilege permissions, immutable
third-party action or container references, non-persisted checkout credentials,
concurrency control, and a job timeout. The main CI workflow validates this
directory with the digest-pinned actionlint container. Environment mutation is
forbidden unless this README documents a repository-specific platform exception.
