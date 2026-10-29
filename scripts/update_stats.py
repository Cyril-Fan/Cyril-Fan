"""Generate profile cards from the owner's public GitHub data; no dependencies."""

import json
import os
import re
import sys
from hashlib import sha256
from datetime import date, datetime, timedelta, timezone
from html import escape
from pathlib import Path
from urllib.request import Request, urlopen


QUERY = """
query Profile($login: String!) {
  user(login: $login) {
    followers { totalCount }
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount contributionLevel } }
      }
    }
  }
}
"""


def count(value):
    if type(value) is not int or not 0 <= value <= 9_007_199_254_740_991:
        raise ValueError('GitHub returned an invalid public count')
    return value


CONTRIBUTION_LEVELS = {
    'NONE': 0,
    'FIRST_QUARTILE': 1,
    'SECOND_QUARTILE': 2,
    'THIRD_QUARTILE': 3,
    'FOURTH_QUARTILE': 4,
}


def contribution_day(day):
    level = day.get('contributionLevel')
    if level not in CONTRIBUTION_LEVELS:
        raise ValueError('GitHub returned an invalid contribution color level')
    value = count(day['contributionCount'])
    if (value == 0) != (level == 'NONE'):
        raise ValueError('Contribution count and color level disagree')
    return {'date': day['date'], 'count': value, 'level': CONTRIBUTION_LEVELS[level]}


def calendar_hash(calendar):
    return sha256(json.dumps(calendar, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def fetch_public_repository_totals(login, token):
    """Count public repositories, rejecting an incomplete installation-scoped list."""
    headers = {
        'Accept': 'application/vnd.github+json',
        'Authorization': f'Bearer {token}',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'github-profile-stats',
        'Cache-Control': 'no-cache',
    }
    request = Request(f'https://api.github.com/users/{login}', headers=headers)
    with urlopen(request, timeout=30) as response:
        profile = json.load(response)
    if not isinstance(profile, dict) or not isinstance(profile.get('login'), str) or profile['login'].lower() != login.lower():
        raise ValueError('GitHub returned an invalid public profile')
    expected_repositories = count(profile.get('public_repos'))
    seen = set()
    stars = 0
    page = 1
    while True:
        request = Request(
            f'https://api.github.com/users/{login}/repos?type=owner&sort=full_name&per_page=100&page={page}',
            headers=headers,
        )
        with urlopen(request, timeout=30) as response:
            repositories = json.load(response)
        if not isinstance(repositories, list) or len(repositories) > 100:
            raise ValueError('GitHub returned an invalid public repository list')
        for repository in repositories:
            if not isinstance(repository, dict):
                raise ValueError('Invalid public repository entry')
            repository_id = count(repository.get('id'))
            owner = repository.get('owner')
            if (
                not isinstance(owner, dict)
                or not isinstance(owner.get('login'), str)
                or owner['login'].lower() != login.lower()
                or repository.get('private') is not False
                or repository_id in seen
            ):
                raise ValueError('Incomplete, duplicate or non-public owner repository list')
            seen.add(repository_id)
            stars += count(repository.get('stargazers_count'))
        if len(repositories) < 100:
            if len(seen) != expected_repositories:
                raise ValueError('Public repository list does not match the profile count')
            return len(seen), count(stars)
        page += 1


def fetch_snapshot(login, token):
    if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?', login):
        raise ValueError('Invalid GitHub login')
    payload = json.dumps({"query": QUERY, "variables": {"login": login}}).encode()
    request = Request(
        "https://api.github.com/graphql",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "github-profile-stats",
            "Cache-Control": "no-cache",
        },
    )
    with urlopen(request, timeout=30) as response:
        result = json.load(response)
    if result.get("errors"):
        raise RuntimeError("GitHub GraphQL returned errors: " + json.dumps(result["errors"]))
    user = result["data"]["user"]
    if user is None:
        raise RuntimeError(f"GitHub user {login!r} was not found")
    total_repositories, stars = fetch_public_repository_totals(login, token)
    calendar = user['contributionsCollection']['contributionCalendar']
    days = [
        contribution_day(day)
        for week in calendar['weeks'] for day in week['contributionDays']
    ]
    if not 350 <= len(days) <= 400:
        raise ValueError('Incomplete contribution calendar')
    start = date.fromisoformat(days[0]['date'])
    if any(day['date'] != (start + timedelta(days=i)).isoformat() for i, day in enumerate(days)):
        raise ValueError('Contribution dates must be valid, unique and consecutive')
    contributions = count(calendar['totalContributions'])
    if sum(day['count'] for day in days) != contributions:
        raise ValueError('Contribution total does not match daily activity')
    return {
        'login': login,
        'stats': [
            ['Repositories', total_repositories, 'Public repositories'],
            ['Stars', count(stars), 'Across public repositories'],
            ['Followers', count(user['followers']['totalCount']), 'GitHub community'],
            ['Contributions', contributions, 'In the past year'],
        ],
        'calendar': days,
    }


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


def refresh(root, login, token, force=False):
    # Finish fetching and validating before touching the last known good assets.
    snapshot = fetch_snapshot(login, token)
    assets = root / 'assets'
    assets.mkdir(exist_ok=True)
    state_file = assets / 'profile-data.json'
    try:
        previous = json.loads(state_file.read_text(encoding='utf-8'))
    except (FileNotFoundError, ValueError):
        previous = {}
    if not isinstance(previous, dict) or not isinstance(previous.get('updated'), str):
        previous = {}
    changed = force or any(previous.get(key) != value for key, value in snapshot.items())
    snake_changed = force or previous.get('snake_calendar_hash') != calendar_hash(snapshot['calendar']) or any(
        not (assets / filename).is_file() for filename in SNAKES
    )
    updated = previous.get('updated', '')
    if changed or any(not (assets / filename).is_file() for filename in CARDS):
        updated = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')
        for dark, filename in [(False, 'github-stats.svg'), (True, 'github-stats-dark.svg')]:
            (assets / filename).write_text(make_svg(login, snapshot['stats'], updated, dark), encoding='utf-8')
        state_file.write_text(json.dumps({
            **snapshot, 'updated': updated,
            'snake_calendar_hash': '' if force else previous.get('snake_calendar_hash', ''),
        }, indent=2) + '\n', encoding='utf-8')
    print(f"Checked public statistics for {login}: " + ", ".join(f"{label}={value}" for label, value, _ in snapshot['stats']))
    return snake_changed


CARDS = ['github-stats.svg', 'github-stats-dark.svg']
SNAKES = ['github-contribution-grid-snake.svg', 'github-contribution-grid-snake-dark.svg']
STATUS_START = '<!-- profile-sync:status:start -->'
STATUS_END = '<!-- profile-sync:status:end -->'


def publish_assets(root, include_snakes=True):
    """Publish cards immediately; acknowledge snake data only after successful rendering."""
    assets = root / 'assets'
    state = json.loads((assets / 'profile-data.json').read_text(encoding='utf-8'))
    readme_file = root / 'README.md'
    readme = readme_file.read_text(encoding='utf-8')
    base = f"https://raw.githubusercontent.com/{state['login']}/{state['login']}/main/assets/"
    for filename in CARDS + (SNAKES if include_snakes else []):
        version = sha256((assets / filename).read_bytes()).hexdigest()[:20]
        pattern = re.escape(base + filename) + r'(?:\?[^"\s<>]*)?'
        readme, replacements = re.subn(pattern, lambda _: base + filename + '?v=' + version, readme)
        if replacements != 1:
            raise ValueError(f'Expected one README image for {filename}; found {replacements}')
    status = (
        STATUS_START + '\n'
        f"<sub>Public-data snapshot · Updated {escape(state['updated'])} UTC · "
        f"[Scheduled checks every 5 minutes](https://github.com/{state['login']}/{state['login']}/actions/workflows/profile.yml). "
        'GitHub scheduling and caching can delay updates; this is not a live counter.</sub>\n'
        + STATUS_END
    )
    if STATUS_START in readme or STATUS_END in readme:
        if readme.count(STATUS_START) != 1 or readme.count(STATUS_END) != 1:
            raise ValueError('Invalid profile status markers')
        readme = re.sub(re.escape(STATUS_START) + r'.*?' + re.escape(STATUS_END), lambda _: status, readme, flags=re.S)
    else:
        readme = readme.replace('## 📊 GitHub Stats', '## 📊 GitHub Stats\n\n' + status, 1)
    readme_file.write_text(readme, encoding='utf-8')
    if include_snakes:
        state['snake_calendar_hash'] = calendar_hash(state['calendar'])
        (assets / 'profile-data.json').write_text(json.dumps(state, indent=2) + '\n', encoding='utf-8')


def main():
    root = Path(__file__).resolve().parents[1]
    if sys.argv[1:] in (['--publish'], ['--publish-cards']):
        publish_assets(root, include_snakes=sys.argv[1:] == ['--publish'])
        return
    if sys.argv[1:]:
        raise ValueError('Supported options: --publish, --publish-cards')
    login = os.environ.get('PROFILE_USER') or os.environ['GITHUB_REPOSITORY_OWNER']
    snake_changed = refresh(root, login, os.environ['GITHUB_TOKEN'], os.environ.get('FORCE_PROFILE_REFRESH') == 'true')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
            output.write(f'snake_changed={str(snake_changed).lower()}\n')


if __name__ == "__main__":
    main()


