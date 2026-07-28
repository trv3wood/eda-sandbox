from __future__ import annotations

"""Reproducible A/B benchmark orchestration for SystemC/TLM modeling."""

import hashlib
import json
import os
import shlex
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .io import dump_json, load_json
from .workflow import CONTRACT_CATEGORIES

ARMS = ("baseline", "skill")
SANDBOX_ROOT = Path("/tmp/systemc-tlm-benchmark")
SANDBOX_WORKSPACE = SANDBOX_ROOT / "workspace"
SANDBOX_MANIFEST = SANDBOX_ROOT / "case.json"
SANDBOX_INPUTS = SANDBOX_ROOT / "inputs"
SANDBOX_TREATMENT = SANDBOX_ROOT / "treatment"
SANDBOX_EVIDENCE = SANDBOX_ROOT / "evidence"
CASES = (
    ("chipbench", "FracWidthConv_24to128"),
    ("chipbench", "data_accumulation_output"),
    ("chipbench", "least_common_multiple"),
    ("chipbench", "synchronous_FIFO"),
    ("chipbench", "asynchronous_FIFO"),
    ("chipbench", "cpu_top"),
    ("chipbench", "div"),
    ("chipbench", "ctrl"),
    ("opentitan", "i2c"),
    ("opentitan", "dma"),
)
SOURCES = {
    "chipbench": {
        "url": "https://github.com/zhongkaiyu/ChipBench.git",
        "license": "Apache-2.0",
    },
    "opentitan": {
        "url": "https://github.com/lowRISC/opentitan.git",
        "license": "Apache-2.0",
    },
}


def repository_root() -> Path:
    """Resolve the source checkout without assuming a user's home directory."""
    return Path(__file__).resolve().parents[2]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def prepare_workspace(work: Path) -> dict[str, Any]:
    """Create metadata only; deliberately do not clone or build large projects."""
    work = work.resolve()
    for relative in (
        "sources", "corpus/chipbench", "corpus/opentitan",
        "oracle/contracts", "oracle/stimuli", "oracle/expected",
        "runs/luna", "reports",
    ):
        (work / relative).mkdir(parents=True, exist_ok=True)
    sources, commands = [], []
    for name, metadata in SOURCES.items():
        destination = work / "sources" / name
        sources.append({
            "name": name, **metadata, "commit": None, "tree_sha256": None,
            "status": "pending", "path": str(destination),
        })
        commands.append(
            f"git clone --filter=blob:none {shlex.quote(metadata['url'])} "
            f"{shlex.quote(str(destination))}"
        )
    dump_json(work / "sources" / "lock.json",
              {"schema_version": 1, "sources": sources})
    dump_json(work / "benchmark.json", {
        "schema_version": 1, "created_at": utc_now(), "model": "gpt-5.6-luna",
        "trials": 3,
        "modeling": {
            "skill_path": str(
                repository_root()
                / "skills"
                / "modeling-systemc-tlm"
                / "SKILL.md"
            ),
            "cli_path": str(repository_root() / "scripts" / "systemc-tlm-agent"),
        },
        "isolation": {
            "backend": "bubblewrap-selective",
            "codex_sandbox": "workspace-write",
            "ignore_user_config": True,
            "codex_auth_file": str(Path.home() / ".codex" / "auth.json"),
        },
        "cases": [{"suite": suite, "case": case, "enabled": True}
                  for suite, case in CASES],
        "contract_categories": [key for key, _ in CONTRACT_CATEGORIES],
        "seeds": [104729, 130363, 155921],
    })
    fetch = work / "sources" / "FETCH_COMMANDS.txt"
    fetch.write_text(
        "\n".join(commands) + "\n\n# Then pin commits and tree digests:\n"
        f"scripts/benchmark-systemc-tlm lock --work {shlex.quote(str(work))}\n",
        encoding="utf-8",
    )
    for suite, case in CASES:
        case_dir = work / "corpus" / suite / case
        case_dir.mkdir(parents=True, exist_ok=True)
        dump_json(case_dir / "case.json", {
            "schema_version": 1, "suite": suite, "case": case,
            "input_paths": [], "status": "requires-corpus-adapter",
        })
    return {"work": str(work), "cases": len(CASES),
            "status": "prepared-metadata", "next": f"run commands in {fetch}"}


def lock_sources(work: Path) -> dict[str, Any]:
    """Pin already downloaded repositories and record their Git tree IDs."""
    lock_path = work.resolve() / "sources" / "lock.json"
    lock = load_json(lock_path)
    for source in lock["sources"]:
        path = Path(source["path"])
        if not (path / ".git").exists():
            raise FileNotFoundError(f"source checkout is missing: {path}")
        commit = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"], check=True,
            text=True, capture_output=True,
        ).stdout.strip()
        tree_listing = subprocess.run(
            ["git", "-C", str(path), "ls-tree", "-r", "--full-tree", "HEAD"], check=True,
            text=True, capture_output=True,
        ).stdout
        source.update({"commit": commit,
                       "tree_sha256": sha256_text(tree_listing),
                       "status": "locked", "locked_at": utc_now()})
    dump_json(lock_path, lock)
    return {"lock": str(lock_path), "sources": lock["sources"]}


def extract_case_with_container(
    work: Path,
    *,
    case: str,
    top: str,
    reference_top: str | None = None,
    agent_image: str = "localhost/eda-agent:local",
    uhdm_image: str = "localhost/eda-uhdm:local",
    rtl_image: str = "localhost/eda-rtl:local",
    image: str | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    """Plan or run extraction with role-specific, independently built images."""
    work = work.resolve()
    _assert_ready(work)
    manifest_path = _case_manifest(work, case)
    case_data = load_json(manifest_path)
    rtl = [
        Path(value).resolve()
        for value in case_data.get("input_paths", [])
        if Path(value).suffix.lower() in {".v", ".sv"}
    ]
    configured_testbench = {
        Path(value).resolve()
        for value in case_data.get("testbench_paths", [])
    }
    if not configured_testbench:
        configured_testbench = {
            path for path in rtl
            if path.stem.lower().endswith(("_test", "_tb"))
        }
    design_rtl = [path for path in rtl if path not in configured_testbench]
    if not rtl:
        raise ValueError(f"case {case} has no Verilog/SystemVerilog inputs")
    for path in rtl:
        if not path.is_file():
            raise FileNotFoundError(path)
        try:
            path.relative_to(work)
        except ValueError as exc:
            raise ValueError(f"container input must be under --work: {path}") from exc
    project = manifest_path.parent / "eda-project"
    container_project = Path("/benchmark-work") / project.relative_to(work)
    if image:
        agent_image = uhdm_image = rtl_image = image
    agent_cli = "systemc-tlm-agent"
    init = [
        agent_cli, "init", str(container_project),
        "--name", case, "--top", top, "--backend", "local",
    ]
    if reference_top:
        init.extend(["--reference-top", reference_top])
    for path in design_rtl:
        init.extend([
            "--rtl", str(Path("/benchmark-work") / path.relative_to(work))
        ])
    for path in sorted(configured_testbench):
        init.extend([
            "--tb", str(Path("/benchmark-work") / path.relative_to(work))
        ])
    podman = shutil.which("podman")
    if execute and podman is None:
        raise RuntimeError("podman is required for container extraction")
    podman = podman or "podman"
    def prefix(selected_image: str) -> list[str]:
        return [
            podman, "run", "--rm",
            "-v", f"{work}:/benchmark-work:Z",
            "-w", "/benchmark-work",
            selected_image,
        ]

    commands = [
        prefix(agent_image) + init,
        prefix(agent_image) + [
            agent_cli, "extract", str(container_project), "--skip-tools",
        ],
        prefix(uhdm_image) + [
            "eda-uhdm-produce", str(container_project),
        ],
        prefix(rtl_image) + [
            "eda-rtl-produce", str(container_project),
        ],
        prefix(agent_image) + [
            agent_cli, "tools", "finalize", str(container_project),
        ],
    ]
    result = {
        "case": case,
        "top": top,
        "reference_top": reference_top or top,
        "images": {
            "agent": agent_image,
            "uhdm": uhdm_image,
            "rtl": rtl_image,
        },
        "project": str(project),
        "commands": commands,
        "status": "planned",
    }
    if execute:
        if project.exists():
            raise FileExistsError(
                f"extraction project already exists, preserve or remove it: {project}"
            )
        returncodes = []
        for index, command in enumerate(commands):
            completed = subprocess.run(command, check=False)
            returncodes.append(completed.returncode)
            if completed.returncode and index not in {2, 3}:
                raise subprocess.CalledProcessError(
                    completed.returncode, command
                )
        summary = load_json(project / ".systemc-agent/facts/summary.json")
        rtl_facts = load_json(project / ".systemc-agent/facts/rtl.json")
        result.update({
            "status": (
                "completed_with_tool_failures"
                if any(returncodes[index] for index in (2, 3))
                else "completed"
            ),
            "summary": summary,
            "tools": rtl_facts.get("tools", {}),
            "returncodes": returncodes,
        })
        dump_json(project / "container-extraction.json", result)
    return result


def _assert_ready(work: Path) -> dict[str, Any]:
    lock = load_json(work / "sources" / "lock.json")
    pending = [x["name"] for x in lock["sources"] if x["status"] != "locked"]
    if pending:
        raise ValueError("source commits are not locked: " + ", ".join(pending))
    return lock


def _case_manifest(work: Path, case: str) -> Path:
    matches = list(work.glob(f"corpus/*/{case}/case.json"))
    if len(matches) != 1:
        raise FileNotFoundError(f"unknown or ambiguous case: {case}")
    return matches[0]


def _prompt(
    arm: str,
    stage: str,
    runner: str,
    *,
    manifest_path: Path = SANDBOX_MANIFEST,
    evidence_path: Path = SANDBOX_EVIDENCE,
    treatment_path: Path = SANDBOX_TREATMENT,
) -> str:
    common = (
        "You are participating in a blinded SystemC TLM benchmark.\n"
        f"Case manifest: {manifest_path}\n"
        f"Stage: {stage}. Start from the case manifest and its declared inputs. "
        "You may inspect the available toolchain and run targeted local EDA "
        "commands when they help extract or cross-check evidence. The modeling "
        "Skill and its CLI are authorized only for the skill arm. Do not inspect "
        "other benchmark runs, another arm's outputs, *.codex.jsonl, run.json, "
        "oracle/, or reports/. Every design claim must cite a source locator. "
        "Keep tool output concise: use targeted searches and small line ranges "
        "instead of dumping entire sources or generated artifacts. "
        f"Use the shared container-generated EDA evidence at {evidence_path} "
        "as a starting point when present, but independently verify stale, "
        "failed, or incomplete parser views with available lightweight tools. "
        "Do not claim a tool is unavailable without checking the environment. "
        "Report commands that fail and continue with other evidence sources. "
        "Do not launch large downloads, image builds, or full regressions. "
        "Do not invent missing behavior. Before declaring "
        "the sources consistent, evaluate each supported input against both "
        "the specification mapping and the RTL equations; record every "
        "mismatch in conflicts.yaml. Produce all eight contract categories and stop on "
        "unresolved evidence or conflicts. "
    )
    common += (
        "Do not implement code yet.\n" if stage == "architect" else
        "Implement only the approved contracts. Keep minres-SCC isolated behind adapters "
        "and emit contract-traceable tests.\n"
    )
    if arm == "baseline":
        return common + "Do not use the repository-specific modeling Skill.\n"
    if treatment_path == repository_root():
        treatment_skill = (
            treatment_path / "skills/modeling-systemc-tlm/SKILL.md"
        )
        treatment_cli = treatment_path / "scripts/systemc-tlm-agent"
        treatment_agents = treatment_path / "integrations/claude/agents"
    else:
        treatment_skill = treatment_path / "skill/SKILL.md"
        treatment_cli = treatment_path / "bin/systemc-tlm-agent"
        treatment_agents = treatment_path / "claude-agents"
    treatment = (
        f"Use the modeling-systemc-tlm Skill at "
        f"{treatment_skill} and the deterministic CLI at "
        f"{treatment_cli}; respect "
        "role separation and the explicit approval gate.\n"
    )
    if runner == "claude":
        treatment += (
            f"Use the authorized Claude role adapters at "
            f"{treatment_agents} when assigning roles.\n"
        )
    return common + treatment


def architecture_is_approved(review: dict[str, Any]) -> bool:
    reviews = review.get("reviews", [])
    if len(reviews) < 2:
        return False
    reviewers = [item.get("reviewer") for item in reviews]
    if any(not name for name in reviewers) or len(reviewers) != len(set(reviewers)):
        return False
    first, second = reviews[0].get("decision"), reviews[1].get("decision")
    if first == second:
        return first == "approve"
    return len(reviews) >= 3 and reviews[2].get("decision") == "approve"


def _isolated_command(
    *,
    agent_dir: Path,
    sandbox_manifest: Path,
    input_mounts: list[tuple[Path, Path]],
    arm: str,
    skill_path: Path | None,
    cli_path: Path | None,
    runner: str,
    runner_command: list[str],
    config: dict[str, Any],
) -> list[str]:
    isolation = config.get("isolation", {})
    if isolation.get("backend") not in {
        "bubblewrap",
        "bubblewrap-selective",
    }:
        raise ValueError(
            "benchmark isolation.backend must be bubblewrap-selective"
        )
    bubblewrap = shutil.which("bwrap")
    if bubblewrap is None:
        raise RuntimeError("bubblewrap is required for benchmark read isolation")
    executable = Path(shutil.which(runner) or "").resolve()
    if not executable.is_file():
        raise RuntimeError(f"{runner} executable was not found")
    command = [
        bubblewrap,
        "--die-with-parent",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        # Preserve the host toolchain (including EDA installations), then mask
        # benchmark control data and arm-specific materials below.
        "--ro-bind", "/", "/",
        "--proc", "/proc",
        "--dev-bind", "/dev", "/dev",
        "--tmpfs", "/tmp",
        "--tmpfs", str(Path(config["_work"]).resolve()),
        "--dir", str(SANDBOX_ROOT),
        "--dir", str(SANDBOX_ROOT / "runner-bin"),
        "--ro-bind", str(executable), str(SANDBOX_ROOT / f"runner-bin/{runner}"),
        "--setenv", "PATH",
        f"{SANDBOX_ROOT}/runner-bin:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "--dir", str(SANDBOX_WORKSPACE),
        "--bind", str(agent_dir), str(SANDBOX_WORKSPACE),
        "--dir", str(SANDBOX_INPUTS),
        "--dir", str(SANDBOX_EVIDENCE),
        "--ro-bind", str(sandbox_manifest), str(SANDBOX_MANIFEST),
    ]
    if runner == "codex":
        auth_file = Path(
            isolation.get("codex_auth_file", "")
        ).expanduser().resolve()
        if not auth_file.is_file():
            raise FileNotFoundError(f"Codex auth file does not exist: {auth_file}")
        command.extend([
            "--tmpfs", str(Path.home() / ".codex"),
            "--dir", str(SANDBOX_ROOT / "runner-home"),
            "--ro-bind", str(auth_file),
            str(SANDBOX_ROOT / "runner-home/auth.json"),
            "--setenv", "CODEX_HOME", str(SANDBOX_ROOT / "runner-home"),
            "--setenv", "HOME", str(SANDBOX_WORKSPACE),
        ])
    else:
        # Claude OAuth is supplied by the host session/keyring. Claude Code also
        # writes session-env below ~/.claude before running any Bash tool, so a
        # read-only host HOME would silently disable evidence inspection. Give
        # each run a private writable config overlay, copying only provider
        # settings (never host agents, history, or unrelated user data).
        claude_home = agent_dir.parent / ".claude-runtime"
        claude_home.mkdir(parents=True, exist_ok=True)
        host_claude_home = Path.home() / ".claude"
        for name in ("ds-settings.json", "wzw-settings.json"):
            source = host_claude_home / name
            destination = claude_home / name
            if source.is_file() and not destination.exists():
                shutil.copy2(source, destination)
        host_state = Path.home() / ".claude.json"
        runtime_state = agent_dir.parent / ".claude-runtime.json"
        if host_state.is_file() and not runtime_state.exists():
            shutil.copy2(host_state, runtime_state)
        command.extend([
            "--bind", str(claude_home), str(host_claude_home),
            "--setenv", "HOME", str(Path.home()),
        ])
        if runtime_state.is_file():
            command.extend(["--bind", str(runtime_state), str(host_state)])
    for source, destination in input_mounts:
        command.extend(["--ro-bind", str(source), str(destination)])
    if arm == "skill":
        assert skill_path is not None and cli_path is not None
        command.extend([
            "--dir", str(SANDBOX_TREATMENT),
            "--dir", str(SANDBOX_TREATMENT / "skill"),
            "--ro-bind", str(skill_path.parent), str(SANDBOX_TREATMENT / "skill"),
            "--dir", str(SANDBOX_TREATMENT / "bin"),
            "--ro-bind", str(cli_path),
            str(SANDBOX_TREATMENT / "bin/systemc-tlm-agent"),
            "--dir", str(SANDBOX_TREATMENT / "src"),
            "--ro-bind", str(repository_root() / "src"),
            str(SANDBOX_TREATMENT / "src"),
            "--dir", str(SANDBOX_TREATMENT / "claude-agents"),
            "--ro-bind", str(repository_root() / "integrations/claude/agents"),
            str(SANDBOX_TREATMENT / "claude-agents"),
        ])
    else:
        # Baseline cannot inspect the checkout containing the Treatment Skill.
        command.extend(["--tmpfs", str(repository_root())])
    command.extend(runner_command)
    return command


def _sandbox_case(
    case_manifest: Path, run_dir: Path
) -> tuple[Path, list[tuple[Path, Path]]]:
    """Rewrite host input paths to a small, stable sandbox namespace."""
    case_data = load_json(case_manifest)
    mounts = []
    sandbox_paths = []
    for index, value in enumerate(case_data.get("input_paths", []), start=1):
        source = Path(value).resolve()
        if not source.is_file():
            raise FileNotFoundError(f"case input does not exist: {source}")
        destination = SANDBOX_INPUTS / f"{index:03d}{source.suffix}"
        mounts.append((source, destination))
        sandbox_paths.append(str(destination))
    case_data["input_paths"] = sandbox_paths
    evidence = case_manifest.parent / "eda-project"
    if evidence.is_dir():
        case_data["eda_evidence_path"] = str(SANDBOX_EVIDENCE)
        mounts.append((evidence, SANDBOX_EVIDENCE))
    sandbox_manifest = run_dir / "sandbox-case.json"
    dump_json(sandbox_manifest, case_data)
    return sandbox_manifest, mounts


def _stage_neutral_eda_evidence(source: Path, destination: Path) -> Path:
    """Copy parser-native outputs without treatment facts or contracts."""
    if destination.exists():
        for path in destination.rglob("*"):
            if path.is_file():
                path.chmod(path.stat().st_mode & ~0o222)
        return destination
    destination.mkdir(parents=True)
    tools = source / ".systemc-agent" / "tools"
    if tools.is_dir():
        shutil.copytree(tools, destination / "tools")
    for name in ("slpp_all", "obj_dir"):
        artifact = source / name
        if artifact.is_dir():
            shutil.copytree(artifact, destination / name)
    rtl_facts_path = source / ".systemc-agent" / "facts" / "rtl.json"
    if rtl_facts_path.is_file():
        rtl_facts = load_json(rtl_facts_path)
        dump_json(destination / "eda-status.json", {
            "schema_version": 1,
            "target_top": rtl_facts.get("target_top", rtl_facts.get("top")),
            "reference_top": rtl_facts.get("reference_top"),
            "tools": {
                name: {
                    key: value.get(key)
                    for key in ("status", "returncode")
                    if key in value
                }
                for name, value in rtl_facts.get("tools", {}).items()
            },
        })
    for path in destination.rglob("*"):
        if path.is_file():
            path.chmod(path.stat().st_mode & ~0o222)
    return destination


def _summarize_codex_jsonl(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    usage = None
    final_message = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("type") == "turn.completed":
            usage = event.get("usage")
        item = event.get("item", {})
        if item.get("type") == "agent_message" and item.get("text"):
            final_message = item["text"]
    return usage, final_message


def _summarize_claude_jsonl(
    path: Path,
) -> tuple[dict[str, Any] | None, str | None]:
    usage = None
    final_message = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("type") == "result":
            usage = event.get("usage")
            final_message = event.get("result")
    return usage, final_message


def _claude_actual_model(path: Path) -> str | None:
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("type") == "system" and event.get("subtype") == "init":
            return event.get("model")
    return None


def _run_claude_filtered(
    command: list[str],
    *,
    cwd: Path,
    jsonl_path: Path,
    stderr_path: Path,
) -> tuple[int, int]:
    """Stream Claude JSONL while dropping per-token progress notifications."""
    discarded = 0
    with (
        jsonl_path.open("w", encoding="utf-8") as out,
        stderr_path.open("w", encoding="utf-8") as errors,
        subprocess.Popen(
            command,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=errors,
            stdin=subprocess.DEVNULL,
        ) as process,
    ):
        assert process.stdout is not None
        for line in process.stdout:
            event = json.loads(line)
            if (
                event.get("type") == "system"
                and event.get("subtype") == "thinking_tokens"
            ):
                discarded += 1
                continue
            out.write(line)
        return process.wait(), discarded


def run_benchmark(
    work: Path, *, model: str, arm: str, trials: int,
    cases: list[str] | None = None, execute: bool = False,
    stage: str = "architect",
    runner: str = "codex",
    isolation_mode: str = "none",
) -> dict[str, Any]:
    work = work.resolve()
    if arm not in ARMS:
        raise ValueError(f"arm must be one of: {', '.join(ARMS)}")
    if stage not in {"architect", "implement"}:
        raise ValueError("stage must be architect or implement")
    if runner not in {"codex", "claude"}:
        raise ValueError("runner must be codex or claude")
    if isolation_mode not in {"none", "bubblewrap-selective"}:
        raise ValueError("isolation_mode must be none or bubblewrap-selective")
    lock = _assert_ready(work)
    config = load_json(work / "benchmark.json")
    # Runtime-only value used by the mount builder; it is not persisted.
    config["_work"] = str(work)
    modeling = config.get("modeling", {})
    skill_path = Path(modeling["skill_path"]).resolve() if modeling.get(
        "skill_path"
    ) else None
    cli_path = Path(modeling["cli_path"]).resolve() if modeling.get(
        "cli_path"
    ) else None
    if arm == "skill":
        for name, path in (("skill_path", skill_path), ("cli_path", cli_path)):
            if path is None or not path.is_file():
                raise FileNotFoundError(
                    f"modeling.{name} does not exist; update benchmark.json: {path}"
                )
    selected = cases or [x["case"] for x in config["cases"] if x["enabled"]]
    planned = []
    for case in selected:
        for trial in range(1, trials + 1):
            run_dir = work / "runs" / model / case / arm / str(trial)
            run_dir.mkdir(parents=True, exist_ok=True)
            agent_dir = run_dir / "agent-workspace"
            agent_dir.mkdir(parents=True, exist_ok=True)
            case_manifest = _case_manifest(work, case)
            sandbox_manifest, input_mounts = _sandbox_case(case_manifest, run_dir)
            source_evidence = case_manifest.parent / "eda-project"
            neutral_evidence = None
            if source_evidence.is_dir():
                neutral_evidence = _stage_neutral_eda_evidence(
                    source_evidence,
                    run_dir / "shared-eda-evidence",
                )
                input_mounts = [
                    mount
                    for mount in input_mounts
                    if mount[1] != SANDBOX_EVIDENCE
                ]
                input_mounts.append((neutral_evidence, SANDBOX_EVIDENCE))
            if stage == "implement":
                review_path = run_dir / "architecture-review.json"
                if not review_path.exists():
                    raise ValueError(f"architecture review is missing: {review_path}")
                review = load_json(review_path)
                if not architecture_is_approved(review):
                    raise ValueError(
                        "two matching blind reviews, or a positive third "
                        f"adjudication, are required: {review_path}"
                    )
            if isolation_mode == "none":
                direct_case = load_json(case_manifest)
                evidence = neutral_evidence or source_evidence
                if neutral_evidence is not None:
                    direct_case["eda_evidence_path"] = str(neutral_evidence)
                direct_manifest = run_dir / "direct-case.json"
                dump_json(direct_manifest, direct_case)
                manifest_path = direct_manifest
                evidence_path = evidence
                treatment_path = repository_root()
            else:
                manifest_path = SANDBOX_MANIFEST
                evidence_path = SANDBOX_EVIDENCE
                treatment_path = SANDBOX_TREATMENT
            prompt = _prompt(
                arm, stage, runner,
                manifest_path=manifest_path,
                evidence_path=evidence_path,
                treatment_path=treatment_path,
            )
            (run_dir / f"{stage}.prompt.txt").write_text(prompt, encoding="utf-8")
            if runner == "codex":
                runner_command = [
                    (
                        str(SANDBOX_ROOT / "runner-bin/codex")
                        if isolation_mode != "none"
                        else str(Path(shutil.which("codex") or "codex").resolve())
                    ),
                    "exec", "--skip-git-repo-check",
                    "-m", model, "--json", "--ephemeral",
                    "--sandbox", config["isolation"]["codex_sandbox"],
                    "-C", str(
                        SANDBOX_WORKSPACE
                        if isolation_mode != "none"
                        else agent_dir
                    ),
                ]
                if config["isolation"].get("ignore_user_config", True):
                    runner_command.append("--ignore-user-config")
                runner_command.append(prompt)
            else:
                runner_command = [
                    (
                        str(SANDBOX_ROOT / "runner-bin/claude")
                        if isolation_mode != "none"
                        else str(Path(shutil.which("claude") or "claude").resolve())
                    ),
                    "-p", "--model", model,
                    "--output-format", "stream-json", "--verbose",
                    "--no-session-persistence",
                    "--permission-mode", "bypassPermissions",
                    "--allow-dangerously-skip-permissions",
                ]
                if arm == "baseline":
                    baseline_settings = (
                        agent_dir / ".claude-baseline-settings.json"
                    )
                    dump_json(baseline_settings, {
                        "permissions": {
                            "deny": [
                                "Skill",
                                "Agent",
                                "Task",
                                "Task(systemc-*)",
                            ]
                        }
                    })
                    settings_path = (
                        SANDBOX_WORKSPACE / baseline_settings.name
                        if isolation_mode != "none"
                        else baseline_settings
                    )
                    runner_command.extend([
                        "--safe-mode",
                        "--disable-slash-commands",
                        "--tools", "Bash,Read,Write,Edit,Glob,Grep",
                        "--disallowedTools", "Skill,Agent,Task,Task(systemc-*)",
                        "--settings", str(settings_path),
                    ])
                runner_command.append(prompt)
            command = (
                runner_command
                if isolation_mode == "none"
                else _isolated_command(
                    agent_dir=agent_dir,
                    sandbox_manifest=sandbox_manifest,
                    input_mounts=input_mounts,
                    arm=arm,
                    skill_path=skill_path,
                    cli_path=cli_path,
                    runner=runner,
                    runner_command=runner_command,
                    config=config,
                )
            )
            metadata = {
                "schema_version": 1, "case": case, "arm": arm, "trial": trial,
                "model": model, "runner": runner, "stage": stage,
                "isolation": isolation_mode,
                "capability_policy": (
                    "baseline-no-skill-agent-task"
                    if runner == "claude" and arm == "baseline"
                    else "runner-default"
                ),
                "prompt_sha256": sha256_text(prompt),
                "input_commits": {x["name"]: x["commit"] for x in lock["sources"]},
                "command": command, "created_at": utc_now(), "started_at": None,
                "ended_at": None, "token_usage": None, "exit_status": "planned",
            }
            dump_json(run_dir / "run.json", metadata)
            if execute:
                metadata["started_at"] = utc_now()
                jsonl_path = run_dir / f"{stage}.{runner}.jsonl"
                stderr_path = run_dir / f"{stage}.{runner}.stderr.log"
                with (
                    jsonl_path.open("w", encoding="utf-8")
                    if runner == "codex"
                    else open(os.devnull, "w", encoding="utf-8") as out,
                    stderr_path.open("w", encoding="utf-8")
                    if runner == "codex"
                    else open(os.devnull, "w", encoding="utf-8") as errors,
                ):
                    if runner == "codex":
                        proc = subprocess.run(
                            command, cwd=agent_dir, text=True, stdout=out,
                            stderr=errors, stdin=subprocess.DEVNULL,
                        )
                        returncode = proc.returncode
                        discarded_events = 0
                    else:
                        returncode, discarded_events = _run_claude_filtered(
                            command,
                            cwd=agent_dir,
                            jsonl_path=jsonl_path,
                            stderr_path=stderr_path,
                        )
                summarizer = (
                    _summarize_codex_jsonl
                    if runner == "codex"
                    else _summarize_claude_jsonl
                )
                usage, final_message = summarizer(jsonl_path)
                if final_message is not None:
                    (run_dir / f"{stage}.final.md").write_text(
                        final_message + "\n", encoding="utf-8"
                    )
                metadata.update({
                    "ended_at": utc_now(), "exit_code": returncode,
                    "exit_status": "completed" if returncode == 0 else "failed",
                    "token_usage": usage,
                    "stderr_log": str(stderr_path),
                    "discarded_progress_events": discarded_events,
                })
                if runner == "claude":
                    metadata["actual_model"] = _claude_actual_model(jsonl_path)
                dump_json(run_dir / "run.json", metadata)
            planned.append(str(run_dir))
    return {
        "arm": arm, "model": model, "runner": runner, "runs": len(planned),
        "status": "executed" if execute else "planned",
        "run_directories": planned,
        "stage": stage,
        "note": "two blind approvals are required before implementation",
    }


def _percent(points: float, possible: float) -> float | None:
    return round(100 * points / possible, 2) if possible else None


def score_benchmark(work: Path) -> dict[str, Any]:
    """Aggregate reviewer-owned scores without exposing hidden oracles."""
    work = work.resolve()
    rows = []
    for path in sorted((work / "runs").glob("*/*/*/*/score.json")):
        score, run = load_json(path), load_json(path.parent / "run.json")
        sections = ("evidence", "architecture", "implementation", "functional")
        missing = [x for x in sections if x not in score]
        if missing:
            raise ValueError(f"{path} misses score sections: {missing}")
        points = sum(float(score[x]["points"]) for x in sections)
        possible = sum(float(score[x]["possible"]) for x in sections)
        rows.append({
            "case": run["case"], "arm": run["arm"], "trial": run["trial"],
            "points": points, "possible": possible,
            "percent": _percent(points, possible),
            "gate_violations": score.get("gate_violations", 0),
            "fabricated_evidence": score.get("fabricated_evidence", 0),
        })
    if not rows:
        raise ValueError("no reviewer score.json files found")
    arms = {}
    for arm in ARMS:
        selected = [x for x in rows if x["arm"] == arm]
        points, possible = (sum(x[k] for x in selected)
                            for k in ("points", "possible"))
        arms[arm] = {
            "runs": len(selected), "percent": _percent(points, possible),
            "gate_violations": sum(x["gate_violations"] for x in selected),
            "fabricated_evidence": sum(x["fabricated_evidence"] for x in selected),
        }
    b, s = arms["baseline"]["percent"], arms["skill"]["percent"]
    delta = round(s - b, 2) if b is not None and s is not None else None
    result = {"schema_version": 1, "generated_at": utc_now(),
              "arms": arms, "delta_points": delta, "runs": rows}
    dump_json(work / "reports" / "scores.json", result)
    return result


def report_benchmark(work: Path) -> dict[str, Any]:
    work = work.resolve()
    scores = load_json(work / "reports" / "scores.json")
    b, s = scores["arms"]["baseline"], scores["arms"]["skill"]
    lines = [
        "# SystemC TLM Benchmark Report", "", f"Generated: {utc_now()}", "",
        "| Arm | Scored runs | Correctness | Gate violations | Fabricated evidence |",
        "|---|---:|---:|---:|---:|",
        f"| baseline | {b['runs']} | {b['percent']}% | {b['gate_violations']} | {b['fabricated_evidence']} |",
        f"| skill | {s['runs']} | {s['percent']}% | {s['gate_violations']} | {s['fabricated_evidence']} |",
        "", f"Treatment delta: {scores['delta_points']} percentage points.", "",
        "The added SystemC harness makes this result not directly comparable "
        "to ChipBench paper pass@k.",
    ]
    path = work / "reports" / "report.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"report": str(path), "delta_points": scores["delta_points"]}
