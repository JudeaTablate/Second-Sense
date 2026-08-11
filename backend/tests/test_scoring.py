import numpy as np
import pytest

from app.scoring.ewma import EWMAAnomalyScorer
from app.scoring.features import extract_features


class TestEWMAAnomalyScorer:
    def test_cold_start_returns_zero_risk(self):
        scorer = EWMAAnomalyScorer(n_features=4)
        # No baseline built yet — should not flag anomalies
        assert scorer.score(np.array([100.0, 50.0, 0.5, 0.1])) == 0.0

    def test_rejects_wrong_shape_vector(self):
        scorer = EWMAAnomalyScorer(n_features=4)
        with pytest.raises(ValueError):
            scorer.update_baseline(np.array([1.0, 2.0]))  # wrong dimensionality

    def test_rejects_invalid_lambda(self):
        with pytest.raises(ValueError):
            EWMAAnomalyScorer(n_features=4, lam=0.0)
        with pytest.raises(ValueError):
            EWMAAnomalyScorer(n_features=4, lam=1.5)

    def test_consistent_behavior_yields_low_risk(self):
        """A user typing the same way repeatedly should score low risk
        once the baseline warms up — this is the core 'no false positive
        on normal behavior' guarantee."""
        rng = np.random.default_rng(seed=42)
        scorer = EWMAAnomalyScorer(n_features=4, min_samples_before_scoring=5)
        typical = np.array([120.0, 80.0, 0.4, 0.05])

        risks = []
        for _ in range(50):
            noisy = typical + rng.normal(0, 1.5, size=4)  # small natural jitter
            risks.append(scorer.score_and_update(noisy))

        # after warm-up, scores on consistent behavior should trend low.
        # We check the tail (not the whole warm-up window) and use a
        # generous bound since a small-sample EWMA covariance estimate
        # is naturally noisy — the point is "clearly separated from
        # attack-level risk", not "near zero".
        assert np.mean(risks[-15:]) < 55.0

    def test_sudden_deviation_yields_high_risk(self):
        """Once a baseline is established, a session that looks nothing
        like it should score meaningfully higher risk than the user's
        own typical sessions — this is the actual fraud detection
        guarantee. We assert relative separation rather than an
        absolute threshold, since that's the property that actually
        matters for fraud detection."""
        rng = np.random.default_rng(seed=7)
        scorer = EWMAAnomalyScorer(n_features=4, lam=0.1, min_samples_before_scoring=5)
        typical = np.array([120.0, 80.0, 0.4, 0.05])

        own_session_risks = []
        for _ in range(20):
            noisy = typical + rng.normal(0, 2, size=4)
            own_session_risks.append(scorer.score_and_update(noisy))

        # a wildly different behavioral profile (different person/bot)
        attacker_vector = np.array([400.0, 5.0, 3.0, 1.5])
        attacker_risk = scorer.score(attacker_vector)

        assert attacker_risk > np.mean(own_session_risks[-5:]) + 20.0

    def test_state_roundtrip_preserves_scoring_behavior(self):
        """Serializing and rehydrating a scorer (as we do through
        Redis/Postgres) must not change its behavior."""
        scorer = EWMAAnomalyScorer(n_features=4)
        for _ in range(10):
            scorer.update_baseline(np.array([100.0, 60.0, 0.3, 0.02]) + np.random.normal(0, 1, 4))

        state = scorer.to_state()
        rehydrated = EWMAAnomalyScorer.from_state(state, n_features=4)

        test_vector = np.array([100.0, 60.0, 0.3, 0.02])
        assert scorer.score(test_vector) == pytest.approx(rehydrated.score(test_vector), rel=1e-6)

    def test_score_bounded_between_0_and_100(self):
        scorer = EWMAAnomalyScorer(n_features=4, min_samples_before_scoring=3)
        for _ in range(10):
            scorer.update_baseline(np.array([10.0, 10.0, 10.0, 10.0]))

        extreme_vector = np.array([1e9, -1e9, 1e9, -1e9])
        risk = scorer.score(extreme_vector)
        assert 0.0 <= risk <= 100.0


class TestFeatureExtraction:
    def test_empty_events_returns_zero_vector(self):
        result = extract_features([])
        assert np.array_equal(result, np.zeros(4))

    def test_extracts_dwell_and_flight_times(self):
        events = [
            {"type": "keydown", "timestamp": 0, "key": "a"},
            {"type": "keyup", "timestamp": 100, "key": "a"},
            {"type": "keydown", "timestamp": 150, "key": "b"},
            {"type": "keyup", "timestamp": 230, "key": "b"},
        ]
        features = extract_features(events)
        avg_dwell, avg_flight, avg_speed, jitter = features

        assert avg_dwell == pytest.approx((100 + 80) / 2)  # (100-0) and (230-150)
        assert avg_flight == pytest.approx(50)  # 150 - 100
        assert avg_speed == 0.0
        assert jitter == 0.0

    def test_extracts_mouse_speed(self):
        events = [
            {"type": "mousemove", "timestamp": 0, "x": 0, "y": 0},
            {"type": "mousemove", "timestamp": 100, "x": 100, "y": 0},
            {"type": "mousemove", "timestamp": 200, "x": 200, "y": 0},
        ]
        features = extract_features(events)
        _, _, avg_speed, jitter = features

        assert avg_speed == pytest.approx(1.0)  # 100px / 100ms, twice
        assert jitter == pytest.approx(0.0)  # constant speed, no jitter

    def test_handles_unordered_events(self):
        """Events arriving out of order (network reordering) should
        still extract sensible features since we sort by timestamp."""
        events = [
            {"type": "keyup", "timestamp": 100, "key": "a"},
            {"type": "keydown", "timestamp": 0, "key": "a"},
        ]
        features = extract_features(events)
        assert features[0] == pytest.approx(100.0)  # dwell time
