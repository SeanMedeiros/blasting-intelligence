"""Server-side translation of user-facing texts (English source, French catalogue).

* The language of a request comes from `?lang=`, then `X-Lang`, then `Accept-Language` (en | fr; default en).
  It is stored in a context variable by `LanguageMiddleware`, so every function reached by the request
  (routers, services, report generators) can call `_()` without passing the language around.
* `_("Pattern {code} has no drillhole design", code=p.code)` returns the English template or its French
  translation from `app/locales/fr.py`, formatted with the keyword arguments. Unknown texts fall back to
  English. A test checks that every `_()` template in the code has a French entry with the same fields.
* Codes (statuses, parameters, units) are never translated here: the interface translates codes itself.
"""
from __future__ import annotations

import contextvars
from datetime import date, datetime

LANGS = ("en", "fr")
_lang: contextvars.ContextVar[str] = contextvars.ContextVar("bi_lang", default="en")


def get_lang() -> str:
    return _lang.get()


def set_lang(lang: str) -> contextvars.Token:
    return _lang.set(lang if lang in LANGS else "en")


def pick(query: str | None, header: str | None, accept: str | None) -> str:
    for v in (query, header):
        if v and v[:2].lower() in LANGS:
            return v[:2].lower()
    for part in (accept or "").split(","):
        code = part.split(";")[0].strip()[:2].lower()
        if code in LANGS:
            return code
    return "en"


def N_(text: str) -> str:
    """Marks a constant for translation without translating it now (translated later with _())."""
    return text


def translate(text: str, lang: str, **kw) -> str:
    """Translation into an explicit language (e.g. the site language for stored default templates)."""
    if lang == "fr":
        from .locales.fr import FR

        text = FR.get(text, text)
    return text.format(**kw) if kw else text


def S_(text: str, /, **kw) -> str:
    """Text STORED in a record (notes, generated descriptions): written in the site language, BI_DEFAULT_LANGUAGE."""
    from .config import DEFAULT_LANGUAGE

    return translate(text, DEFAULT_LANGUAGE, **kw)


def _(text: str, /, **kw) -> str:
    if _lang.get() == "fr":
        from .locales.fr import FR

        text = FR.get(text, text)
    return text.format(**kw) if kw else text


class LanguageMiddleware:
    """Pure ASGI middleware (keeps the context variable visible to sync endpoints run in the thread pool)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        from urllib.parse import parse_qs

        q = parse_qs(scope.get("query_string", b"").decode("latin-1")).get("lang", [None])[0]
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        token = set_lang(pick(q, headers.get("x-lang"), headers.get("accept-language")))
        try:
            await self.app(scope, receive, send)
        finally:
            _lang.reset(token)


# ----------------------------------------------------------------------------- formatting
MONTHS_FR = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre")
MONTHS_EN = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
DAYS_FR = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
DAYS_EN = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def month_year(d: date) -> str:
    return f"{MONTHS_FR[d.month - 1]} {d.year}" if get_lang() == "fr" else f"{MONTHS_EN[d.month - 1]} {d.year}"


def long_date(d: date) -> str:
    if get_lang() == "fr":
        return f"{DAYS_FR[d.weekday()]} {d.day} {MONTHS_FR[d.month - 1]} {d.year}"
    return f"{DAYS_EN[d.weekday()]} {d.day} {MONTHS_EN[d.month - 1]} {d.year}"


def code_label(code: str) -> str:
    """Display label of a code (status, type) in the request language — same wording as the UI; unknown codes unchanged."""
    from .locales.codes import CODES
    return CODES.get(get_lang(), {}).get(code, code)


def num(v, digits: int = 1) -> str:
    """Number for reports: 1,234.5 (en) / 1 234,5 (fr — narrow no-break space thousands, decimal comma)."""
    if v is None:
        return "—"
    if isinstance(v, int) and not isinstance(v, bool):
        s = f"{v:,}"
    else:
        s = f"{float(v):,.{digits}f}"
    return s.replace(",", " ").replace(".", ",") if get_lang() == "fr" else s


def stamp(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")  # ISO-like in both languages (unambiguous)


# ----------------------------------------------------------------------------- input validation messages
_VALIDATION = {
    "missing": N_("required"),
    "string_too_short": N_("at least {min_length} characters"),
    "string_too_long": N_("at most {max_length} characters"),
    "greater_than": N_("must be greater than {gt}"),
    "greater_than_equal": N_("must be at least {ge}"),
    "less_than": N_("must be less than {lt}"),
    "less_than_equal": N_("must be at most {le}"),
    "int_parsing": N_("must be a whole number"),
    "int_from_float": N_("must be a whole number"),
    "float_parsing": N_("must be a number"),
    "date_from_datetime_parsing": N_("must be a date (YYYY-MM-DD)"),
    "date_parsing": N_("must be a date (YYYY-MM-DD)"),
    "datetime_from_date_parsing": N_("must be a date and time"),
    "datetime_parsing": N_("must be a date and time"),
    "bool_parsing": N_("must be true or false"),
    "string_pattern_mismatch": N_("invalid format"),
    "string_type": N_("must be text"),
    "literal_error": N_("must be one of {expected}"),
    "enum": N_("must be one of {expected}"),
    "json_invalid": N_("invalid JSON"),
    "list_type": N_("must be a list"),
}


def validation_message(err: dict) -> dict:
    """{loc, msg} with msg translated; custom ValueError messages are translated through the catalogue."""
    loc = [str(x) for x in err.get("loc", ()) if x not in ("body", "query", "path", "form")]
    field = ".".join(loc)
    typ = err.get("type", "")
    ctx = {k: v for k, v in (err.get("ctx") or {}).items() if isinstance(v, (int, float, str))}
    tpl = _VALIDATION.get(typ)
    if typ == "value_error":
        msg = _(str((err.get("ctx") or {}).get("error", err.get("msg", ""))))
    elif tpl:
        try:
            msg = _(tpl, **ctx) if ctx else _(tpl)
        except KeyError:
            msg = err.get("msg", "")
    else:
        msg = err.get("msg", "")
    return {"loc": loc, "msg": f"{field}: {msg}" if field else msg, "type": typ}
