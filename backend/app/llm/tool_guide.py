"""What each built-in tool is, where it runs and what stops it misbehaving, written for the Tools page.

Hand-written text drifts from the code, so numbers come from the same constants the handlers use, and
`tests/unit/test_tool_guide.py` fails when a tool exists without an entry here."""

from dataclasses import dataclass
from typing import Literal

from app.llm.agent_tools import (
    DISCOVER_TIMEOUT_SECONDS,
    FORM_SUBMIT_TIMEOUT_SECONDS,
    MAX_FETCH_BYTES,
    MAX_REDIRECTS,
    NC_TIMEOUT_SECONDS,
    NMAP_TIMEOUT_SECONDS,
    WEB_TIMEOUT_SECONDS,
)
from app.llm.inspect_tools import HTTP_TIMEOUT_SECONDS
from app.llm.tool_base import MAX_OUTPUT_CHARS

RunsOn = Literal["local_program", "in_process", "lan", "internet", "target_host"]

RUNS_ON_LABELS: dict[RunsOn, str] = {
    "local_program": "A program on the Banana host",
    "in_process": "Inside the Banana process",
    "lan": "Network calls from the Banana host to a LAN address",
    "internet": "Network calls from the Banana host to the internet",
    "target_host": "On the target machine, through a stored integration",
}


@dataclass(frozen=True)
class ToolGuide:
    runs_on: RunsOn
    where: str
    safeguards: tuple[str, ...]


_TARGET = "The target must be a single IP address inside a configured network (or loopback)."
_OUTPUT = f"Output is cut at {MAX_OUTPUT_CHARS:,} characters before the model sees it."
_NO_CREDENTIAL = (
    "The integration's credential is used and dropped; it never appears in a result, trace or log."
)

TOOL_GUIDES: dict[str, ToolGuide] = {
    "run_nmap": ToolGuide(
        "local_program",
        "Runs the nmap program on the Banana host with no shell. The model's flags become its command line.",
        (
            _TARGET,
            "Flags must match a fixed allowlist (for example -sT, -sV, -Pn, -F, -T0 to -T5, --top-ports=N).",
            "Ports may only contain digits, commas and dashes.",
            f"Stops after {NMAP_TIMEOUT_SECONDS:.0f} seconds.",
            _OUTPUT,
        ),
    ),
    "run_nc": ToolGuide(
        "local_program",
        "Runs the nc (netcat) program on the Banana host to open one connection and read the banner. "
        "With tls on, Banana makes the TLS connection itself instead.",
        (
            _TARGET,
            "The port must be an integer from 1 to 65535.",
            "A payload is cut at 256 bytes.",
            f"Stops after {NC_TIMEOUT_SECONDS:.0f} seconds.",
            "TLS mode does not verify certificates, because many home services self-sign.",
            _OUTPUT,
        ),
    ),
    "discover_hosts": ToolGuide(
        "in_process",
        "Runs Banana's own network scan (ping, ARP, port probes, nmap fingerprinting) and records what "
        "answers through the normal discovery pipeline.",
        (
            "The range must sit inside a configured network and within the scan size limit.",
            "A range outside every configured network needs the administrator's switch, must be private "
            "(RFC1918) and gets a smaller limit.",
            "Range size is judged from its prefix, never by listing its hosts.",
            f"Stops after {DISCOVER_TIMEOUT_SECONDS:.0f} seconds.",
            "A dry run scans nothing.",
        ),
    ),
    "record_service": ToolGuide(
        "in_process",
        "Writes a service the agent identified into Banana's own database, attached to a device.",
        (
            _TARGET,
            "The service type must be http, https, dns or tcp.",
            "Marked as coming from AI, so you can tell it from monitored services.",
            "A dry run records nothing.",
        ),
    ),
    "report_open_ports": ToolGuide(
        "in_process",
        "Tells the other agents which ports a host has open. Writes nothing itself.",
        (_TARGET, "Ports must be a list of integers.", "A dry run reports nothing."),
    ),
    "record_finding": ToolGuide(
        "in_process",
        "Saves one fact about a host (its OS, patch level, a vulnerability, a performance problem or an "
        "incident) into Banana's database, where the run's reports pick it up.",
        (
            _TARGET,
            "Kind and severity must be from the fixed lists; the same host and title in one run updates "
            "the earlier record.",
            "A dry run records nothing.",
        ),
    ),
    "publish_message": ToolGuide(
        "in_process",
        "Puts a message on the internal message bus for other agents. Handled by the orchestrator, not a "
        "program.",
        (
            "An agent may only publish to the topics listed for it.",
            "If the agent's approval setting asks, a human approves the message first.",
        ),
    ),
    "get_network_snapshot": ToolGuide(
        "in_process",
        "Reads devices and services from Banana's database. Read-only.",
        ("Without a host list the result is capped at 50 devices, to keep the prompt small.",),
    ),
    "get_status_delta": ToolGuide(
        "in_process",
        "Compares the current inventory with the one saved in the latest report. Read-only.",
        ("Read-only: it reads the database and the last report.",),
    ),
    "save_report": ToolGuide(
        "in_process",
        "Saves a report to Banana's Reports page, with a snapshot of the inventory.",
        (
            "A title and content are required.",
            "The title is cut at 200 characters.",
            "A dry run saves nothing.",
        ),
    ),
    "remember": ToolGuide(
        "in_process",
        "Saves a short note for this agent's own future runs.",
        (
            "Notes are private to the agent that wrote them.",
            "Each agent keeps a limited number of notes of limited length; the oldest are removed first.",
            "You can read and delete them on the Agents page.",
        ),
    ),
    "web_search": ToolGuide(
        "internet",
        "Searches the web from the Banana host and returns titles, links and snippets.",
        (
            "Covered by the internet kill switch.",
            "At most 10 results per call.",
            f"Stops after {WEB_TIMEOUT_SECONDS:.0f} seconds.",
        ),
    ),
    "fetch_url": ToolGuide(
        "internet",
        "Downloads a web page from the Banana host (GET only) and returns its text.",
        (
            "Covered by the internet kill switch.",
            "Only http and https, and only public addresses: a private or loopback address is refused, "
            "checked again on every redirect.",
            f"At most {MAX_REDIRECTS} redirects, {MAX_FETCH_BYTES:,} bytes read and "
            f"{WEB_TIMEOUT_SECONDS:.0f} seconds.",
            _OUTPUT,
        ),
    ),
    "submit_http_form": ToolGuide(
        "lan",
        "Sends an HTTP GET or POST to a service on the LAN, for example to see how a login page behaves.",
        (
            _TARGET,
            "Only the GET and POST methods.",
            f"Stops after {FORM_SUBMIT_TIMEOUT_SECONDS:.0f} seconds.",
            "Cookies and authorization headers are removed from the response.",
            "A dry run sends nothing.",
            _OUTPUT,
        ),
    ),
    "list_inspect_targets": ToolGuide(
        "in_process",
        "Lists the enabled integrations and web services an agent may look inside. Read-only.",
        ("Lists names and ids only; no credentials.",),
    ),
    "ssh_readonly": ToolGuide(
        "target_host",
        "Logs in over SSH with a stored credential and runs one read-only command on the target machine.",
        (
            "Only allowlisted read-only programs and subcommands; options that write, execute, follow or "
            "kill are refused.",
            "No quotes, pipes, redirects, substitution or globbing; a program is named without a path; '..' "
            "is refused.",
            "Paths that may hold secrets are refused.",
            "Your custom guardrails apply to its arguments.",
            _NO_CREDENTIAL,
            _OUTPUT,
        ),
    ),
    "winrm_readonly": ToolGuide(
        "target_host",
        "Runs one read-only PowerShell command on a Windows machine over WinRM with a stored credential.",
        (
            "Only allowlisted Get- style cmdlets, with plain parameter names.",
            "Paths that may hold secrets are refused.",
            "Your custom guardrails apply to its arguments.",
            _NO_CREDENTIAL,
            _OUTPUT,
        ),
    ),
    "proxmox_get": ToolGuide(
        "target_host",
        "Reads from the Proxmox API with a stored API token (GET only).",
        (
            "Only allowlisted read-only paths: status, tasks, logs, updates, VM and container state.",
            "Your custom guardrails apply to its arguments.",
            _NO_CREDENTIAL,
            _OUTPUT,
        ),
    ),
    "http_inspect": ToolGuide(
        "lan",
        "Fetches a monitored web service's own URL and reports redirects, headers and its TLS certificate.",
        (
            "Only a service Banana already monitors, at the URL stored for it.",
            f"At most {MAX_REDIRECTS} redirects and {HTTP_TIMEOUT_SECONDS:.0f} seconds.",
            "Cookies and authorization headers are removed from the result.",
            "Your custom guardrails apply to its arguments.",
        ),
    ),
    "apply_updates": ToolGuide(
        "target_host",
        "Runs the package manager's upgrade (apt or dnf) over SSH on a target machine. The one tool that "
        "changes a host.",
        (
            "Refused unless the agent has 'May change hosts' ticked.",
            "Always waits for a human to approve, even when approvals are off.",
            "Leaves a warning event saying which agent started it and where.",
            "A dry run changes nothing.",
            "Your custom guardrails apply to its arguments.",
            _NO_CREDENTIAL,
        ),
    ),
    "virustotal_lookup": ToolGuide(
        "internet",
        "Looks a file hash, public IP address or public domain up on VirusTotal with your API key.",
        (
            "Covered by the internet kill switch.",
            "Only the identifier is sent, never a file, a URL or a local name.",
            "Rate limited to the integration's configured limits and cached for an hour.",
            "Every call leaves an outbound event saying where it went.",
        ),
    ),
    "search_knowledge": ToolGuide(
        "lan",
        "Embeds your query (a call to the configured Ollama-compatible host) and ranks every entry "
        "in one knowledge collection by similarity to it.",
        (
            "Refused unless the knowledge base is switched on (AI Settings).",
            "The collection name must already exist, or the call is refused.",
            "No write: search only ever reads.",
        ),
    ),
    "add_knowledge_entry": ToolGuide(
        "lan",
        "Embeds and saves one entry into an existing knowledge collection, for later search_knowledge "
        "calls (by any agent) to find.",
        (
            "Refused unless the knowledge base is switched on (AI Settings).",
            "Never creates a new collection - the collection name must already exist.",
            "A dry run changes nothing.",
        ),
    ),
}
