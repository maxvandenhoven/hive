"""Route handlers of the API, one module per resource.

The resource routers live under `API_PREFIX`; the health probes stay at the root, where
orchestrators expect them. Each router carries the full prefix itself rather than being
included under a parent prefix, because FastAPI keeps the path of a route relative to the
router that defines it, and the access log and metrics label requests by that path.
"""

API_PREFIX = "/api"
"""The path prefix of every resource route, separating them from the frontend files."""
