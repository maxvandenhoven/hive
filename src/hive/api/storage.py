"""Object storage for photos, datasets and models in an S3 bucket.

boto3 blocks, so every request runs in a worker thread and never stalls the event loop.
Only what the app uses is wrapped; uploads and downloads arrive with photos (WP 16).
"""

from functools import partial
from typing import Any

import anyio.to_thread
import boto3
from botocore.config import Config

from hive.api.settings import ApiSettings

S3_CLIENT_CONFIG = Config(
    s3={"addressing_style": "path"},
    connect_timeout=2,
    read_timeout=30,
    retries={"mode": "standard", "max_attempts": 2},
)
"""Path-style addressing as Garage expects, and short connection timeouts and few
retries, so readiness checks and requests fail quickly when the store is down."""


class ObjectStoreError(Exception):
    """Raised when the store reports that an operation failed for some objects."""


class ObjectStore:
    """A flat key-value store of binary objects in an S3 bucket, for example on Garage.

    Attributes:
        client: The boto3 S3 client, which is thread-safe.
        bucket: The bucket name.
    """

    def __init__(self, client: Any, bucket: str) -> None:
        """Create a store on an existing bucket.

        Args:
            client: The boto3 S3 client.
            bucket: The bucket name.
        """
        self.client = client
        self.bucket = bucket

    @classmethod
    def from_settings(cls, settings: ApiSettings) -> "ObjectStore":
        """Create a store from the S3 settings of the service.

        Args:
            settings: The service settings with the endpoint, region, bucket and keys.

        Returns:
            The store, with the client configured by `S3_CLIENT_CONFIG`.
        """
        client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key.get_secret_value(),
            config=S3_CLIENT_CONFIG,
        )

        return cls(client=client, bucket=settings.s3_bucket)

    async def request(self, operation: str, **params: Any) -> Any:
        """Call a client operation on the bucket in a worker thread.

        Args:
            operation: The name of the client method, for example `head_bucket`.
            **params: The parameters of the operation besides `Bucket`.

        Returns:
            The response of the operation.
        """
        method = getattr(self.client, operation)

        return await anyio.to_thread.run_sync(
            partial(method, Bucket=self.bucket, **params)
        )

    async def delete_prefix(self, prefix: str) -> int:
        """Delete every object whose key starts with a prefix.

        Each round lists up to 1000 keys, the most one `DeleteObjects` request takes, and
        deletes them, until no keys are left.

        Args:
            prefix: The key prefix, for example `photos/<game_id>/`.

        Returns:
            The number of deleted objects.

        Raises:
            ObjectStoreError: If the store could not delete some of the objects.
        """
        deleted = 0

        while True:
            page = await self.request("list_objects_v2", Prefix=prefix)
            keys = [{"Key": item["Key"]} for item in page.get("Contents", [])]

            if not keys:
                return deleted

            response = await self.request(
                "delete_objects", Delete={"Objects": keys, "Quiet": True}
            )

            if errors := response.get("Errors"):
                msg = f"Could not delete {len(errors)} objects, for example {errors[0]}."
                raise ObjectStoreError(msg)

            deleted += len(keys)

    async def check(self) -> None:
        """Check that the bucket exists and the keys may access it, for readiness probes.

        Raises:
            botocore.exceptions.ClientError: If the bucket is missing or not accessible.
            botocore.exceptions.EndpointConnectionError: If the endpoint is unreachable.
        """
        await self.request("head_bucket")
