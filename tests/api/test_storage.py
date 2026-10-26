import pytest
from pydantic import SecretStr

from hive.api.settings import ApiSettings
from hive.api.storage import ObjectStore, ObjectStoreError

pytestmark = pytest.mark.anyio


def put(store: ObjectStore, *keys: str) -> None:
    """Store empty objects under some keys."""
    for key in keys:
        store.client.put_object(Bucket=store.bucket, Key=key, Body=b"")


def list_keys(store: ObjectStore) -> list[str]:
    """List the keys of every object in the store."""
    response = store.client.list_objects_v2(Bucket=store.bucket)

    return [item["Key"] for item in response.get("Contents", [])]


def test_from_settings() -> None:
    settings = ApiSettings(
        _env_file=None,
        database_url="postgresql+psycopg://u@db.invalid/x",
        s3_endpoint_url="http://s3.invalid:3900",
        s3_access_key_id="key",
        s3_secret_access_key=SecretStr("secret"),
    )
    store = ObjectStore.from_settings(settings)

    assert store.bucket == "hive"
    assert store.client.meta.endpoint_url == "http://s3.invalid:3900"
    assert store.client.meta.region_name == "garage"


async def test_delete_prefix(store: ObjectStore) -> None:
    put(store, "photos/a/1.jpg", "photos/a/2.jpg", "photos/ab/1.jpg")

    assert await store.delete_prefix("photos/a/") == 2
    assert list_keys(store) == ["photos/ab/1.jpg"]


async def test_delete_prefix_in_rounds(store: ObjectStore) -> None:
    put(store, *(f"photos/a/{index:04}.jpg" for index in range(1001)))

    assert await store.delete_prefix("photos/a/") == 1001
    assert list_keys(store) == []


async def test_delete_prefix_without_objects(store: ObjectStore) -> None:
    assert await store.delete_prefix("photos/a/") == 0


async def test_delete_prefix_reports_failed_objects(
    store: ObjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    put(store, "photos/a/1.jpg")
    monkeypatch.setattr(
        store.client,
        "delete_objects",
        lambda **_: {"Errors": [{"Key": "photos/a/1.jpg", "Code": "AccessDenied"}]},
    )

    with pytest.raises(ObjectStoreError, match="AccessDenied"):
        await store.delete_prefix("photos/a/")


async def test_check(store: ObjectStore) -> None:
    await store.check()
    store.client.delete_bucket(Bucket=store.bucket)

    with pytest.raises(store.client.exceptions.ClientError):
        await store.check()
