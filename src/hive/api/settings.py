"""Settings of the API service, read from `HIVE_` environment variables or `.env`."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiSettings(BaseSettings):
    """The configuration of the API service.

    Every field is read from an environment variable with the `HIVE_` prefix, for example
    `HIVE_DATABASE_URL`, or from a `.env` file in the working directory. The connection
    settings have no defaults, so a deployment cannot silently fall back to development
    credentials; `make dev` creates `.env` from `.env.example`, which matches the local
    stack in `deploy/compose.yaml`.

    Attributes:
        database_url: The SQLAlchemy URL of the Postgres database, using psycopg 3.
        s3_endpoint_url: The URL of the S3 API of the object store.
        s3_region: The region name the object store expects in signed requests.
        s3_bucket: The bucket holding photos, datasets and models.
        s3_access_key_id: The access key ID for the bucket.
        s3_secret_access_key: The secret access key for the bucket.
        log_level: The level of the root logger, for example `INFO`.
    """

    model_config = SettingsConfigDict(
        env_prefix="HIVE_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str
    s3_endpoint_url: str
    s3_region: str = "garage"
    s3_bucket: str = "hive"
    s3_access_key_id: str
    s3_secret_access_key: SecretStr
    log_level: str = "INFO"
