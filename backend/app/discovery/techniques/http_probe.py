import httpx

_TLS_PORTS = {443, 8443, 8006, 8043, 8843}


async def probe_http(host: str, port: int, timeout: float = 3.0) -> dict[str, str] | None:
    scheme = "https" if port in _TLS_PORTS else "http"
    url = f"{scheme}://{host}:{port}/"
    try:
        async with httpx.AsyncClient(timeout=timeout, verify=False, follow_redirects=True) as client:
            response = await client.get(url)
    except httpx.HTTPError:
        return None
    return {
        "status_code": str(response.status_code),
        "server": response.headers.get("server", ""),
        "title": _extract_title(response.text),
    }


def _extract_title(html: str) -> str:
    lower = html.lower()
    start = lower.find("<title>")
    end = lower.find("</title>")
    if start == -1 or end == -1 or end <= start:
        return ""
    return html[start + len("<title>") : end].strip()[:200]
