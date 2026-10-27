# Hourly Job Watch

## Google Sheets delivery

The monitor also supports a filterable `Jobs` worksheet with 20 columns, a frozen header
at row 5, company/role columns on the left, numeric fit and dates, employer evidence,
and an editable `My notes` column. The `Job ID` column is the delivery ledger; retain it
when sorting and do not delete its values. The writer appends with RAW input so employer
text cannot become a formula. It never changes existing notes or application statuses.

To switch an existing deployment: enable Google Sheets API in the OAuth client's project,
run `python scripts/authorize_google.py secrets/client.json --sheets`, update
`GOOGLE_OAUTH_JSON`, and add the destination ID as `GOOGLE_SHEET_ID`. Import the prepared
workbook before switching. Set Actions variable `DELIVERY_TARGET=sheets` only after verifying
the imported rows. Without that variable the monitor keeps writing to Docs.

Sheets delivery has its own destination-specific state. Existing Docs delivery flags do not
skip jobs in a new Sheet. Migrated rows are reconciled by Job ID; historical jobs which have
closed must be migrated from the original report before switching. The Doc remains as an archive.
The same workflow concurrency group serializes all runs. Do not run a separate local writer
concurrently. Existing rows may be sorted and notes edited; do not rename the Jobs tab,
reorder the columns, or insert non-job rows inside the table.

A zero-paid-API monitor for US new-grad/entry-level SWE, Backend, AI/ML and Data Engineering jobs.
Python 3.11+ standard library only. It reads public employer job boards and appends new matches
to a Google Doc. It has no application submission code, browser automation, paid models or paid scraping service.

## What it records

Company, direct posting link, role, exact experience text, matched and unmatched keywords,
fit score and calculation, sponsorship status and quoted evidence with source/check time,
location, stated salary, source posting date, first-seen date, and review flags.
Missing information stays “Not stated”; update dates are never relabeled as posting dates.

Fit is **recognized posting-skill coverage**: resume skills matched / recognized skills in the
posting × 100. It is not a probability of being hired and does not evaluate every qualification.
The inclusive threshold is 50%. The public example profile is not the user's resume.
Profiles must use the canonical skill names in `monitor/core.py`.

Explicit sponsorship denials are excluded. Unknown, questions, conditional policies, and
conflicting evidence stay flagged. A work-authorization requirement alone is not a sponsorship denial.
Employer wording is always included; automated text rules are imperfect and require human review.
No historical sponsorship claim is substituted for the actual posting.

Senior/intern roles are excluded. Roles with stated minimum experience above one year
are excluded, even when the title says new-grad, junior, or entry-level. Ranges such as
0–2 or 1–2 years remain eligible because their minimum is at most one year; preferred
experience is not treated as required. Generic titles need
graduate wording or a stated experience requirement of at most one year. Unspecified seniority
without that evidence is excluded. Remote-only locations without US evidence
are excluded rather than assumed to be US eligible.

## Run locally

1. Create `local-profile.json` from `profile.example.json` using skills from your actual resume.
2. Run `python -m unittest discover -s tests -v`.
3. Run `python -m monitor.run --profile local-profile.json` for a live read-only preview.
4. Inspect `matches.json` and `run-status.json`. Preview does not mark results delivered.
5. Configure Google credentials below; run with `--deliver` to append matches.

On first run, currently open matching jobs are included as an initial backfill. Later runs report
each job only once, including jobs whose wording changes enough to cross the fit threshold.
First seen means first observed by this monitor, not newly published. No source guarantees all
vacancies or immediate detection. Add employers in `sources.json` using public board slugs.

## Google setup (no billing account needed for Docs API)

Create a Google Cloud project, enable Google Docs API, configure the OAuth consent screen,
and create a **Desktop app** OAuth client. Download its client JSON into the ignored `secrets/`
folder. Run:

```text
python scripts/authorize_google.py secrets/client.json
```

Approve Google access in your own browser. The helper uses a local callback, state validation,
and PKCE; saves the refresh credentials to `secrets/google-oauth.json`; never prints credentials.
For sustained use, move an external OAuth consent app out of Testing: refresh tokens for
non-basic scopes in Testing commonly expire after seven days. A revoked/expired credential
makes the workflow fail and requires authorization again.

Create a private Google Doc named **Hourly SWE and AI Job Watch**, or use an existing one.
The document ID is the portion between `/d/` and `/edit` in its URL.
The chat's Google connection cannot be exported as the workflow's OAuth credential.

## GitHub Actions setup

Use a **public** repository with a standard `ubuntu-latest` hosted runner. The workflow refuses
to run on private repositories, avoiding account-wide paid-minute overages. No artifacts,
caches, package installs or external paid APIs are used. Do not publish the resume/profile.

Set repository Actions secrets:

| Secret | Value |
| --- | --- |
| `PROFILE_JSON` | Your private resume-derived skills profile JSON |
| `GOOGLE_OAUTH_JSON` | Contents of `secrets/google-oauth.json` |
| `GOOGLE_DOC_ID` | Private destination document ID |

Set repository Actions variable `MONITOR_ENABLED` to `true` only after these are ready.
Run **Hourly job watch → Run workflow** and verify the Doc. Run again to verify no duplicates.
It is scheduled at minute 17 of every UTC hour. Schedules run from the default branch and
may be delayed/skipped by GitHub; public schedules may disable after 60 days of repository
inactivity. Review Actions failures and re-enable if needed. This is best-effort hourly polling,
not a real-time service-level guarantee.

## Persistent state and recovery

`monitor-state` is a separate branch holding only hashed job IDs, first-seen timestamps and
reported booleans. It does not contain resume data, scores, descriptions or Google credentials.
The Doc contains `[job-watch:...]` markers that form a second delivery ledger. Keep these markers.
The writer reads markers before each batch and uses a Google revision precondition. If Google
accepted a write but the runner crashed before saving state, the next run reconciles those markers
and avoids another append. An uncertain write is never blindly retried. Concurrent runs are serialized.
If markers and state are both deleted, historical duplicate protection is lost. Do not run separate
copies locally at the same time as Actions. Keep the default first Doc tab for monitor entries.

One source failure does not discard successful sources, but the run is marked failed to make
coverage loss visible. All-source failures abort delivery. `run-status.json` has diagnostic counts.
The eight-minute job cap bounds runaway runs; a large board list may need a smaller batch.

## Existing project and third-party review

Reviewed [JobApplicationAgent](https://github.com/YCK72/JobApplicationAgent) for the existing
public ATS approach. This independent application deliberately contains no submission modules.
Reviewed [Simplify New-Grad Positions](https://github.com/SimplifyJobs/New-Grad-Positions) as
a useful discovery list, but did not treat community labels as employer sponsorship evidence.
Reviewed [JobSpy](https://github.com/speedyapply/JobSpy); direct ATS APIs avoid its scraper
dependencies, blocking/proxy concerns, and the need to infer facts from partial search snippets.
Current coverage is 78 configured employers, not all US job listings. On October 26,
2026, 63 additional public feeds were validated and Palantir was removed from future
collection. Existing historical rows are retained. The list includes AI labs, cloud
and data infrastructure, developer tools, fintech, and consumer technology companies.
Only feeds returning postings through the supported free APIs were added; employers
using other systems or unavailable feeds are not covered. See `sources.json` for the
exact current list. A working feed does not imply current entry-level vacancies or
visa sponsorship; the existing role, fit, location, and sponsorship checks still apply.

Primary references:
- [Greenhouse public API](https://docs.greenhouse.io/job-board.html)
- [Lever public API](https://github.com/lever/postings-api)
- [Ashby public API](https://developers.ashbyhq.com/docs/public-job-posting-api)
- [Google Docs API limits and no-cost usage](https://developers.google.com/docs/api/limits)
- [Google OAuth token expiration](https://developers.google.com/identity/protocols/oauth2#expiration)
- [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
- [Scheduled workflow limitations](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
