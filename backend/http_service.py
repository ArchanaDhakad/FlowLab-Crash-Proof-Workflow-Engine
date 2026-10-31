"""Make bounded HTTPS requests to explicitly configured public API hosts."""

import ipaddress
import json
import os
import re
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


MAX_RESPONSE_BYTES = 1_000_000
MAX_REQUEST_BYTES = 1_000_000
MAX_HEADER_COUNT = 50
MAX_HEADER_VALUE_LENGTH = 8_192
ENVIRONMENT_VARIABLE_PATTERN = re.compile(r"\$\{ENV:([A-Za-z_][A-Za-z0-9_]*)\}")
CONTEXT_TEMPLATE_PATTERN = re.compile(
    r"\{\{\s*([A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_][A-Za-z0-9_-]*)*)\s*\}\}"
)
HEADER_NAME_PATTERN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z")
FORBIDDEN_HEADERS = {
    "connection",
    "content-length",
    "host",
    "proxy-authorization",
    "proxy-connection",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request: Any, response: Any, code: int, message: str,
                         headers: Any, new_url: str) -> None:
        return None


def _resolve_allowed_host(hostname: str) -> None:
    allowed_hosts = {
        host.strip().rstrip(".").lower()
        for host in os.environ.get("HTTP_ALLOWED_HOSTS", "").split(",")
        if host.strip()
    }
    normalized_host = hostname.rstrip(".").lower()
    if normalized_host not in allowed_hosts:
        raise ValueError(
            f"HTTP host '{normalized_host}' is not in HTTP_ALLOWED_HOSTS."
        )

    try:
        addresses = socket.getaddrinfo(normalized_host, 443, type=socket.SOCK_STREAM)
    except OSError as error:
        raise ValueError(f"Could not resolve allowlisted HTTP host '{normalized_host}'.") from error
    if not addresses:
        raise ValueError(f"HTTP host '{normalized_host}' did not resolve to an IP address.")

    for address in addresses:
        ip_address = ipaddress.ip_address(address[4][0])
        if not ip_address.is_global:
            raise ValueError(
                f"HTTP host '{normalized_host}' resolves to a non-public IP address."
            )


def _render_http_template(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, str):
        rendered = re.sub(
            CONTEXT_TEMPLATE_PATTERN,
            lambda match: _context_value(match.group(1), context),
            value,
        )

        def substitute_environment(match: re.Match[str]) -> str:
            variable_name = match.group(1)
            if variable_name not in os.environ:
                raise ValueError(
                    f"HTTP step requires the '{variable_name}' environment variable."
                )
            return os.environ[variable_name]

        return ENVIRONMENT_VARIABLE_PATTERN.sub(substitute_environment, rendered)
    if isinstance(value, list):
        return [_render_http_template(item, context) for item in value]
    if isinstance(value, dict):
        return {
            key: _render_http_template(item, context) for key, item in value.items()
        }
    return value


def _context_value(key: str, context: dict[str, Any]) -> str:
    parts = key.split(".")
    value: Any = context
    for part in parts:
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdecimal() and int(part) < len(value):
            value = value[int(part)]
        else:
            raise ValueError(f"HTTP template references missing data path '{key}'.")
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _parse_response_body(body: bytes, content_type: str) -> Any:
    if not body:
        return None
    text = body.decode("utf-8", errors="replace")
    media_type = content_type.partition(";")[0].strip().lower()
    if media_type == "application/json" or media_type.endswith("+json"):
        try:
            return json.loads(text)
        except json.JSONDecodeError as error:
            raise ValueError("HTTP service returned invalid JSON.") from error
    return text


def send_http_request(step: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Send one JSON request and return a bounded, parsed response."""
    rendered_url = _render_http_template(step["url"], context)
    parsed_url = urllib.parse.urlsplit(rendered_url)
    hostname = parsed_url.hostname
    if (
        parsed_url.scheme.lower() != "https"
        or not hostname
        or parsed_url.username is not None
        or parsed_url.password is not None
        or parsed_url.fragment
        or parsed_url.port not in (None, 443)
    ):
        raise ValueError(
            "HTTP steps require an HTTPS URL on port 443 without credentials or a fragment."
        )
    _resolve_allowed_host(hostname)

    method = step.get("method", "GET").upper()
    headers = step.get("headers", {})
    if len(headers) > MAX_HEADER_COUNT:
        raise ValueError(f"HTTP steps support at most {MAX_HEADER_COUNT} headers.")
    rendered_headers: dict[str, str] = {}
    for name, value in headers.items():
        if not HEADER_NAME_PATTERN.fullmatch(name):
            raise ValueError("HTTP header names must use valid token characters.")
        if name.lower() in FORBIDDEN_HEADERS:
            raise ValueError(f"The '{name}' HTTP header is controlled by the engine.")
        rendered_value = _render_http_template(value, context)
        if "\r" in rendered_value or "\n" in rendered_value:
            raise ValueError("HTTP header values cannot contain line breaks.")
        if len(rendered_value) > MAX_HEADER_VALUE_LENGTH:
            raise ValueError("HTTP header values must be 8192 characters or fewer.")
        rendered_headers[name] = rendered_value

    request_body = None
    if "body" in step:
        rendered_body = _render_http_template(step["body"], context)
        try:
            request_body = json.dumps(
                rendered_body, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise ValueError("HTTP request body must be valid JSON data.") from error
        if len(request_body) > MAX_REQUEST_BYTES:
            raise ValueError("HTTP request bodies must be 1 MB or smaller.")
        if not any(name.lower() == "content-type" for name in rendered_headers):
            rendered_headers["Content-Type"] = "application/json"
    if len(rendered_headers) > MAX_HEADER_COUNT:
        raise ValueError(f"HTTP steps support at most {MAX_HEADER_COUNT} headers.")

    request = urllib.request.Request(
        rendered_url, data=request_body, headers=rendered_headers, method=method
    )
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoRedirectHandler(),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
    )

    try:
        with opener.open(request, timeout=15) as response:
            response_body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(response_body) > MAX_RESPONSE_BYTES:
                raise ValueError("HTTP response body exceeded the 1 MB limit.")
            status_code = response.status
            content_type = response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as error:
        error.close()
        raise ValueError(f"HTTP service returned status {error.code}.") from error
    except (urllib.error.URLError, OSError, ssl.SSLError) as error:
        raise ValueError(
            f"HTTP request failed ({type(error).__name__}); check the allowlist and API availability."
        ) from error

    return {
        "status_code": status_code,
        "body": _parse_response_body(response_body, content_type),
    }
