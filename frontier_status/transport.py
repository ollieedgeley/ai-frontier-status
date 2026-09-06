"""Bounded HTTPS fetching with validated numeric destinations and verified TLS."""

from __future__ import annotations

import http.client
import ipaddress
import re
import socket
import ssl
import time
import urllib.parse
from collections.abc import Iterator
from contextlib import contextmanager

from .policy import (
    TIMEOUT_SEC, MAX_RESPONSE_BYTES, MAX_REDIRECTS, MAX_DNS_ADDRESSES,
    MAX_URL_CHARS, MAX_HOST_CHARS, MAX_DNS_LABEL_CHARS, HTTPS_PORT,
    HTTP_READ_CHUNK_BYTES,
)

USER_AGENT = "ai-frontier-status/1.0.0 (Omarchy plugin; +https://github.com/ollieedgeley/ai-frontier-status)"

def validate_url(url: str, allowed_host: str | None = None) -> urllib.parse.SplitResult:
    if len(url) > MAX_URL_CHARS or any(ord(char) <= 32 or ord(char) >= 127 for char in url) or "\\" in url:
        raise ValueError("Invalid status URL")
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    if (parts.scheme != "https" or parts.username is not None or parts.password is not None
            or parts.port not in (None, HTTPS_PORT) or parts.fragment or len(host) > MAX_HOST_CHARS
            or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host)
            or any(not label or len(label) > MAX_DNS_LABEL_CHARS or label.startswith("-") or label.endswith("-")
                   for label in host.split("."))):
        raise ValueError("Status URL must use a canonical HTTPS host")
    if allowed_host is not None and host != allowed_host:
        raise ValueError("Cross-host status redirect rejected")
    return parts


def public_address(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if not ip.is_global or ip.is_multicast or ip.is_reserved:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped or ip.sixtofour or ip.teredo:
            return False
        if ip in ipaddress.ip_network("64:ff9b::/96") or ip in ipaddress.ip_network("64:ff9b:1::/48"):
            return False
    return True


def remaining_time(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Status response timed out")
    return min(TIMEOUT_SEC, remaining)


class PublicHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, deadline: float):
        context = ssl.create_default_context()
        context.set_alpn_protocols(["http/1.1"])
        super().__init__(host, port=HTTPS_PORT, timeout=remaining_time(deadline), context=context)
        self.deadline = deadline

    def connect(self) -> None:
        addresses = socket.getaddrinfo(self.host, HTTPS_PORT, type=socket.SOCK_STREAM)
        if not addresses or len(addresses) > MAX_DNS_ADDRESSES or any(
            not public_address(info[4][0]) for info in addresses
        ):
            raise ValueError("Status host resolves to a non-public or excessive address set")
        last_error = None
        for family, socktype, protocol, _name, address in addresses:
            raw = socket.socket(family, socktype, protocol)
            try:
                raw.settimeout(remaining_time(self.deadline))
                # Use the validated numeric sockaddr directly, with no second DNS lookup.
                raw.connect(address)
                raw.settimeout(remaining_time(self.deadline))
                self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
                return
            except OSError as exc:
                raw.close()
                last_error = exc
        raise last_error or OSError("Status connection failed")


@contextmanager
def open_https(url: str, deadline: float) -> Iterator[http.client.HTTPResponse]:
    parts = validate_url(url)
    # Direct connections deliberately do not inherit environment proxy routing.
    connection = PublicHTTPSConnection(parts.hostname, deadline)
    try:
        connection.request("GET", urllib.parse.urlunsplit(("", "", parts.path or "/", parts.query, "")),
                           headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity",
                                    "Accept": "application/json, application/xml, text/xml, text/html;q=0.8"})
        connection.sock.settimeout(remaining_time(deadline))
        with connection.getresponse() as response:
            yield response
    finally:
        connection.close()


def read_response(response: http.client.HTTPResponse, deadline: float) -> tuple[str, str]:
    length = response.headers.get("Content-Length")
    if length is not None and (int(length) < 0 or int(length) > MAX_RESPONSE_BYTES):
        raise ValueError("Status response exceeds byte limit")
    if response.headers.get("Content-Encoding", "identity").lower() != "identity":
        raise ValueError("Compressed status responses are not supported")
    raw = bytearray()
    while True:
        if time.monotonic() >= deadline:
            raise TimeoutError("Status response timed out")
        chunk = response.read1(min(HTTP_READ_CHUNK_BYTES, MAX_RESPONSE_BYTES + 1 - len(raw)))
        if time.monotonic() >= deadline:
            raise TimeoutError("Status response timed out")
        if not chunk:
            break
        raw.extend(chunk)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("Status response exceeds byte limit")
    charset = response.headers.get_content_charset() or "utf-8"
    content_type = response.headers.get_content_type() or ""
    return raw.decode(charset, "replace"), content_type


def http_get(url: str, timeout: int = TIMEOUT_SEC) -> tuple[str, str]:
    """Return decoded body and media type, or raise on transport/policy failure.

    The initial catalog URL fixes the allowed redirect host. The caller must arm
    the process deadline: socket timeouts cannot bound a stalled DNS resolver.
    Connections bypass environment proxies so the checked destination is used.
    """
    deadline = time.monotonic() + timeout
    allowed_host = validate_url(url).hostname
    for redirects in range(MAX_REDIRECTS + 1):
        validate_url(url, allowed_host)
        with open_https(url, deadline) as response:
            if response.status in (301, 302, 303, 307, 308):
                location = response.headers.get("Location")
                if not location or redirects == MAX_REDIRECTS:
                    raise ValueError("Status redirect limit exceeded or missing location")
                # Validate before urljoin can strip controls or reinterpret malformed input.
                if len(location) > MAX_URL_CHARS or any(ord(char) <= 32 or ord(char) >= 127 for char in location):
                    raise ValueError("Invalid status redirect")
                url = urllib.parse.urljoin(url, location)
                continue
            if response.status != 200:
                raise ValueError(f"HTTP {response.status}")
            return read_response(response, deadline)
    raise ValueError("Status redirect limit exceeded")
