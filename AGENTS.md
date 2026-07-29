# Repository Guidelines

## Project Structure & Module Organization

The Python package lives in `src/tlm_agent/`. `cli.py` defines the
command-line workflow; extraction, contract handling, generation, and
verification are separated into `extractors.py`, `workflow.py`, `generator.py`,
and `verifier.py`. Tests and synthetic RTL/spec fixtures are under `tests/`.

Container definitions are in `Dockerfile.ubuntu`, `Dockerfile.rocky8`, and
`compose.yaml`. Reusable commands belong in `scripts/`. The canonical Codex
skill is in `skills/modeling-systemc-tlm/`; Claude adapters are in
`integrations/claude/agents/`. Keep generated project data outside the package,
normally in a mounted project directory under `/workspace`.

## Build, Test, and Development Commands

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests
PYTHONPATH=src python3 -m tlm_agent.cli --help
podman-compose run --rm eda-agent bash scripts/regress.sh
```

The first command runs the workflow tests; the second catches Python syntax
errors; the third exercises CLI registration. The regression script checks the
container toolchain. Build only the image needed, for example
`podman-compose build eda-agent`. SCC and container builds may download or
compile large dependencies; agents must ask the user to run commands expected
to block for a long time.

## Coding Style & Naming Conventions

Use Python 3.10+, four-space indentation, type hints, and short docstrings for
policy or orchestration code. Follow `snake_case` for functions, variables, and
modules; use `PascalCase` for classes and `UPPER_CASE` for constants. Prefer
`pathlib.Path`, deterministic sorting, explicit errors, and small functions.
Shell scripts should use Bash with `set -Eeuo pipefail`. No formatter or linter
is currently enforced, so keep changes PEP 8-compatible and run `compileall`.

## Testing Guidelines

Tests use the standard `unittest` framework and follow `test_*.py` naming.
Add focused fixtures under `tests/fixtures/<design>/`. Cover both success and
gate behavior, especially conflicts, approval hashes, stale approvals, and RTL
discovery for `.v` and `.sv`. Tests should not require network access or
commercial EDA tools.

## Commit & Pull Request Guidelines

History is minimal and has no established message convention. Use concise,
imperative subjects such as `Add recursive RTL discovery`, with one logical
change per commit. Pull requests should explain intent, affected workflow
stages, commands run, and any skipped container/SCC validation. Link relevant
issues and include logs for build failures; screenshots are only needed for
user-interface changes.

## Security & Configuration

Do not commit licenses, credentials, proprietary RTL/specifications, or
company network paths. Keep commercial tools and license-server configuration
outside these open-source images.
