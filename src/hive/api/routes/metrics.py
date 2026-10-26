"""The Prometheus metrics endpoint."""

from fastapi import APIRouter, Response, status

from hive.api.dependencies import MetricsDependency
from hive.api.metrics import METRICS_CONTENT_TYPE

router = APIRouter(tags=["metrics"])


@router.get(
    "/metrics",
    response_class=Response,
    description="Expose the metrics of the service in the Prometheus text format.",
    responses={
        status.HTTP_200_OK: {
            "description": "The metrics.",
            "content": {METRICS_CONTENT_TYPE: {"schema": {"type": "string"}}},
        }
    },
)
async def read_metrics(metrics: MetricsDependency) -> Response:
    """Expose the metrics of the service in the Prometheus text format.

    Args:
        metrics: The metrics of the app.

    Returns:
        The metrics as text.
    """
    return Response(content=metrics.render(), media_type=METRICS_CONTENT_TYPE)
