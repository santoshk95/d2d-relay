"""DAX text helpers for the PBIP build and the checks: quoting table names, and finding what a calculated column
depends on. DAX is not parsed here; strings, 'quoted names', [columns] and comments are skipped as whole tokens."""
import re

TOKEN = re.compile(r'''"(?:[^"]|"")*"            # "string"
                     | '(?:[^']|'')*'            # 'quoted table name'
                     | \[[^\]]*\]                # [column] or [measure]
                     | //[^\n]* | --[^\n]* | /\*.*?\*/    # comments
                     | (?P<id>[A-Za-z_][A-Za-z0-9_]*)     # a bare word
                  ''', re.S | re.X)
VAR = re.compile(r"\bVAR\s+([A-Za-z_][A-Za-z0-9_]*)", re.I)


def _words(expr: str):
    """(start, end, word) for every bare word outside strings, quoted names, brackets and comments."""
    for m in TOKEN.finditer(expr):
        if m.group("id"):
            yield m.start(), m.end(), m.group("id")


def _next_char(expr: str, i: int) -> str:
    rest = expr[i:].lstrip()
    return rest[:1]


def quote_tables(expr: str, tables) -> str:
    """Put every bare table name in single quotes: Batch[Yield] -> 'Batch'[Yield], COUNTROWS ( Batch ) ->
    COUNTROWS ( 'Batch' ). Power BI rejects a bare table name that is a reserved word or a function name (Batch,
    Date, Product …) and accepts quotes on every name. A word is a table reference when it names a table, is
    followed by [ ) , or the end, is not a variable and not part of a dotted name (STDEV.S)."""
    names = {t.lower() for t in tables}
    text = str(expr)
    variables = {m.group(1).lower() for m in VAR.finditer(_mask(text))}
    out, last = [], 0
    for start, end, word in _words(text):
        if word.lower() not in names or word.lower() in variables:
            continue
        if (start and text[start - 1] == ".") or text[end:end + 1] == ".":
            continue
        if _next_char(text, end) not in ("[", ")", ",", ""):
            continue
        out.append(text[last:start] + f"'{word}'")
        last = end
    return "".join(out) + text[last:]


def _mask(expr: str) -> str:
    """The expression with strings, quoted names, brackets and comments blanked out."""
    return TOKEN.sub(lambda m: m.group(0) if m.group("id") else " " * len(m.group(0)), str(expr))


def uses_whole_table(expr: str, table: str) -> bool:
    """Does a calculated column on `table` depend on every column of it? A bare or quoted reference to the table
    that is not a column qualifier (ALL ( Batch ), FILTER ( 'Batch', … ), COUNTROWS ( Batch )), or CALCULATE /
    CALCULATETABLE (context transition) do."""
    text, low = str(expr), table.lower()
    for m in TOKEN.finditer(text):
        tok = m.group(0)
        name = m.group("id") or (tok[1:-1].replace("''", "'") if tok.startswith("'") else None)
        if name is None:
            continue
        if m.group("id") and name.upper() in ("CALCULATE", "CALCULATETABLE") and _next_char(text, m.end()) == "(":
            return True
        if name.lower() == low and _next_char(text, m.end()) != "[":
            return True
    return False


def refers_to(expr: str, table: str, column: str) -> bool:
    """Does the expression read table[column] (qualified, in either quoting) or [column] on its own?"""
    text = str(expr)
    for m in re.finditer(r"(?:'((?:[^']|'')*)'|([A-Za-z_][A-Za-z0-9_]*))?\s*\[([^\]]*)\]", _strip_strings(text)):
        t = (m.group(1) or m.group(2) or "").replace("''", "'")
        if m.group(3).strip().lower() == column.lower() and (not t or t.lower() == table.lower()):
            return True
    return False


def _strip_strings(expr: str) -> str:
    return re.sub(r'"(?:[^"]|"")*"|//[^\n]*|--[^\n]*|/\*.*?\*/', lambda m: " " * len(m.group(0)), expr, flags=re.S)
