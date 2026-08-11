"""
EWMA-based multivariate anomaly scorer.

This is the core statistical engine: it builds a rolling behavioral
baseline per user (mean + covariance of their typing/mouse features)
using an exponentially weighted moving average, then scores new
sessions by their Mahalanobis distance from that baseline.

A large distance = "this doesn't look like how this user normally
behaves" = high fraud/account-takeover risk.

Design notes:
- lam (lambda) controls how fast the baseline adapts. Lower = more
  stable baseline, slower to adapt to genuine behavior drift.
  Higher = adapts fast, but is more easily poisoned by an attacker
  who slowly shifts the baseline toward their own behavior.
- We apply shrinkage toward a diagonal covariance matrix (a simplified
  Ledoit-Wolf-style regularization) to keep the covariance matrix
  well-conditioned and invertible even with few samples.
- The raw squared Mahalanobis distance is converted to a bounded
  0-100 risk score using an exponential CDF-style transform, which
  is easier to threshold and alert on than a raw unbounded distance.
"""

from __future__ import annotations

import numpy as np


class EWMAAnomalyScorer:
    def __init__(self, n_features: int, lam: float = 0.2, shrinkage: float = 0.1,
                 min_samples_before_scoring: int = 5):
        """
        n_features: dimensionality of the feature vector (e.g. 4 for
            [avg_dwell_time, avg_flight_time, avg_mouse_speed, mouse_jitter])
        lam: EWMA smoothing factor, 0 < lam <= 1
        shrinkage: how much to shrink the covariance matrix toward its
            diagonal each update, for numerical stability (0-1)
        min_samples_before_scoring: don't score until the baseline has
            seen at least this many observations, to avoid false
            positives on a cold-start baseline
        """
        if not 0 < lam <= 1:
            raise ValueError("lam must be in (0, 1]")
        if not 0 <= shrinkage <= 1:
            raise ValueError("shrinkage must be in [0, 1]")

        self.n_features = n_features
        self.lam = lam
        self.shrinkage = shrinkage
        self.min_samples_before_scoring = min_samples_before_scoring

        self.mean: np.ndarray | None = None
        self.cov: np.ndarray | None = None
        self.count: int = 0

    def to_state(self) -> dict:
        """Serialize baseline state for persistence (e.g. to Postgres/Redis)."""
        return {
            "mean": self.mean.tolist() if self.mean is not None else None,
            "cov": self.cov.tolist() if self.cov is not None else None,
            "count": self.count,
        }

    @classmethod
    def from_state(cls, state: dict, n_features: int, lam: float = 0.2,
                    shrinkage: float = 0.1) -> "EWMAAnomalyScorer":
        """Rehydrate a scorer from persisted state."""
        scorer = cls(n_features=n_features, lam=lam, shrinkage=shrinkage)
        if state.get("mean") is not None:
            scorer.mean = np.array(state["mean"], dtype=float)
            scorer.cov = np.array(state["cov"], dtype=float)
            scorer.count = state.get("count", 0)
        return scorer

    def update_baseline(self, feature_vector: np.ndarray) -> None:
        """Fold a new observation into the rolling baseline."""
        feature_vector = np.asarray(feature_vector, dtype=float)
        if feature_vector.shape != (self.n_features,):
            raise ValueError(
                f"expected feature vector of shape ({self.n_features},), "
                f"got {feature_vector.shape}"
            )

        if self.mean is None:
            self.mean = feature_vector.copy()
            self.cov = np.eye(self.n_features) * 1e-3
            self.count = 1
            return

        self.count += 1
        prev_mean = self.mean.copy()
        self.mean = self.lam * feature_vector + (1 - self.lam) * self.mean

        deviation = np.outer(feature_vector - prev_mean, feature_vector - prev_mean)
        self.cov = self.lam * deviation + (1 - self.lam) * self.cov

        # Shrinkage toward diagonal for numerical stability / invertibility
        target = np.diag(np.diag(self.cov))
        self.cov = (1 - self.shrinkage) * self.cov + self.shrinkage * target

    def score(self, feature_vector: np.ndarray) -> float:
        """
        Return a risk score in [0, 100]. 0 = perfectly matches baseline,
        100 = maximally anomalous. Returns 0.0 if the baseline isn't
        warm yet (cold start), since we can't judge anomaly without
        enough history.
        """
        if self.mean is None or self.count < self.min_samples_before_scoring:
            return 0.0

        feature_vector = np.asarray(feature_vector, dtype=float)
        diff = feature_vector - self.mean

        try:
            inv_cov = np.linalg.pinv(self.cov)
        except np.linalg.LinAlgError:
            inv_cov = np.eye(self.n_features)

        mahalanobis_sq = float(diff.T @ inv_cov @ diff)
        mahalanobis_sq = max(0.0, mahalanobis_sq)  # guard against fp noise

        # Bounded 0-100 transform. Dividing by 2*n_features roughly
        # normalizes against the expected chi-square mean under H0.
        risk = 1 - np.exp(-mahalanobis_sq / (2 * self.n_features))
        return float(min(100.0, max(0.0, risk * 100)))

    def score_and_update(self, feature_vector: np.ndarray) -> float:
        """Score against the current baseline, then fold the observation
        in. Order matters: we want to flag anomalies against the OLD
        baseline before an attacker's session can pollute it."""
        risk = self.score(feature_vector)
        self.update_baseline(feature_vector)
        return risk
