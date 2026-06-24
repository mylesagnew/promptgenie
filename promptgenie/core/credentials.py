"""credentials.py — credential resolution and secure storage.

Resolution order (highest priority first)
------------------------------------------
1. Environment variable (e.g. ANTHROPIC_API_KEY)
2. Keyring / system credential store (macOS Keychain, Windows Credential Manager,
   SecretService on Linux) — requires ``pip install promptgenie[secrets]``
3. Plaintext config reference in providers.yaml (api_key field — not recommended)
4. Interactive prompt (non-CI only)

Stored credential references use the format::

  keyring:<service>:<account>

where ``service`` is "promptgenie" and ``account`` is the provider name.

Public API
----------
  ``store_credential(provider, key)``   → None  (saves to keyring)
  ``get_credential(provider)``          → str | None
  ``delete_credential(provider)``       → bool
  ``list_stored_credentials()``         → list[str]  (provider names)
  ``is_keyring_available()``            → bool
"""

from __future__ import annotations

import os
from pathlib import Path

_KEYRING_SERVICE = "promptgenie"


def is_keyring_available() -> bool:
    """Return True if the keyring package is installed and functional."""
    try:
        import keyring  # type: ignore[import-untyped]
        # Test that a backend is available
        keyring.get_keyring()
        return True
    except (ImportError, Exception):
        return False


def store_credential(provider: str, api_key: str) -> None:
    """Store *api_key* for *provider* in the system keyring.

    Raises ImportError if keyring is not installed.
    """
    try:
        import keyring  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError(
            "keyring is not installed. Install it with: pip install 'promptgenie[secrets]'"
        ) from exc
    keyring.set_password(_KEYRING_SERVICE, provider, api_key)


def get_credential(provider: str) -> str | None:
    """Return the stored API key for *provider*, or None if not found.

    Resolution order:
    1. Environment variable (provider config's api_key_env)
    2. Keyring
    """
    from promptgenie.core.providers import load_providers_config
    configs = load_providers_config()
    cfg = configs.get(provider)

    # 1. Environment variable
    if cfg and cfg.api_key_env:
        val = os.environ.get(cfg.api_key_env)
        if val:
            return val

    # 2. Keyring
    try:
        import keyring  # type: ignore[import-untyped]
        val = keyring.get_password(_KEYRING_SERVICE, provider)
        if val:
            return val
    except (ImportError, Exception):
        pass

    # 3. Direct api_key in config — may be a ref: pointer or a raw key
    if cfg and cfg.api_key:
        if cfg.api_key.startswith(_REF_PREFIX):
            return resolve_credential_ref(cfg.api_key)
        return cfg.api_key

    return None


def delete_credential(provider: str) -> bool:
    """Delete the stored credential for *provider*. Returns True if deleted."""
    try:
        import keyring  # type: ignore[import-untyped]
        existing = keyring.get_password(_KEYRING_SERVICE, provider)
        if existing:
            keyring.delete_password(_KEYRING_SERVICE, provider)
            return True
    except (ImportError, Exception):
        pass
    return False


def list_stored_credentials() -> list[str]:
    """Return provider names that have credentials stored in the keyring."""
    try:
        import keyring  # type: ignore[import-untyped]
        from promptgenie.core.providers import load_providers_config
        providers = load_providers_config()
        stored = []
        for name in providers:
            val = keyring.get_password(_KEYRING_SERVICE, name)
            if val:
                stored.append(name)
        return stored
    except (ImportError, Exception):
        return []


# ---------------------------------------------------------------------------
# External secret manager backends
# ---------------------------------------------------------------------------

# A credential reference stored in providers.yaml looks like:
#   api_key: "ref:aws-ssm:/promptgenie/anthropic/api_key"
# get_credential() resolves these at runtime.

_REF_PREFIX = "ref:"


def resolve_credential_ref(ref: str) -> str | None:
    """Resolve a stored secret reference (e.g. ``ref:aws-ssm:/path``).

    Supported schemes:
    * ``ref:aws-ssm:<parameter-path>``        — AWS Systems Manager Parameter Store
    * ``ref:gcp-secret:<project/secret>``     — GCP Secret Manager
    * ``ref:azure-kv:<vault>/<secret>``       — Azure Key Vault
    * ``ref:1password:<vault>/<item>/<field>`` — 1Password CLI (op)
    """
    if not ref.startswith(_REF_PREFIX):
        return ref  # treat as literal value

    scheme_path = ref[len(_REF_PREFIX):]

    if scheme_path.startswith("aws-ssm:"):
        return _resolve_aws_ssm(scheme_path[len("aws-ssm:"):])
    if scheme_path.startswith("gcp-secret:"):
        return _resolve_gcp_secret(scheme_path[len("gcp-secret:"):])
    if scheme_path.startswith("azure-kv:"):
        return _resolve_azure_kv(scheme_path[len("azure-kv:"):])
    if scheme_path.startswith("1password:"):
        return _resolve_1password(scheme_path[len("1password:"):])

    return None


def _resolve_aws_ssm(parameter_path: str) -> str | None:
    try:
        import boto3  # type: ignore[import-untyped]
        ssm = boto3.client("ssm")
        resp = ssm.get_parameter(Name=parameter_path, WithDecryption=True)
        return resp["Parameter"]["Value"]
    except ImportError as exc:
        raise ImportError(
            "boto3 is required for AWS SSM credential resolution. pip install boto3"
        ) from exc
    except Exception as exc:
        raise RuntimeError(f"AWS SSM fetch failed for '{parameter_path}': {exc}") from exc


def _resolve_gcp_secret(resource: str) -> str | None:
    try:
        from google.cloud import secretmanager  # type: ignore[import-untyped]
        client = secretmanager.SecretManagerServiceClient()
        if resource.startswith("projects/"):
            name = resource if resource.endswith("/versions/latest") else resource + "/versions/latest"
        else:
            parts = resource.split("/", 1)
            if len(parts) != 2:
                raise ValueError(f"Invalid GCP secret resource: {resource!r}. Use project/secret.")
            name = f"projects/{parts[0]}/secrets/{parts[1]}/versions/latest"
        resp = client.access_secret_version(request={"name": name})
        return resp.payload.data.decode("utf-8").strip()
    except ImportError as exc:
        raise ImportError(
            "google-cloud-secret-manager required. pip install google-cloud-secret-manager"
        ) from exc
    except Exception as exc:
        raise RuntimeError(f"GCP Secret Manager fetch failed for '{resource}': {exc}") from exc


def _resolve_azure_kv(path: str) -> str | None:
    try:
        from azure.keyvault.secrets import SecretClient  # type: ignore[import-untyped]
        from azure.identity import DefaultAzureCredential  # type: ignore[import-untyped]
        parts = path.split("/", 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid Azure Key Vault path: {path!r}. Use vault/secret.")
        vault_name, secret_name = parts
        client = SecretClient(
            vault_url=f"https://{vault_name}.vault.azure.net",
            credential=DefaultAzureCredential(),
        )
        return client.get_secret(secret_name).value
    except ImportError as exc:
        raise ImportError(
            "azure-keyvault-secrets and azure-identity required. "
            "pip install azure-keyvault-secrets azure-identity"
        ) from exc
    except Exception as exc:
        raise RuntimeError(f"Azure Key Vault fetch failed for '{path}': {exc}") from exc


def _resolve_1password(path: str) -> str | None:
    import subprocess
    parts = path.split("/")
    if len(parts) < 3:
        raise ValueError(f"Invalid 1Password path: {path!r}. Use vault/item/field.")
    vault, item, field = parts[0], parts[1], "/".join(parts[2:])
    try:
        result = subprocess.run(
            ["op", "read", f"op://{vault}/{item}/{field}"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "op CLI returned non-zero exit code")
        return result.stdout.strip()
    except FileNotFoundError as exc:
        raise ImportError(
            "1Password CLI ('op') not found in PATH. "
            "Install from https://1password.com/downloads/command-line/"
        ) from exc
    except Exception as exc:
        raise RuntimeError(f"1Password fetch failed for '{path}': {exc}") from exc


def store_credential_ref(provider: str, ref: str) -> None:
    """Store a ``ref:`` reference (not a raw key) in providers.yaml."""
    from promptgenie.core.providers import load_providers_config, save_providers_config
    providers = load_providers_config()
    if provider not in providers:
        from promptgenie.core.errors import EXIT_USAGE, PromptGenieError
        raise PromptGenieError(
            f"Provider '{provider}' not configured. "
            f"Add it first with: promptgenie provider add {provider}",
            code=EXIT_USAGE,
        )
    providers[provider].api_key = ref
    save_providers_config(providers)
