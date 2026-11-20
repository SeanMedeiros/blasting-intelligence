"""Administration commands. Run from the backend folder:

    python -m app.manage db-upgrade                 apply pending schema migrations
    python -m app.manage db-current                 show schema revision and database type
    python -m app.manage backup [--reason TEXT]     create a backup now (server may be running)
    python -m app.manage backups                    list backups
    python -m app.manage verify FILE                check a backup
    python -m app.manage restore FILE --yes         restore a backup (STOP THE SERVER FIRST)
    python -m app.manage copy-db --to URL [--from URL]   copy all data into another empty database
    python -m app.manage set-password USERNAME      set a password (prompts), unlocks the account
    python -m app.manage create-admin USERNAME      create an administrator (prompts for the password)
    python -m app.manage ensure-admin               if no account exists yet, create the first administrator (prompts)
    python -m app.manage make-cert [--dns NAME]... [--ip ADDR]... [--days N]
                                                    HTTPS certificate from the site's internal CA (created if needed)
    python -m app.manage import-pfx FILE            HTTPS certificate issued by IT (.pfx / .p12; prompts for its password)
    python -m app.manage cert-info [FILE]           names and expiry of a certificate (default: the configured one)
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys

from sqlalchemy.engine import make_url


def _mask(url: str) -> str:
    return make_url(url).render_as_string(hide_password=True)


def _password(args) -> str:
    pwd = os.getenv("BI_NEW_PASSWORD") or getpass.getpass("New password: ")
    if not os.getenv("BI_NEW_PASSWORD") and getpass.getpass("Repeat: ") != pwd:
        sys.exit("Passwords do not match")
    return pwd


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.manage", description="Blasting Intelligence administration")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("db-upgrade")
    sub.add_parser("db-current")
    b = sub.add_parser("backup")
    b.add_argument("--reason", default="manual")
    sub.add_parser("backups")
    v = sub.add_parser("verify")
    v.add_argument("file")
    r = sub.add_parser("restore")
    r.add_argument("file")
    r.add_argument("--yes", action="store_true", help="confirm that the server is stopped and data will be replaced")
    c = sub.add_parser("copy-db")
    c.add_argument("--from", dest="src", default=None, help="source URL (default: BI_DATABASE_URL)")
    c.add_argument("--to", dest="dst", required=True, help="destination URL, e.g. postgresql+psycopg://user:pass@host/db")
    s = sub.add_parser("set-password")
    s.add_argument("username")
    a = sub.add_parser("create-admin")
    a.add_argument("username")
    a.add_argument("--full-name", default="Administrator")
    sub.add_parser("ensure-admin")
    mc = sub.add_parser("make-cert")
    mc.add_argument("--dns", action="append", default=None, help="server name users type (repeatable); default: this computer's names")
    mc.add_argument("--ip", action="append", default=None, help="server IP address (repeatable); default: this computer's IPv4 addresses")
    mc.add_argument("--days", type=int, default=365)
    ip_ = sub.add_parser("import-pfx")
    ip_.add_argument("file")
    ci = sub.add_parser("cert-info")
    ci.add_argument("file", nargs="?")
    args = p.parse_args(argv)

    from .config import DATABASE_URL
    from .ops import backup as bk

    try:
        if args.cmd == "db-upgrade":
            from .migrate import upgrade

            print("Schema revision:", upgrade())
        elif args.cmd == "db-current":
            from .migrate import current, head

            print(json.dumps({"database": _mask(DATABASE_URL), "revision": current(), "head": head()}, indent=2))
        elif args.cmd == "backup":
            print(bk.create_backup(reason=args.reason))
        elif args.cmd == "backups":
            for x in bk.list_backups():
                print(f"{x['file']:60s} {x['size_bytes'] / 1e6:8.1f} MB  {x['dialect'] or '?':10s} rev {x['schema_revision']}")
        elif args.cmd == "verify":
            m = bk.verify_backup(bk.resolve(args.file))
            print("OK —", json.dumps({k: m[k] for k in ("created_at", "reason", "dialect", "schema_revision", "app_version")}))
        elif args.cmd == "restore":
            if not args.yes:
                sys.exit("Refused: stop the server, then repeat with --yes (the current data is backed up first).")
            print(json.dumps(bk.restore_backup(bk.resolve(args.file)), indent=2))
        elif args.cmd == "copy-db":
            src = args.src or DATABASE_URL
            print(f"Copying {_mask(src)} → {_mask(args.dst)}")
            res = bk.copy_database(src, args.dst)
            print(f"Done: {res['tables']} tables, {res['rows']} rows. Set BI_DATABASE_URL to the destination and restart.")
        elif args.cmd in ("make-cert", "import-pfx", "cert-info"):
            return _tls(args)
        elif args.cmd == "ensure-admin":
            from .db import SessionLocal
            from . import models as m

            with SessionLocal() as db:
                if db.query(m.AppUser.id).first() is not None:
                    print("User accounts already exist — nothing to do.")
                    return 0
            print("No user account yet. Create the first administrator.")
            uname = (input("Username [admin]: ").strip() or "admin").lower()
            full = input("Full name [Administrator]: ").strip() or "Administrator"
            return main(["create-admin", uname, "--full-name", full])
        elif args.cmd in ("set-password", "create-admin"):
            from sqlalchemy import select

            from . import models as m
            from .db import SessionLocal
            from .services.audit import record
            from .services.security import check_password_policy, hash_password, revoke_sessions

            uname = args.username.strip().lower()
            with SessionLocal() as db:
                u = db.scalars(select(m.AppUser).where(m.AppUser.username == uname)).first()
                if args.cmd == "create-admin" and u is not None:
                    sys.exit(f"User '{uname}' already exists — use set-password")
                if args.cmd == "set-password" and u is None:
                    sys.exit(f"Unknown user '{uname}'")
                pwd = _password(args)
                try:
                    check_password_policy(pwd, uname)
                except Exception as e:  # HTTPException from the policy check
                    sys.exit(getattr(e, "detail", str(e)))
                if u is None:
                    u = m.AppUser(username=uname, full_name=args.full_name, role="ADMIN", password_hash=hash_password(pwd),
                                  must_change_password=False)
                    db.add(u)
                    db.flush()
                    record(db, "app_user", u.id, "CREATE", "console", {"username": uname, "role": "ADMIN"})
                else:
                    u.password_hash, u.locked_until, u.failed_attempts, u.active = hash_password(pwd), None, 0, True
                    revoke_sessions(db, u.id)
                    record(db, "app_user", u.id, "UPDATE", "console", {"password": "set from console"})
                db.commit()
            print(f"OK — {uname}")
    except bk.BackupError as e:
        print("ERROR:", e, file=sys.stderr)
        return 2
    return 0


def _tls(args) -> int:
    from pathlib import Path

    from .config import TLS_CERT, TLS_DIR
    from .ops import tls

    try:
        if args.cmd == "make-cert":
            dns0, ips0 = tls.default_names()
            dns = [d.lower() for d in (args.dns or dns0)]
            ips = args.ip if args.ip is not None else ips0
            crt, key = tls.make_server_cert(TLS_DIR, dns, ips, args.days)
            info = tls.cert_info(crt)
            print(f"Certificate for: {', '.join(info.names)} — valid until {info.not_after:%Y-%m-%d}")
        elif args.cmd == "import-pfx":
            pwd = os.getenv("BI_PFX_PASSWORD")
            if pwd is None:
                pwd = getpass.getpass("PFX password (empty if none): ")
            crt, key = tls.import_pfx(TLS_DIR, Path(args.file), pwd or None)
            info = tls.check_pair(str(crt), str(key))
            print(f"Imported: {info.subject} — {', '.join(info.names)} — valid until {info.not_after:%Y-%m-%d}")
        else:
            f = args.file or TLS_CERT or str(TLS_DIR / "server.crt")
            print(json.dumps(tls.cert_info(f).as_dict(), indent=2))
            return 0
    except tls.TlsError as e:
        print("ERROR:", e, file=sys.stderr)
        return 2
    print(f"\nIn server.env set:\n  BI_TLS_CERT={crt}\n  BI_TLS_KEY={key}")
    if args.cmd == "make-cert":
        print(f"Install {TLS_DIR / 'ca.crt'} as a trusted root on every workstation (see docs/DEPLOYMENT.md), "
              f"then keep {TLS_DIR / 'ca.key'} offline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
