"""Prometheus metrics of the API service: requests, agent decisions and the worker pool.

Every app has its own `ApiMetrics` with its own registry, so apps in one process (as in
tests) do not share counts. Request latency is measured by a plain ASGI middleware rather
than Starlette's `BaseHTTPMiddleware`, which would buffer the thinking streams.
"""

import time

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from hive.api.pool import AgentPool
from hive.match.records import DecisionRecord

METRICS_CONTENT_TYPE = CONTENT_TYPE_LATEST
"""The content type of the Prometheus text format."""

UNMATCHED_ROUTE = "unmatched"
"""The route label of requests that matched no route, so unknown paths add no labels."""

REQUEST_BUCKETS_S = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)
"""The histogram buckets of request durations in seconds, up to long thinking streams."""

DECISION_BUCKETS_S = (0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 60.0)
"""The histogram buckets of decision times in seconds, spanning the usual budgets."""

OVERRUN_BUCKETS_S = (0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0)
"""The histogram buckets of decision overruns in seconds, up to past the grace period."""


class ApiMetrics:
    """The metrics of one app, in a registry of their own.

    Attributes:
        registry: The registry `/metrics` exposes.
        http_request_seconds: Request durations by method, route template and status
            code, until the response body is sent, so a stream counts until it ends.
        decision_seconds: Decision times by agent kind, from sending the state to closing
            the turn.
        decision_overrun_seconds: The seconds past the deadline until the agent returned,
            by agent kind.
        decision_close: Decisions by the reason their turn closed.
        worker_restarts: Worker processes killed and restarted after a decision.
        illegal_submissions: Moves agents submitted that were not legal.
        worker_pool_size: The worker processes in the pool, idle or busy.
        worker_pool_busy: The worker processes lent to a decision.
    """

    def __init__(self) -> None:
        """Create the metrics in a new registry."""
        self.registry = CollectorRegistry(auto_describe=True)
        self.http_request_seconds = Histogram(
            "hive_http_request_seconds",
            "Seconds from receiving a request to sending the end of its response.",
            labelnames=["method", "route", "status"],
            buckets=REQUEST_BUCKETS_S,
            registry=self.registry,
        )
        self.decision_seconds = Histogram(
            "hive_decision_seconds",
            "Seconds from sending the state to an agent to closing its turn.",
            labelnames=["kind"],
            buckets=DECISION_BUCKETS_S,
            registry=self.registry,
        )
        self.decision_overrun_seconds = Histogram(
            "hive_decision_overrun_seconds",
            "Seconds past the deadline until the agent returned or was killed.",
            labelnames=["kind"],
            buckets=OVERRUN_BUCKETS_S,
            registry=self.registry,
        )
        self.decision_close = Counter(
            "hive_decision_close",
            "Decisions by the reason their turn closed.",
            labelnames=["reason"],
            registry=self.registry,
        )
        self.worker_restarts = Counter(
            "hive_worker_restarts",
            "Worker processes killed and restarted after a decision.",
            registry=self.registry,
        )
        self.illegal_submissions = Counter(
            "hive_illegal_submissions",
            "Moves agents submitted that were not legal.",
            registry=self.registry,
        )
        self.worker_pool_size = Gauge(
            "hive_worker_pool_size",
            "Agent worker processes in the pool, idle or busy.",
            registry=self.registry,
        )
        self.worker_pool_busy = Gauge(
            "hive_worker_pool_busy",
            "Agent worker processes lent to a decision.",
            registry=self.registry,
        )

    def observe_request(
        self, method: str, route: str, status_code: int, seconds: float
    ) -> None:
        """Record a handled request.

        Args:
            method: The HTTP method.
            route: The path template of the route, such as `/api/games/{game_id}`.
            status_code: The status code of the response.
            seconds: The seconds until the end of the response was sent.
        """
        self.http_request_seconds.labels(
            method=method, route=route, status=str(status_code)
        ).observe(seconds)

    def observe_decision(self, kind: str, decision: DecisionRecord) -> None:
        """Record a decision that ran to the end of its turn.

        Args:
            kind: The kind of the agent.
            decision: The record of the decision.
        """
        self.decision_seconds.labels(kind=kind).observe(decision.elapsed_s)
        self.decision_overrun_seconds.labels(kind=kind).observe(decision.overrun_s)
        self.decision_close.labels(reason=decision.close_reason.value).inc()
        self.illegal_submissions.inc(decision.illegal_submissions)

        if decision.worker_restarted:
            self.worker_restarts.inc()

    def watch_pool(self, pool: AgentPool) -> None:
        """Read the pool gauges from a pool whenever metrics are collected.

        Args:
            pool: The worker pool of the app.
        """
        self.worker_pool_size.set_function(lambda: pool.size)
        self.worker_pool_busy.set_function(lambda: pool.busy)

    def render(self) -> bytes:
        """Render every metric in the Prometheus text format.

        Returns:
            The text, of the type `METRICS_CONTENT_TYPE`.
        """
        return generate_latest(self.registry)


class HttpMetricsMiddleware:
    """ASGI middleware that records the duration of every HTTP request.

    Requests are labelled by the path template of the route they matched, which the
    router stores in the scope, so path parameters such as game IDs add no labels.

    Attributes:
        app: The app the requests are passed to.
        metrics: The metrics the durations are recorded in.
    """

    def __init__(self, app: ASGIApp, metrics: ApiMetrics) -> None:
        """Wrap an app.

        Args:
            app: The app the requests are passed to.
            metrics: The metrics the durations are recorded in.
        """
        self.app = app
        self.metrics = metrics

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pass a request on and record its duration once the response is sent.

        Args:
            scope: The connection scope.
            receive: Receives messages from the client.
            send: Sends messages to the client.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        # A request that raises before responding becomes a 500 of the server.
        status_code = 500

        async def send_with_status(message: Message) -> None:
            """Note the status code of the response and send the message on.

            Args:
                message: The message to send.
            """
            nonlocal status_code

            if message["type"] == "http.response.start":
                status_code = message["status"]

            await send(message)

        try:
            await self.app(scope, receive, send_with_status)
        finally:
            self.metrics.observe_request(
                method=scope["method"],
                route=getattr(scope.get("route"), "path", None) or UNMATCHED_ROUTE,
                status_code=status_code,
                seconds=time.perf_counter() - start,
            )
