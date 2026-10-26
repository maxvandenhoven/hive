"""Settings of the API service, read from `HIVE_` environment variables or `.env`."""

from pathlib import Path

from alembic.config import Config
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

MIGRATIONS_LOCATION = "hive.api.db:migrations"
"""The Alembic script location, as a package resource so it works when installed."""


class DatabaseSettings(BaseSettings):
    """The database configuration, which is all that migrations need.

    Read from `HIVE_DATABASE_URL` or a `.env` file in the working directory. There is no
    default, so a deployment cannot silently fall back to development credentials;
    `make dev` creates `.env` from `.env.example`, which matches `deploy/compose.yaml`.

    Attributes:
        database_url: The SQLAlchemy URL of the Postgres database, using psycopg 3. The
            same URL serves the async app and the synchronous migrations.
    """

    model_config = SettingsConfigDict(
        env_prefix="HIVE_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str

    def alembic_config(self) -> Config:
        """Build the Alembic configuration for migrating the database.

        Returns:
            The configuration, with the packaged migrations and the database URL.
        """
        config = Config()
        config.set_main_option("script_location", MIGRATIONS_LOCATION)
        config.attributes["database_url"] = self.database_url

        return config


class ApiSettings(DatabaseSettings):
    """The configuration of the API service.

    Every field is read from an environment variable with the `HIVE_` prefix, for example
    `HIVE_S3_BUCKET`, or from `.env`. The connection settings have no defaults.

    Attributes:
        s3_endpoint_url: The URL of the S3 API of the object store.
        s3_region: The region name the object store expects in signed requests.
        s3_bucket: The bucket holding photos, datasets and models.
        s3_access_key_id: The access key ID for the bucket.
        s3_secret_access_key: The secret access key for the bucket.
        log_level: The level of the root logger, for example `INFO`.
        pool_size: The most agent worker processes kept at once, idle or busy.
        pool_wait_s: The seconds a thinking request waits for a free worker before it
            fails with 503.
        max_budget_s: The longest time budget of one decision in seconds; longer budgets
            are shortened to it.
        frontend_dir: The built frontend, served at `/` with a fallback to `index.html`
            for client-side routes. Relative paths start at the working directory. If it
            is `None` or does not exist, only the API is served.
    """

    s3_endpoint_url: str
    s3_region: str = "garage"
    s3_bucket: str = "hive"
    s3_access_key_id: str
    s3_secret_access_key: SecretStr
    log_level: str = "INFO"
    pool_size: int = Field(default=2, ge=1)
    pool_wait_s: float = Field(default=10.0, ge=0.0)
    max_budget_s: float = Field(default=30.0, gt=0.0)
    frontend_dir: Path | None = Path("frontend/dist")
