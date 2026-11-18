"""A local mail server for development: accepts any message and appends it to a JSON-lines file. Plain SMTP, no TLS, no authentication.

    python scripts/dev_smtp_sink.py --port 2525 --out dev_mail.jsonl
    # then point the worker at it:  SMTP_HOST=127.0.0.1 SMTP_PORT=2525 SMTP_SECURITY=none SMTP_FROM_ADDRESS=astra@local.test

Secure mode, to test the real protocol (STARTTLS, certificate checking, login):
    python scripts/dev_smtp_sink.py --port 2525 --tls-cert cert.pem --tls-key key.pem --auth user:password

Never run this anywhere a real recipient is expected: it delivers nothing.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import ssl
import time
from pathlib import Path


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, out: Path, tls: ssl.SSLContext | None = None,
                  auth: tuple[str, str] | None = None) -> None:
    async def reply(text: str) -> None:
        writer.write((text + "\r\n").encode())
        await writer.drain()

    await reply("220 dev-smtp-sink ready")
    mail_from, rcpt, in_data, data = "", [], False, []
    secure, user = False, None
    try:
        while True:
            try:
                raw = await reader.readline()
            except ConnectionError:
                return                  # the client went away mid-conversation (a restarted worker): not an error
            if not raw:
                return
            line = raw.decode(errors="replace").rstrip("\r\n")
            if in_data:
                if line == ".":
                    in_data = False
                    with out.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps({"at": time.time(), "from": mail_from, "to": rcpt, "tls": secure, "auth_user": user, "data": "\n".join(data)}) + "\n")
                    mail_from, rcpt, data = "", [], []
                    await reply("250 queued")
                else:
                    data.append(line[1:] if line.startswith("..") else line)
                continue
            cmd = line.upper()
            if cmd.startswith(("EHLO", "HELO")):
                caps = []
                if tls and not secure:
                    caps.append("STARTTLS")
                if auth and (secure or not tls):
                    caps.append("AUTH PLAIN LOGIN")
                if caps:
                    lines = ["250-dev-smtp-sink"] + [f"250-{c}" for c in caps[:-1]] + [f"250 {caps[-1]}"]
                    writer.write(("\r\n".join(lines) + "\r\n").encode())
                    await writer.drain()
                else:
                    await reply("250 dev-smtp-sink")
            elif cmd == "STARTTLS" and tls and not secure:
                await reply("220 ready to start TLS")
                await writer.start_tls(tls)
                secure = True
            elif cmd.startswith("AUTH") and auth:
                parts = line.split()
                if parts[1].upper() == "PLAIN":
                    blob = parts[2] if len(parts) > 2 else None
                    if blob is None:
                        await reply("334 ")
                        blob = (await reader.readline()).decode().strip()
                    _, u, p = base64.b64decode(blob).decode().split(chr(0))
                else:
                    await reply("334 " + base64.b64encode(b"Username:").decode())
                    u = base64.b64decode((await reader.readline()).decode().strip()).decode()
                    await reply("334 " + base64.b64encode(b"Password:").decode())
                    p = base64.b64decode((await reader.readline()).decode().strip()).decode()
                if (u, p) == auth:
                    user = u
                    await reply("235 authenticated")
                else:
                    await reply("535 authentication failed")
            elif cmd.startswith("MAIL FROM"):
                if auth and not user:
                    await reply("530 authentication required")
                    continue
                mail_from = line.split(":", 1)[1].strip().strip("<>")
                await reply("250 ok")
            elif cmd.startswith("RCPT TO"):
                rcpt.append(line.split(":", 1)[1].strip().strip("<>"))
                await reply("250 ok")
            elif cmd == "DATA":
                in_data = True
                await reply("354 end with a line holding a single dot")
            elif cmd == "RSET" or cmd == "NOOP":
                await reply("250 ok")
            elif cmd == "QUIT":
                await reply("221 bye")
                return
            else:
                await reply("502 not implemented")
    finally:
        writer.close()


async def main(host: str, port: int, out: Path, cert: str | None = None, key: str | None = None, auth: str | None = None) -> None:
    ctx = None
    if cert:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
    creds = tuple(auth.split(":", 1)) if auth else None
    server = await asyncio.start_server(lambda r, w: _handle(r, w, out, ctx, creds), host, port)
    print(f"dev SMTP sink on {host}:{port}, writing {out}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=2525)
    ap.add_argument("--out", default="dev_mail.jsonl")
    ap.add_argument("--tls-cert", help="enable STARTTLS with this certificate (PEM)")
    ap.add_argument("--tls-key", help="the certificate's private key (PEM)")
    ap.add_argument("--auth", help="require login: user:password")
    a = ap.parse_args()
    asyncio.run(main(a.host, a.port, Path(a.out), a.tls_cert, a.tls_key, a.auth))
