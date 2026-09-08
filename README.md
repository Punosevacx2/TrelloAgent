# Agenti — AI-Powered Trello Kanban Autopilot

An autonomous development pipeline that uses **CrewAI** agents to process Trello cards end-to-end: from picking up a task to writing code, reviewing it, and opening a GitHub pull request — all without manual intervention.

---

## Overview

Agenti connects your Trello board to your Git repository and drives cards through a four-stage Kanban pipeline using three specialized AI agents:

```
ToDo  -->  Review  -->  MadePR  -->  Success
```

| Stage | Agent | Action |
|-------|-------|--------|
| **ToDo → Review** | Senior Python Developer | Reads the card, implements the task, commits & pushes a branch, moves card to Review |
| **Review → MadePR / ToDo** | Code Reviewer | Checks the diff for correctness and scope; approves (MadePR) or rejects with comments (back to ToDo) |
| **MadePR → Success** | PR Creator | Opens a GitHub PR via `gh`, comments the PR URL on the card, moves card to Success |

---

## Requirements

- Python 3.10+
- [GitHub CLI](https://cli.github.com/) (`gh`) — authenticated via `gh auth login`
- A Trello board with four lists: **ToDo**, **Review**, **MadePR**, **Success**
- Trello API key and token

### Python dependencies

```bash
pip install crewai crewai-tools requests python-dotenv
```

---

## Setup

### 1. Clone the repository

```bash
git clone <repo-url>
cd agenti
```

### 2. Create a virtual environment

```bash
python -m venv venv312
source venv312/bin/activate
pip install crewai crewai-tools requests python-dotenv
```

### 3. Authenticate GitHub CLI

```bash
gh auth login
```

### 4. Configure environment variables

Create a `.env` file in the project root:

```env
# Trello credentials
TRELLO_KEY=your_trello_api_key
TRELLO_TOKEN=your_trello_token
TRELLO_BOARD_ID=your_board_id

# Trello list IDs
TRELLO_LIST_TODO=list_id_todo
TRELLO_LIST_REVIEW=list_id_review
TRELLO_LIST_MADEPR=list_id_madepr
TRELLO_LIST_SUCCESS=list_id_success

# Optional
DEFAULT_BASE_BRANCH=main
MAX_CARDS_PER_RUN=3
```

To get your Trello credentials, visit the [Trello Developer Portal](https://trello.com/power-ups/admin).
List IDs can be found via the Trello API: `GET /1/boards/{boardId}/lists`.

---

## Usage

```bash
python ai_trello_dev/run_board.py
```

The script will:
1. Process up to `MAX_CARDS_PER_RUN` cards from the **ToDo** list (dev phase)
2. Process up to `MAX_CARDS_PER_RUN` cards from the **Review** list (review phase)
3. Process up to `MAX_CARDS_PER_RUN` cards from the **MadePR** list (PR phase)

Each run is stateless — you can run it on a schedule (e.g. cron) or trigger it manually.

---

## Project Structure

```
agenti/
├── ai_trello_dev/
│   └── run_board.py      # Main entry point — agents, tasks, and pipeline runner
├── .env                  # Environment variables (not committed)
└── README.md
```

---

## How It Works

### Agents

- **Senior Python Developer** — picks one card from ToDo, creates a git branch (`ai/<shortLink>-<slug>`), implements the task, commits with a reference to the Trello card (`feat: <title> (trello:<shortLink>)`), pushes the branch, and moves the card to Review.

- **Code Reviewer** — fetches the branch, reviews the diff against the base branch, and decides: approve (→ MadePR) or reject with specific feedback comments (→ ToDo).

- **PR Creator** — finds the branch, creates a GitHub PR using `gh pr create`, posts the PR URL as a Trello comment, and moves the card to Success.

### Branch naming convention

```
ai/<trello-shortLink>-<slugified-card-title>
```

Example: `ai/Hyp6sTZr-add-user-authentication`

### Commit message convention

```
feat: <card title> (trello:<shortLink>)
```

---

## Configuration Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TRELLO_KEY` | Yes | — | Trello API key |
| `TRELLO_TOKEN` | Yes | — | Trello API token |
| `TRELLO_BOARD_ID` | Yes | — | Target Trello board ID |
| `TRELLO_LIST_TODO` | Yes | — | ID of the ToDo list |
| `TRELLO_LIST_REVIEW` | Yes | — | ID of the Review list |
| `TRELLO_LIST_MADEPR` | Yes | — | ID of the MadePR list |
| `TRELLO_LIST_SUCCESS` | Yes | — | ID of the Success list |
| `DEFAULT_BASE_BRANCH` | No | `main` | Fallback base branch if `gh` detection fails |
| `MAX_CARDS_PER_RUN` | No | `3` | Maximum cards processed per phase per run |

---

## License

MIT
