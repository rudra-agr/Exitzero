from __future__ import annotations

from enum import Enum

from ..models import Diagnosis, Category, VerificationStatus, Confidence


class Action(str, Enum):
    AUTO_APPLY   = "auto_apply"
    PROMPT_USER  = "prompt_user"
    EXPLAIN_ONLY = "explain_only"


def gate(diagnosis: Diagnosis) -> Action:
    if diagnosis.category == Category.UNKNOWN:
        return Action.EXPLAIN_ONLY

    if diagnosis.verification_status not in (
        VerificationStatus.SUPPORTED,
        VerificationStatus.VERIFIED,
    ):
        return Action.EXPLAIN_ONLY

    if diagnosis.patch_diff is None and diagnosis.shell_fix is None:
        return Action.EXPLAIN_ONLY

    if diagnosis.confidence == Confidence.HIGH:
        # Require at least one observed file-read in evidence before auto-applying
        has_file_evidence = any(
            e.observed and e.source.startswith("read_file")
            for e in diagnosis.evidence
        )
        if has_file_evidence or diagnosis.patch_diff is None:
            return Action.AUTO_APPLY
        return Action.PROMPT_USER

    if diagnosis.confidence == Confidence.MEDIUM:
        return Action.PROMPT_USER

    return Action.EXPLAIN_ONLY
