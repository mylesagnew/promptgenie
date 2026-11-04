from pydantic_settings import BaseSettings, SettingsConfigDict


class ServiceSettings(BaseSettings):
    """Runtime configuration for promptgenie_service, sourced from the environment.

    Kept deliberately small: only what the current sync generate/lint
    endpoints need. Add fields here as later phases wire in real state
    (DATABASE_URL, REDIS_URL, OBJECT_STORAGE_*, OIDC_*, ...).
    """

    model_config = SettingsConfigDict(env_prefix="PROMPTGENIE_", extra="ignore")

    env: str = "development"
    log_level: str = "info"
    # Path to a .promptgenie.yaml to load for every request. If unset, config
    # resolution falls back to searching the process's working directory,
    # matching CLI behavior.
    config_path: str | None = None


def get_settings() -> ServiceSettings:
    return ServiceSettings()
