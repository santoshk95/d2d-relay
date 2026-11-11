"""D2D Relay: the AI engine's shell runs the toolkit, `genbi <command> ...`, and nothing else.

Claude Code calls this before every Bash command: a PreToolUse hook in /etc/claude-code/managed-settings.json, which
nothing in a project folder can change (the agent runs with --restricted: project and user settings are not read).
A command passes only when every part of it is a `genbi` call with one of the dashboard toolkit's commands:
  - parts may be chained with ; && || or new lines (the agent often runs `genbi validate && genbi prototype`),
    but every part is `genbi ...`: no other program, and no environment assignment in front (FOO=bar genbi ...),
  - no pipe or background job (a single | or &), no redirection or process substitution (< >), no subshell or
    grouping (parentheses), no command or variable substitution ($..., `...`, also inside double quotes).
Claude Code's own rules let read-only commands such as cat or ls run without asking; this hook is what stops a data
file or an attachment that tells the AI to "read ~/.claude", "list /data/projects" or "send this to ..." from doing
it. Paths given to genbi are kept inside the dashboard's folder by the toolkit itself (genbi_kit/cli.py).

Exit code 2 refuses the command, and what this prints to stderr is what the AI is told. Any failure here refuses too.
"""
import json
import sys

# The dashboard toolkit (GENBI.md, CLAUDE.md). Not repo, deck or doc: D2D Relay neither pushes to Git nor makes decks.
COMMANDS = {"profile", "sql", "validate", "prototype", "build", "daxcheck", "datagen", "gates", "catalog", "visual", "read"}
HELP = {"-h", "--help"}
SPECIAL_AFTER_DOLLAR = set("({[_?$!#@*-0123456789")


def commands(cmd: str):
    """The chained commands, each as its words the way the shell would see them, or a str saying why the whole
    command is refused."""
    out, cur, have, quote, i, n = [], [], False, None, 0, len(cmd)
    parts = [out]

    def end_word():
        nonlocal cur, have
        if cur or have:
            parts[-1].append("".join(cur))
            cur, have = [], False

    def next_part():
        end_word()
        if parts[-1]:
            parts.append([])

    while i < n:
        c = cmd[i]
        if quote == "'":                                   # single quotes: everything is literal
            if c == "'":
                quote = None
            else:
                cur.append(c)
        elif quote == '"':                                 # double quotes: $ and ` still expand in a shell
            if c == '"':
                quote = None
            elif c == "\\" and i + 1 < n and cmd[i + 1] in '"\\$`\n':
                i += 1
                if cmd[i] != "\n":
                    cur.append(cmd[i])
            elif c == "`" or (c == "$" and i + 1 < n and (cmd[i + 1].isalpha() or cmd[i + 1] in SPECIAL_AFTER_DOLLAR)):
                return "no command or variable substitution ($... or `...`) in a toolkit call"
            else:
                cur.append(c)
        elif c in "'\"":
            quote, have = c, True
        elif c == "\\":
            if i + 1 >= n or cmd[i + 1] in "\n\r":
                return "no line continuations (\\ at the end of a line)"
            i += 1
            cur.append(cmd[i])
            have = True
        elif c in " \t":
            end_word()
        elif c in ";\n\r":
            next_part()
        elif c in "&|" and i + 1 < n and cmd[i + 1] == c:     # && and ||: the next part runs depending on this one
            next_part()
            i += 1
        elif c in "&|<>()`$":
            what = {"&": "a background job", "|": "a pipe", "<": "redirection", ">": "redirection", "(": "a subshell",
                    ")": "a subshell", "`": "command substitution", "$": "substitution"}[c]
            return (f"{c!r} outside quotes ({what}) is not allowed: run `genbi` commands only, on their own or "
                    "chained with && or ;")
        else:
            cur.append(c)
            have = True
        i += 1
    if quote:
        return "a quote is not closed"
    end_word()
    return [p for p in parts if p]


def verdict(cmd: str):
    """None when the command may run, else why not."""
    if not isinstance(cmd, str) or not cmd.strip():
        return "an empty command"
    if len(cmd) > 100_000:
        return "the command is too long"
    parts = commands(cmd)
    if isinstance(parts, str):
        return parts
    if not parts:
        return "an empty command"
    if len(parts) > 20:
        return "too many chained commands: run them in smaller groups"
    for w in parts:
        if w[0] != "genbi":
            return (f"the shell runs only the toolkit (`genbi <command> ...`), not `{w[0][:40]}`. Read and write files "
                    "with the Read, Write and Edit tools, inside this dashboard's folder; query the data with `genbi sql`.")
        if len(w) > 1 and w[1] not in HELP and w[1] not in COMMANDS:
            return f"`genbi {w[1][:40]}` is not available here; the toolkit's commands are: " + ", ".join(sorted(COMMANDS))
    return None


def main() -> int:
    try:
        event = json.load(sys.stdin)
        if event.get("tool_name") not in (None, "Bash"):
            return 0
        reason = verdict((event.get("tool_input") or {}).get("command"))
    except Exception as e:  # noqa: BLE001 - refuse when in doubt
        reason = f"the command could not be checked ({type(e).__name__})"
    if reason is None:
        return 0
    print(f"Refused by D2D Relay: {reason}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
