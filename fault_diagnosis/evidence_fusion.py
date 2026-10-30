"""Research-facing evidence fusion API."""

from fru_diagnosis.evidence_fusion import (
    build_fusion_candidates,
    combine_beliefs_dempster_shafer,
)

__all__ = ["build_fusion_candidates", "combine_beliefs_dempster_shafer"]

