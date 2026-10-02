# crawler/

Declarative configuration and fixtures for job discovery. The discovery **code** lives in
`backend/app/crawlers/` (sources, registry, compliance) and `backend/app/jobs/` (normalization
helpers); this folder holds the data they consume. Set `CRAWLER_DIR` to use another folder.

| Path | Purpose |
|---|---|
| `sources.yaml` | Source policy: every source with its kind, policy, priority, rate limit and review notes |
| `companies.yaml` | Seed for the company watchlist (import it on the Companies page or with `POST /api/v1/companies/import`) |
| `fixtures/mock_jobs/boards/<board_token>.json` | Fictional company boards served by the `mock_ats` source |
| `fixtures/mock_jobs/feed.json` | A fictional aggregator feed served by the `mock_feed` source |

## sources.yaml

```yaml
version: 1
user_agent: "JobAgent/0.1 (self-hosted personal job search; respects robots.txt)"
sources:
  - key: greenhouse            # stable identifier (jobs reference it)
    name: Greenhouse Job Board API
    kind: ATS_API              # ATS_API | CAREER_PAGE | FEED | MANUAL
    policy: api_only           # api_only | allowed | manual_only | disabled
    enabled: false
    priority: 100              # the primary record of a duplicated job comes from the highest priority
    rate_limit_per_minute: 60
    available_from_phase: 10
    notes: Public Job Board API, no authentication, one board per company.
```

- `api_only`: only the source's official public API or feed may be used.
- `allowed`: automated access to public pages is permitted, always with robots.txt and rate limits.
- `manual_only`: never fetched; jobs arrive only through imports (LinkedIn, pasted URLs).
- `disabled`: never used.

A source runs in a discovery only when it is enabled, its policy allows automated access, it is
implemented, and it matches the mode (`mock: true` sources only with `MOCK_MODE=true`, real sources
only with `MOCK_MODE=false`). The reason a source does not run is shown on the Jobs page, in
`GET /api/v1/job-sources` and in the run timeline. The file is validated on load (unknown keys, bad
values and duplicate keys are rejected with their path).

Real sources (Greenhouse, Lever, Ashby, SmartRecruiters, Workday, career pages, RSS) are declared but
disabled until their implementation in Phase 10.

## companies.yaml

```yaml
version: 1
companies:
  - name: Nova AI
    career_url: https://nova-ai.example/careers   # public http(s) URL
    country_code: FR                              # ISO 3166 alpha-2
    ats_type: GREENHOUSE                          # GREENHOUSE | LEVER | ASHBY | SMARTRECRUITERS | WORKDAY | GENERIC | OTHER
    board_token: nova-ai                          # the company's identifier in its ATS
    target_roles: [AI Engineer, LLM Engineer]     # extra titles kept for this company
    enabled: true
    notes: optional
```

The companies shipped here are **fictional** (`.example` domains) and only exist on the mock boards.
Importing the file creates missing companies and updates the listed ones; companies you added in the
dashboard are untouched.

## Mock fixtures

Dates are relative to the moment of the run (`posted_hours_ago` on boards, texts such as
"3 hours ago", "il y a 6 heures", "30+ days ago" or no date in the feed), so the same fixtures always
exercise the posting window: jobs inside and outside the window, an unknown date, a non-AI title, a
non-target country, a disabled watchlist company, a duplicate through tracking parameters and a
duplicate through identical content.

## Compliance rules

See `docs/security.md` §6. Public APIs and feeds are preferred over HTML crawling, robots.txt and
site terms are respected (`RobotsPolicy`, RFC 9309), rate limits are enforced per domain in Redis
(`RateLimiter`), CAPTCHAs and access controls are never bypassed, and LinkedIn is never scraped —
it is `manual_only`.
