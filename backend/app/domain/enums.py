import enum


class DeviceType(enum.StrEnum):
    LINUX = "linux"
    WINDOWS = "windows"
    PROXMOX_NODE = "proxmox_node"
    PROXMOX_VM = "proxmox_vm"
    PROXMOX_LXC = "proxmox_lxc"
    NETWORK_EQUIPMENT = "network_equipment"
    PLATFORM_SELF = "platform_self"
    OTHER = "other"


class HealthStatus(enum.StrEnum):
    UP = "up"
    DOWN = "down"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


class ServiceType(enum.StrEnum):
    HTTP = "http"
    HTTPS = "https"
    TCP = "tcp"
    DNS = "dns"
    DHCP = "dhcp"
    PROXMOX_VM = "proxmox_vm"
    PROXMOX_LXC = "proxmox_lxc"
    SYSTEMD_UNIT = "systemd_unit"


class IntegrationStatus(enum.StrEnum):
    OK = "ok"
    ERROR = "error"
    DISABLED = "disabled"
    UNKNOWN = "unknown"


class AlertConditionType(enum.StrEnum):
    DEVICE_DOWN = "device_down"
    SERVICE_DOWN = "service_down"
    HIGH_CPU = "high_cpu"
    HIGH_MEMORY = "high_memory"
    DISK_USAGE_HIGH = "disk_usage_high"
    INTEGRATION_FAILING = "integration_failing"
    METRIC_THRESHOLD = "metric_threshold"


class AlertSeverity(enum.StrEnum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class AlertState(enum.StrEnum):
    OK = "ok"
    PENDING = "pending"
    FIRING = "firing"
    RESOLVED = "resolved"
    FLAPPING = "flapping"


class EntityType(enum.StrEnum):
    DEVICE = "device"
    SERVICE = "service"
    INTEGRATION = "integration"


class CandidateType(enum.StrEnum):
    DEVICE = "device"
    SERVICE = "service"


class CandidateStatus(enum.StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    IGNORED = "ignored"
    EXPIRED = "expired"


class NotificationChannelType(enum.StrEnum):
    LOG = "log"


class CredentialType(enum.StrEnum):
    SSH_KEY = "ssh_key"
    SSH_PASSWORD = "ssh_password"
    API_TOKEN = "api_token"
    BASIC_AUTH = "basic_auth"


class EventSeverity(enum.StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class AssistantProvider(enum.StrEnum):
    OLLAMA = "ollama"
    OPENROUTER = "openrouter"


class AssistantMessageRole(enum.StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
