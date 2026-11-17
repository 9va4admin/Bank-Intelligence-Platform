"""A local mail server for development: accepts any message and appends it to a JSON-lines file. Plain SMTP, no TLS, no authentication.

    python scripts/dev_smtp_sink.py --port 2525 --out dev_mail.jsonl
    # then point the worker at it:  SMTP_HOST=127.0.0.1 SMTP_PORT=2525 SMTP_SECURITY=none SMTP_FROM_ADDRESS=astra@local.test

Never run this anywhere a real recipient is expected: it delivers nothing.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, out: Path) -> None:
    async def reply(text: str) -> None:
        writer.write((text + "\r\n").encode())
        await writer.drain()

    await reply("220 dev-smtp-sink ready")
    mail_from, rcpt, in_data, data = "", [], False, []
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
                        fh.write(json.dumps({"at": time.time(), "from": mail_from, "to": rcpt, "data": "\n".join(data)}) + "\n")
                    mail_from, rcpt, data = "", [], []
                    await reply("250 queued")
                else:
                    data.append(line[1:] if line.startswith("..") else line)
                continue
            cmd = line.upper()
            if cmd.startswith(("EHLO", "HELO")):
                await reply("250 dev-smtp-sink")
            elif cmd.startswith("MAIL FROM"):
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


async def main(host: str, port: int, out: Path) -> None:
    server = await asyncio.start_server(lambda r, w: _handle(r, w, out), host, port)
    print(f"dev SMTP sink on {host}:{port}, writing {out}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=2525)
    ap.add_argument("--out", default="dev_mail.jsonl")
    a = ap.parse_args()
    asyncio.run(main(a.host, a.port, Path(a.out)))
