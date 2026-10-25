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


class VerificationStatus(str, Enum):
    OBSERVED             = "OBSERVED"
    SUPPORTED            = "SUPPORTED"
    VERIFIED             = "VERIFIED"
    UNSUPPORTED          = "UNSUPPORTED"   # reserved for future use; pipeline never sets this
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


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
class Evidence:
    source: str
    fact: str
    observed: bool = True


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
    original_command: Optional[str] = None


@dataclass
class Diagnosis:
    category: Category
    confidence: Confidence
    plain_english: str
    fix_explanation: str
    verification_status: VerificationStatus = VerificationStatus.INSUFFICIENT_EVIDENCE
    evidence: list[Evidence] = field(default_factory=list)
    patch_diff: Optional[str] = None
    shell_fix: Optional[str] = None
    source: Source = Source.PRIMARY
    schema_version: int = SCHEMA_VERSION
    language: Language = Language.GENERIC
    cache_hit: bool = field(default=False, compare=False)  # transient — not serialized

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("cache_hit", None)  # transient — never persisted
        d["category"]            = self.category.value
        d["confidence"]          = self.confidence.value
        d["verification_status"] = self.verification_status.value
        d["source"]              = self.source.value
        d["language"]            = self.language.value
        d["evidence"]            = [
            {"source": e.source, "fact": e.fact, "observed": e.observed}
            for e in self.evidence
        ]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Diagnosis:
        return cls(
            category            = Category(d["category"]),
            confidence          = Confidence(d["confidence"]),
            plain_english       = d["plain_english"],
            fix_explanation     = d["fix_explanation"],
            verification_status = VerificationStatus(d.get("verification_status", VerificationStatus.INSUFFICIENT_EVIDENCE.value)),
            evidence            = [
                Evidence(
                    source=e["source"],
                    fact=e["fact"],
                    observed=e.get("observed", True),
                )
                for e in d.get("evidence", [])
            ],
            patch_diff          = d.get("patch_diff"),
            shell_fix           = d.get("shell_fix"),
            source              = Source(d.get("source", Source.PRIMARY.value)),
            schema_version      = d.get("schema_version", SCHEMA_VERSION),
            language            = Language(d.get("language", Language.GENERIC.value)),
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
