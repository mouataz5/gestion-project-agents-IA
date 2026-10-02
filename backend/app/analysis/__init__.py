"""Job analysis (Phase 4): visa/sponsorship classification, skill-match verification, language
checks and the qualification rules that turn an LLM assessment into APPLY / REVIEW / SKIP.

Everything here is deterministic and grounded: the LLM proposes, these rules verify (quotes must be
verbatim, skill matches must be backed by CV evidence) and decide.
"""
