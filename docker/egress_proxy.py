#!/usr/local/bin/python3
"""The AI engine's only way out (security audit S6): an HTTPS proxy on 127.0.0.1:3128 for the AI engine's user.

relay-init stops every other connection that user makes (iptables, when the container may: NET_ADMIN), and gives the
AI engine HTTPS_PROXY=http://127.0.0.1:3128. This proxy runs as the web app's user and opens a tunnel (HTTP CONNECT)
only to port 443 of the hosts in D2D_AGENT_EGRESS_ALLOW (default: Anthropic's API and sign-in hosts). Anything else
is refused with 403; the log names the refused host, never what was sent. Nothing but CONNECT is served.
"""
import asyncio
import os
import sys

LISTEN = ("127.0.0.1", int(os.environ.get("D2D_AGENT_EGRESS_PORT") or 3128))
ALLOW = {h.strip().lower().rstrip(".") for h in (os.environ.get("D2D_AGENT_EGRESS_ALLOW") or
         "api.anthropic.com,platform.claude.com,console.anthropic.com,claude.ai,claude.com").split(",") if h.strip()}
HEAD_LIMIT = 8192
IDLE = 600                                    # seconds a tunnel may stay silent (a long Claude answer streams slowly)


def allowed(host: str, port: int) -> bool:
    return port == 443 and host.lower().rstrip(".") in ALLOW


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await asyncio.wait_for(reader.read(65536), IDLE)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (asyncio.TimeoutError, ConnectionError, OSError):
        pass
    finally:
        try:
            writer.close()
        except (ConnectionError, OSError):
            pass


async def refuse(writer: asyncio.StreamWriter, code: int, why: str) -> None:
    body = why.encode()
    writer.write(f"HTTP/1.1 {code} {why}\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body)
    try:
        await writer.drain()
    finally:
        writer.close()


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 30)
    except (asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError):
        writer.close()
        return
    if len(head) > HEAD_LIMIT:
        return await refuse(writer, 431, "Request Header Fields Too Large")
    line = head.split(b"\r\n", 1)[0].decode("latin-1")
    parts = line.split()
    if len(parts) != 3 or parts[0].upper() != "CONNECT":
        return await refuse(writer, 405, "Only CONNECT")
    host, _, port = parts[1].rpartition(":")
    host = host.strip("[]")
    try:
        port_n = int(port)
    except ValueError:
        return await refuse(writer, 400, "Bad Request")
    if not allowed(host, port_n):
        print(f"[egress] refused {host}:{port_n}", flush=True)
        return await refuse(writer, 403, "Forbidden")
    try:
        up_r, up_w = await asyncio.wait_for(asyncio.open_connection(host, port_n), 20)
    except (OSError, asyncio.TimeoutError):
        return await refuse(writer, 502, "Bad Gateway")
    writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
    await writer.drain()
    await asyncio.gather(pipe(reader, up_w), pipe(up_r, writer))


async def main() -> None:
    server = await asyncio.start_server(handle, *LISTEN, limit=HEAD_LIMIT * 2)
    print(f"[egress] the AI engine may reach {', '.join(sorted(ALLOW))} (port 443) through {LISTEN[0]}:{LISTEN[1]}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
