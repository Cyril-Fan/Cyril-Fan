"""Generate profile cards from the owner's public GitHub data; no dependencies."""

import json
import os
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from urllib.request import Request, urlopen


QUERY = """
query Profile($login: String!, $after: String) {
  user(login: $login) {
    followers { totalCount }
    contributionsCollection {
      contributionCalendar { totalContributions }
    }
    repositories(first: 100, after: $after, privacy: PUBLIC, ownerAffiliations: [OWNER]) {
      totalCount
      nodes { stargazerCount }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""


def fetch_stats(login, token):
    after = None
    stars = 0
    while True:
        payload = json.dumps({"query": QUERY, "variables": {"login": login, "after": after}}).encode()
        request = Request(
            "https://api.github.com/graphql",
            data=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": "github-profile-stats",
            },
        )
        with urlopen(request, timeout=30) as response:
            result = json.load(response)
        if result.get("errors"):
            raise RuntimeError("GitHub GraphQL returned errors: " + json.dumps(result["errors"]))
        user = result["data"]["user"]
        if user is None:
            raise RuntimeError(f"GitHub user {login!r} was not found")
        repos = user["repositories"]
        stars += sum(repo["stargazerCount"] for repo in repos["nodes"])
        if not repos["pageInfo"]["hasNextPage"]:
            return [
                ("Repositories", repos["totalCount"], "Public repositories"),
                ("Stars", stars, "Across public repositories"),
                ("Followers", user["followers"]["totalCount"], "GitHub community"),
                ("Contributions", user["contributionsCollection"]["contributionCalendar"]["totalContributions"], "In the past year"),
            ]
        after = repos["pageInfo"]["endCursor"]


ICONS = [
    '<path d="M4 3h13a2 2 0 0 1 2 2v16H6a3 3 0 0 1-3-3V6a3 3 0 0 1 3-3m-3 15a3 3 0 0 1 3-3h13M8 7h7"/>',
    '<path d="m12 2 3.1 6.3L22 9.3l-5 4.9 1.2 6.8-6.2-3.2L5.8 21 7 14.2 2 9.3l6.9-1z"/>',
    '<circle cx="9" cy="7" r="3"/><path d="M2 21v-3a7 7 0 0 1 14 0v3m1-17a3 3 0 0 1 0 6m3 11v-3a7 7 0 0 0-3-5"/>',
    '<path d="M3 19V9m6 10V4m6 15v-7m6 7V2"/>',
]


def make_svg(login, stats, updated, dark=False):
    # Transparent backgrounds follow the host page, including Soft dark.
    bg, border, text, muted = ("none", "#3d444d", "#f0f6fc", "#9198a1") if dark else ("none", "#d1d9e0", "#1f2328", "#59636e")
    blue, green = ("#4493f8", "#3fb950") if dark else ("#0969da", "#1a7f37")
    summary = "; ".join(f"{label}: {value}" for label, value, _ in stats)
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="840" height="166" viewBox="0 0 840 166" role="img" aria-labelledby="title desc">',
        f'<title id="title">{escape(login)} on GitHub</title>',
        f'<desc id="desc">{escape(summary)}. Updated {escape(updated)}.</desc>',
        '<g font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">',
    ]
    for i, (label, value, detail) in enumerate(stats):
        x = 1 + i * 212
        accent = blue if i % 2 == 0 else green
        parts.extend([
            f'<g transform="translate({x},1)">',
            f'<rect width="202" height="132" rx="10" fill="{bg}" stroke="{border}"/>',
            f'<g transform="translate(18,18)" fill="none" stroke="{accent}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">{ICONS[i]}</g>',
            f'<text x="52" y="35" font-size="14" font-weight="600" fill="{text}">{escape(label)}</text>',
            f'<text x="18" y="82" font-size="34" font-weight="650" fill="{accent}">{value:,}</text>',
            f'<text x="18" y="110" font-size="11" fill="{muted}">{escape(detail)}</text>',
            '</g>',
        ])
    parts.extend([
        f'<text x="839" y="157" text-anchor="end" font-size="10" fill="{muted}">Public GitHub data · Updated {escape(updated)} UTC</text>',
        '</g></svg>\n',
    ])
    return "\n".join(parts)


def main():
    login = os.environ.get("PROFILE_USER") or os.environ["GITHUB_REPOSITORY_OWNER"]
    stats = fetch_stats(login, os.environ["GITHUB_TOKEN"])
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assets = Path(__file__).resolve().parents[1] / "assets"
    assets.mkdir(exist_ok=True)
    for dark, filename in [(False, "github-stats.svg"), (True, "github-stats-dark.svg")]:
        (assets / filename).write_text(make_svg(login, stats, updated, dark), encoding="utf-8")
    print(f"Updated public statistics for {login}: " + ", ".join(f"{label}={value}" for label, value, _ in stats))


if __name__ == "__main__":
    main()
