from app.integrations.base import IntegrationPlugin

_REGISTRY: dict[str, IntegrationPlugin] = {}


def register(plugin: IntegrationPlugin) -> None:
    _REGISTRY[plugin.type_key] = plugin


def get_plugin(type_key: str) -> IntegrationPlugin | None:
    return _REGISTRY.get(type_key)


def list_plugins() -> list[IntegrationPlugin]:
    return list(_REGISTRY.values())


# Real plugins register themselves here as they land:
#   - http_tcp (M3)
#   - generic_ssh (M4)
#   - proxmox (M5)
# Adding one is a new module plus a call to register() - no other core code changes.
