# Profile data updates

The README statistics and contribution animations are generated snapshots, not live GitHub widgets.

- The workflow checks public GitHub data every five minutes, offset from minute zero. GitHub may delay or drop scheduled jobs, so five minutes is a polling target, not a guaranteed maximum delay.
- Repository count, stars across owned public repositories, followers, and the past year's contribution total come from the same GitHub GraphQL refresh. Calendar days are validated against the contribution total. All repository pages are included in the star count.
- Light and dark statistics cards update together. The snake is regenerated when the daily contribution calendar changes, an animation is missing, or a manual/code-triggered refresh runs.
- Each README image URL carries a hash of its actual SVG content. A changed image therefore gets a new cache key rather than reusing the old proxy URL. Assets and README URLs are committed together after all generators succeed.
- Failed API calls, incomplete calendars, invalid counts, or failed animation generation do not publish invented zeroes or partial snapshots. A later successful run retries automatically.
- Identical data leaves the files unchanged. The displayed UTC timestamp is the time the published snapshot was generated, not a claim that the page is being updated continuously.

To refresh manually, open [Update profile assets](https://github.com/Cyril-Fan/Cyril-Fan/actions/workflows/profile.yml) and select **Run workflow** on `main`. Check that the run succeeds; a green run with no data changes need not create a commit.

GitHub's native profile sidebar is the authoritative place for the latest follower count. README rendering, GitHub's image proxy, and an already-open browser tab can still delay a displayed snapshot. Reload the profile to load changed README image URLs. The repository does not expose a personal token in README images; the workflow uses its existing repository-scoped `GITHUB_TOKEN`.

The biography and contact text are maintained in `README.md`. The external visitor badge is provided by its own service and is not a GitHub follower count.

Run the refresh regression tests without credentials or network access:

```sh
python3 -m unittest discover -s tests -v
```

References: [GitHub scheduled workflow limits](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule), [GitHub image proxy caching](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/about-anonymized-urls).
