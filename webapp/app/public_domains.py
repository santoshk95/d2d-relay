"""D2D Relay: email domains that are not an organisation's own - free mail and disposable (throw-away) mail.

Since item 39 (the user, 2026-11-13: "allow gmail and all emails ... they can only buy online"): an address at a free
mail domain (Gmail, Outlook, Yahoo ...: FREE and FAMILY) signs in to a personal workspace of its own (orgs.py), never to
an organisation shared by domain. Disposable mail (DISPOSABLE, and D2D_PUBLIC_DOMAINS_EXTRA) still cannot sign in.

  D2D_PUBLIC_DOMAINS_EXTRA   more domains to refuse (comma-separated)
  D2D_PUBLIC_DOMAINS_ALLOW   domains to accept although they are listed here (comma-separated)
"""
from __future__ import annotations

import os
import re

# Free mail providers, with the brands that use many country domains matched by FAMILY below.
FREE = {
    "gmail.com", "googlemail.com", "yahoo.com", "ymail.com", "rocketmail.com", "outlook.com", "hotmail.com", "live.com",
    "msn.com", "passport.com", "icloud.com", "me.com", "mac.com", "aol.com", "aim.com", "protonmail.com", "protonmail.ch",
    "proton.me", "pm.me", "gmx.com", "gmx.net", "gmx.de", "gmx.at", "gmx.ch", "gmx.us", "mail.com", "email.com", "usa.com",
    "yandex.com", "yandex.ru", "ya.ru", "yandex.ua", "yandex.by", "yandex.kz", "zoho.com", "zohomail.com", "zohomail.in",
    "zohomail.eu", "rediffmail.com", "rediff.com", "qq.com", "foxmail.com", "163.com", "126.com", "yeah.net", "188.com",
    "sina.com", "sina.cn", "sohu.com", "aliyun.com", "139.com", "naver.com", "daum.net", "hanmail.net", "mail.ru", "bk.ru",
    "inbox.ru", "list.ru", "internet.ru", "rambler.ru", "web.de", "t-online.de", "freenet.de", "libero.it", "virgilio.it",
    "tiscali.it", "alice.it", "laposte.net", "orange.fr", "wanadoo.fr", "free.fr", "sfr.fr", "seznam.cz", "centrum.cz",
    "wp.pl", "o2.pl", "op.pl", "interia.pl", "onet.pl", "abv.bg", "ukr.net", "i.ua", "meta.ua", "tutanota.com",
    "tutanota.de", "tutamail.com", "tuta.io", "tuta.com", "fastmail.com", "fastmail.fm", "hushmail.com", "hey.com",
    "mailfence.com", "posteo.de", "posteo.net", "runbox.com", "disroot.org", "mailbox.org", "inbox.com", "lycos.com",
    "excite.com", "juno.com", "netzero.net", "earthlink.net", "comcast.net", "verizon.net", "att.net", "sbcglobal.net",
    "bellsouth.net", "cox.net", "charter.net", "optonline.net", "btinternet.com", "sky.com", "virginmedia.com",
    "talktalk.net", "ntlworld.com", "bigpond.com", "bigpond.net.au", "optusnet.com.au", "shaw.ca", "rogers.com",
    "sympatico.ca", "telus.net", "uol.com.br", "bol.com.br", "terra.com.br", "ig.com.br", "sapo.pt", "indiatimes.com",
    "sify.com", "duck.com", "privaterelay.appleid.com", "anonaddy.com", "anonaddy.me", "simplelogin.com", "simplelogin.co",
    "aleeas.com", "slmail.me", "33mail.com",
}
# Disposable / throw-away mail
DISPOSABLE = {
    "mailinator.com", "guerrillamail.com", "guerrillamail.net", "guerrillamail.org", "guerrillamail.biz",
    "guerrillamailblock.com", "sharklasers.com", "grr.la", "spam4.me", "10minutemail.com", "10minutemail.net",
    "temp-mail.org", "temp-mail.io", "tempmail.com", "tempmail.net", "tempmailo.com", "tempr.email", "tempail.com",
    "throwawaymail.com", "yopmail.com", "yopmail.net", "yopmail.fr", "trashmail.com", "trashmail.de", "trashmail.net",
    "getnada.com", "nada.email", "dispostable.com", "maildrop.cc", "mailnesia.com", "mintemail.com", "mohmal.com",
    "mytemp.email", "emailondeck.com", "fakeinbox.com", "fakemail.net", "burnermail.io", "spamgourmet.com",
    "mailcatch.com", "moakt.com", "tmail.ws", "tmpmail.org", "tmpmail.net", "discard.email", "emailfake.com",
    "crazymailing.com", "inboxkitten.com", "mail.tm", "mail.gw", "getairmail.com", "mailpoof.com", "emailtemporanea.com",
    "spambox.us", "mailforspam.com", "tempinbox.com", "jetable.org", "mail-temp.com", "minuteinbox.com",
}
# Brands with a free-mail domain in many countries: yahoo.co.in, hotmail.co.uk, outlook.com.au, live.fr, gmx.it ...
FAMILY = re.compile(r"^(yahoo|ymail|rocketmail|hotmail|outlook|live|msn|windowslive|gmx|yandex|aol|rediffmail|zohomail"
                    r"|protonmail|gmail|googlemail|icloud)\.(com|net|org|[a-z]{2}|co\.[a-z]{2}|com\.[a-z]{2})$")


def _env(name: str) -> set[str]:
    return {d.strip().lower().lstrip("@") for d in (os.environ.get(name) or "").split(",") if d.strip()}


EXTRA, ALLOW = _env("D2D_PUBLIC_DOMAINS_EXTRA"), _env("D2D_PUBLIC_DOMAINS_ALLOW")


def _norm(domain: str) -> str:
    return (domain or "").strip().lower().rstrip(".")


def is_disposable(domain: str) -> bool:
    """Throw-away mail (and D2D_PUBLIC_DOMAINS_EXTRA): it cannot sign in at all."""
    d = _norm(domain)
    return bool(d) and d not in ALLOW and (d in DISPOSABLE or d in EXTRA)


def is_free(domain: str) -> bool:
    """Free mail (Gmail, Outlook, Yahoo ...): each address gets a personal workspace (item 39)."""
    d = _norm(domain)
    return bool(d) and d not in ALLOW and not is_disposable(d) and (d in FREE or bool(FAMILY.match(d)))


def is_public(domain: str) -> bool:
    """Whether an email domain is free or disposable mail (not an organisation's own)."""
    return is_free(domain) or is_disposable(domain)
