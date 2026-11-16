"""HTTP API adapter around promptgenie.core.

This package contains no business logic — it translates HTTP requests into
calls against ``promptgenie.core`` (the same functions the CLI uses) and
serializes the results back to JSON. Keep it that way: if a rule/behavior
needs to change, it belongs in ``promptgenie.core``, not here.
"""
