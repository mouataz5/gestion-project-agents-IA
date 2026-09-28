# prompts/

Versioned prompt templates used by the LLM layer (`backend/app/llm/`, from Phase 4).

Conventions:

- One file per task, named `<task>.v<N>.md` (e.g. `job_analysis.v1.md`, `visa_classification.v1.md`).
  A behaviour change means a new version file, never an in-place edit, so every stored analysis can
  record the exact prompt version that produced it.
- Prompts request **structured JSON** validated against Pydantic schemas; free-form text is never parsed
  with regular expressions.
- Prompts must restate the truthfulness rules: use only the provided master CV, profile and job text;
  mark unknowns as `NEEDS_USER_INPUT`; quote evidence verbatim.
- No secrets, personal contact data or credentials in prompt files.
