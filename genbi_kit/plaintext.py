"""Plain keyboard characters in what people read (D2D Relay, 2026-11-12: "humanize it ... ensure all characters look
human"). A long dash becomes a hyphen, curly quotes straight ones, an ellipsis three dots, an arrow "->", a bullet or a
middle dot "-". Kept: check marks, crosses, up and down arrows, multiplication, approx, plus-minus and currency signs,
which are icons and data symbols.

The web app shows the AI's notes and answers through human(); the report builder writes titles, subtitles, text boxes,
alt text, page names, descriptions and display folders through it; the Report & accessibility gate names what is left
(measure, column and table names, which other parts of the report refer to)."""
import re

MAP = {"\u2014": "-", "\u2013": "-", "\u2212": "-", "\u2026": "...", "\u201c": '"', "\u201d": '"', "\u2018": "'",
       "\u2019": "'", "\u00b7": "-", "\u2022": "-", "\u203a": ">", "\u2039": "<", "\u2192": "->", "\u2190": "<-",
       "\u2194": "<->", "\u00ab": '"', "\u00bb": '"'}
WORDS = {"\u2014": "a long dash", "\u2013": "a long dash", "\u2212": "a minus sign", "\u2026": "an ellipsis character",
         "\u201c": "curly quotes", "\u201d": "curly quotes", "\u2018": "curly quotes", "\u2019": "curly quotes",
         "\u00b7": "a middle dot", "\u2022": "a bullet character", "\u203a": "an angle quote", "\u2039": "an angle quote",
         "\u2192": "an arrow", "\u2190": "an arrow", "\u2194": "an arrow", "\u00ab": "angle quotes", "\u00bb": "angle quotes"}
_ANY = re.compile("[" + "".join(MAP) + "]")
_DASH_JOIN = re.compile("(?<=\\w)\u2014(?=\\w)")               # "data\u2014and more": a long dash between two words


def human(text):
    """The text in plain keyboard characters. Anything that is not a string comes back as it is."""
    if not isinstance(text, str) or not _ANY.search(text):
        return text
    text = _DASH_JOIN.sub(" - ", text)
    return _ANY.sub(lambda m: MAP[m.group()], text)


def found(text) -> list[str]:
    """What a text has that is not plain, in words ("a long dash", "curly quotes"), each once; [] when it is plain."""
    if not isinstance(text, str):
        return []
    return list(dict.fromkeys(WORDS[c] for c in _ANY.findall(text)))
