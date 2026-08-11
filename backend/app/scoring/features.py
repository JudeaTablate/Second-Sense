"""
Turns a raw list of client-captured input events into a fixed-length
numeric feature vector the EWMA scorer can consume.

Event schema (sent from the frontend, see frontend/app.js):
  {"type": "keydown" | "keyup" | "mousemove", "timestamp": <ms>, "key": <str>, "x": <int>, "y": <int>}

Features extracted (4-dimensional, deliberately small and interpretable):
  0. avg_dwell_time   - avg time a key is held down (ms)
  1. avg_flight_time  - avg time between releasing one key and pressing next (ms)
  2. avg_mouse_speed  - avg pixels/ms between consecutive mouse samples
  3. mouse_jitter     - stddev of mouse speed (smoothness / shakiness of movement)
"""

from __future__ import annotations

import numpy as np

N_FEATURES = 4
FEATURE_NAMES = ["avg_dwell_time", "avg_flight_time", "avg_mouse_speed", "mouse_jitter"]


def extract_features(events: list[dict]) -> np.ndarray:
    if not events:
        return np.zeros(N_FEATURES)

    keydown_times: dict[str, float] = {}
    dwell_times: list[float] = []
    flight_times: list[float] = []
    last_keyup_time: float | None = None

    for e in sorted(events, key=lambda ev: ev["timestamp"]):
        etype = e.get("type")
        ts = e.get("timestamp")
        key = e.get("key")

        if etype == "keydown" and key is not None:
            keydown_times[key] = ts
            if last_keyup_time is not None:
                flight_times.append(max(0.0, ts - last_keyup_time))
        elif etype == "keyup" and key is not None:
            if key in keydown_times:
                dwell_times.append(max(0.0, ts - keydown_times.pop(key)))
            last_keyup_time = ts

    mouse_points = [
        (e["x"], e["y"], e["timestamp"])
        for e in events
        if e.get("type") == "mousemove" and "x" in e and "y" in e
    ]
    mouse_points.sort(key=lambda p: p[2])

    speeds: list[float] = []
    for (x0, y0, t0), (x1, y1, t1) in zip(mouse_points, mouse_points[1:]):
        dt = max(1.0, t1 - t0)
        dist = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        speeds.append(dist / dt)

    avg_dwell = float(np.mean(dwell_times)) if dwell_times else 0.0
    avg_flight = float(np.mean(flight_times)) if flight_times else 0.0
    avg_speed = float(np.mean(speeds)) if speeds else 0.0
    jitter = float(np.std(speeds)) if len(speeds) > 1 else 0.0

    return np.array([avg_dwell, avg_flight, avg_speed, jitter])
