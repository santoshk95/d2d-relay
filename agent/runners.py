"""Other agent CLIs behind the agent's Runner interface (platform plan, phase 8): OpenAI Codex CLI, Gemini CLI and
Antigravity CLI. Each runs headless in the project folder and streams JSON lines, which are turned into the same
normalised events as Claude Code's (start, say, tool, result, done with usage - or error), so the web app, the
activity log, the cost records and the review gates work the same for every runner.

The same limits as Claude Code, as far as each CLI can enforce them:
  codex        `codex exec --json`, sandbox workspace-write (files in the project only, no network for commands),
               approvals never (nothing waits for a person), web search off
  gemini       `gemini -p --output-format stream-json`, the system settings file (/etc/gemini-cli/settings.json in
               the image) allows only the file tools and `run_shell_command(genbi)`; web tools and MCP are excluded
  antigravity  `agy --input-format stream-json --output-format stream-json --mode accept-edits` (prompt on stdin),
               the CLI's settings allow `command(genbi)` and a few read-only commands; file writes inside the
               workspace are accepted, anything else is denied in headless mode (which ends the run);
               it signs in with the owner's Gemini API key, else the antigravity-api gateway's shared Google login
The guide each reads: AGENTS.md (Codex, Antigravity) and GEMINI.md (Gemini CLI), written by the web app next to
CLAUDE.md from the same genbi_kit/GENBI.md.
"""
import asyncio
import json
import os
import shutil
from collections.abc import AsyncIterator
from pathlib import Path


def _short(text, n: int = 400) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 3] + "..."


def _prompt(run) -> str:
    """CLIs without a system-prompt flag get the app's instructions in front of the task."""
    return (f"# Instructions from the app\n{run.system}\n\n# Task\n" if run.system else "") + run.prompt


class CliRunner:
    """Start the CLI, read JSON lines from stdout, normalise them; kill it on timeout or when the client goes."""
    name = ""
    binary = ""

    @classmethod
    def available(cls) -> bool:
        return shutil.which(cls.binary) is not None

    def args(self, run, model: str | None) -> list[str]:
        raise NotImplementedError

    def stdin(self, run) -> bytes | None:
        return _prompt(run).encode()

    def parse(self, obj: dict, st: dict):
        raise NotImplementedError

    async def run(self, run, workdir: Path, model: str | None, env: dict) -> AsyncIterator[dict]:
        proc = await asyncio.create_subprocess_exec(
            *self.args(run, model), cwd=workdir, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, limit=16 * 1024 * 1024, env=env)
        data = self.stdin(run)
        if data is not None:
            proc.stdin.write(data)
            await proc.stdin.drain()
        proc.stdin.close()
        st: dict = {"text": [], "turns": 0, "model": model}
        done = False
        try:
            async with asyncio.timeout(run.timeout_s):
                while True:
                    line = await proc.stdout.readline()
                    if not line:
                        break
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    for ev in self.parse(obj, st):
                        done = done or ev["kind"] in ("done", "error")
                        yield ev
                await proc.wait()
        except TimeoutError:
            yield {"kind": "error", "text": f"Agent run timed out after {run.timeout_s // 60} minutes"}
            return
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
        if not done:
            err = (await proc.stderr.read()).decode(errors="replace").strip()
            yield {"kind": "error", "text": _short(st.get("last_error") or err or f"{self.binary} exited with code {proc.returncode}", 1500)}


# ---------------------------------------------------------------- OpenAI Codex CLI

class CodexRunner(CliRunner):
    name, binary = "codex", "codex"

    def args(self, run, model):
        a = ["codex", "exec"]
        if run.resume:
            a += ["resume", run.resume]
        a += ["--json", "--skip-git-repo-check", "--sandbox", "workspace-write",
              "-c", 'approval_policy="never"', "-c", "tools.web_search=false",
              "-c", "sandbox_workspace_write.network_access=false"]
        if model:
            a += ["-m", model]
        return a + ["-"]                                     # the prompt comes on stdin

    def parse(self, obj, st):
        t, item = obj.get("type"), obj.get("item") or {}
        if t == "thread.started":
            st["session"] = obj.get("thread_id")
            yield {"kind": "start", "model": st.get("model"), "session_id": st["session"]}
        elif t == "item.started" and item.get("type") == "command_execution":
            yield {"kind": "tool", "id": item.get("id"), "tool": "Bash", "detail": _short(item.get("command"), 300)}
        elif t == "item.completed":
            kind = item.get("type")
            if kind == "agent_message" and (item.get("text") or "").strip():
                st["text"].append(item["text"].strip())
                yield {"kind": "say", "text": item["text"].strip()}
            elif kind == "command_execution":
                yield {"kind": "result", "id": item.get("id"), "ok": item.get("exit_code") in (0, None) and item.get("status") != "failed",
                       "text": _short(item.get("aggregated_output") or "", 600)}
            elif kind == "file_change":
                paths = ", ".join(Path(c.get("path", "")).name for c in item.get("changes") or [])
                yield {"kind": "tool", "id": item.get("id"), "tool": "Edit", "detail": paths}
                yield {"kind": "result", "id": item.get("id"), "ok": item.get("status") != "failed", "text": paths}
        elif t == "turn.started":
            st["turns"] += 1
        elif t == "turn.completed":
            u = obj.get("usage") or {}
            cached = u.get("cached_input_tokens") or 0
            usage = {"input": max(0, (u.get("input_tokens") or 0) - cached), "cache_write": 0, "cache_read": cached,
                     "output": (u.get("output_tokens") or 0) + (u.get("reasoning_output_tokens") or 0)}
            yield {"kind": "done", "ok": True, "subtype": "success", "text": st["text"][-1] if st["text"] else "",
                   "turns": st["turns"], "cost_usd": None, "duration_ms": None, "session_id": st.get("session"),
                   "usage": usage, "models": {st.get("model") or "codex": {**usage, "cost_usd": 0}}}
        elif t == "turn.failed":
            err = (obj.get("error") or {}).get("message") or "the turn failed"
            yield {"kind": "done", "ok": False, "subtype": "error", "text": _short(err, 1500), "session_id": st.get("session"),
                   "turns": st["turns"], "usage": None}
        elif t == "error":
            # retries ("Reconnecting... 2/5") and warnings; a run that really fails ends with turn.failed (or exits)
            st["last_error"] = _short(obj.get("message") or json.dumps(obj), 1500)
            yield {"kind": "say", "text": f"(warning) {_short(st['last_error'], 300)}"}


# ---------------------------------------------------------------- Gemini CLI

class GeminiRunner(CliRunner):
    name, binary = "gemini", "gemini"

    def args(self, run, model):
        a = ["gemini", "--output-format", "stream-json", "--approval-mode", "yolo", "-p", _prompt(run)]
        if model:
            a += ["-m", model]
        if run.resume:
            a += ["--resume", "latest"]                # resumes by index; the project folder has only its own sessions
        return a

    def stdin(self, run):
        return b""

    @staticmethod
    def _flush(st):
        text = "".join(st.pop("buf", [])).strip()
        if text:
            st["text"].append(text)
            yield {"kind": "say", "text": text}

    def parse(self, obj, st):
        t = obj.get("type")
        if t == "init":
            st["session"] = obj.get("session_id")
            st["model"] = obj.get("model") or st.get("model")
            yield {"kind": "start", "model": st["model"], "session_id": st["session"]}
        elif t == "message" and obj.get("role") == "assistant":
            st.setdefault("buf", []).append(obj.get("content") or "")
            if not obj.get("delta"):
                yield from self._flush(st)
        elif t == "tool_use":
            yield from self._flush(st)
            p = obj.get("parameters") or {}
            detail = p.get("command") or p.get("file_path") or p.get("absolute_path") or p.get("pattern") or json.dumps(p)[:200]
            yield {"kind": "tool", "id": obj.get("tool_id"), "tool": obj.get("tool_name"), "detail": _short(detail, 300)}
        elif t == "tool_result":
            yield {"kind": "result", "id": obj.get("tool_id"), "ok": obj.get("status") != "error",
                   "text": _short(obj.get("output") or (obj.get("error") or {}).get("message") or "", 600)}
        elif t == "error":
            yield {"kind": "say", "text": f"(warning) {_short(obj.get('message'), 300)}"}
        elif t == "result":
            yield from self._flush(st)
            s = obj.get("stats") or {}
            cached = s.get("cached") or s.get("cached_tokens") or 0
            usage = {"input": max(0, (s.get("input_tokens") or s.get("input") or 0) - cached), "cache_write": 0, "cache_read": cached,
                     "output": s.get("output_tokens") or s.get("output") or 0}
            ok = obj.get("status", "success") == "success"
            yield {"kind": "done", "ok": ok, "subtype": "success" if ok else "error",
                   "text": st["text"][-1] if st["text"] else _short((obj.get("error") or {}).get("message") or "", 1500),
                   "turns": s.get("tool_calls"), "cost_usd": None, "duration_ms": s.get("duration_ms"),
                   "session_id": st.get("session"), "usage": usage, "models": {st.get("model") or "gemini": {**usage, "cost_usd": 0}}}


# ---------------------------------------------------------------- Antigravity CLI

class AntigravityRunner(CliRunner):
    """With the owner's Gemini API key the CLI uses it (settings modelProvider "gemini"). Without one it uses this
    installation's Google login: the sign-in of the separate antigravity-api gateway (Downloads/antigravity-cli),
    whose volume `antigravity-api-auth` is mounted read-only at AGY_SHARED_LOGIN. Its token is copied in before each
    run, so D2D never writes the gateway's settings, conversations or token."""
    name, binary = "antigravity", "agy"
    shared = Path(os.environ.get("AGY_SHARED_LOGIN", "/opt/agy-login")) / "antigravity-cli"
    home = Path.home() / ".gemini" / "antigravity-cli"
    LOGIN_FILES = ("antigravity-oauth-token", "cache/default_project_id.txt")

    def prepare(self, env: dict) -> str | None:
        """Point the CLI at the key or at the shared login; returns a message when neither is there."""
        self.home.mkdir(parents=True, exist_ok=True)
        f = self.home / "settings.json"
        try:
            settings = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            settings = {}
        if env.get("GEMINI_API_KEY"):
            settings["modelProvider"] = "gemini"
        else:
            settings.pop("modelProvider", None)
            if not (self.shared / self.LOGIN_FILES[0]).is_file():
                return ("No Gemini API key and no shared Google login: sign in the antigravity-api gateway once "
                        "(docker compose run --rm -it antigravity-api agy) or paste a Gemini API key in Settings.")
            for name in self.LOGIN_FILES:
                src, dst = self.shared / name, self.home / name
                if src.is_file():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, dst)
                    dst.chmod(0o600)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        tmp.replace(f)
        return None

    async def run(self, run, workdir, model, env):
        problem = self.prepare(env)
        if problem:
            yield {"kind": "error", "text": problem}
            return
        async for ev in super().run(run, workdir, model, env):
            yield ev

    # Headless agy does not skip a denied tool: the whole run ends. So the agent is told the rules up front.
    RULES = ("# Antigravity CLI rules in this app\nShell commands allowed: `genbi ...` and the read-only commands ls, cat, "
             "head, tail, wc, pwd, grep. Any other shell command (python, sed, find, rm, curl, ...) is denied and ENDS "
             "the run. Use your file tools to read, create and edit files, only inside the current folder.\n\n")

    def args(self, run, model):
        # `-p` is a yes/no switch in agy, so a prompt after it would swallow the flags that follow; the prompt goes
        # on stdin as one stream-json message instead (stdin closes after it, so agy runs one turn and exits).
        # accept-edits: file writes inside the workspace go through, writes elsewhere are still denied.
        a = ["agy", "--input-format", "stream-json", "--output-format", "stream-json", "--disable-slash-commands",
             "--mode", "accept-edits"]
        if model:
            a += ["--model", model]
        if run.resume:
            a += ["--conversation", run.resume]
        return a

    def stdin(self, run):
        return (json.dumps({"event": "user", "message": {"content": self.RULES + _prompt(run)}}) + "\n").encode()

    def parse(self, obj, st):
        ev = obj.get("event")
        if ev == "init":
            st["session"] = obj.get("conversation_id")
            init = obj.get("init") or {}
            st["model"] = init.get("model") or st.get("model")
            yield {"kind": "start", "model": st["model"], "session_id": st["session"]}
        elif ev == "step_update":
            s = obj.get("step_update") or {}
            if s.get("step_type") == "agent_response" and s.get("text_delta"):
                st.setdefault("buf", {}).setdefault(s.get("step_index"), []).append(s["text_delta"])
            if s.get("state") != "DONE":
                return
            if s.get("step_type") == "agent_response":
                text = "".join((st.get("buf") or {}).pop(s.get("step_index"), [])).strip()
                if text:
                    st["text"].append(text)
                    yield {"kind": "say", "text": text}
            elif s.get("step_type") == "tool":
                info = s.get("tool_info") or {}
                p = info.get("parameters") or {}
                detail = p.get("CommandLine") or p.get("TargetFile") or p.get("Path") or p.get("AbsolutePath") or json.dumps(p)[:200]
                sid = f"step-{s.get('step_index')}"
                yield {"kind": "tool", "id": sid, "tool": info.get("name") or s.get("tool_name"), "detail": _short(detail, 300)}
                err = info.get("error") or {}
                yield {"kind": "result", "id": sid, "ok": not err, "text": _short(err.get("message") or info.get("output") or "", 600)}
        elif ev == "result":
            r = obj.get("result") or obj
            u = r.get("usage") or {}
            cached = u.get("cache_read_tokens") or 0
            usage = {"input": max(0, (u.get("input_tokens") or 0) - cached), "cache_write": 0, "cache_read": cached,
                     "output": (u.get("output_tokens") or 0) + (u.get("thinking_tokens") or 0)}
            ok = r.get("status") == "SUCCESS"
            yield {"kind": "done", "ok": ok, "subtype": "success" if ok else (r.get("status") or "error").lower(),
                   "text": r.get("response") or (st["text"][-1] if st["text"] else _short(r.get("error") or "", 1500)),
                   "turns": r.get("num_turns"), "cost_usd": None,
                   "duration_ms": int((r.get("duration_seconds") or 0) * 1000) or None, "session_id": r.get("conversation_id") or st.get("session"),
                   "usage": usage, "models": {st.get("model") or "antigravity": {**usage, "cost_usd": 0}}}


CLI_RUNNERS = (CodexRunner, GeminiRunner, AntigravityRunner)
# Credentials each runner may receive from the run's owner (never logged or echoed back)
RUNNER_ENV = {"OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL", "GEMINI_API_KEY", "GOOGLE_API_KEY",
              "GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION"}


def installed() -> list[CliRunner]:
    """The CLI runners present in this image (each runner image adds one CLI to the agent image)."""
    wanted = {n.strip() for n in os.environ.get("D2D_RUNNERS", "").split(",") if n.strip()}
    return [r() for r in CLI_RUNNERS if r.available() and (not wanted or r.name in wanted)]
