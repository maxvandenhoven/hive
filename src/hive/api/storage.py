"""Object storage for photos, datasets and models in an S3 bucket.

boto3 blocks, so every request runs in a worker thread and never stalls the event loop.
"""

from functools import partial
from typing import Any

import anyio.to_thread
import boto3
from botocore.config import Config

from hive.api.settings import ApiSettings

S3_DELETE_BATCH_SIZE = 1000
"""The most keys one S3 `DeleteObjects` request may delete."""

S3_CLIENT_CONFIG = Config(
    s3={"addressing_style": "path"},
    connect_timeout=2,
    read_timeout=30,
    retries={"mode": "standard", "max_attempts": 2},
)
"""Path-style addressing as Garage expects, and short connection timeouts and few
retries, so readiness checks and requests fail quickly when the store is down."""


class ObjectNotFoundError(KeyError):
    """Raised when an object key does not exist in the store."""


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

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        """Store an object, replacing any object with the same key.

        Args:
            key: The object key, for example `photos/<game_id>/<photo_id>.jpg`.
            data: The object contents.
            content_type: The media type of the contents, for example `image/jpeg`.
        """
        await anyio.to_thread.run_sync(
            partial(
                self.client.put_object,
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
        )

    async def get(self, key: str) -> bytes:
        """Read an object.

        Args:
            key: The object key.

        Returns:
            The object contents.

        Raises:
            ObjectNotFoundError: If there is no object with the key.
        """
        return await anyio.to_thread.run_sync(self.get_blocking, key)

    def get_blocking(self, key: str) -> bytes:
        """Read an object in the calling thread.

        Args:
            key: The object key.

        Returns:
            The object contents.

        Raises:
            ObjectNotFoundError: If there is no object with the key.
        """
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except self.client.exceptions.NoSuchKey as e:
            raise ObjectNotFoundError(key) from e

        return response["Body"].read()

    async def delete_prefix(self, prefix: str) -> int:
        """Delete every object whose key starts with a prefix.

        Args:
            prefix: The key prefix, for example `photos/<game_id>/`.

        Returns:
            The number of deleted objects.
        """
        return await anyio.to_thread.run_sync(self.delete_prefix_blocking, prefix)

    def delete_prefix_blocking(self, prefix: str) -> int:
        """Delete every object whose key starts with a prefix, in the calling thread.

        Args:
            prefix: The key prefix.

        Returns:
            The number of deleted objects.
        """
        keys = self.list_keys_blocking(prefix)

        for start in range(0, len(keys), S3_DELETE_BATCH_SIZE):
            batch = keys[start : start + S3_DELETE_BATCH_SIZE]
            self.client.delete_objects(
                Bucket=self.bucket,
                Delete={"Objects": [{"Key": key} for key in batch], "Quiet": True},
            )

        return len(keys)

    async def list_keys(self, prefix: str = "") -> list[str]:
        """List the keys of the objects whose key starts with a prefix.

        Args:
            prefix: The key prefix, or `""` for every object.

        Returns:
            The keys in lexicographic order.
        """
        return await anyio.to_thread.run_sync(self.list_keys_blocking, prefix)

    def list_keys_blocking(self, prefix: str = "") -> list[str]:
        """List the keys of the objects under a prefix, in the calling thread.

        Args:
            prefix: The key prefix, or `""` for every object.

        Returns:
            The keys in lexicographic order.
        """
        paginator = self.client.get_paginator("list_objects_v2")

        return [
            item["Key"]
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix)
            for item in page.get("Contents", [])
        ]

    async def check(self) -> None:
        """Check that the bucket exists and the keys may access it, for readiness probes.

        Raises:
            botocore.exceptions.ClientError: If the bucket is missing or not accessible.
            botocore.exceptions.EndpointConnectionError: If the endpoint is unreachable.
        """
        await anyio.to_thread.run_sync(
            partial(self.client.head_bucket, Bucket=self.bucket)
        )
