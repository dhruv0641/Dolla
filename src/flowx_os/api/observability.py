"""Privacy-conscious, process-local HTTP request metrics."""

from __future__ import annotations

from threading import Lock


_DURATION_BUCKETS_MS = (50, 100, 250, 500, 1000, 2500, 5000)
_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"})


class RequestMetrics:
    """Bounded-cardinality request counters and duration buckets."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._series: dict[tuple[str, str, str], dict[str, object]] = {}

    def observe(self, *, method: str, route: str, status_code: int, duration_ms: float) -> None:
        safe_method = method if method in _METHODS else "OTHER"
        safe_route = route if route.startswith("/") and "{" in route or route.startswith("/") and "?" not in route else "unmatched"
        status_class = f"{status_code // 100}xx" if 100 <= status_code <= 599 else "other"
        key = (safe_method, safe_route[:200], status_class)
        with self._lock:
            series = self._series.setdefault(
                key,
                {"count": 0, "duration_ms_sum": 0.0, "duration_ms_buckets": {str(bound): 0 for bound in _DURATION_BUCKETS_MS}, "duration_ms_inf": 0},
            )
            series["count"] = int(series["count"]) + 1
            series["duration_ms_sum"] = float(series["duration_ms_sum"]) + max(0.0, duration_ms)
            buckets = series["duration_ms_buckets"]
            assert isinstance(buckets, dict)
            for bound in _DURATION_BUCKETS_MS:
                if duration_ms <= bound:
                    buckets[str(bound)] = int(buckets[str(bound)]) + 1
            series["duration_ms_inf"] = int(series["duration_ms_inf"]) + 1

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            observations = [
                {
                    "method": method,
                    "route": route,
                    "status_class": status_class,
                    **{
                        "count": values["count"],
                        "duration_ms_sum": round(float(values["duration_ms_sum"]), 3),
                        "duration_ms_buckets": dict(values["duration_ms_buckets"]),
                        "duration_ms_inf": values["duration_ms_inf"],
                    },
                }
                for (method, route, status_class), values in sorted(self._series.items())
            ]
        return {"scope": "process_lifetime", "requests": observations}
