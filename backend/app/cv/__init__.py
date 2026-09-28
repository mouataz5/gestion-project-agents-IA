"""Master CV handling: file validation, text extraction, deterministic parsing, skill evidence.

Parsing never uses an LLM and never invents text: every value in a parsed CV is a substring
of the uploaded document. The result is a *draft* that the user corrects and confirms.
"""
