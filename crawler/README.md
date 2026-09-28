# crawler/

Declarative configuration and fixtures for job discovery. The discovery **code** lives in
`backend/app/crawlers/` (the `JobSource` implementations); this folder holds the data they consume.

Planned contents (Phase 3 and Phase 10):

| Path | Purpose |
|---|---|
| `sources.yaml` | Enabled sources, per-source rate limits, compliance flags (robots.txt respected, ToS reviewed, API-only) |
| `companies.yaml` | Seed for the company watchlist (name, career URL, country, ATS type, target roles, enabled) |
| `fixtures/mock_jobs/` | Deterministic fake job postings used when `MOCK_MODE=true` |

Compliance rules (see `docs/security.md`): public APIs/feeds are preferred over HTML crawling,
`robots.txt` and site terms are respected, rate limits are enforced per domain, and LinkedIn is never
an architectural dependency.
