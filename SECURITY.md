# Security policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Use GitHub's
[private vulnerability reporting](../../security/advisories/new) (Security tab → *Report a vulnerability*).
Include the version, the affected screen or endpoint, steps to reproduce and the impact you observed.
You should receive an acknowledgement within 5 working days.

## Supported versions

Only the latest release receives fixes.

## Scope and design notes

- Authentication: personal accounts, scrypt password hashes, HttpOnly SameSite=Strict session cookies (Secure over
  HTTPS), CSRF header on writes, account lock-out, role-based permissions checked on the server for every write.
- Network: host-name and origin checks, Content-Security-Policy, HSTS over HTTPS, forwarded headers trusted only from
  declared proxies (see `docs/DEPLOYMENT.md` §5).
- Evidence files: type recognised from content, macros / executables / HTML / SVG refused, SHA-256 checked at every
  download, served with a sandboxing policy.
- Out of scope: findings that require an administrator account or physical access to the server, and the
  demonstration accounts/password documented for the bundled fictional dataset (demonstration mode only).

The software never calculates explosive loads, issues loading or firing instructions, or authorizes blasting;
reports that it can be made to do so are treated as safety issues with the same priority as security issues.
