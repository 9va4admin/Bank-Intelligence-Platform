"""
ASTRA Dev Server Launcher — loads .env.dev then starts uvicorn.
Run: python run_dev.py
"""
import os
import sys


def load_env(path: str) -> None:
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            # Strip surrounding double-quotes and unescape \n
            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
            val = val.replace("\\n", "\n")
            os.environ.setdefault(key, val)


if __name__ == "__main__":
    load_env(os.path.join(os.path.dirname(__file__), ".env.dev"))

    import uvicorn

    uvicorn.run(
        "apps.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
