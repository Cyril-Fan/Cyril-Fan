import copy
import io
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import update_stats as stats


def response(followers=2):
    days = [
        {'date': (date(2025, 10, 20) + timedelta(days=i)).isoformat(), 'contributionCount': 0}
        for i in range(365)
    ]
    days[-1]['contributionCount'] = 6
    return {'data': {'user': {
        'followers': {'totalCount': followers},
        'contributionsCollection': {'contributionCalendar': {
            'totalContributions': 6, 'weeks': [{'contributionDays': days}],
        }},
        'repositories': {
            'totalCount': 2, 'nodes': [{'stargazerCount': 1}, {'stargazerCount': 0}],
            'pageInfo': {'hasNextPage': False, 'endCursor': None},
        },
    }}}


def replies(*values):
    return patch.object(stats, 'urlopen', side_effect=[io.BytesIO(json.dumps(value).encode()) for value in values])


class ProfileRefreshTests(unittest.TestCase):
    def setUp(self):
        sandbox = (Path(__file__).resolve().parents[1] / '.test-tmp').resolve()
        sandbox.mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=sandbox)
        self.root = Path(self.directory.name).resolve()
        if not self.root.is_relative_to(sandbox):
            raise RuntimeError('Test cleanup must stay inside this repository')
        self.addCleanup(self.directory.cleanup)
        (self.root / 'assets').mkdir()
        (self.root / 'README.md').write_text(
            (Path(__file__).resolve().parents[1] / 'README.md').read_text(encoding='utf-8'), encoding='utf-8'
        )
        for name in stats.SNAKES:
            (self.root / 'assets' / name).write_text('<svg/>', encoding='utf-8')

    def files(self):
        return {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob('*') if path.is_file()}

    def refresh(self, data, force=False):
        with replies(data):
            return stats.refresh(self.root, 'Cyril-Fan', 'test-token', force)

    def test_followers_two_to_three_updates_both_cards_and_cache_keys(self):
        self.refresh(response(2))
        stats.publish_assets(self.root)
        before = (self.root / 'README.md').read_text(encoding='utf-8')
        self.assertFalse(self.refresh(response(3)), 'A follower change should not regenerate the snake')
        stats.publish_assets(self.root)
        after = (self.root / 'README.md').read_text(encoding='utf-8')
        self.assertNotEqual(before, after)
        for name in stats.CARDS:
            self.assertIn('Followers: 3;', (self.root / 'assets' / name).read_text(encoding='utf-8'))
        for name in stats.CARDS + stats.SNAKES:
            version = stats.sha256((self.root / 'assets' / name).read_bytes()).hexdigest()[:20]
            self.assertIn(name + '?v=' + version, after)
        self.assertIn('not a live counter', after)
        self.assertEqual(after.count(stats.STATUS_START), 1)

    def test_no_data_change_does_not_rewrite_images_state_or_readme(self):
        self.refresh(response())
        stats.publish_assets(self.root)
        before = self.files()
        self.assertFalse(self.refresh(response()))
        stats.publish_assets(self.root)
        self.assertEqual(self.files(), before)

    def test_repository_stars_contributions_and_calendar_changes_all_refresh(self):
        self.refresh(response())
        updated = response()
        user = updated['data']['user']
        user['repositories']['totalCount'] = 3
        user['repositories']['nodes'].append({'stargazerCount': 4})
        calendar = user['contributionsCollection']['contributionCalendar']
        calendar['weeks'][0]['contributionDays'][-1]['contributionCount'] += 1
        calendar['totalContributions'] += 1
        self.assertTrue(self.refresh(updated))
        values = json.loads((self.root / 'assets/profile-data.json').read_text(encoding='utf-8'))['stats']
        self.assertEqual([row[1] for row in values], [3, 5, 2, 7])

    def test_snake_image_changes_also_change_its_readme_url(self):
        self.refresh(response())
        stats.publish_assets(self.root)
        before = (self.root / 'README.md').read_text(encoding='utf-8')
        (self.root / 'assets' / stats.SNAKES[0]).write_text('<svg>new animation</svg>', encoding='utf-8')
        stats.publish_assets(self.root)
        self.assertNotEqual(before, (self.root / 'README.md').read_text(encoding='utf-8'))

    def test_force_refresh_and_missing_animation_are_not_skipped(self):
        self.refresh(response())
        self.assertTrue(self.refresh(response(), force=True))
        (self.root / 'assets' / stats.SNAKES[0]).unlink()
        self.assertTrue(self.refresh(response()))

    def test_graphql_or_network_errors_preserve_the_last_good_snapshot(self):
        self.refresh(response())
        before = self.files()
        with replies({'errors': [{'message': 'Temporary upstream failure'}]}), self.assertRaises(RuntimeError):
            stats.refresh(self.root, 'Cyril-Fan', 'test-token')
        with patch.object(stats, 'urlopen', side_effect=TimeoutError), self.assertRaises(TimeoutError):
            stats.refresh(self.root, 'Cyril-Fan', 'test-token')
        self.assertEqual(self.files(), before)

    def test_invalid_counts_dates_and_incomplete_responses_cannot_publish_zeroes(self):
        self.refresh(response())
        before = self.files()
        invalid = []
        for value in [None, True, -1, 2.5, '3']:
            payload = response()
            payload['data']['user']['followers']['totalCount'] = value
            invalid.append(payload)
        duplicate = response()
        days = duplicate['data']['user']['contributionsCollection']['contributionCalendar']['weeks'][0]['contributionDays']
        days[10]['date'] = days[9]['date']
        invalid.append(duplicate)
        partial = response()
        partial['data']['user']['repositories']['nodes'].pop()
        invalid.append(partial)
        for payload in invalid:
            with self.subTest(payload=payload['data']['user']['followers']), self.assertRaises(ValueError):
                self.refresh(payload)
        self.assertEqual(self.files(), before)

    def test_star_pagination_covers_all_public_repositories_and_rejects_loops(self):
        first = response()
        first['data']['user']['repositories'].update({
            'nodes': [{'stargazerCount': 4}],
            'pageInfo': {'hasNextPage': True, 'endCursor': 'page-two'},
        })
        second = response()
        second['data']['user']['repositories']['nodes'] = [{'stargazerCount': 5}]
        with replies(first, second):
            self.assertEqual(stats.fetch_snapshot('Cyril-Fan', 'test-token')['stats'][1][1], 9)
        with replies(first, copy.deepcopy(first)), self.assertRaises(ValueError):
            stats.fetch_snapshot('Cyril-Fan', 'test-token')

    def test_missing_asset_never_replaces_the_readme_with_a_broken_url(self):
        self.refresh(response())
        before = (self.root / 'README.md').read_bytes()
        (self.root / 'assets' / stats.SNAKES[-1]).unlink()
        with self.assertRaises(FileNotFoundError):
            stats.publish_assets(self.root)
        self.assertEqual((self.root / 'README.md').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
