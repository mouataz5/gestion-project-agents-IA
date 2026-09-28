# candidate/

Candidate-owned inputs. The system is designed for one candidate initially, but every
candidate-scoped database table carries a `candidate_id` so more candidates can be added later.

| Path | Purpose | In Git? |
|---|---|---|
| `profile.yaml` | Identity, work authorization, relocation, target roles/countries, declared core skills, application defaults | yes |
| `profile.local.yaml` | Optional private overrides (contact details, salary expectations, notice period) | **no** (git-ignored) |
| `master_cv/` | The master CV (DOCX/PDF). **Source of truth** for all experience, skills, dates, employers, metrics | **no** (git-ignored) |

Rules enforced by the system (see `docs/architecture.md` → *Truthfulness guard*):

- Nothing in a tailored CV or an application answer may contradict or exceed the master CV.
- Unknown values stay `null` and surface as `NEEDS_USER_INPUT`; they are never guessed.
- Declared `core_skills` are not proficiency claims — evidence must come from the master CV.

Schema validation, database sync, master CV upload/parsing and UI editing are delivered in **Phase 2**.
