# SF Chronicle filtered feed

A free, self-updating RSS feed of San Francisco Chronicle SF / Bay Area / California
coverage, with sports and national/world news removed. GitHub rebuilds it every
30 minutes and hosts it for free.

## Setup (about 15 minutes, all in the browser)

1. **Create a repository.** On github.com: **+** (top right) → **New repository**.
   Name it e.g. `sfchron-feed`, set it to **Public** (free GitHub Pages hosting
   requires a public repo), leave "Add a README" unchecked, then **Create repository**.

2. **Upload the files.** On the new repo page click **uploading an existing file**,
   then drag in everything from the unzipped folder: `generate_feed.py`,
   `config.json`, `README.md`, and the `.github` folder. **Commit changes**.
   - Check that `.github/workflows/build-feed.yml` appears in the repo. If the
     `.github` folder didn't upload, use **Add file → Create new file**, type
     `.github/workflows/build-feed.yml` as the name, paste the file's contents,
     and commit.

3. **Run it once.** Go to the **Actions** tab (click the green button to enable
   workflows if asked) → **Build feed** → **Run workflow**. In about a minute
   you should get a green check and a new `docs/` folder in the repo.

4. **Turn on hosting.** **Settings → Pages**. Under "Build and deployment" set
   Source = **Deploy from a branch**, Branch = **main**, folder = **/docs**, and **Save**.
   Wait 1–2 minutes.

5. **Subscribe.** Your feed is at
   `https://YOUR-USERNAME.github.io/sfchron-feed/feed.xml`
   Paste that into Feedly's Follow search.

6. **Optional:** put that URL in `"feed_url"` in `config.json`. It's only feed
   metadata and isn't required.

## Checking and tuning

Open `https://YOUR-USERNAME.github.io/sfchron-feed/sections.txt` after a run. It shows:

- **Source used.** `sitemap` (the Chronicle's own sitemaps; precise filtering by
  section) or `google_news` (fallback; filtering by headline only).
- **Kept, by section.** Any section you don't want, add to `blocked_sections`.
- **Blocked headlines.** Check these for local stories wrongly removed.

To tune, edit `config.json` on GitHub (pencil icon) and commit. The next run uses
the new settings. Key settings:

| Setting | What it does |
|---|---|
| `blocked_sections` | URL path segments to drop, e.g. `/sports/`, `/nation/` |
| `national_title_regex` | Headlines matching this are dropped... |
| `local_rescue_regex` | ...unless they also match this (e.g. "Newsom sues Trump" is kept) |
| `sports_title_regex` | Used only in Google News fallback mode |
| `max_age_hours` | Ignore items older than this |

The regex values are regular expressions inside JSON, so a literal backslash is
written `\\`. Words are separated by `|`.

## Troubleshooting

- **Push fails with a permissions error:** Settings → Actions → General →
  Workflow permissions → **Read and write permissions** → Save.
- **"Scheduled workflow disabled" email:** GitHub can pause scheduled jobs in
  repos with no activity for 60 days. The feed commits should prevent that; if it
  happens anyway, re-enable it from the Actions tab.
- **Feed stops updating:** check the Actions tab for the latest run's log. A
  yellow warning saying no items were found means both sources failed that run;
  the previous feed is left in place.
