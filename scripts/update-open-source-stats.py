#!/usr/bin/env python3
"""Update the auto-generated stats line in the Open Source section.

Counts merged pull requests authored by the profile owner and the distinct
repositories those PRs were merged into. Only public repositories are visible
to the Search API, so private contributions are not counted.

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
from datetime import datetime
from pathlib import Path

README = Path(__file__).resolve().parent.parent / "README.md"
START = "<!-- OPEN-SOURCE-STATS:START -->"
END = "<!-- OPEN-SOURCE-STATS:END -->"
SEARCH_API = "https://api.github.com/search/issues"


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


def build_stats_line(total: int, items: list[dict]) -> str:
    projects = {
        item["repository_url"].rsplit("/repos/", 1)[-1]
        for item in items
        if item.get("repository_url", "").rsplit("/repos/", 1)[-1]
    }
    project_count = len(projects)

    merged_dates: list[datetime] = []
    for item in items:
        merged_at = (item.get("pull_request") or {}).get("merged_at")
        if merged_at:
            try:
                merged_dates.append(
                    datetime.fromisoformat(merged_at.replace("Z", "+00:00"))
                )
            except ValueError:
                pass

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

    stats_line = build_stats_line(total, items)
    content = README.read_text(encoding="utf-8")
    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.DOTALL)
    if not pattern.search(content):
        print(f"Markers not found in {README}", file=sys.stderr)
        return 1

    updated = pattern.sub(f"{START}\n{stats_line}\n{END}", content, count=1)
    if updated == content:
        print(f"Stats unchanged: {stats_line}")
        return 0

    README.write_text(updated, encoding="utf-8")
    print(f"Stats updated: {stats_line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
