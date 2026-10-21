"""What a user-defined command tool may run. No shell is involved anywhere, but an interpreter or a
tool with an exec/script option is still code execution, so the executable must come from a short list of
network diagnostics and each has the options that run code or touch files removed."""

import re

ALLOWED_EXECUTABLES = ("nmap", "nc", "ncat", "dig", "nslookup", "host", "ping", "traceroute", "whatweb")
PLACEHOLDERS = {"{target}", "{port}"}

_DENIED_OPTIONS: dict[str, re.Pattern[str]] = {
    "nmap": re.compile(
        r"^(--script.*|-sC|-A|-i[LR].*|-o.*|--(datadir|resume|stylesheet|servicedb|versiondb|excludefile|"
        r"iflist|append-output|webxml|no-stylesheet).*)$"
    ),
    "nc": re.compile(r"^(-[a-zA-Z]*[ecl][a-zA-Z]*|--(exec|sh-exec|lua-exec|listen|keep-open).*)$"),
    "dig": re.compile(r"^(-f|-k|-y|-b|-m)$"),
    "ping": re.compile(r"^(-f|-I.*|-p)$"),
    "whatweb": re.compile(r"^(--custom-plugin.*|--plugins.*|-p|-i|--input-file.*|--log-.*|--url-prefix.*)$"),
}
_DENIED_OPTIONS["ncat"] = _DENIED_OPTIONS["nc"]


def validate_command(command: list[str]) -> None:
    """Raises ValueError with the reason when the argument list is not allowed."""
    if not command:
        raise ValueError("command tools need a command")
    executable, *arguments = command
    if executable not in ALLOWED_EXECUTABLES:
        raise ValueError(
            f"{executable!r} is not allowed; the executable must be one of {', '.join(ALLOWED_EXECUTABLES)} "
            "(a bare name, no path)"
        )
    denied = _DENIED_OPTIONS.get(executable)
    for argument in arguments:
        if re.search(r"\{[^}]*\}", argument) and not set(re.findall(r"\{[^}]*\}", argument)) <= PLACEHOLDERS:
            raise ValueError(f"unknown placeholder in {argument!r}; only {{target}} and {{port}} exist")
        if denied and denied.match(argument):
            raise ValueError(f"option {argument!r} is not allowed for {executable}")
