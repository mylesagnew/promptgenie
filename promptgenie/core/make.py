"""make.py — a tiny YAML task-graph batch runner for PromptGenie.

``promptgenie make`` is to prompt pipelines what ``make`` / ``just`` /
``Taskfile`` are to builds: a declarative ``promptgenie.make.yaml`` that wires
``lint`` / ``scan`` / ``test`` / ``evaluate`` (and any shell command) into a
dependency graph, then runs the requested targets in topological order — with
optional changed-file filtering and bounded parallelism.

Makefile shape
--------------
.. code-block:: yaml

    tasks:
      lint:
        run: promptgenie lint prompts/**/*.md
        inputs: ["prompts/**/*.md"]
      scan:
        run: promptgenie scan prompts/**/*.md
        inputs: ["prompts/**/*.md"]
      test:
        run: promptgenie test tests/**/*.prompt-test.yaml
        inputs: ["tests/**", "prompts/**"]
      ci:
        needs: [lint, scan, test]

* ``run`` — a shell command, or a list of commands run in order (any non-zero
  exit fails the task). Optional; a task may be a pure aggregator (``needs``
  only).
* ``needs`` — task names that must complete first.
* ``inputs`` — glob patterns used by ``--changed`` filtering.
* ``desc`` / ``description`` — a human label for ``--list``.

Changed-file filtering (``--changed``)
--------------------------------------
A task is *dirty* (and therefore run) when:

* it declares ``inputs`` and one of them matches a changed file; or
* it declares no ``inputs`` but at least one of its ``needs`` is dirty; or
* it declares neither ``inputs`` nor ``needs`` (an unconditional task).

Clean tasks are skipped but still satisfy their dependents, so an aggregator
like ``ci`` runs only the sub-tasks whose inputs actually changed.

This module is dependency-free (stdlib only) and the command runner is
injectable, so the scheduler is fully unit-testable without spawning processes.
"""

from __future__ import annotations

import concurrent.futures as cf
import re
import subprocess  # nosec B404
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from promptgenie.core.fileio import safe_read_yaml

# A command runner takes a shell command string and returns (exit_code, output).
CommandRunner = Callable[[str], "tuple[int, str]"]

DEFAULT_MAKEFILE = "promptgenie.make.yaml"


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass
class MakeTask:
    name: str
    run: list[str] = field(default_factory=list)
    needs: list[str] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    description: str = ""


@dataclass
class Makefile:
    tasks: dict[str, MakeTask]

    def get(self, name: str) -> MakeTask:
        return self.tasks[name]


@dataclass
class TaskResult:
    name: str
    status: str  # "pass" | "fail" | "skipped" | "dry-run"
    exit_code: int = 0
    duration_ms: int = 0
    output: str = ""
    commands: list[str] = field(default_factory=list)
    reason: str = ""  # why skipped / dry-run note


@dataclass
class MakeRun:
    results: list[TaskResult]

    @property
    def ok(self) -> bool:
        return not any(r.status == "fail" for r in self.results)

    @property
    def failed(self) -> list[TaskResult]:
        return [r for r in self.results if r.status == "fail"]


class MakefileError(Exception):
    """Raised when a makefile cannot be parsed or fails validation."""


# ---------------------------------------------------------------------------
# Loading & validation
# ---------------------------------------------------------------------------


def load_makefile(path: str | Path) -> Makefile:
    """Load and validate *path* (a ``promptgenie.make.yaml``)."""
    p = Path(path)
    if not p.exists():
        raise MakefileError(f"Makefile not found: {p}")
    try:
        raw = safe_read_yaml(str(p))
    except (OSError, ValueError) as exc:
        raise MakefileError(f"Cannot read {p}: {exc}") from exc
    if not isinstance(raw, dict):
        raise MakefileError(f"{p}: top level must be a mapping with a 'tasks:' key.")
    tasks_raw = raw.get("tasks")
    if not isinstance(tasks_raw, dict) or not tasks_raw:
        raise MakefileError(f"{p}: missing or empty 'tasks:' mapping.")

    tasks: dict[str, MakeTask] = {}
    for name, body in tasks_raw.items():
        tasks[str(name)] = _parse_task(str(name), body)

    mf = Makefile(tasks=tasks)
    validate_makefile(mf)
    return mf


def _parse_task(name: str, body: object) -> MakeTask:
    if body is None:
        return MakeTask(name=name)
    if not isinstance(body, dict):
        raise MakefileError(f"Task '{name}': definition must be a mapping.")
    run = _as_str_list(body.get("run"), f"Task '{name}': 'run'")
    needs = _as_str_list(body.get("needs"), f"Task '{name}': 'needs'")
    inputs = _as_str_list(body.get("inputs"), f"Task '{name}': 'inputs'")
    desc = str(body.get("desc") or body.get("description") or "")
    return MakeTask(name=name, run=run, needs=needs, inputs=inputs, description=desc)


def _as_str_list(value: object, label: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise MakefileError(f"{label}: list items must be strings.")
            out.append(item)
        return out
    raise MakefileError(f"{label}: must be a string or a list of strings.")


def validate_makefile(mf: Makefile) -> None:
    """Validate dependency references and detect cycles."""
    for task in mf.tasks.values():
        for dep in task.needs:
            if dep not in mf.tasks:
                raise MakefileError(f"Task '{task.name}' needs unknown task '{dep}'.")

    visiting: set[str] = set()
    visited: set[str] = set()

    def dfs(name: str, path: list[str]) -> None:
        if name in visited:
            return
        if name in visiting:
            cycle = " → ".join(path + [name])
            raise MakefileError(f"Dependency cycle detected: {cycle}")
        visiting.add(name)
        for dep in mf.tasks[name].needs:
            dfs(dep, path + [name])
        visiting.discard(name)
        visited.add(name)

    for name in mf.tasks:
        dfs(name, [])


# ---------------------------------------------------------------------------
# Target resolution & ordering
# ---------------------------------------------------------------------------


def resolve_targets(mf: Makefile, targets: Iterable[str]) -> list[str]:
    """Return the topologically ordered closure of *targets* and their needs.

    With no targets, every task is selected.
    """
    requested = list(targets)
    for t in requested:
        if t not in mf.tasks:
            raise MakefileError(f"Unknown target: '{t}'. Available: {', '.join(sorted(mf.tasks))}")

    if not requested:
        wanted = set(mf.tasks)
    else:
        wanted = set()
        stack = list(requested)
        while stack:
            name = stack.pop()
            if name in wanted:
                continue
            wanted.add(name)
            stack.extend(mf.tasks[name].needs)

    return _topo_order(mf, wanted)


def _topo_order(mf: Makefile, subset: set[str]) -> list[str]:
    ordered: list[str] = []
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visited:
            return
        visited.add(name)
        for dep in mf.tasks[name].needs:
            if dep in subset:
                visit(dep)
        ordered.append(name)

    # Iterate in declaration order for deterministic output.
    for name in mf.tasks:
        if name in subset:
            visit(name)
    return ordered


# ---------------------------------------------------------------------------
# Changed-file filtering
# ---------------------------------------------------------------------------


def compute_dirty(mf: Makefile, order: list[str], changed: Iterable[str]) -> dict[str, bool]:
    """Return ``{task: is_dirty}`` for *order* given *changed* file paths.

    *order* must be topologically sorted so a task's needs are resolved first.
    """
    changed_paths = [c.replace("\\", "/") for c in changed]
    matchers: dict[str, list[re.Pattern[str]]] = {}
    dirty: dict[str, bool] = {}
    for name in order:
        task = mf.tasks[name]
        if task.inputs:
            pats = matchers.setdefault(name, [_glob_to_regex(g) for g in task.inputs])
            dirty[name] = any(p.match(c) for c in changed_paths for p in pats)
        elif task.needs:
            dirty[name] = any(dirty.get(d, False) for d in task.needs)
        else:
            dirty[name] = True
    return dirty


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a glob (with ``**``) into an anchored regex over posix paths."""
    pattern = pattern.replace("\\", "/")
    i, n = 0, len(pattern)
    out: list[str] = ["^"]
    while i < n:
        c = pattern[i]
        if c == "*":
            if pattern[i : i + 2] == "**":
                i += 2
                if pattern[i : i + 1] == "/":
                    i += 1
                    out.append("(?:.*/)?")  # zero or more directory segments
                else:
                    out.append(".*")
                continue
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c in ".()[]{}+^$|\\":
            out.append("\\" + c)
        else:
            out.append(c)
        i += 1
    out.append("$")
    return re.compile("".join(out))


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def _subprocess_runner(command: str) -> tuple[int, str]:
    # ``shell=True`` is intentional and by design: like ``make`` / ``just`` /
    # ``Taskfile``, ``promptgenie make`` runs the commands written in a
    # project-committed, author-trusted makefile, and those commands rely on
    # shell features (globs such as ``prompts/**/*.md``, pipes, redirection).
    # The makefile is part of the repository under the same trust as a Makefile;
    # untrusted input is never routed here.
    proc = subprocess.run(  # nosec B602
        command,
        shell=True,  # noqa: S602
        capture_output=True,
        text=True,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _execute_task(task: MakeTask, runner: CommandRunner) -> TaskResult:
    start = time.monotonic()
    chunks: list[str] = []
    exit_code = 0
    for command in task.run:
        code, output = runner(command)
        if output:
            chunks.append(output)
        if code != 0:
            exit_code = code
            break
    elapsed = int((time.monotonic() - start) * 1000)
    status = "fail" if exit_code != 0 else "pass"
    return TaskResult(
        name=task.name,
        status=status,
        exit_code=exit_code,
        duration_ms=elapsed,
        output="".join(chunks),
        commands=list(task.run),
    )


def run_makefile(
    mf: Makefile,
    targets: Iterable[str],
    *,
    changed: Iterable[str] | None = None,
    parallel: int = 1,
    keep_going: bool = False,
    dry_run: bool = False,
    runner: CommandRunner | None = None,
    on_complete: Callable[[TaskResult], None] | None = None,
) -> MakeRun:
    """Resolve *targets* and run them in dependency order.

    Parameters
    ----------
    changed:
        When provided, tasks whose inputs (transitively) did not change are
        skipped. Pass an empty iterable to skip everything change-gated.
    parallel:
        Maximum number of tasks to run concurrently (>= 1).
    keep_going:
        Continue scheduling independent tasks after a failure instead of
        aborting the run.
    dry_run:
        Resolve and report the plan without executing any command.
    runner:
        Command executor; defaults to a real subprocess runner. Injected in
        tests to avoid spawning processes.
    on_complete:
        Optional callback invoked with each :class:`TaskResult` as it finishes
        (in completion order) — used for live progress output.
    """
    runner = runner or _subprocess_runner
    parallel = max(1, parallel)
    order = resolve_targets(mf, targets)
    dirty = compute_dirty(mf, order, changed) if changed is not None else None

    results: dict[str, TaskResult] = {}

    def finish(result: TaskResult) -> None:
        results[result.name] = result
        if on_complete is not None:
            on_complete(result)

    if dry_run:
        for name in order:
            task = mf.tasks[name]
            if dirty is not None and not dirty[name]:
                finish(TaskResult(name, "skipped", reason="no changes", commands=list(task.run)))
            else:
                finish(TaskResult(name, "dry-run", commands=list(task.run)))
        return MakeRun(results=[results[n] for n in order])

    done: set[str] = set()
    pending: set[str] = set(order)
    aborted = False

    def deps_done(name: str) -> bool:
        return all(d in done for d in mf.tasks[name].needs if d in pending or d in done)

    with cf.ThreadPoolExecutor(max_workers=parallel) as pool:
        futures: dict[cf.Future[TaskResult], str] = {}
        while pending or futures:
            progressed = False
            for name in order:
                if name not in pending or not deps_done(name):
                    continue
                task = mf.tasks[name]
                dep_failed = any(
                    results.get(d) is not None and results[d].status == "fail"
                    for d in task.needs
                )
                # Resolve skips eagerly (no worker needed). A task whose
                # dependency failed is always skipped — you cannot run it. The
                # --keep-going flag only governs whether *independent* tasks
                # keep going (i.e. whether the whole run is aborted).
                if aborted or dep_failed:
                    reason = "dependency failed" if dep_failed else "aborted"
                    pending.discard(name)
                    done.add(name)
                    finish(TaskResult(name, "skipped", reason=reason, commands=list(task.run)))
                    progressed = True
                    continue
                if dirty is not None and not dirty[name]:
                    pending.discard(name)
                    done.add(name)
                    finish(TaskResult(name, "skipped", reason="no changes", commands=list(task.run)))
                    progressed = True
                    continue
                if len(futures) >= parallel:
                    continue  # at capacity — wait for a slot
                pending.discard(name)
                futures[pool.submit(_execute_task, task, runner)] = name
                progressed = True

            if futures:
                completed = next(cf.as_completed(list(futures)))
                name = futures.pop(completed)
                result = completed.result()
                done.add(name)
                finish(result)
                if result.status == "fail" and not keep_going:
                    aborted = True
            elif not progressed:
                break  # safety: no progress possible (should not happen on a DAG)

    return MakeRun(results=[results[n] for n in order if n in results])
