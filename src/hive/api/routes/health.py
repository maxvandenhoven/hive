"""Liveness and readiness probes."""

import logging

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from hive.api.dependencies import DatabaseDependency, StoreDependency

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/healthz")
def read_liveness() -> dict[str, str]:
    """Report that the process is serving requests."""
    return {"status": "ok"}


@router.get("/readyz")
def read_readiness(database: DatabaseDependency, store: StoreDependency) -> JSONResponse:
    """Report whether the database and the object store are reachable.

    Responds with 503 and the failing checks if either is not.
    """
    checks = {"database": database.check, "storage": store.check}
    results = {}

    for name, check in checks.items():
        try:
            check()
        except Exception:
            logger.warning("Readiness check `%s` failed.", name, exc_info=True)
            results[name] = "failed"
        else:
            results[name] = "ok"

    ready = all(result == "ok" for result in results.values())

    return JSONResponse(
        status_code=status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"status": "ready" if ready else "not ready", "checks": results},
    )
