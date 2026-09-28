# frontend/

Next.js 16 (App Router, TypeScript, Tailwind CSS 4) dashboard for the job agent.

## How it talks to the backend

- **Pages are Server Components.** They read the API at request time through
  `src/lib/server/backend.ts` using `BACKEND_INTERNAL_URL` and the server-side `API_AUTH_TOKEN`.
- **Browser actions** (e.g. "Run system diagnostic") call the same-origin route handler
  `/api/backend/[...path]`, which validates the path, forwards allow-listed headers and injects the
  API token. The token and the backend URL never reach the browser.
- **API types** are generated from the backend OpenAPI schema: `make openapi`
  (→ `src/lib/api/openapi.json` → `src/lib/api/schema.d.ts`).

| Variable               | Default                 | Purpose                                          |
| ---------------------- | ----------------------- | ------------------------------------------------ |
| `BACKEND_INTERNAL_URL` | `http://localhost:8000` | Backend base URL as seen from the Next.js server |
| `API_AUTH_TOKEN`       | —                       | Bearer token for the backend (server-side only)  |
| `API_PREFIX`           | `/api/v1`               | Backend API prefix                               |

## Commands

```bash
npm ci                 # install
npm run dev            # development server on http://localhost:3000
npm run lint           # ESLint
npm run typecheck      # next typegen + tsc
npm test               # Vitest unit tests
npm run build          # production build (standalone output)
npm run format         # Prettier
```

From the repository root, `make frontend` starts the dev server with the variables from `.env`.

Pages for later phases (jobs, applications, candidate, CV, companies) appear in the navigation as
disabled items tagged with their delivery phase.
