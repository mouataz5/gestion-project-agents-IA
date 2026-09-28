# candidate/

Candidate-owned inputs. The system is designed for one candidate initially, but every
candidate-scoped database table carries a `candidate_id` so more candidates can be added later.

| Path | Purpose | In Git? |
|---|---|---|
| `profile.yaml` | Identity, work authorization, relocation, target roles/countries, declared core skills, application defaults | yes |
| `profile.local.yaml` | Optional private overrides (contact details, salary expectations, notice period) | **no** (git-ignored) |
| `master_cv/` | Optional place for your own copy of the master CV. The system itself stores uploads (made at `/cv`) in `STORAGE_DIR` | **no** (git-ignored) |

Rules enforced by the system (see `docs/architecture.md` → *Truthfulness guard*):

- Nothing in a tailored CV or an application answer may contradict or exceed the master CV.
- Unknown values stay `null` and surface as `NEEDS_USER_INPUT`; they are never guessed.
- Declared `core_skills` are not proficiency claims — evidence must come from the master CV.

## How these files are used (Phase 2)

- On first use, `profile.yaml` (deep-merged with `profile.local.yaml`: mappings merge, lists
  replace) is validated and imported into the database, which then holds the live profile. Edit it
  at `/candidate`; **Import from YAML** reloads the files and **Export YAML** downloads the current
  profile (private contact details only on request).
- Validation is strict: unknown keys (typos) and wrong types are rejected with the field path, for
  example `identity.fullname: Extra inputs are not permitted`. Country codes are ISO alpha-2 (quote
  `"NO"` for Norway, otherwise YAML reads it as a boolean).
- Upload the master CV at `/cv`, review the parsed draft and confirm it: the confirmed version is the
  **source of truth** for experience, skills, dates, employers and metrics.
