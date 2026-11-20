"""Pipeline configuration. A release is a configuration; regressions are configuration deltas."""

from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import asdict, dataclass, replace
from pathlib import Path

ACL_MODES = ("pre", "post", "off")
PROMPT_VARIANTS = ("grounded", "plain", "grounded_v2", "abstain_strong")
VERIFIERS = ("lexical", "always_accept")


@dataclass(frozen=True)
class PipelineConfig:
    # retrieval
    top_k: int = 5
    candidate_k: int = 20
    use_bm25: bool = True
    use_dense: bool = False
    use_rerank: bool = False
    acl_mode: str = "pre"            # pre: filter before ranking; post: after the top-k cut; off: no filter
    # generation
    prompt_variant: str = "grounded"
    system_prompt: str = ""          # free-text system prompt; overrides prompt_variant when set
    temperature: float = 0.0
    max_tokens: int = 256
    # guardrail
    verifier: str = "lexical"
    regenerate: bool = True
    cost_wrong: float = 4.0          # cost of shipping an unsupported answer
    cost_abstain: float = 1.0        # cost of abstaining
    regenerate_band: float = 0.25    # uncalibrated mode: support band below the accept threshold that triggers one retry
    cost_regen: float = 0.5          # cost of one retry (latency + tokens), used with a calibrator
    calibration: str = ""           # path to a calibrator fitted on the dev split (empty = uncalibrated)
    router: str = "cost"             # cost: accept/regenerate/abstain; open_loop: ship every generated
                                     # answer (measurement only: unbiased calibration data, cost sweeps)

    def __post_init__(self):
        if self.acl_mode not in ACL_MODES:
            raise ValueError(f"acl_mode must be one of {ACL_MODES}")
        if self.prompt_variant not in PROMPT_VARIANTS:
            raise ValueError(f"prompt_variant must be one of {PROMPT_VARIANTS}")
        if self.verifier not in VERIFIERS:
            raise ValueError(f"verifier must be one of {VERIFIERS}")
        if self.router not in ("cost", "open_loop"):
            raise ValueError("router must be 'cost' or 'open_loop'")
        if self.top_k < 1 or self.candidate_k < self.top_k:
            raise ValueError("need 1 <= top_k <= candidate_k")
        if self.cost_wrong <= 0 or self.cost_abstain <= 0 or self.cost_regen < 0:
            raise ValueError("costs must be positive")

    @property
    def accept_threshold(self) -> float:
        """Accept iff expected cost of shipping <= cost of abstaining:
        (1 - support) * cost_wrong <= cost_abstain  <=>  support >= 1 - cost_abstain / cost_wrong."""
        return max(0.0, 1.0 - self.cost_abstain / self.cost_wrong)

    def with_(self, **changes) -> PipelineConfig:
        return replace(self, **changes)

    def to_dict(self) -> dict:
        return asdict(self)

    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True).encode()).hexdigest()[:12]


def load_config(path: str | Path | None) -> PipelineConfig:
    if path is None:
        return PipelineConfig()
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return PipelineConfig(**data.get("pipeline", data))
