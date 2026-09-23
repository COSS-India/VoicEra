"""Rate limiting and call-admission primitives.

See docs/developer/rate-limiting-plan.md. This package is additive — nothing
here changes behaviour unless a route wires in a dependency from ``deps.py``,
and nothing takes effect unless ``settings.RATE_LIMIT_ENABLED`` is true.
"""
