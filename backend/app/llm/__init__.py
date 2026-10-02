"""LLM provider layer: the ``LLMProvider`` protocol, the Claude provider (official ``anthropic``
SDK, structured outputs, refusal handling, prompt caching, usage recording), a deterministic mock
provider for offline use and tests, versioned prompts and provider selection from the settings.

Prompts and model answers are never logged; only metadata (model, tokens, duration, request id).
"""
