#!/usr/bin/env python3
"""Update the auto-generated Open Source stats and project cards.

Counts merged pull requests authored by the profile owner, and renders one
repository card per project those PRs were merged into. Only public
repositories are visible to the Search API, so private contributions are not
counted.

Environment:
  USERNAME       GitHub login to inspect (defaults to GITHUB_REPOSITORY_OWNER)
  GITHUB_TOKEN   token used for the Search API (optional locally)
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

README = Path(__file__).resolve().parent.parent / "README.md"
STATS_START = "<!-- OPEN-SOURCE-STATS:START -->"
STATS_END = "<!-- OPEN-SOURCE-STATS:END -->"
CARDS_START = "<!-- OPEN-SOURCE-CARDS:START -->"
CARDS_END = "<!-- OPEN-SOURCE-CARDS:END -->"
SEARCH_API = "https://api.github.com/search/issues"

CARD_BASE = "https://github-readme-stats.vercel.app/api/pin/"
CARD_PARAMS = (
    "show_owner=true&card_width=400&border_radius=14"
    "&description_lines_count=1&cache_seconds=21600"
)
CARD_DARK = (
    "bg_color=0B1020&title_color=F8FAFC&text_color=CBD5E1"
    "&icon_color=7DD3FC&border_color=1E293B"
)
CARD_LIGHT = (
    "bg_color=FFFFFF&title_color=082F49&text_color=475569"
    "&icon_color=0284C7&border_color=E2E8F0"
)


def _get(url: str, token: str) -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "open-source-stats-action",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def fetch_merged_prs(username: str, token: str) -> tuple[int, list[dict]]:
    query = f"author:{username} is:pr is:merged"
    items: list[dict] = []
    total = 0

    for page in range(1, 11):  # Search API exposes at most 1000 results
        params = urllib.parse.urlencode(
            {
                "q": query,
                "sort": "updated",
                "order": "desc",
                "per_page": 100,
                "page": page,
            }
        )
        data = _get(f"{SEARCH_API}?{params}", token)
        total = data.get("total_count", 0)
        batch = data.get("items", [])
        items.extend(batch)
        if len(batch) < 100 or len(items) >= total:
            break

    return total, items


def _merged_at(item: dict) -> datetime | None:
    value = (item.get("pull_request") or {}).get("merged_at")
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _repo_full_name(item: dict) -> str | None:
    marker = "/repos/"
    url = item.get("repository_url", "")
    if marker not in url:
        return None
    full = url.split(marker, 1)[1].strip("/")
    return full or None


def build_projects(items: list[dict]) -> list[tuple[str, datetime | None]]:
    projects: dict[str, datetime | None] = {}
    for item in items:
        full = _repo_full_name(item)
        if not full:
            continue
        when = _merged_at(item)
        if full not in projects:
            projects[full] = when
        elif when and (projects[full] is None or when > projects[full]):
            projects[full] = when

    epoch = datetime.min.replace(tzinfo=timezone.utc)
    return sorted(projects.items(), key=lambda pair: (pair[1] or epoch, pair[0]), reverse=True)


def build_stats_line(total: int, projects: list[tuple[str, datetime | None]]) -> str:
    project_count = len(projects)
    merged_dates = [when for _, when in projects if when]

    if total == 0:
        text = "No merged pull requests yet."
    else:
        pr_word = "pull request" if total == 1 else "pull requests"
        text = f"<strong>{total}</strong> merged {pr_word}"
        if project_count:
            project_word = "project" if project_count == 1 else "projects"
            text += f" across <strong>{project_count}</strong> {project_word}"
        if merged_dates:
            text += f" · latest {max(merged_dates).strftime('%b %Y')}"

    return f'<p align="center"><sub>{text}</sub></p>'


def _card_html(full: str) -> str:
    base = (
        f"{CARD_BASE}?username={full.split('/', 1)[0]}"
        f"&repo={full.split('/', 1)[1]}&{CARD_PARAMS}"
    )
    return (
        f'  <a href="https://github.com/{full}">\n'
        f"    <picture>\n"
        f'      <source media="(prefers-color-scheme: dark)" srcset="{base}&{CARD_DARK}" />\n'
        f'      <img alt="{full}" src="{base}&{CARD_LIGHT}" width="400" />\n'
        f"    </picture>\n"
        f"  </a>"
    )


def build_cards(projects: list[tuple[str, datetime | None]]) -> str:
    if not projects:
        return '<p align="center"><sub>No merged pull requests yet.</sub></p>'

    rows: list[str] = []
    for index in range(0, len(projects), 2):
        cards = [_card_html(full) for full, _ in projects[index : index + 2]]
        body = "\n  &nbsp;&nbsp;\n".join(cards)
        rows.append(f'<p align="center">\n{body}\n</p>')
    return "\n\n".join(rows)


def _replace_block(content: str, start: str, end: str, body: str) -> str:
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
    if not pattern.search(content):
        raise ValueError(f"markers not found: {start} / {end}")
    return pattern.sub(lambda _match: f"{start}\n{body}\n{end}", content, count=1)


def main() -> int:
    username = os.environ.get("USERNAME") or os.environ.get("GITHUB_REPOSITORY_OWNER")
    if not username:
        print("USERNAME is not set", file=sys.stderr)
        return 1

    token = os.environ.get("GITHUB_TOKEN", "")
    try:
        total, items = fetch_merged_prs(username, token)
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        print(f"GitHub API error {error.code}: {body}", file=sys.stderr)
        return 1
    except urllib.error.URLError as error:
        print(f"GitHub API request failed: {error.reason}", file=sys.stderr)
        return 1

    projects = build_projects(items)
    stats_line = build_stats_line(total, projects)
    cards = build_cards(projects)

    content = README.read_text(encoding="utf-8")
    try:
        updated = _replace_block(content, STATS_START, STATS_END, stats_line)
        updated = _replace_block(updated, CARDS_START, CARDS_END, cards)
    except ValueError as error:
        print(f"{error} in {README}", file=sys.stderr)
        return 1

    if updated == content:
        print("Open Source section unchanged.")
        return 0

    README.write_text(updated, encoding="utf-8")
    print(f"Open Source section updated ({total} PRs, {len(projects)} projects).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
