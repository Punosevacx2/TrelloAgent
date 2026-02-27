# ai_trello_dev/run_board.py
# Kanban autopilot: Trello(ToDo -> Review -> MadePR -> Success) + repo changes + PR via gh
#
# ✅ Requirements:
#   pip install crewai crewai-tools requests python-dotenv
#   brew install gh
#   gh auth login
#
# ✅ .env in repo root:
#   TRELLO_KEY=...
#   TRELLO_TOKEN=...
#   TRELLO_BOARD_ID=...
#   TRELLO_LIST_TODO=...
#   TRELLO_LIST_REVIEW=...
#   TRELLO_LIST_MADEPR=...
#   TRELLO_LIST_SUCCESS=...
#
#   # optional (recommended)
#   DEFAULT_BASE_BRANCH=main
#   MAX_CARDS_PER_RUN=3

from __future__ import annotations

import os
import re
import json
import time
import textwrap
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv

from crewai import Agent, Task, Crew
from crewai.tools import tool

# -----------------------------
# Config + helpers
# -----------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")

TRELLO_KEY = os.getenv("TRELLO_KEY", "").strip()
TRELLO_TOKEN = os.getenv("TRELLO_TOKEN", "").strip()
TRELLO_BOARD_ID = os.getenv("TRELLO_BOARD_ID", "").strip()

LIST_TODO = os.getenv("TRELLO_LIST_TODO", "").strip()
LIST_REVIEW = os.getenv("TRELLO_LIST_REVIEW", "").strip()
LIST_MADEPR = os.getenv("TRELLO_LIST_MADEPR", "").strip()
LIST_SUCCESS = os.getenv("TRELLO_LIST_SUCCESS", "").strip()

DEFAULT_BASE_BRANCH = os.getenv("DEFAULT_BASE_BRANCH", "main").strip()
MAX_CARDS_PER_RUN = int(os.getenv("MAX_CARDS_PER_RUN", "3"))

if not all([TRELLO_KEY, TRELLO_TOKEN, TRELLO_BOARD_ID, LIST_TODO, LIST_REVIEW, LIST_MADEPR, LIST_SUCCESS]):
    raise SystemExit(
        "Missing Trello env vars. Add TRELLO_KEY/TRELLO_TOKEN/TRELLO_BOARD_ID and list IDs in .env"
    )

TRELLO_API = "https://api.trello.com/1"


def _slug(s: str, max_len: int = 42) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s[:max_len] or "task"


def _run(cmd: str) -> Tuple[int, str]:
    p = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        shell=True,
        text=True,
        capture_output=True,
        env=os.environ.copy(),
    )
    out = (p.stdout or "") + (p.stderr or "")
    return p.returncode, out.strip()


def _require_ok(rc: int, out: str, context: str) -> str:
    if rc != 0:
        return f"ERROR in {context} (rc={rc}):\n{out}"
    return out


def _detect_base_branch() -> str:
    # Prefer env override if set explicitly
    if DEFAULT_BASE_BRANCH:
        # still verify if repo uses different default, but keep env as fallback
        pass
    rc, out = _run("gh repo view --json defaultBranchRef --jq .defaultBranchRef.name")
    if rc == 0 and out:
        return out.strip()
    return DEFAULT_BASE_BRANCH or "main"


# -----------------------------
# Trello client
# -----------------------------

@dataclass
class TrelloCard:
    id: str
    name: str
    desc: str
    shortLink: str
    url: str
    idList: str


def trello_get(path: str, params: Dict[str, Any] | None = None) -> Any:
    params = params or {}
    params.update({"key": TRELLO_KEY, "token": TRELLO_TOKEN})
    r = requests.get(f"{TRELLO_API}{path}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def trello_post(path: str, data: Dict[str, Any] | None = None) -> Any:
    data = data or {}
    data.update({"key": TRELLO_KEY, "token": TRELLO_TOKEN})
    r = requests.post(f"{TRELLO_API}{path}", data=data, timeout=30)
    r.raise_for_status()
    return r.json()


def trello_put(path: str, data: Dict[str, Any] | None = None) -> Any:
    data = data or {}
    data.update({"key": TRELLO_KEY, "token": TRELLO_TOKEN})
    r = requests.put(f"{TRELLO_API}{path}", data=data, timeout=30)
    r.raise_for_status()
    return r.json()


def get_cards(list_id: str, limit: int = 10) -> List[TrelloCard]:
    cards = trello_get(f"/lists/{list_id}/cards", params={"fields": "name,desc,shortLink,url,idList"})
    out: List[TrelloCard] = []
    for c in cards[:limit]:
        out.append(
            TrelloCard(
                id=c["id"],
                name=c.get("name", ""),
                desc=c.get("desc", "") or "",
                shortLink=c.get("shortLink", ""),
                url=c.get("url", ""),
                idList=c.get("idList", list_id),
            )
        )
    return out


def move_card(card_id: str, list_id: str) -> None:
    trello_put(f"/cards/{card_id}", data={"idList": list_id})


def add_comment(card_id: str, text: str) -> None:
    trello_post(f"/cards/{card_id}/actions/comments", data={"text": text})


# -----------------------------
# CrewAI tools
# -----------------------------

@tool("shell")
def shell(cmd: str) -> str:
    """Executes a shell command in repo root (git/pytest/ruff/black/gh). Returns output."""
    rc, out = _run(cmd)
    return _require_ok(rc, out, f"shell: {cmd}")


@tool("trello_get_cards")
def trello_get_cards(list_id: str, limit: int = 5) -> str:
    """Get cards from a Trello list. Returns JSON array with id,name,desc,shortLink,url,idList."""
    cards = get_cards(list_id, limit=limit)
    return json.dumps([c.__dict__ for c in cards], ensure_ascii=False, indent=2)


@tool("trello_move_card")
def trello_move_card(card_id: str, list_id: str) -> str:
    """Move a Trello card to another list."""
    move_card(card_id, list_id)
    return f"OK moved {card_id} -> {list_id}"


@tool("trello_add_comment")
def trello_add_comment(card_id: str, text: str) -> str:
    """Add a comment to a Trello card."""
    add_comment(card_id, text)
    return "OK comment added"


# -----------------------------
# Agents
# -----------------------------

dev = Agent(
    role="Senior Python Developer",
    goal="Pick one Trello ToDo card, implement it safely, run tests, push branch, and move card to Review.",
    backstory=(
        "You are a careful maintainer. You keep diffs small and always run tests. "
        "You never start a new task until the current card is moved to Review."
    ),
    tools=[shell, trello_get_cards, trello_move_card, trello_add_comment],
    allow_delegation=False,
    verbose=True,
)

reviewer = Agent(
    role="Code Reviewer",
    goal="Review cards in Review list: either request changes (move back to ToDo with clear comments) or approve (move to MadePR).",
    backstory="You are strict but fair. You prioritize correctness, tests, and maintainability.",
    tools=[shell, trello_get_cards, trello_move_card, trello_add_comment],
    allow_delegation=False,
    verbose=True,
)

pr_agent = Agent(
    role="PR Creator",
    goal="For approved cards in MadePR list, create a PR using gh, comment the PR URL, then move card to Success.",
    backstory="You write clean PR titles/bodies and include testing evidence.",
    tools=[shell, trello_get_cards, trello_move_card, trello_add_comment],
    allow_delegation=False,
    verbose=True,
)


# -----------------------------
# Task templates (single-run processing)
# -----------------------------

DEV_TASK = Task(
    description=textwrap.dedent(
        f"""
        You will process exactly ONE Trello card from the ToDo list.

        Steps:
        1) Use trello_get_cards(list_id="{LIST_TODO}", limit=1) to pick the top card.
        2) Read the card name + desc. Treat desc as requirements.
        3) Create a new git branch named: ai/<shortLink>-<slugified-title>
        4) Implement the changes in this repo. Keep diffs minimal.
        5) Run tests:
           - If this is a Python repo, run: pytest -q (if pytest exists).
           - If ruff exists, run: ruff check .
           - If black exists, run: black .
        6) Commit with message: "feat/fix: <short title> (trello:<shortLink>)"
        7) Push the branch to origin.
        8) Add a Trello comment with:
           - Branch name
           - What changed
           - Test commands + results
        9) Move the card to Review list id="{LIST_REVIEW}".

        Constraints:
        - Do NOT modify more than 6 files unless truly necessary (explain in Trello comment).
        - Do NOT skip tests unless there are none; if none, say so explicitly.
        """
    ).strip(),
    agent=dev,
    expected_output="Card moved to Review with branch pushed and tests run.",
)

REVIEW_TASK = Task(
    description=textwrap.dedent(
        f"""
        You will process exactly ONE Trello card from the Review list.

        Steps:
        1) Use trello_get_cards(list_id="{LIST_REVIEW}", limit=1)
        2) Read the latest Trello comments (you cannot fetch them here), so infer needed info from:
           - card desc
           - and by inspecting git: list local branches, fetch, and locate branch name in recent commits.
           Suggested commands:
             - git fetch --all
             - git branch -a
             - git log --oneline -20
             - git show --name-only --oneline -1
           If you can’t confidently find the branch, ask for it by commenting on the card and move it back to ToDo.
        3) Checkout the branch and review diff vs base.
           - Detect base branch via: gh repo view --json defaultBranchRef --jq .defaultBranchRef.name
           - Then: git diff <base>...HEAD
        4) Run tests if available (pytest -q).
        5) Decision:
           A) If changes required:
              - Add Trello comment: "Needs changes:" + bullet list of exact fixes
              - Move card back to ToDo id="{LIST_TODO}"
           B) If approved:
              - Add Trello comment: "LGTM ✅ Ready for PR"
              - Move card to MadePR id="{LIST_MADEPR}"

        Be precise. If rejecting, give concrete instructions.
        """
    ).strip(),
    agent=reviewer,
    expected_output="Card moved either back to ToDo with clear comments or to MadePR with approval.",
)

PR_TASK = Task(
    description=textwrap.dedent(
        f"""
        You will process exactly ONE Trello card from the MadePR list and create a PR via GitHub CLI.

        Steps:
        1) Use trello_get_cards(list_id="{LIST_MADEPR}", limit=1)
        2) Find and checkout the corresponding branch (same approach as reviewer):
           - git fetch --all
           - git log --oneline -30 (look for trello:<shortLink>)
        3) Determine base branch:
           - gh repo view --json defaultBranchRef --jq .defaultBranchRef.name
        4) Create PR:
           - Title: use card name
           - Body: include:
             - What / Why
             - Summary of changes (3-6 bullets)
             - Testing evidence (commands + results)
             - Trello link (card url)
           Command:
             gh pr create --title "<TITLE>" --body "<BODY>" --base <BASE>
        5) Add Trello comment with PR URL.
        6) Move card to Success id="{LIST_SUCCESS}"

        If PR already exists, comment the existing PR URL and still move to Success.
        """
    ).strip(),
    agent=pr_agent,
    expected_output="PR created (or found) and card moved to Success with PR link commented.",
)

# -----------------------------
# Runner: process a few cards per run
# -----------------------------

def _has_any_cards(list_id: str) -> bool:
    return len(get_cards(list_id, limit=1)) > 0


def preflight() -> None:
    # Ensure we're in git repo and gh auth works
    rc, out = _run("git rev-parse --is-inside-work-tree")
    if rc != 0 or "true" not in out:
        raise SystemExit(f"Not inside a git repo at {REPO_ROOT}\n{out}")
    rc, out = _run("gh auth status")
    if rc != 0:
        raise SystemExit(f"gh is not authenticated:\n{out}")


def main() -> None:
    preflight()
    base = _detect_base_branch()
    print(f"Repo root: {REPO_ROOT}")
    print(f"Base branch: {base}")
    print(f"Max cards per run: {MAX_CARDS_PER_RUN}\n")

    crew_dev = Crew(agents=[dev], tasks=[DEV_TASK], verbose=True)
    crew_review = Crew(agents=[reviewer], tasks=[REVIEW_TASK], verbose=True)
    crew_pr = Crew(agents=[pr_agent], tasks=[PR_TASK], verbose=True)

    processed = 0

    # Phase 1: ToDo -> Review (dev)
    while processed < MAX_CARDS_PER_RUN and _has_any_cards(LIST_TODO):
        print("\n=== DEV PHASE: ToDo -> Review ===")
        res = crew_dev.kickoff()
        print(res)
        processed += 1
        time.sleep(1)

    # Phase 2: Review -> (ToDo or MadePR)
    processed = 0
    while processed < MAX_CARDS_PER_RUN and _has_any_cards(LIST_REVIEW):
        print("\n=== REVIEW PHASE: Review -> ToDo/MadePR ===")
        res = crew_review.kickoff()
        print(res)
        processed += 1
        time.sleep(1)

    # Phase 3: MadePR -> Success (PR create)
    processed = 0
    while processed < MAX_CARDS_PER_RUN and _has_any_cards(LIST_MADEPR):
        print("\n=== PR PHASE: MadePR -> Success ===")
        res = crew_pr.kickoff()
        print(res)
        processed += 1
        time.sleep(1)

    print("\nDone.")


if __name__ == "__main__":
    main()