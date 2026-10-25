import io

import pytest
from botocore.response import StreamingBody
from botocore.stub import Stubber
from pydantic import SecretStr

from hive.api.settings import ApiSettings
from hive.api.storage import InMemoryObjectStore, ObjectNotFoundError, S3ObjectStore


class TestInMemoryObjectStore:
    def test_put_get_and_replace(self) -> None:
        store = InMemoryObjectStore()
        store.put(key="a", data=b"1", content_type="text/plain")
        store.put(key="a", data=b"2", content_type="text/plain")

        assert store.get("a") == b"2"

    def test_get_missing(self) -> None:
        with pytest.raises(ObjectNotFoundError):
            InMemoryObjectStore().get("missing")

    def test_delete_prefix(self) -> None:
        store = InMemoryObjectStore()

        for key in ("photos/a/1.jpg", "photos/a/2.jpg", "photos/ab/1.jpg"):
            store.put(key=key, data=b"", content_type="image/jpeg")

        assert store.delete_prefix("photos/a/") == 2
        assert list(store.objects) == ["photos/ab/1.jpg"]

    def test_check(self) -> None:
        InMemoryObjectStore().check()


@pytest.fixture(scope="function")
def s3_store() -> S3ObjectStore:
    """Build an S3 store on a client that makes no requests outside a stubber."""
    settings = ApiSettings(
        s3_endpoint_url="http://s3.invalid:3900",
        s3_access_key_id="key",
        s3_secret_access_key=SecretStr("secret"),
    )
    return S3ObjectStore.from_settings(settings)


class TestS3ObjectStore:
    def test_from_settings(self, s3_store: S3ObjectStore) -> None:
        assert s3_store.bucket == "hive"
        assert s3_store.client.meta.endpoint_url == "http://s3.invalid:3900"
        assert s3_store.client.meta.region_name == "garage"

    def test_put_and_get(self, s3_store: S3ObjectStore) -> None:
        with Stubber(s3_store.client) as stubber:
            stubber.add_response(
                "put_object",
                {},
                {
                    "Bucket": "hive",
                    "Key": "k",
                    "Body": b"data",
                    "ContentType": "image/jpeg",
                },
            )
            stubber.add_response(
                "get_object",
                {"Body": StreamingBody(io.BytesIO(b"data"), 4)},
                {"Bucket": "hive", "Key": "k"},
            )
            s3_store.put(key="k", data=b"data", content_type="image/jpeg")

            assert s3_store.get("k") == b"data"

    def test_get_missing(self, s3_store: S3ObjectStore) -> None:
        with Stubber(s3_store.client) as stubber:
            stubber.add_client_error("get_object", service_error_code="NoSuchKey")

            with pytest.raises(ObjectNotFoundError):
                s3_store.get("k")

    def test_delete_prefix_in_batches(
        self, s3_store: S3ObjectStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("hive.api.storage.S3_DELETE_BATCH_SIZE", 2)
        keys = ["p/1", "p/2", "p/3"]

        with Stubber(s3_store.client) as stubber:
            stubber.add_response(
                "list_objects_v2",
                {"Contents": [{"Key": key} for key in keys], "IsTruncated": False},
                {"Bucket": "hive", "Prefix": "p/"},
            )

            for batch in (keys[:2], keys[2:]):
                stubber.add_response(
                    "delete_objects",
                    {},
                    {
                        "Bucket": "hive",
                        "Delete": {
                            "Objects": [{"Key": key} for key in batch],
                            "Quiet": True,
                        },
                    },
                )

            assert s3_store.delete_prefix("p/") == 3
            stubber.assert_no_pending_responses()

    def test_delete_prefix_without_objects(self, s3_store: S3ObjectStore) -> None:
        with Stubber(s3_store.client) as stubber:
            stubber.add_response("list_objects_v2", {"IsTruncated": False})

            assert s3_store.delete_prefix("p/") == 0

    def test_check(self, s3_store: S3ObjectStore) -> None:
        with Stubber(s3_store.client) as stubber:
            stubber.add_response("head_bucket", {}, {"Bucket": "hive"})
            s3_store.check()
            stubber.add_client_error("head_bucket", http_status_code=404)

            with pytest.raises(s3_store.client.exceptions.ClientError):
                s3_store.check()
