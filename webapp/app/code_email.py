"""The sign-in code email in D2D's look (item 51; until then it was three plain paragraphs).

On top, the sign-in page's dark band with the D2D lockup for dark grounds (white tile, ink rows, the middle row in the
logo mint) and a thin mint bar under it, as on the share image. Then the code, large, in a mint panel, one line on how
long it lasts and one on what to do with an email nobody asked for. A short footer names the product.

Email clients are not browsers, so it is built the way email has to be: tables and inline styles; no pictures (the mark
is drawn with table cells, so it shows where images are blocked, and nothing is fetched when the email is opened); no
web fonts (Manrope and Inter where they are installed, then the system's own); <style> only for phones and dark mode,
which a client that drops it never misses. Classic Outlook on Windows draws the corners square. The code is one run of
digits: the gaps between them are letter-spacing, so a double-click copies it whole. Plain keyboard characters only
(docs/d2d-relay.md, "Text people read").

    subject, html = code_email.render("123456", 10)                 the public site's sign-in
    subject, html = code_email.render("123456", 10, admin=True)     the admin portal's

    python -m app.code_email [out.html] [admin]                      writes an example, to look at in a browser
"""
from __future__ import annotations

import html as _html
import sys
from string import Template

SITE = "https://d2d.pasdacs.com"
HELP = "info@pasdacs.com"
HEAD = "Manrope,'Segoe UI',-apple-system,BlinkMacSystemFont,Roboto,'Helvetica Neue',Arial,sans-serif"
BODY = "Inter,'Segoe UI',-apple-system,BlinkMacSystemFont,Roboto,'Helvetica Neue',Arial,sans-serif"
INK, MINT = "#111111", "#00C48C"
_SP = "font-size:1px;line-height:1px;mso-line-height-rule:exactly;"          # a spacer cell


def _cell(width: int, height: int, color: str = "", corners: str = "", colspan: int = 1) -> str:
    fill = f' bgcolor="{color}"' if color else ""
    paint = f"background-color:{color};" if color else ""
    span = f' colspan="{colspan}"' if colspan > 1 else ""
    return (f'<td{span} width="{width}" height="{height}"{fill} style="width:{width}px;height:{height}px;{paint}{corners}{_SP}">'
            "&nbsp;</td>")


def _mark() -> str:
    """The D2D mark for small sizes (branding/pasdacs/assets/D2D, d2d-favicon-mark: three rows) on a dark ground: a
    44 px white tile, the D 22 px square in it, its rows 6 px high with 2 px gaps. The bowl's curve is each outer row's
    corner (the first value is for clients that only take round corners)."""
    gap = f'<tr><td colspan="2" height="2" style="height:2px;{_SP}">&nbsp;</td></tr>'
    rows = ('<table role="presentation" width="22" cellpadding="0" cellspacing="0" border="0" '
            'style="width:22px;border-collapse:separate;">'
            "<tr>" + _cell(21, 6, INK, "border-top-left-radius:2px;border-top-right-radius:6px;"
                                       "border-top-right-radius:10px 6px;") + _cell(1, 6) + "</tr>"
            + gap
            + "<tr>" + _cell(22, 6, MINT, "border-top-right-radius:1px 3px;border-bottom-right-radius:1px 3px;", 2) + "</tr>"
            + gap
            + "<tr>" + _cell(21, 6, INK, "border-bottom-left-radius:2px;border-bottom-right-radius:6px;"
                                         "border-bottom-right-radius:10px 6px;") + _cell(1, 6) + "</tr>"
            "</table>")
    edge = f'<tr><td colspan="3" height="11" style="height:11px;{_SP}">&nbsp;</td></tr>'
    return ('<table role="presentation" width="44" cellpadding="0" cellspacing="0" border="0" bgcolor="#FFFFFF" '
            'style="width:44px;background-color:#FFFFFF;border-radius:11px;border-collapse:separate;">'
            + edge + "<tr>" + _cell(11, 22) + f'<td width="22" style="width:22px;">{rows}</td>' + _cell(11, 22) + "</tr>"
            + edge + "</table>")


_PAGE = Template("""<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="x-apple-disable-message-reformatting">
<meta name="format-detection" content="telephone=no, date=no, address=no, email=no, url=no">
<meta name="color-scheme" content="light dark">
<meta name="supported-color-schemes" content="light dark">
<title>$title</title>
<!--[if mso]><noscript><xml><o:OfficeDocumentSettings><o:PixelsPerInch>96</o:PixelsPerInch></o:OfficeDocumentSettings></xml></noscript><![endif]-->
<style>
table,td{mso-table-lspace:0pt;mso-table-rspace:0pt}
@media only screen and (max-width:600px){
.d2d-outer{padding:24px 12px 32px!important}
.d2d-pad{padding-left:24px!important;padding-right:24px!important}
.d2d-code{font-size:32px!important;letter-spacing:6px!important;padding-left:6px!important}
}
</style>
<style>
:root{color-scheme:light dark;supported-color-schemes:light dark}
a[x-apple-data-detectors]{color:inherit!important;text-decoration:none!important;font-size:inherit!important;font-family:inherit!important;font-weight:inherit!important;line-height:inherit!important}
@media (prefers-color-scheme:dark){
.d2d-page{background-color:#0A0A0A!important}
.d2d-card{background-color:#161616!important;border-color:#262626!important}
.d2d-ink{color:#F5F5F5!important}
.d2d-ink2{color:#A3A3A3!important}
.d2d-faint{color:#8A8A8A!important}
.d2d-mint{color:#33D6A6!important}
.d2d-panel{background-color:#0F2A22!important;border-color:#1E4B3C!important}
.d2d-rule{border-top-color:#262626!important}
}
</style>
</head>
<body class="d2d-page" style="margin:0;padding:0;width:100%;background-color:#F6F6F6;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;">
<div style="display:none;font-size:1px;line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden;mso-hide:all;">$preheader</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#F6F6F6" class="d2d-page" style="width:100%;background-color:#F6F6F6;">
<tr><td align="center" class="d2d-outer" style="padding:40px 16px 48px;">
<!--[if mso]><table role="presentation" width="520" cellpadding="0" cellspacing="0" border="0" align="center"><tr><td><![endif]-->
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:520px;margin:0 auto;border-collapse:separate;">
<tr><td class="d2d-pad" bgcolor="#111111" style="padding:28px 40px;background-color:#111111;background-image:radial-gradient(circle at 88% 0%,rgba(0,196,140,0.18) 0%,rgba(0,196,140,0) 38%),linear-gradient(135deg,#111111 0%,#1C1C1C 55%,#262626 100%);border-radius:16px 16px 0 0;">
<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
<td width="44" valign="middle" style="width:44px;" aria-hidden="true">$mark</td>
<td width="14" style="width:14px;font-size:1px;line-height:1px;">&nbsp;</td>
<td valign="middle">
<div style="font-family:$head;font-size:23px;line-height:24px;font-weight:800;letter-spacing:3px;color:#FFFFFF;mso-line-height-rule:exactly;">D2D</div>
<div style="padding-top:3px;font-family:$head;font-size:10px;line-height:12px;font-weight:700;letter-spacing:2px;color:#A3A3A3;mso-line-height-rule:exactly;">DATA TO DECISION</div>
</td>
</tr></table>
</td></tr>
<tr><td height="4" bgcolor="#00C48C" style="height:4px;background-color:#00C48C;font-size:4px;line-height:4px;mso-line-height-rule:exactly;">&nbsp;</td></tr>
<tr><td class="d2d-card d2d-pad" bgcolor="#FFFFFF" style="padding:36px 40px;background-color:#FFFFFF;border:1px solid #E5E5E5;border-top:0;border-radius:0 0 16px 16px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;border-collapse:separate;">
<tr><td class="d2d-mint" style="padding:0 0 10px;font-family:$head;font-size:12px;line-height:16px;font-weight:700;letter-spacing:1.5px;color:#007A57;">$eyebrow</td></tr>
<tr><td><h1 class="d2d-ink" style="margin:0;font-family:$head;font-size:26px;line-height:32px;font-weight:800;letter-spacing:-0.5px;color:#111111;">Your sign-in code</h1></td></tr>
<tr><td class="d2d-ink2" style="padding:10px 0 0;font-family:$body;font-size:15px;line-height:24px;color:#525252;">$lead</td></tr>
<tr><td style="padding:24px 0 0;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;border-collapse:separate;">
<tr><td class="d2d-panel" align="center" bgcolor="#EBFBF5" style="padding:20px 12px;background-color:#EBFBF5;border:1px solid #CCF5E8;border-radius:12px;">
<span class="d2d-code d2d-ink" style="display:inline-block;padding-left:8px;font-family:$head;font-size:36px;line-height:44px;font-weight:800;letter-spacing:8px;color:#111111;">$code</span>
</td></tr>
</table>
</td></tr>
<tr><td class="d2d-ink2" style="padding:14px 0 0;font-family:$body;font-size:14px;line-height:22px;color:#525252;">$lasts</td></tr>
<tr><td style="padding:28px 0 0;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;"><tr><td class="d2d-rule" height="1" style="height:1px;border-top:1px solid #E5E5E5;font-size:1px;line-height:1px;mso-line-height-rule:exactly;">&nbsp;</td></tr></table>
</td></tr>
<tr><td class="d2d-faint" style="padding:18px 0 0;font-family:$body;font-size:13px;line-height:20px;color:#666666;">If you did not ask for this code, you can ignore this email. Never share it with anyone.</td></tr>
</table>
</td></tr>
<tr><td align="center" class="d2d-faint" style="padding:24px 16px 0;font-family:$body;font-size:12px;line-height:20px;color:#666666;">
D2D Relay - Data to Decision, a Relay Platform product by PASDACS<br>
<a href="$site" class="d2d-mint" style="color:#007A57;text-decoration:none;">$site_name</a>&nbsp;&nbsp;|&nbsp;&nbsp;<a href="mailto:$help" class="d2d-mint" style="color:#007A57;text-decoration:none;">$help</a>
</td></tr>
</table>
<!--[if mso]></td></tr></table><![endif]-->
</td></tr>
</table>
</body>
</html>
""")


def render(code: str, minutes: int, admin: bool = False) -> tuple[str, str]:
    """(subject, html) of the email that carries a sign-in code; admin=True for the admin portal's."""
    e = _html.escape
    lasts = f"It works once and expires in {minutes} minutes."
    page = _PAGE.substitute(
        title="D2D Relay sign-in code", preheader=e(lasts), mark=_mark(), head=HEAD, body=BODY,
        eyebrow="D2D RELAY ADMIN" if admin else "D2D RELAY",
        lead=f"Enter this code on the {'admin ' if admin else ''}sign-in page to continue.",
        code=e(code), lasts=e(lasts), site=SITE, site_name=SITE.split("://", 1)[-1], help=HELP)
    return f"D2D Relay sign-in code: {code}", page


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "sign-in-code-email.html"
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(render("482913", 10, admin="admin" in sys.argv[2:])[1])
    print(f"Wrote {out}")
