"""Liveness and readiness probes."""

import logging

from fastapi import APIRouter, Response, status

from hive.api.dependencies import DatabaseDependency, StoreDependency
from hive.api.schemas import HealthCheckResult, LivenessReport, ReadinessReport

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/healthz", description="Report that the process is serving requests.")
async def read_liveness() -> LivenessReport:
    """Report that the process is serving requests.

    Returns:
        The status `ok`.
    """
    return LivenessReport()


@router.get(
    "/readyz",
    description="Report whether the database and the object store are reachable. "
    "Responds with 503 and the failing checks if either is not.",
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": ReadinessReport,
            "description": "A check failed.",
        }
    },
)
async def read_readiness(
    database: DatabaseDependency, store: StoreDependency, response: Response
) -> ReadinessReport:
    """Report whether the database and the object store are reachable.

    Args:
        database: The database of the app.
        store: The object store of the app.
        response: The response, whose status code is set to 503 if a check failed.

    Returns:
        The overall status and the result of each check.
    """
    checks = {"database": database.check, "storage": store.check}
    results: dict[str, HealthCheckResult] = {}

    for name, check in checks.items():
        try:
            await check()
        except Exception:
            logger.warning("Readiness check `%s` failed.", name, exc_info=True)
            results[name] = "failed"
        else:
            results[name] = "ok"

    report = ReadinessReport.from_checks(results)

    if report.status != "ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return report
