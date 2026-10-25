import pytest
from pydantic import SecretStr

from hive.api.settings import ApiSettings
from hive.api.storage import ObjectNotFoundError, ObjectStore

pytestmark = pytest.mark.anyio


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


async def test_put_get_and_replace(store: ObjectStore) -> None:
    await store.put(key="a", data=b"1", content_type="text/plain")
    await store.put(key="a", data=b"2", content_type="text/plain")
    response = store.client.head_object(Bucket=store.bucket, Key="a")

    assert await store.get("a") == b"2"
    assert response["ContentType"] == "text/plain"


async def test_get_missing(store: ObjectStore) -> None:
    with pytest.raises(ObjectNotFoundError):
        await store.get("missing")


async def test_delete_prefix_in_batches(
    store: ObjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("hive.api.storage.S3_DELETE_BATCH_SIZE", 2)

    for key in ("photos/a/1.jpg", "photos/a/2.jpg", "photos/a/3.jpg", "photos/ab/1.jpg"):
        await store.put(key=key, data=b"", content_type="image/jpeg")

    assert await store.delete_prefix("photos/a/") == 3
    assert await store.list_keys() == ["photos/ab/1.jpg"]


async def test_delete_prefix_without_objects(store: ObjectStore) -> None:
    assert await store.delete_prefix("photos/a/") == 0


async def test_check(store: ObjectStore) -> None:
    await store.check()
    store.client.delete_bucket(Bucket=store.bucket)

    with pytest.raises(store.client.exceptions.ClientError):
        await store.check()
