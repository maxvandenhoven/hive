"""Object storage for photos, datasets and models, with an S3 and an in-memory store."""

from typing import Any, Protocol

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


class ObjectStore(Protocol):
    """A flat key-value store of binary objects, such as an S3 bucket."""

    def put(self, key: str, data: bytes, content_type: str) -> None:
        """Store an object, replacing any object with the same key.

        Args:
            key: The object key, for example `photos/<game_id>/<photo_id>.jpg`.
            data: The object contents.
            content_type: The media type of the contents, for example `image/jpeg`.
        """
        ...

    def get(self, key: str) -> bytes:
        """Read an object.

        Args:
            key: The object key.

        Returns:
            The object contents.

        Raises:
            ObjectNotFoundError: If there is no object with the key.
        """
        ...

    def delete_prefix(self, prefix: str) -> int:
        """Delete every object whose key starts with a prefix.

        Args:
            prefix: The key prefix, for example `photos/<game_id>/`.

        Returns:
            The number of deleted objects.
        """
        ...

    def check(self) -> None:
        """Check that the store is reachable, for readiness probes.

        Raises:
            Exception: If the store cannot be reached.
        """
        ...


class InMemoryObjectStore:
    """An object store in a dictionary, for tests.

    Attributes:
        objects: The stored contents and media type by key.
    """

    def __init__(self) -> None:
        """Create an empty store."""
        self.objects: dict[str, tuple[bytes, str]] = {}

    def put(self, key: str, data: bytes, content_type: str) -> None:
        """Store an object, replacing any object with the same key.

        Args:
            key: The object key.
            data: The object contents.
            content_type: The media type of the contents.
        """
        self.objects[key] = (data, content_type)

    def get(self, key: str) -> bytes:
        """Read an object.

        Args:
            key: The object key.

        Returns:
            The object contents.

        Raises:
            ObjectNotFoundError: If there is no object with the key.
        """
        if key not in self.objects:
            raise ObjectNotFoundError(key)

        return self.objects[key][0]

    def delete_prefix(self, prefix: str) -> int:
        """Delete every object whose key starts with a prefix.

        Args:
            prefix: The key prefix.

        Returns:
            The number of deleted objects.
        """
        keys = [key for key in self.objects if key.startswith(prefix)]

        for key in keys:
            del self.objects[key]

        return len(keys)

    def check(self) -> None:
        """Do nothing, since an in-memory store is always reachable."""


class S3ObjectStore:
    """An object store in one bucket of an S3 compatible service such as Garage.

    Attributes:
        client: The boto3 S3 client.
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
    def from_settings(cls, settings: ApiSettings) -> "S3ObjectStore":
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

    def put(self, key: str, data: bytes, content_type: str) -> None:
        """Store an object, replacing any object with the same key.

        Args:
            key: The object key.
            data: The object contents.
            content_type: The media type of the contents.
        """
        self.client.put_object(
            Bucket=self.bucket, Key=key, Body=data, ContentType=content_type
        )

    def get(self, key: str) -> bytes:
        """Read an object.

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

    def delete_prefix(self, prefix: str) -> int:
        """Delete every object whose key starts with a prefix.

        Args:
            prefix: The key prefix.

        Returns:
            The number of deleted objects.
        """
        paginator = self.client.get_paginator("list_objects_v2")
        keys = [
            item["Key"]
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix)
            for item in page.get("Contents", [])
        ]

        for start in range(0, len(keys), S3_DELETE_BATCH_SIZE):
            batch = keys[start : start + S3_DELETE_BATCH_SIZE]
            self.client.delete_objects(
                Bucket=self.bucket,
                Delete={"Objects": [{"Key": key} for key in batch], "Quiet": True},
            )

        return len(keys)

    def check(self) -> None:
        """Check that the bucket exists and the keys may access it.

        Raises:
            botocore.exceptions.ClientError: If the bucket is missing or not accessible.
            botocore.exceptions.EndpointConnectionError: If the endpoint is unreachable.
        """
        self.client.head_bucket(Bucket=self.bucket)
