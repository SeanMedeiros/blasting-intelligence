"""Network deployment: host/origin checks, security headers, HTTPS redirect, health probe, settings file,
certificates (internal CA, PFX import, checks) and the server launcher's configuration checks."""
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient
from helpers import CSRF, signed_client

from app import config, web
from app.main import app
from app.ops import tls


@pytest.fixture
def hosts(monkeypatch):
    """Change BI_ALLOWED_HOSTS / BI_PUBLIC_URL for one test."""
    def set_(allowed=(), public=""):
        monkeypatch.setattr(config, "ALLOWED_HOSTS", [*allowed, "testserver"])  # testserver: the in-process client
        monkeypatch.setattr(config, "PUBLIC_URL", public)
        web.allowed_hosts.cache_clear()
    yield set_
    web.allowed_hosts.cache_clear()


# ------------------------------------------------------------------ host, origin, headers
def test_security_headers_on_api_and_pages():
    with TestClient(app) as c:
        for path in ("/api/health", "/api/v1/meta", "/"):
            h = c.get(path).headers
            assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY", path
            assert "frame-ancestors 'none'" in h["content-security-policy"] and "script-src 'self'" in h["content-security-policy"]
            assert h["referrer-policy"] == "same-origin" and "strict-transport-security" not in h  # plain HTTP: no HSTS
    with TestClient(app, base_url="https://testserver") as c:
        assert "max-age=" in c.get("/api/health").headers["strict-transport-security"]


def test_attachment_policy_is_not_overridden():
    with signed_client("admin") as c:
        bid = c.get("/api/v1/blasts").json()["blasts"][0]["id"]
        up = c.post("/api/v1/attachments", data={"entity": "blast", "entity_id": str(bid)},
                    files={"file": ("note.txt", b"field note\n", "text/plain")})
        assert up.status_code == 201, up.text
        r = c.get(f"/api/v1/attachments/{up.json()['id']}/file")
        csp = r.headers.get_list("content-security-policy")
        assert r.status_code == 200 and len(csp) == 1 and csp[0].startswith("sandbox")  # the stricter file policy is kept


def test_unknown_host_names_are_refused(hosts):
    hosts(["blast.mine.local"])
    with TestClient(app) as c:
        assert c.get("/api/health", headers={"Host": "evil.example"}).status_code == 400
        assert c.get("/api/health", headers={"Host": "blast.mine.local:8443"}).status_code == 200
        assert c.get("/api/health", headers={"Host": "127.0.0.2"}).status_code == 200  # loopback
        assert c.get("/api/health", headers={"Host": "[::1]:8000"}).status_code == 200
    hosts([], public="https://blasting.example.org")
    assert web.host_allowed("blasting.example.org") and not web.host_allowed("other.example.org")
    hosts(["*"])
    assert web.host_allowed("anything.example")


def test_cross_site_writes_are_refused(hosts):
    hosts()
    with TestClient(app, headers=CSRF) as c:
        body = {"username": "admin", "password": "wrong-password-x"}
        assert c.post("/api/v1/auth/login", json=body, headers={"Origin": "https://evil.example"}).status_code == 403
        assert c.post("/api/v1/auth/login", json=body, headers={"Origin": "http://testserver"}).status_code == 401  # same site
        assert c.post("/api/v1/auth/login", json=body).status_code == 401  # no Origin (older clients, scripts)
        assert c.get("/api/v1/meta", headers={"Origin": "https://evil.example"}).status_code == 200  # reads unaffected
    # the development server is accepted only when the server itself is addressed as this computer
    assert web.origin_allowed("http://localhost:5173", "127.0.0.1:8000")
    assert not web.origin_allowed("http://localhost:5173", "blast.mine.local")
    hosts([], public="https://blasting.example.org")
    assert web.origin_allowed("https://blasting.example.org", "10.0.0.5:8443")  # behind a proxy that rewrites Host


def test_secure_cookie_when_https(monkeypatch):
    import app.routers.auth as auth_router
    monkeypatch.setattr(auth_router, "COOKIE_SECURE", True)
    with TestClient(app, base_url="https://testserver", headers=CSRF) as c:
        r = c.post("/api/v1/auth/login", json={"username": "admin", "password": config.DEMO_PASSWORD})
        sc = r.headers["set-cookie"].lower()
        assert r.status_code == 200 and "secure" in sc and "httponly" in sc and "samesite=strict" in sc


# ------------------------------------------------------------------ health, redirect, settings file
def test_health_reports_database_state(monkeypatch):
    with TestClient(app) as c:
        r = c.get("/api/health")
        assert r.status_code == 200 and r.json()["status"] == "ok"

        class Broken:
            url = None

            def connect(self):
                raise RuntimeError("down")
        import app.main as main
        monkeypatch.setattr(main, "engine", Broken())
        assert c.get("/api/health").status_code == 503


def test_http_listener_redirects_to_https(monkeypatch, hosts):
    hosts()
    monkeypatch.setattr(config, "PORT", 8443)
    with TestClient(web.redirect_app, base_url="http://localhost:8080") as c:
        r = c.get("/kpi?month=2026-11", follow_redirects=False)
        assert r.status_code == 308 and r.headers["location"] == "https://localhost:8443/kpi?month=2026-11"
        assert c.get("/", headers={"Host": "evil.example"}, follow_redirects=False).status_code == 400
    monkeypatch.setattr(config, "PORT", 443)
    hosts([], public="https://blasting.example.org")
    with TestClient(web.redirect_app, base_url="http://blasting.example.org") as c:
        assert c.get("/a", follow_redirects=False).headers["location"] == "https://blasting.example.org/a"


def test_server_env_file(tmp_path, monkeypatch):
    f = tmp_path / "server.env"
    f.write_text("# comment\nBI_TEST_ONE = 'quoted value'\n\nBI_TEST_TWO=2\n", encoding="utf-8")
    monkeypatch.delenv("BI_TEST_ONE", raising=False)
    monkeypatch.setenv("BI_TEST_TWO", "from-environment")
    config._load_env_file(f)
    import os
    assert os.environ["BI_TEST_ONE"] == "quoted value" and os.environ["BI_TEST_TWO"] == "from-environment"
    monkeypatch.delenv("BI_TEST_ONE")
    f.write_text("PATH=C:\\evil\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="line 1"):
        config._load_env_file(f)


# ------------------------------------------------------------------ certificates
def test_internal_ca_and_server_certificate(tmp_path):
    crt, key = tls.make_server_cert(tmp_path, ["blast.mine.local"], ["10.20.30.40"], days=365)
    info = tls.check_pair(str(crt), str(key))
    assert info.names == ["blast.mine.local", "10.20.30.40"] and 360 <= info.days_left <= 365 and not info.self_signed
    chain = x509.load_pem_x509_certificates(crt.read_bytes())
    assert len(chain) == 2 and chain[1].subject == chain[0].issuer  # server + CA
    if hasattr(Path, "stat") and not __import__("sys").platform.startswith("win"):
        assert (key.stat().st_mode & 0o077) == 0 and ((tmp_path / "ca.key").stat().st_mode & 0o077) == 0
    ca_before = (tmp_path / "ca.crt").read_bytes()
    tls.make_server_cert(tmp_path, ["blast2.mine.local"], [], days=200)  # renewal reuses the CA
    assert (tmp_path / "ca.crt").read_bytes() == ca_before
    (tmp_path / "ca.key").unlink()  # CA key kept offline: no silent new CA
    with pytest.raises(tls.TlsError, match="offline"):
        tls.make_server_cert(tmp_path, ["x.local"], [])
    with pytest.raises(tls.TlsError, match="397"):
        tls.make_server_cert(tmp_path, ["x.local"], [], days=800)
    with pytest.raises(tls.TlsError, match="IP"):
        tls.make_ca(tmp_path / "other") and tls.make_server_cert(tmp_path / "other", [], ["not-an-ip"])


def test_mismatched_or_expired_pair_refused(tmp_path):
    crt, _key = tls.make_server_cert(tmp_path, ["a.local"], [])
    other = tmp_path / "other.key"
    other.write_bytes(ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    with pytest.raises(tls.TlsError, match="does not belong"):
        tls.check_pair(str(crt), str(other))
    k, c = _self_signed(days=-1)
    (tmp_path / "old.crt").write_bytes(c.public_bytes(serialization.Encoding.PEM))
    (tmp_path / "old.key").write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    with pytest.raises(tls.TlsError, match="expired"):
        tls.check_pair(str(tmp_path / "old.crt"), str(tmp_path / "old.key"))


def _self_signed(days=90):
    k = ec.generate_private_key(ec.SECP256R1())
    n = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "blast.example.org")])
    now = datetime.now(UTC)
    c = (x509.CertificateBuilder().subject_name(n).issuer_name(n).public_key(k.public_key()).serial_number(1)
         .not_valid_before(now - timedelta(days=400)).not_valid_after(now + timedelta(days=days))
         .add_extension(x509.SubjectAlternativeName([x509.DNSName("blast.example.org")]), critical=False)
         .sign(k, hashes.SHA256()))
    return k, c


def test_import_company_pfx(tmp_path):
    k, c = _self_signed()
    pfx = tmp_path / "it.pfx"
    pfx.write_bytes(pkcs12.serialize_key_and_certificates(b"srv", k, c, None, serialization.BestAvailableEncryption(b"Pfx-pass-1")))
    with pytest.raises(tls.TlsError, match="password"):
        tls.import_pfx(tmp_path / "out", pfx, "wrong")
    crt, key = tls.import_pfx(tmp_path / "out", pfx, "Pfx-pass-1")
    info = tls.check_pair(str(crt), str(key))
    assert info.names == ["blast.example.org"] and info.self_signed


def test_manage_commands(tmp_path, monkeypatch, capsys):
    from app import manage
    monkeypatch.setattr(config, "TLS_DIR", tmp_path)
    assert manage.main(["make-cert", "--dns", "Blast.Mine.Local", "--ip", "10.0.0.5"]) == 0
    out = capsys.readouterr().out
    assert "blast.mine.local, 10.0.0.5" in out and "BI_TLS_CERT=" in out and "ca.crt" in out
    assert manage.main(["cert-info", str(tmp_path / "server.crt")]) == 0 and '"days_left"' in capsys.readouterr().out
    assert manage.main(["make-cert", "--dns", "x.local", "--days", "900"]) == 2


# ------------------------------------------------------------------ launcher configuration
def test_launcher_refuses_bad_settings(tmp_path, monkeypatch):
    from app import serve
    crt, key = tls.make_server_cert(tmp_path, ["localhost"], ["127.0.0.1"])
    for k, v in {"TLS_CERT": str(crt), "TLS_KEY": "", "HTTPS": False, "HTTP_REDIRECT_PORT": 0, "PUBLIC_URL": ""}.items():
        monkeypatch.setattr(config, k, v)
    assert any("together" in p for p in serve.settings_problems())
    monkeypatch.setattr(config, "TLS_KEY", str(key))
    monkeypatch.setattr(config, "HTTPS", True)
    monkeypatch.setattr(config, "PORT", 8443)
    assert serve.settings_problems() == [] and serve.address() == "https://127.0.0.1:8443"
    monkeypatch.setattr(config, "HTTP_REDIRECT_PORT", 8443)
    assert any("differ" in p for p in serve.settings_problems())
    monkeypatch.setattr(config, "TLS_KEY", str(tmp_path / "ca.key"))  # wrong key
    monkeypatch.setattr(config, "HTTP_REDIRECT_PORT", 0)
    assert any("does not belong" in p for p in serve.settings_problems())
    monkeypatch.setattr(config, "HTTPS", False)
    monkeypatch.setattr(config, "TLS_CERT", "")
    monkeypatch.setattr(config, "TLS_KEY", "")
    monkeypatch.setattr(config, "HTTP_REDIRECT_PORT", 80)
    assert any("needs HTTPS" in p for p in serve.settings_problems())
    servers = None
    monkeypatch.setattr(config, "HTTP_REDIRECT_PORT", 0)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "logs")
    servers = serve.build_servers()
    assert len(servers) == 1 and servers[0].config.proxy_headers is False  # X-Forwarded-* ignored unless a proxy is declared
    assert (tmp_path / "logs").is_dir()


def test_status_shows_server_access():
    with signed_client("admin") as c:
        s = c.get("/api/v1/system/status").json()["server"]
        assert s["https"] is False and s["certificate"] is None and "localhost" in s["host_check"] and "testserver" in s["host_check"]
        assert s["unencrypted_network"] is False
    with signed_client("eroy") as c:
        assert c.get("/api/v1/system/status").status_code == 403


def test_certificate_expiry_alert(tmp_path, monkeypatch):
    from app.analytics.rules import run_rules
    from app.db import SessionLocal
    crt, _key = tls.make_server_cert(tmp_path, ["blast.mine.local"], [], days=20)
    monkeypatch.setattr(config, "HTTPS", True)
    monkeypatch.setattr(config, "TLS_CERT", str(crt))
    with SessionLocal() as db:
        a = [x for x in run_rules(db) if x["rule"] == "TLS_CERTIFICATE"]
    assert len(a) == 1 and a[0]["severity"] == "HIGH" and "blast.mine.local" in a[0]["detail"]
    tls.make_server_cert(tmp_path, ["blast.mine.local"], [], days=200)
    with SessionLocal() as db:
        assert not [x for x in run_rules(db) if x["rule"] == "TLS_CERTIFICATE"]
