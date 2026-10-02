"""Versioned prompt files: ``prompts/<task>.v<N>.md``.

A behaviour change means a new version file, never an in-place edit, so every stored analysis
records exactly which prompt (name, version, SHA-256) produced it.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from app.core.errors import AppError
from app.llm.types import PromptRef

_NAME_RE = re.compile(r"[a-z][a-z0-9_]{0,63}")
_FILE_RE = re.compile(r"(?P<name>[a-z][a-z0-9_]{0,63})\.v(?P<version>[1-9][0-9]{0,3})\.md")


class PromptNotFoundError(AppError):
    status_code = 500
    code = "prompt_not_found"


@dataclass(frozen=True)
class Prompt:
    name: str
    version: int
    text: str
    sha256: str

    @property
    def ref(self) -> str:
        return f"{self.name}.v{self.version}"

    def reference(self) -> PromptRef:
        return PromptRef(name=self.name, version=self.version, sha256=self.sha256)


class PromptRegistry:
    def __init__(self, prompts_dir: Path) -> None:
        self._dir = prompts_dir

    def versions(self, name: str) -> list[int]:
        if not _NAME_RE.fullmatch(name) or not self._dir.is_dir():
            return []
        found: list[int] = []
        for path in self._dir.glob(f"{name}.v*.md"):
            match = _FILE_RE.fullmatch(path.name)
            if match and match.group("name") == name:
                found.append(int(match.group("version")))
        return sorted(found)

    def get(self, name: str, version: int | None = None) -> Prompt:
        versions = self.versions(name)
        if not versions:
            raise PromptNotFoundError(f"No prompt named {name!r} in the prompts folder")
        chosen = versions[-1] if version is None else version
        if chosen not in versions:
            raise PromptNotFoundError(f"Prompt {name!r} has no version {version}")
        data = (self._dir / f"{name}.v{chosen}.md").read_bytes()
        return Prompt(
            name=name,
            version=chosen,
            text=data.decode("utf-8"),
            sha256=hashlib.sha256(data).hexdigest(),
        )
