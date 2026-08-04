#!/usr/bin/env python3
"""Generate local SVG assets for the GitHub profile README."""

from __future__ import annotations

import datetime as dt
import html
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
USERNAME = os.getenv("PROFILE_USERNAME", "cslsolow")

BG = "#0b1220"
PANEL = "#111827"
BORDER = "#334155"
TEXT = "#e2e8f0"
MUTED = "#94a3b8"
SOFT = "#cbd5e1"
ACCENT = "#9fb3c8"


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def get_token() -> str:
    token = os.getenv("GITHUB_TOKEN")
    if token:
        return token

    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return ""


def graphql(query: str, variables: dict[str, object], token: str) -> dict[str, object]:
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required to query GitHub GraphQL API")

    payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    request = urllib.request.Request(
        "https://api.github.com/graphql",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "cslsolow-profile-assets",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API failed: HTTP {error.code}: {details}") from error

    if body.get("errors"):
        raise RuntimeError(json.dumps(body["errors"], ensure_ascii=False))
    return body["data"]


def fetch_profile_data(token: str) -> dict[str, object]:
    profile_query = """
    query($login: String!) {
      user(login: $login) {
        login
        name
        createdAt
        followers { totalCount }
        following { totalCount }
        contributionsCollection {
          contributionCalendar {
            totalContributions
            weeks {
              contributionDays {
                color
                contributionCount
                date
                weekday
              }
            }
          }
          totalCommitContributions
          totalIssueContributions
          totalPullRequestContributions
          totalPullRequestReviewContributions
          totalRepositoryContributions
        }
      }
    }
    """

    repos_query = """
    query($login: String!, $cursor: String) {
      user(login: $login) {
        repositories(
          first: 100
          after: $cursor
          ownerAffiliations: OWNER
          privacy: PUBLIC
          orderBy: {field: UPDATED_AT, direction: DESC}
        ) {
          totalCount
          pageInfo {
            hasNextPage
            endCursor
          }
          nodes {
            name
            description
            forkCount
            isFork
            pushedAt
            stargazerCount
            primaryLanguage {
              name
              color
            }
          }
        }
      }
    }
    """

    data = graphql(profile_query, {"login": USERNAME}, token)
    user = data["user"]
    if user is None:
        raise RuntimeError(f"GitHub user not found: {USERNAME}")

    repos: list[dict[str, object]] = []
    cursor = None
    total_repos = 0
    while True:
        repo_data = graphql(repos_query, {"login": USERNAME, "cursor": cursor}, token)
        connection = repo_data["user"]["repositories"]
        total_repos = int(connection["totalCount"])
        repos.extend(connection["nodes"])
        page_info = connection["pageInfo"]
        if not page_info["hasNextPage"]:
            break
        cursor = page_info["endCursor"]

    user["repositories"] = {"totalCount": total_repos, "nodes": repos}
    return user


def calendar_days(profile: dict[str, object]) -> list[dict[str, object]]:
    collection = profile["contributionsCollection"]
    calendar = collection["contributionCalendar"]
    days: list[dict[str, object]] = []
    for week in calendar["weeks"]:
        days.extend(week["contributionDays"])
    return sorted(days, key=lambda day: str(day["date"]))


def streaks(days: list[dict[str, object]]) -> tuple[int, int, int, dict[str, object]]:
    longest = 0
    running = 0
    active_days = 0
    best_day = {"date": "n/a", "contributionCount": 0}

    for day in days:
        count = int(day["contributionCount"])
        if count > int(best_day["contributionCount"]):
            best_day = day
        if count > 0:
            active_days += 1
            running += 1
            longest = max(longest, running)
        else:
            running = 0

    current = 0
    for day in reversed(days):
        if int(day["contributionCount"]) <= 0:
            break
        current += 1

    return active_days, longest, current, best_day


def heat_color(count: int) -> str:
    if count <= 0:
        return "#111827"
    if count <= 2:
        return "#1e293b"
    if count <= 5:
        return "#334155"
    if count <= 10:
        return "#64748b"
    return "#cbd5e1"


def svg_header(width: int, height: int) -> str:
    return f"""<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" fill="none" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="{width}" y2="{height}" gradientUnits="userSpaceOnUse">
      <stop stop-color="{BG}"/>
      <stop offset="0.58" stop-color="#111827"/>
      <stop offset="1" stop-color="#172033"/>
    </linearGradient>
  </defs>
  <rect width="{width}" height="{height}" rx="8" fill="url(#bg)"/>
  <rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="7.5" stroke="{BORDER}"/>
"""


def svg_footer() -> str:
    return "</svg>\n"


def stat_card(x: int, y: int, width: int, label: str, value: object, sub: str) -> str:
    return f"""  <rect x="{x}" y="{y}" width="{width}" height="82" rx="8" fill="{PANEL}" stroke="{BORDER}"/>
  <text x="{x + 18}" y="{y + 28}" fill="{MUTED}" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" font-size="13">{esc(label)}</text>
  <text x="{x + 18}" y="{y + 58}" fill="{TEXT}" font-family="Inter, system-ui, sans-serif" font-size="26" font-weight="700">{esc(value)}</text>
  <text x="{x + width - 18}" y="{y + 58}" fill="{ACCENT}" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" font-size="12" text-anchor="end">{esc(sub)}</text>
"""


def render_contribution_console(profile: dict[str, object]) -> str:
    width, height = 1000, 330
    days = calendar_days(profile)
    active_days, longest, current, best_day = streaks(days)
    calendar = profile["contributionsCollection"]["contributionCalendar"]
    updated = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M UTC+8")

    svg = svg_header(width, height)
    svg += f"""  <text x="32" y="46" fill="{TEXT}" font-family="Inter, system-ui, sans-serif" font-size="28" font-weight="800">Contribution Console</text>
  <text x="32" y="72" fill="{MUTED}" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" font-size="13">local SVG generated from GitHub API · {esc(updated)}</text>
  <text x="945" y="46" fill="{ACCENT}" font-family="Inter, system-ui, sans-serif" font-size="22" text-anchor="end">雪</text>
"""
    svg += stat_card(32, 98, 220, "total contributions", int(calendar["totalContributions"]), "1y")
    svg += stat_card(272, 98, 220, "active days", active_days, f"{active_days}/365")
    svg += stat_card(512, 98, 220, "longest streak", longest, "days")
    svg += stat_card(752, 98, 216, "current streak", current, "days")

    svg += f"""  <text x="32" y="216" fill="{SOFT}" font-family="Inter, system-ui, sans-serif" font-size="16" font-weight="700">Annual trace</text>
  <text x="968" y="216" fill="{MUTED}" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" font-size="12" text-anchor="end">best day: {esc(best_day["date"])} · {esc(best_day["contributionCount"])} commits/events</text>
"""

    cell = 10
    gap = 3
    x0 = 36
    y0 = 236
    weeks = profile["contributionsCollection"]["contributionCalendar"]["weeks"]
    for week_index, week in enumerate(weeks):
        for day in week["contributionDays"]:
            x = x0 + week_index * (cell + gap)
            y = y0 + int(day["weekday"]) * (cell + gap)
            count = int(day["contributionCount"])
            svg += f'  <rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2" fill="{heat_color(count)}"><title>{esc(day["date"])}: {count} contributions</title></rect>\n'

    legend_x = 830
    svg += f"""  <text x="{legend_x}" y="260" fill="{MUTED}" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" font-size="12">less</text>
"""
    for index, color in enumerate(["#111827", "#1e293b", "#334155", "#64748b", "#cbd5e1"]):
        svg += f'  <rect x="{legend_x + 42 + index * 18}" y="250" width="10" height="10" rx="2" fill="{color}" stroke="{BORDER}"/>\n'
    svg += f'  <text x="{legend_x + 140}" y="260" fill="{MUTED}" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" font-size="12">more</text>\n'
    return svg + svg_footer()


def language_mix(repos: list[dict[str, object]]) -> list[tuple[str, int, str]]:
    counts: Counter[str] = Counter()
    colors: dict[str, str] = {}
    for repo in repos:
        if repo.get("isFork"):
            continue
        language = repo.get("primaryLanguage")
        if not language:
            continue
        name = str(language["name"])
        counts[name] += 1
        colors[name] = str(language.get("color") or ACCENT)

    if not counts:
        return [("Markdown", 1, ACCENT)]
    return [(name, count, colors[name]) for name, count in counts.most_common(5)]


def render_language_console(profile: dict[str, object]) -> str:
    width, height = 490, 220
    repos = profile["repositories"]["nodes"]
    languages = language_mix(repos)
    total = sum(count for _, count, _ in languages)

    svg = svg_header(width, height)
    svg += f"""  <text x="26" y="42" fill="{TEXT}" font-family="Inter, system-ui, sans-serif" font-size="22" font-weight="800">Code Language Mix</text>
  <text x="26" y="66" fill="{MUTED}" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" font-size="12">primary languages across public source repos</text>
"""

    y = 92
    for name, count, color in languages:
        percentage = int(round(count / total * 100))
        bar_width = max(8, int(300 * count / total))
        svg += f"""  <text x="28" y="{y}" fill="{SOFT}" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" font-size="13">{esc(name)}</text>
  <rect x="150" y="{y - 11}" width="300" height="10" rx="5" fill="#1e293b"/>
  <rect x="150" y="{y - 11}" width="{bar_width}" height="10" rx="5" fill="{esc(color)}"/>
  <text x="464" y="{y}" fill="{MUTED}" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" font-size="12" text-anchor="end">{percentage}%</text>
"""
        y += 27
    return svg + svg_footer()


def render_repository_console(profile: dict[str, object]) -> str:
    width, height = 490, 220
    repos = [repo for repo in profile["repositories"]["nodes"] if not repo.get("isFork")]
    total_repos = int(profile["repositories"]["totalCount"])
    stars = sum(int(repo["stargazerCount"]) for repo in repos)
    forks = sum(int(repo["forkCount"]) for repo in repos)
    recent = sorted(repos, key=lambda repo: str(repo.get("pushedAt") or ""), reverse=True)[:4]

    svg = svg_header(width, height)
    svg += f"""  <text x="26" y="42" fill="{TEXT}" font-family="Inter, system-ui, sans-serif" font-size="22" font-weight="800">Repository Console</text>
  <text x="26" y="66" fill="{MUTED}" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" font-size="12">public source work, not third-party badges</text>
"""
    svg += stat_card(26, 86, 136, "repos", total_repos, "public")
    svg += stat_card(177, 86, 136, "stars", stars, "total")
    svg += stat_card(328, 86, 136, "forks", forks, "total")

    svg += f'  <text x="26" y="194" fill="{MUTED}" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" font-size="12">recent: </text>\n'
    names = " · ".join(str(repo["name"]) for repo in recent)
    if len(names) > 54:
        names = names[:51] + "..."
    svg += f'  <text x="82" y="194" fill="{SOFT}" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" font-size="12">{esc(names)}</text>\n'
    return svg + svg_footer()


def write_assets(profile: dict[str, object]) -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    files = {
        "contribution-console.svg": render_contribution_console(profile),
        "language-console.svg": render_language_console(profile),
        "repository-console.svg": render_repository_console(profile),
    }

    for filename, content in files.items():
        (ASSETS / filename).write_text(content, encoding="utf-8")
        print(f"wrote assets/{filename}")


def main() -> int:
    token = get_token()
    try:
        profile = fetch_profile_data(token)
    except Exception as error:
        print(f"failed to fetch GitHub data: {error}", file=sys.stderr)
        return 1

    write_assets(profile)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
