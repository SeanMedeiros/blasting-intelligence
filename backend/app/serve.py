"""Starts the application server (used by start.bat, start_demo.bat and the Windows service).

    python -m app.serve            (from the backend folder)

Settings come from environment variables or the server.env file next to the application folder:
BI_HOST, BI_PORT, BI_TLS_CERT / BI_TLS_KEY (HTTPS), BI_HTTP_REDIRECT_PORT, BI_PUBLIC_URL, BI_ALLOWED_HOSTS,
BI_TRUSTED_PROXIES, BI_LOG_DIR. Logs: <data>/logs/server.log and access.log (rotated daily, 90 days kept).
"""
from __future__ import annotations

import asyncio
import logging
import logging.config
import sys

import uvicorn

from . import config

log = logging.getLogger("blasting")


def log_config() -> dict:
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = {"format": "%(asctime)s %(levelname)-7s %(name)s: %(message)s"}
    rot = {"class": "logging.handlers.TimedRotatingFileHandler", "when": "midnight", "backupCount": 90,
           "encoding": "utf-8", "formatter": "plain"}
    return {
        "version": 1, "disable_existing_loggers": False,
        "formatters": {"plain": fmt},
        "handlers": {
            "console": {"class": "logging.StreamHandler", "formatter": "plain", "stream": "ext://sys.stdout"},
            "server": {**rot, "filename": str(config.LOG_DIR / "server.log")},
            "access": {**rot, "filename": str(config.LOG_DIR / "access.log")},
        },
        "loggers": {
            "blasting": {"handlers": ["console", "server"], "level": "INFO", "propagate": False},
            "uvicorn": {"handlers": ["console", "server"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"handlers": ["console", "server"], "level": "INFO", "propagate": False},
            "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
        },
        "root": {"handlers": ["console", "server"], "level": "WARNING"},
    }


def settings_problems() -> list[str]:
    """Configuration errors that must stop the start (clear message instead of a stack trace)."""
    out = []
    if bool(config.TLS_CERT) != bool(config.TLS_KEY):
        out.append("BI_TLS_CERT and BI_TLS_KEY must be set together")
    if config.HTTPS:
        from .ops.tls import TlsError, check_pair
        try:
            info = check_pair(config.TLS_CERT, config.TLS_KEY, config.TLS_KEY_PASSWORD)
            if info.days_left < 30:
                log.warning("HTTPS certificate expires in %d day(s) (%s) — renew it", info.days_left, info.not_after.date())
        except TlsError as e:
            out.append(f"HTTPS certificate: {e}")
    if config.HTTP_REDIRECT_PORT and not config.HTTPS:
        out.append("BI_HTTP_REDIRECT_PORT needs HTTPS (BI_TLS_CERT / BI_TLS_KEY)")
    if config.HTTP_REDIRECT_PORT and config.HTTP_REDIRECT_PORT == config.PORT:
        out.append("BI_HTTP_REDIRECT_PORT must differ from BI_PORT")
    if config.PUBLIC_URL and not config.PUBLIC_URL.startswith(("http://", "https://")):
        out.append("BI_PUBLIC_URL must start with https:// (or http://)")
    return out


def address() -> str:
    if config.PUBLIC_URL:
        return config.PUBLIC_URL
    host = "127.0.0.1" if config.HOST in ("0.0.0.0", "::", "") else config.HOST
    scheme = "https" if config.HTTPS else "http"
    default = 443 if config.HTTPS else 80
    return f"{scheme}://{host}" + ("" if config.PORT == default else f":{config.PORT}")


def build_servers() -> list[uvicorn.Server]:
    common = dict(log_config=log_config(), server_header=False, timeout_keep_alive=10,
                  proxy_headers=bool(config.TRUSTED_PROXIES), forwarded_allow_ips=config.TRUSTED_PROXIES or None)
    main = uvicorn.Config("app.main:app", host=config.HOST, port=config.PORT,
                          ssl_certfile=config.TLS_CERT or None, ssl_keyfile=config.TLS_KEY or None,
                          ssl_keyfile_password=config.TLS_KEY_PASSWORD, **common)
    servers = [uvicorn.Server(main)]
    if config.HTTP_REDIRECT_PORT:
        from .web import redirect_app
        servers.append(uvicorn.Server(uvicorn.Config(redirect_app, host=config.HOST, port=config.HTTP_REDIRECT_PORT,
                                                     lifespan="off", **common)))
    return servers


async def _run(servers: list[uvicorn.Server]) -> None:
    tasks = [asyncio.create_task(s.serve()) for s in servers]
    done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for s in servers:  # one stopped (Ctrl+C or error): stop the other
        s.should_exit = True
    await asyncio.gather(*tasks, return_exceptions=True)
    for t in done:
        t.result()


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m app.serve", description="Blasting Intelligence server")
    ap.add_argument("--url", action="store_true", help="print the address users open, then exit")
    ap.add_argument("--check", action="store_true", help="check the settings (server.env, certificate), then exit")
    args = ap.parse_args(argv)
    if args.url:
        print(address())
        return 0
    logging.config.dictConfig(log_config())
    problems = settings_problems()
    if args.check:
        for p in problems:
            print("ERROR:", p)
        if not problems:
            print(f"Settings OK — {address()} (listening on {config.HOST}:{config.PORT}"
                  + (f", HTTP {config.HTTP_REDIRECT_PORT} → HTTPS" if config.HTTP_REDIRECT_PORT else "") + ")")
        return 2 if problems else 0
    if problems:
        for p in problems:
            log.error(p)
        print("\nThe server was not started. Fix the settings above (server.env) and start again.", file=sys.stderr)
        return 2
    if config.HOST in ("0.0.0.0", "::") and not config.HTTPS and not config.TRUSTED_PROXIES:
        log.warning("Listening on the network WITHOUT HTTPS: passwords and data travel unencrypted. "
                    "Configure BI_TLS_CERT / BI_TLS_KEY (see docs/DEPLOYMENT.md).")
    from .config import ENV_FILE
    log.info("Blasting Intelligence %s · mode %s · %s%s", config.APP_VERSION, config.MODE, address(),
             f" · settings {ENV_FILE}" if ENV_FILE.is_file() else "")
    asyncio.run(_run(build_servers()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
