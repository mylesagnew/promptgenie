"""baseline.py — Prompt evaluation baseline and regression gate engine.

Baselines are stored as JSON artifacts at::

    .promptgenie/baselines/<name>.json

A baseline captures per-model metrics from a matrix evaluation run. The
regression gate compares a new run against the stored baseline and fails if
any configured per-metric threshold is exceeded.

Threshold configuration example (in .promptgenie.yaml or passed directly)::

    baselines:
      fail_if_score_drops_by: 5        # rubric score points
      fail_if_cost_increases_by_pct: 20 # percentage
      fail_if_new_high_risk: true       # any new HIGH/CRITICAL scan finding
      fail_if_latency_increases_by_pct: 50  # optional

Public API
----------
  ``save_baseline(name, result, dir)``            → Path
  ``load_baseline(name, dir)``                    → BaselineRecord | None
  ``compare_to_baseline(new, baseline, thresholds)`` → RegressionReport
  ``RegressionReport``                            — dataclass, .has_regressions
  ``BaselineThresholds``                          — config dataclass
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_DEFAULT_BASELINE_DIR = Path(".promptgenie") / "baselines"


@dataclass
class BaselineThresholds:
    fail_if_score_drops_by: float = 5.0
    fail_if_cost_increases_by_pct: float = 20.0
    fail_if_latency_increases_by_pct: float | None = None
    fail_if_new_high_risk: bool = True


# ---------------------------------------------------------------------------
# Stored record
# ---------------------------------------------------------------------------

@dataclass
class BaselineModelEntry:
    provider: str
    model: str
    rubric_score: float | None
    safety_score: float | None
    latency_ms: float
    cost_usd: float
    total_tokens: int
    error: str | None = None


@dataclass
class BaselineRecord:
    name: str
    timestamp: str
    entries: list[BaselineModelEntry] = field(default_factory=list)
    scan_risk: str = "NONE"         # highest risk from prompt scan at baseline time
    meta: dict[str, Any] = field(default_factory=dict)

    def by_display_name(self, display_name: str) -> BaselineModelEntry | None:
        for e in self.entries:
            dn = f"{e.provider}/{e.model}" if e.model != e.provider else e.provider
            if dn == display_name or e.provider == display_name:
                return e
        return None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "timestamp": self.timestamp,
            "scan_risk": self.scan_risk,
            "meta": self.meta,
            "entries": [
                {
                    "provider": e.provider,
                    "model": e.model,
                    "rubric_score": e.rubric_score,
                    "safety_score": e.safety_score,
                    "latency_ms": e.latency_ms,
                    "cost_usd": e.cost_usd,
                    "total_tokens": e.total_tokens,
                    "error": e.error,
                }
                for e in self.entries
            ],
        }


# ---------------------------------------------------------------------------
# Regression report
# ---------------------------------------------------------------------------

@dataclass
class Regression:
    model: str
    metric: str
    baseline_value: float | str
    current_value: float | str
    delta: str
    message: str


@dataclass
class RegressionReport:
    baseline_name: str
    regressions: list[Regression] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def has_regressions(self) -> bool:
        return len(self.regressions) > 0

    def to_dict(self) -> dict:
        return {
            "baseline_name": self.baseline_name,
            "has_regressions": self.has_regressions,
            "regressions": [
                {
                    "model": r.model,
                    "metric": r.metric,
                    "baseline": r.baseline_value,
                    "current": r.current_value,
                    "delta": r.delta,
                    "message": r.message,
                }
                for r in self.regressions
            ],
            "improvements": self.improvements,
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _baseline_path(name: str, baseline_dir: Path) -> Path:
    import re
    safe = re.sub(r"[^\w\-]", "_", name)
    return baseline_dir / f"{safe}.json"


def save_baseline(
    name: str,
    result: "Any",  # MatrixEvalResult from evaluator
    baseline_dir: Path | None = None,
    *,
    scan_risk: str = "NONE",
    meta: dict | None = None,
) -> Path:
    """Save *result* (MatrixEvalResult) as a named baseline artifact."""
    from datetime import datetime, timezone
    bdir = baseline_dir or _DEFAULT_BASELINE_DIR
    bdir.mkdir(parents=True, exist_ok=True)

    entries = []
    for r in result.results:
        entries.append(BaselineModelEntry(
            provider=r.provider,
            model=r.model,
            rubric_score=r.metrics.rubric_score,
            safety_score=r.metrics.safety_score,
            latency_ms=r.metrics.latency_ms,
            cost_usd=r.metrics.cost_usd,
            total_tokens=r.metrics.total_tokens,
            error=r.error,
        ))

    record = BaselineRecord(
        name=name,
        timestamp=datetime.now(timezone.utc).isoformat(),
        entries=entries,
        scan_risk=scan_risk,
        meta=meta or {},
    )
    path = _baseline_path(name, bdir)
    path.write_text(json.dumps(record.to_dict(), indent=2), encoding="utf-8")
    return path


def load_baseline(name: str, baseline_dir: Path | None = None) -> BaselineRecord | None:
    """Load a baseline by name, or None if not found."""
    bdir = baseline_dir or _DEFAULT_BASELINE_DIR
    path = _baseline_path(name, bdir)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = [
        BaselineModelEntry(
            provider=e["provider"],
            model=e["model"],
            rubric_score=e.get("rubric_score"),
            safety_score=e.get("safety_score"),
            latency_ms=e.get("latency_ms", 0.0),
            cost_usd=e.get("cost_usd", 0.0),
            total_tokens=e.get("total_tokens", 0),
            error=e.get("error"),
        )
        for e in data.get("entries", [])
    ]
    return BaselineRecord(
        name=data.get("name", name),
        timestamp=data.get("timestamp", ""),
        entries=entries,
        scan_risk=data.get("scan_risk", "NONE"),
        meta=data.get("meta", {}),
    )


def list_baselines(baseline_dir: Path | None = None) -> list[str]:
    """Return names of all saved baselines."""
    bdir = baseline_dir or _DEFAULT_BASELINE_DIR
    if not bdir.exists():
        return []
    return [p.stem for p in sorted(bdir.glob("*.json"))]


# ---------------------------------------------------------------------------
# Regression comparison
# ---------------------------------------------------------------------------

_RISK_ORDER = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "NONE": 0}


def compare_to_baseline(
    new_result: "Any",          # MatrixEvalResult
    baseline: BaselineRecord,
    thresholds: BaselineThresholds | None = None,
    *,
    current_scan_risk: str = "NONE",
) -> RegressionReport:
    """Compare *new_result* against *baseline* and return a RegressionReport."""
    t = thresholds or BaselineThresholds()
    report = RegressionReport(baseline_name=baseline.name)

    # Check new high-risk findings
    if t.fail_if_new_high_risk:
        baseline_risk_order = _RISK_ORDER.get(baseline.scan_risk.upper(), 0)
        current_risk_order = _RISK_ORDER.get(current_scan_risk.upper(), 0)
        if current_risk_order >= 3 and current_risk_order > baseline_risk_order:
            report.regressions.append(Regression(
                model="(all)",
                metric="scan_risk",
                baseline_value=baseline.scan_risk,
                current_value=current_scan_risk,
                delta=f"+{current_scan_risk}",
                message=f"New {current_scan_risk} security risk detected (baseline: {baseline.scan_risk})",
            ))

    for r in new_result.results:
        if not r.ok:
            report.warnings.append(f"{r.display_name}: errored — {r.error}")
            continue

        baseline_entry = baseline.by_display_name(r.display_name)
        if baseline_entry is None:
            report.improvements.append(f"{r.display_name}: new model (no baseline entry)")
            continue

        # Rubric score regression
        if (
            t.fail_if_score_drops_by is not None
            and r.metrics.rubric_score is not None
            and baseline_entry.rubric_score is not None
        ):
            drop = baseline_entry.rubric_score - r.metrics.rubric_score
            if drop > t.fail_if_score_drops_by:
                report.regressions.append(Regression(
                    model=r.display_name,
                    metric="rubric_score",
                    baseline_value=baseline_entry.rubric_score,
                    current_value=r.metrics.rubric_score,
                    delta=f"-{drop:.1f}",
                    message=(
                        f"Rubric score dropped by {drop:.1f} pts "
                        f"({baseline_entry.rubric_score:.0f} → {r.metrics.rubric_score:.0f}), "
                        f"threshold is {t.fail_if_score_drops_by}"
                    ),
                ))
            elif r.metrics.rubric_score > baseline_entry.rubric_score:
                report.improvements.append(
                    f"{r.display_name}: rubric +{r.metrics.rubric_score - baseline_entry.rubric_score:.1f}"
                )

        # Cost regression
        if (
            t.fail_if_cost_increases_by_pct is not None
            and baseline_entry.cost_usd > 0
        ):
            pct_increase = (r.metrics.cost_usd - baseline_entry.cost_usd) / baseline_entry.cost_usd * 100
            if pct_increase > t.fail_if_cost_increases_by_pct:
                report.regressions.append(Regression(
                    model=r.display_name,
                    metric="cost_usd",
                    baseline_value=baseline_entry.cost_usd,
                    current_value=r.metrics.cost_usd,
                    delta=f"+{pct_increase:.0f}%",
                    message=(
                        f"Cost increased by {pct_increase:.0f}% "
                        f"(${baseline_entry.cost_usd:.6f} → ${r.metrics.cost_usd:.6f}), "
                        f"threshold is {t.fail_if_cost_increases_by_pct}%"
                    ),
                ))

        # Latency regression (optional)
        if (
            t.fail_if_latency_increases_by_pct is not None
            and baseline_entry.latency_ms > 0
        ):
            pct_increase = (
                (r.metrics.latency_ms - baseline_entry.latency_ms)
                / baseline_entry.latency_ms * 100
            )
            if pct_increase > t.fail_if_latency_increases_by_pct:
                report.regressions.append(Regression(
                    model=r.display_name,
                    metric="latency_ms",
                    baseline_value=baseline_entry.latency_ms,
                    current_value=r.metrics.latency_ms,
                    delta=f"+{pct_increase:.0f}%",
                    message=(
                        f"Latency increased by {pct_increase:.0f}% "
                        f"({baseline_entry.latency_ms:.0f}ms → {r.metrics.latency_ms:.0f}ms), "
                        f"threshold is {t.fail_if_latency_increases_by_pct}%"
                    ),
                ))

    return report
