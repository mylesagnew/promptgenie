from promptgenie.core.config import PromptGenieConfig, load_config
from promptgenie_service.settings import get_settings


def resolve_config(no_config: bool, best_effort: bool) -> PromptGenieConfig:
    """Server-side mirror of the CLI's config resolution (see commands/generate.py).

    The API has no per-request working directory, so config comes from
    PROMPTGENIE_CONFIG_PATH (settings.config_path) rather than a CLI cwd
    search, unless the caller passes no_config=True.
    """
    if no_config:
        return PromptGenieConfig()
    try:
        return load_config(get_settings().config_path)
    except (FileNotFoundError, ValueError):
        if best_effort:
            return PromptGenieConfig()
        raise
