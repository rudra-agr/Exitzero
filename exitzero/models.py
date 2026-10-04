from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional

from .config import SCHEMA_VERSION


class Category(str, Enum):
    FLAKY_TEST        = "Flaky Test"
    REAL_BUG          = "Real Bug"
    GIT_CONFLICT      = "Git Conflict"
    ENVIRONMENT_ISSUE = "Environment Issue"
    DEPENDENCY_ERROR  = "Dependency Error"
    PERMISSION_ERROR  = "Permission Error"
    NETWORK_ERROR     = "Network Error"
    UNKNOWN           = "Unknown"


class Confidence(str, Enum):
    HIGH   = "High"
    MEDIUM = "Medium"
    LOW    = "Low"


class Source(str, Enum):
    CACHE   = "cache"
    PRIMARY = "primary-llm"
    BACKUP  = "backup-llm"


class Language(str, Enum):
    PYTHON  = "python"
    NODE    = "node"
    RUST    = "rust"
    GO      = "go"
    JAVA    = "java"
    SHELL   = "shell"
    GENERIC = "generic"


@dataclass
class ErrorContext:
    raw_window: str
    normalized_window: str
    language: Language = Language.GENERIC
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    deep_source_snippet: Optional[str] = None
    git_status: Optional[str] = None
    all_errors: list[str] = field(default_factory=list)


@dataclass
class Diagnosis:
    category: Category
    confidence: Confidence
    plain_english: str
    fix_explanation: str
    shell_fix: Optional[str] = None
    source: Source = Source.PRIMARY
    schema_version: int = SCHEMA_VERSION
    language: Language = Language.GENERIC

    def to_dict(self) -> dict:
        d = asdict(self)
        d["category"]   = self.category.value
        d["confidence"] = self.confidence.value
        d["source"]     = self.source.value
        d["language"]   = self.language.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Diagnosis:
        return cls(
            category        = Category(d["category"]),
            confidence      = Confidence(d["confidence"]),
            plain_english   = d["plain_english"],
            fix_explanation = d["fix_explanation"],
            shell_fix       = d.get("shell_fix"),
            source          = Source(d.get("source", Source.PRIMARY.value)),
            schema_version  = d.get("schema_version", SCHEMA_VERSION),
            language        = Language(d.get("language", Language.GENERIC.value)),
        )


@dataclass
class RemediationResult:
    executed: bool
    returncode: Optional[int]
    stdout: str
    stderr: str
    blocked_reason: Optional[str] = None


@dataclass
class RunResult:
    diagnosis: Diagnosis
    cache_hit: bool
    remediated: bool = False
    exit_code: int = 1

    def to_dict(self) -> dict:
        return {
            "diagnosis":  self.diagnosis.to_dict(),
            "cache_hit":  self.cache_hit,
            "remediated": self.remediated,
            "exit_code":  self.exit_code,
        }
