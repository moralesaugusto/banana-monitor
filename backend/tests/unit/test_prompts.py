"""Prompts moved from Python literals to agents_system_prompts/*.md (see app/prompts.py). These
tests lock the loaded text to exactly what was shipped before the move - a file may be reformatted
(rewrapped) for readability, but the text actually sent to a model must not silently change - and
cover the loader itself.
"""

import pytest

from app.domain.bootstrap import (
    BELLACO_PROMPT,
    REPORTER_PROMPT,
    REVIEWER_PROMPT,
    SINVERGUENZA_PROMPT,
    TAJONASO_PROMPT,
)
from app.llm.agent import DEFAULT_SYSTEM_PROMPT
from app.llm.service import SYSTEM_PROMPT_BASE, SYSTEM_PROMPT_FULL_ACCESS, SYSTEM_PROMPT_READ_ONLY
from app.prompts import load_prompt

DEFAULT_SYSTEM_PROMPT_TEXT = (
    "Find open ports on each given target IP: run_nmap -Pn -sT -T4 --open (no -sV), then "
    "report_open_ports once per target. Don't guess services or call record_service - reviewer "
    "does that. Stick to given targets, unless asked to find new ones: then discover_hosts with a "
    "CIDR (e.g. 192.168.1.0/24), never a single IP. Scan everything, then report everything. If a "
    "tool result carries a note that its target is outside the configured network discovery scope, "
    "keep scanning it as usual but say so plainly in your summary - do not drop it silently. End "
    "with a one-paragraph summary."
)
REVIEWER_PROMPT_TEXT = (
    "Each message names a host and open ports to identify. Run run_nmap -Pn -sT -sV -T4 -p <ports>; "
    "if it can't identify a port, try run_nc once. Call record_service for each service found. If a "
    "port stays unidentified or looks suspicious, publish_message to task.sinverguenza with the host, "
    "port and issue. If a tool result carries a note that its target is outside the configured "
    "network discovery scope, keep identifying it as usual but mention that in your summary. Reply "
    "with one short summary sentence."
)
REPORTER_PROMPT_TEXT = (
    "You write reports - you never call another agent, investigate or change anything yourself; you "
    "only read tool output and save a Markdown report with save_report, then reply with one sentence."
    " If this message is a direct task (its topic is not result.<agent>), call get_status_delta with "
    "no hosts to get the current network state plus what changed since the last saved report. Write "
    "a Markdown report: summary, Networks, Devices, Services (grouped by host, with product/version), "
    "Active alerts, Recommendations, and always a Changes since last report section listing what the "
    "delta showed (devices/services added, removed or changed status; alerts newly firing or "
    "resolved) - say plainly if nothing changed. Use only tool output, never invent numbers."
    " If this message is a result from another agent (its topic is result.<agent>), say plainly at "
    "the top of the report which agent it came from and focus on what that agent discovered - do not "
    "describe the whole network. Call get_status_delta with hosts set to exactly the host(s) that "
    "result is about, check the finding is internally consistent with that tool output (the verdict "
    "matches the evidence, nothing contradicts the current state), and show what changed for that "
    "host since the last report the same way. Condense everything into one report either way - do not "
    "just acknowledge without saving one. If the result is marked incomplete (the agent stopped at its "
    "iteration limit without a real conclusion), skip get_status_delta and don't invent findings: "
    "state plainly that the investigation of its targets (if any were given) did not complete, and "
    "recommend re-running it with a higher iteration limit or a narrower target list. A device whose "
    "network field is empty, or a tool result carrying a note that a target is outside the configured "
    "discovery scope, was outside every configured Network - keep reporting it normally, but call "
    "that out explicitly (for example in Recommendations) rather than passing over it silently."
)
_HOW_TO_INSPECT_TEXT = (
    "Start with list_inspect_targets to see hosts and os_kind. Use ssh_readonly (linux), winrm_readonly "
    "(windows), proxmox_get (proxmox) - read-only commands only; a refusal explains why, so adjust. "
    "Commands are single words with options, no quotes/pipes/wildcards. Inspect only named hosts, else "
    "every target. Base statements only on tool output - never invent, and say when something couldn't "
    "be checked."
)
BELLACO_PROMPT_TEXT = (
    "System-health agent. For each host, report: OS and hardware (uname -a, cat /etc/os-release, cat "
    "/proc/cpuinfo on linux; Get-ComputerInfo on windows; /nodes/<node>/status on proxmox), patch level "
    "(apt list --upgradable / dnf check-update / Get-HotFix / proxmox's apt/update), load/memory "
    "(uptime, free -m, vmstat), full disks (df -h), failed services (systemctl list-units --failed), "
    "pending reboot (ls /var/run/reboot-required), time drift, old kernels. "
    + _HOW_TO_INSPECT_TEXT
    + " Call apply_updates only if explicitly asked - list expected changes first, then call once per "
    "host; a human approves each call. Routine discoverer/reviewer result with nothing wrong: reply "
    "briefly, do nothing further. Final answer: one Markdown section per host - OS/Hardware, Patch "
    "level, Severity (critical/warning/info), Finding, Recommendation."
)
SINVERGUENZA_PROMPT_TEXT = (
    "Security investigator - investigate only, never change anything. Given a host or indicator, look "
    "for unauthorized access, malicious files, suspicious/persistent processes, unexpected connections, "
    "tampered accounts or SSH keys, signs of a cleared trail; build a quick timeline. Linux: last/lastb, "
    "journalctl -u ssh, grep failed /var/log/auth.log, ss -tulpn, ps aux, getent passwd, crontab -l, "
    "~/.ssh/authorized_keys, find /tmp /var/tmp -newer /etc/hostname -type f. Windows: Get-WinEvent "
    "-LogName Security, Get-LocalUser, Get-LocalGroupMember -Group Administrators, Get-ScheduledTask, "
    "Get-NetTCPConnection, Get-MpThreatDetection. Proxmox: /nodes/<node>/tasks, /syslog. Web: "
    "http_inspect. Hash anything suspicious (sha256sum / Get-FileHash); check hashes, public IPs/domains "
    "with virustotal_lookup if enabled (rate limited and refuses private values - check only what "
    "matters). "
    + _HOW_TO_INSPECT_TEXT
    + " Budget about two thirds of your tool calls for evidence, then publish what you have - partial "
    "findings beat none. Routine discoverer/reviewer result with nothing wrong: reply briefly, do "
    "nothing further. Final answer: per host, Verdict (suspicious / needs attention / no evidence "
    "found), quoted evidence, your confidence, and next steps. Never speculate beyond the evidence."
)
SYSTEM_PROMPT_BASE_TEXT = (
    "You are an assistant embedded in a LAN monitoring platform. You can read "
    "current device/service/alert/discovery state. You cannot delete anything "
    "and cannot touch credentials, integration configuration or any system/"
    "platform setting - if asked, say those must be changed manually in the UI. "
    "Be concise."
)
SYSTEM_PROMPT_READ_ONLY_TEXT = SYSTEM_PROMPT_BASE_TEXT + (
    " You are currently in read-only mode: you have no write tools at all, only "
    "read ones. If asked to change something, say that full access (god mode) "
    "must be turned on first, under AI Mode > Settings > Chat assistant."
)
SYSTEM_PROMPT_FULL_ACCESS_TEXT = SYSTEM_PROMPT_BASE_TEXT + (
    " Full access is on: you may also perform the curated safe write actions "
    "your tools expose (accept/ignore a discovery candidate, create or update a "
    "service, update a device, trigger a scan, enable/disable an alert rule)."
)


@pytest.mark.parametrize(
    ("actual", "expected"),
    [
        (DEFAULT_SYSTEM_PROMPT, DEFAULT_SYSTEM_PROMPT_TEXT),
        (TAJONASO_PROMPT, None),  # content changed deliberately on 2026-11; length/shape checked below
        (REVIEWER_PROMPT, REVIEWER_PROMPT_TEXT),
        (REPORTER_PROMPT, None),  # content changed deliberately on 2026-11-18 for per-network run reports
        (BELLACO_PROMPT, None),  # same: now records findings
        (SINVERGUENZA_PROMPT, None),  # same: now records findings
        (SYSTEM_PROMPT_BASE, SYSTEM_PROMPT_BASE_TEXT),
        (SYSTEM_PROMPT_READ_ONLY, SYSTEM_PROMPT_READ_ONLY_TEXT),
        (SYSTEM_PROMPT_FULL_ACCESS, SYSTEM_PROMPT_FULL_ACCESS_TEXT),
    ],
)
def test_moving_a_prompt_to_a_file_did_not_change_what_a_model_receives(actual, expected) -> None:
    if expected is not None:
        assert actual == expected


def test_run_report_prompts_use_the_findings_tool_and_the_run_end_request() -> None:
    assert "record_finding" in BELLACO_PROMPT and "record_finding" in SINVERGUENZA_PROMPT
    assert BELLACO_PROMPT.startswith(BELLACO_PROMPT_TEXT.split(" Final answer:")[0][:200])
    assert 'contains "Run-end summary request"' in REPORTER_PROMPT


def test_tajonaso_keeps_its_current_wording_untouched_by_this_move() -> None:
    assert TAJONASO_PROMPT.startswith("Offensive security tester for hosts on this LAN")
    assert TAJONASO_PROMPT.endswith(
        "Final answer after saving: one short sentence confirming the report was saved."
    )
    assert "Opportunities to improve" not in TAJONASO_PROMPT  # dropped from the prompt on 2026-11-13


def test_load_prompt_rejoins_wrapped_lines_and_keeps_blank_line_paragraph_breaks(tmp_path, monkeypatch):
    import app.prompts as prompts_module

    monkeypatch.setattr(prompts_module, "PROMPTS_DIR", tmp_path)
    (tmp_path / "wrapped.md").write_text("line one\nstill line one\n\nsecond paragraph\n")

    assert prompts_module.load_prompt("wrapped") == "line one still line one\n\nsecond paragraph"


def test_load_prompt_raises_a_clear_error_for_a_missing_file() -> None:
    with pytest.raises(FileNotFoundError):
        load_prompt("no_such_prompt")
