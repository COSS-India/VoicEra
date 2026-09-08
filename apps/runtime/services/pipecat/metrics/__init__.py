"""Pipecat call metrics collection and persistence."""

from apps.runtime.services.pipecat.metrics.writer import CallMetricsWriter

__all__ = ["CallMetricsWriter", "register_call_metrics"]


def register_call_metrics(*args, **kwargs):
    from apps.runtime.services.pipecat.metrics.observers import (
        register_call_metrics as _register_call_metrics,
    )

    return _register_call_metrics(*args, **kwargs)
