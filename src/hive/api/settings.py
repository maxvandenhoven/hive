"""Settings of the API service, read from `HIVE_` environment variables."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiSettings(BaseSettings):
    """The configuration of the API service.

    Every field is read from an environment variable with the `HIVE_` prefix, for example
    `HIVE_DATABASE_URL`. The defaults match the local stack in `deploy/compose.yaml`, so
    `make dev` needs no configuration.

    Attributes:
        database_url: The SQLAlchemy URL of the Postgres database, using psycopg 3.
        s3_endpoint_url: The URL of the S3 API of the object store.
        s3_region: The region name the object store expects in signed requests.
        s3_bucket: The bucket holding photos, datasets and models.
        s3_access_key_id: The access key ID for the bucket.
        s3_secret_access_key: The secret access key for the bucket.
        log_level: The level of the root logger, for example `INFO`.
    """

    model_config = SettingsConfigDict(env_prefix="HIVE_")

    database_url: str = "postgresql+psycopg://hive:hive@localhost:5432/hive"
    s3_endpoint_url: str = "http://localhost:3900"
    s3_region: str = "garage"
    s3_bucket: str = "hive"
    s3_access_key_id: str = "GK0123456789abcdef01234567"
    s3_secret_access_key: SecretStr = SecretStr(
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    )
    log_level: str = "INFO"
