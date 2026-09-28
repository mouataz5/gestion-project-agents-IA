# playwright/

Browser-level testing assets.

| Path | Purpose | Phase |
|---|---|---|
| `tests/e2e/` | End-to-end tests of the dashboard against a running stack (`@playwright/test`) | 1 |
| `mock-ats/` | Static mock ATS sites (Greenhouse-like, Lever-like, generic) for safe automation tests | 8 |
| `.auth/` | Browser authentication state — **git-ignored, never commit** | 8 |

The production browser automation (`ApplicationBrowser` and ATS adapters) is written with **Python
Playwright** in `backend/app/browser/` and `backend/app/ats/`; this folder only holds test assets.

## Running the E2E tests

```bash
make up            # or run backend + worker + frontend natively (see README)
make test-e2e      # E2E_BASE_URL defaults to http://localhost:3000
```

`@playwright/test` is pinned to `1.56.1` (Chromium revision 1194). Install the browser once with
`npx playwright install chromium` if it is not already present.
