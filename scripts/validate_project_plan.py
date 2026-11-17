#!/usr/bin/env python3
"""Validate the generated planning structure and its task dependency graph."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_ROOT_FILES = (
    "story.md",
    "AGENTS.md",
    "TASKS.md",
    "GOALS.md",
    "DECISIONS.md",
    "docs/IMPLEMENTATION_PLAN.md",
    "docs/MCP_CAPABILITY_MATRIX.md",
)
REQUIRED_TASK_SECTIONS = (
    "User Story",
    "Objective",
    "Implementation Steps",
    "Files and Components",
    "Acceptance Criteria",
    "Tests and Verification",
    "Definition of Done",
)
TASK_ID_RE = re.compile(r"TASK-(\d{3})")
DEPENDENCY_RE = re.compile(r"^- \*\*Dependencies:\*\* (.*)$", re.MULTILINE)
INDEX_RECORD_RE = re.compile(
    r"^- \*\*TASK-(\d{3}) [^*]+\*\* — "
    r"(BACKLOG|READY|IN_PROGRESS|BLOCKED|IN_REVIEW|TESTING|DONE) · ([^·]+) · \d+h · deps: ([^·]+)",
    re.MULTILINE,
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def main() -> int:
    for relative in REQUIRED_ROOT_FILES:
        require((ROOT / relative).is_file(), f"Missing required project file: {relative}")

    task_files = sorted((ROOT / "tasks").glob("TASK-*.md"))
    require(len(task_files) == 76, f"Expected 76 task specs, found {len(task_files)}")
    task_ids = {int(path.name[5:8]) for path in task_files}
    require(task_ids == set(range(1, 77)), "Task IDs must be continuous from TASK-001 to TASK-076")

    index_text = (ROOT / "TASKS.md").read_text(encoding="utf-8")
    indexed_ids = {int(value) for value in re.findall(r"^- \*\*TASK-(\d{3})", index_text, re.MULTILINE)}
    require(indexed_ids == task_ids, "TASKS.md and task specification IDs do not match")
    require(len(re.findall(r"^## EPIC-\d{2}:", index_text, re.MULTILINE)) == 15, "Expected 15 epics")
    index_records = {}
    for line in index_text.splitlines():
        match = INDEX_RECORD_RE.match(line)
        if match:
            number, status, agent, dependencies = match.groups()
            index_records[int(number)] = (
                status,
                agent.strip(),
                [int(value) for value in TASK_ID_RE.findall(dependencies)],
            )
    require(index_records.keys() == task_ids, "A task index row has invalid/missing status, owner, estimate, or dependency metadata")

    graph: dict[int, list[int]] = {}
    for path in task_files:
        number = int(path.name[5:8])
        content = path.read_text(encoding="utf-8")
        require(content.startswith(f"# TASK-{number:03d}:"), f"Task title/filename mismatch: {path.name}")
        require(bool(re.search(r"^- \*\*Assigned agent:\*\* .+", content, re.MULTILINE)), f"Missing owner: {path.name}")
        require(bool(re.search(r"^- \*\*Status:\*\* (BACKLOG|READY|IN_PROGRESS|BLOCKED|IN_REVIEW|TESTING|DONE)$", content, re.MULTILINE)), f"Invalid/missing status: {path.name}")
        for section in REQUIRED_TASK_SECTIONS:
            require(f"## {section}" in content, f"Missing {section} section: {path.name}")
        match = DEPENDENCY_RE.search(content)
        require(match is not None, f"Missing dependencies: {path.name}")
        dependencies = [int(value) for value in TASK_ID_RE.findall(match.group(1))]
        require(all(dep in task_ids and dep != number for dep in dependencies), f"Invalid dependency in {path.name}")
        status = re.search(r"^- \*\*Status:\*\* ([A-Z_]+)$", content, re.MULTILINE)
        agent = re.search(r"^- \*\*Assigned agent:\*\* (.+)$", content, re.MULTILINE)
        require(status is not None and agent is not None, f"Missing status or owner: {path.name}")
        require(
            index_records[number] == (status.group(1), agent.group(1).strip(), dependencies),
            f"TASKS.md metadata does not match {path.name}",
        )
        graph[number] = dependencies

    visited: set[int] = set()
    active: set[int] = set()

    def visit(number: int) -> None:
        require(number not in active, f"Dependency cycle contains TASK-{number:03d}")
        if number in visited:
            return
        active.add(number)
        for dependency in graph[number]:
            visit(dependency)
        active.remove(number)
        visited.add(number)

    for number in graph:
        visit(number)

    print(f"Project plan valid: 15 epics, 76 task specs, {len(visited)} dependency nodes, no cycles.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        print(f"Project plan validation failed: {error}", file=sys.stderr)
        raise SystemExit(1)
