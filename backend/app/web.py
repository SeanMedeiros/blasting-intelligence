"""Protections for a server reachable from the site network (pure ASGI middleware).

* Host check — only the names under which this server is known are answered (blocks DNS-rebinding and
  requests for other sites). Allowed: localhost, this computer's name / full name / IP addresses, the host of
  BI_PUBLIC_URL and BI_ALLOWED_HOSTS ("*" turns the check off).
* Origin check — a state-changing request that carries an Origin header must come from this same server
  (defence in depth on top of the SameSite=Strict cookie and the X-Requested-With header).
* Security headers on every response: no MIME sniffing, no framing, strict referrer, a Content-Security-Policy
  that allows only this server's own scripts, and HSTS when the connection is HTTPS.
"""
from __future__ import annotations

import ipaddress
import json
import socket
from functools import lru_cache
from urllib.parse import urlsplit

from . import config

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
DEV_ORIGINS = {"http://localhost:5173", "http://127.0.0.1:5173"}  # Vite development server (see CORS in main.py)

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "font-src 'self' data:; connect-src 'self'; worker-src 'self' blob:; object-src 'none'; base-uri 'self'; "
       "form-action 'self'; frame-ancestors 'none'")
BASE_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "same-origin",
    "permissions-policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "cross-origin-opener-policy": "same-origin",
}
HSTS = "max-age=15552000"  # 180 days; no includeSubDomains (other site systems may still be HTTP)


def _strip_port(host: str) -> str:
    host = host.strip().lower()
    if host.startswith("["):  # [IPv6]:port
        return host[1:host.index("]")] if "]" in host else host
    if host.count(":") == 1:
        return host.rsplit(":", 1)[0]
    return host


@lru_cache(maxsize=1)
def allowed_hosts() -> frozenset[str] | None:
    """Names this server answers to; None = no check."""
    if "*" in config.ALLOWED_HOSTS:
        return None
    names = {"localhost", "127.0.0.1", "::1"}
    names.update(_strip_port(h) for h in config.ALLOWED_HOSTS)
    if config.PUBLIC_URL:
        names.add((urlsplit(config.PUBLIC_URL).hostname or "").lower())
    if config.HOST not in ("0.0.0.0", "::", ""):
        names.add(config.HOST.lower())
    try:
        hn = socket.gethostname()
        names.update({hn.lower(), socket.getfqdn().lower()})
        for info in socket.getaddrinfo(hn, None):
            names.add(str(info[4][0]).split("%")[0].lower())
    except OSError:
        pass
    names.discard("")
    return frozenset(names)


def host_allowed(host: str) -> bool:
    allowed = allowed_hosts()
    if allowed is None:
        return True
    h = _strip_port(host)
    if h in allowed:
        return True
    try:  # loopback addresses in any notation
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def origin_allowed(origin: str, host: str) -> bool:
    """Same scheme-less host:port as the request, the public address, or the development server on this computer."""
    o = urlsplit(origin)
    if not o.netloc:
        return False
    if config.PUBLIC_URL and origin.rstrip("/") == config.PUBLIC_URL:
        return True
    if origin in DEV_ORIGINS:
        try:
            return ipaddress.ip_address(_strip_port(host)).is_loopback or _strip_port(host) == "localhost"
        except ValueError:
            return _strip_port(host) == "localhost"
    return o.netloc.lower() == host.strip().lower()


async def _reply(send, status: int, message: str):
    body = json.dumps({"detail": message}).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                            *((k.encode(), v.encode()) for k, v in BASE_HEADERS.items())]})
    await send({"type": "http.response.body", "body": body})


class NetworkGuardMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        host = headers.get("host", "")
        if not host_allowed(host):
            return await _reply(send, 400, "Unknown host name for this server (see BI_ALLOWED_HOSTS)")
        origin = headers.get("origin")
        if scope.get("method") in UNSAFE and origin and not origin_allowed(origin, host):
            return await _reply(send, 403, "Request from another site refused")
        https = scope.get("scheme") == "https"

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                present = {k.decode("latin-1").lower() for k, _v in message.get("headers", [])}
                extra = [(k, v) for k, v in BASE_HEADERS.items() if k not in present]
                if "content-security-policy" not in present:
                    extra.append(("content-security-policy", CSP))
                if https:
                    extra.append(("strict-transport-security", HSTS))
                message = {**message, "headers": [*message.get("headers", []), *((k.encode(), v.encode()) for k, v in extra)]}
            await send(message)

        await self.app(scope, receive, send_with_headers)


async def redirect_app(scope, receive, send):
    """Plain-HTTP listener (BI_HTTP_REDIRECT_PORT): sends every request to the HTTPS address."""
    if scope["type"] == "lifespan":
        while True:
            m = await receive()
            if m["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif m["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return
    if scope["type"] != "http":
        return
    headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
    host = headers.get("host", "")
    if not host_allowed(host):
        return await _reply(send, 400, "Unknown host name for this server (see BI_ALLOWED_HOSTS)")
    if config.PUBLIC_URL:
        base = config.PUBLIC_URL
    else:
        h = _strip_port(host)
        h = f"[{h}]" if ":" in h else h
        base = f"https://{h}" + ("" if config.PORT == 443 else f":{config.PORT}")
    path = scope.get("raw_path", scope["path"].encode()).decode("latin-1")
    qs = scope.get("query_string", b"").decode("latin-1")
    loc = base + path + (f"?{qs}" if qs else "")
    await send({"type": "http.response.start", "status": 308,
                "headers": [(b"location", loc.encode("latin-1")), (b"content-length", b"0")]})
    await send({"type": "http.response.body", "body": b""})


def server_info() -> dict:
    """Network and HTTPS settings for the administrators' status card (no secrets)."""
    from .serve import address

    cert = None
    if config.HTTPS:
        from .ops.tls import TlsError, cert_info
        try:
            cert = cert_info(config.TLS_CERT).as_dict()
        except TlsError as e:
            cert = {"error": str(e)}
    network = config.HOST not in ("127.0.0.1", "localhost", "::1")
    allowed = allowed_hosts()
    return {"address": address(), "listen": f"{config.HOST}:{config.PORT}", "network": network, "https": config.HTTPS,
            "behind_proxy": bool(config.TRUSTED_PROXIES), "cookie_secure": config.COOKIE_SECURE,
            "http_redirect_port": config.HTTP_REDIRECT_PORT or None, "certificate": cert,
            "host_check": sorted(allowed) if allowed is not None else None,
            "unencrypted_network": network and not config.HTTPS and not config.TRUSTED_PROXIES}
