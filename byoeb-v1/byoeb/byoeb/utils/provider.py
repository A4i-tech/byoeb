from typing import Optional

PROVIDERS = ("azure", "openai")


def validate_provider(env_var: str, value: str) -> str:
    if value not in PROVIDERS:
        raise ValueError(f"{env_var}='{value}' is not a known provider. Set {env_var} to 'azure' or 'openai'.")
    return value


def check_provider_settings(
    env_var: str,
    provider: str,
    has_openai_key: bool,
    base_url: Optional[str],
    azure_settings: dict,
) -> None:
    if provider == "azure":
        missing = [name for name, value in azure_settings.items() if not value]
        if missing:
            raise ValueError(
                f"{env_var}=azure needs these settings: {', '.join(missing)}. "
                f"Set them or set {env_var}=openai."
            )
    elif not has_openai_key and not base_url:
        base_url_var = env_var.replace("_PROVIDER", "_BASE_URL")
        raise ValueError(
            f"{env_var}=openai needs OPENAI_API_KEY for public OpenAI, or {base_url_var} (or OPENAI_BASE_URL) "
            f"for a self-hosted server. Set one of them or set {env_var}=azure."
        )
