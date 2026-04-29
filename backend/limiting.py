"""Shared rate limiter so routers can `@limiter.limit(...)` without
introducing a circular import on `main.py`.

Note: slowapi's default backend is in-process memory — it doesn't share
state across workers or across restarts. Acceptable for single-instance
deployments and small teams; switch to a Redis backend for larger fleets.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
