"""Launch from repository root; load only known credentials/config, never print them."""
import os
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[2]
allowed = {"OPENAI_API_KEY", "OPENAI_REALTIME_MODEL", "GAUSSIAN_A2F_ENDPOINT", "GAUSSIAN_GENERATOR_URL", "GAUSSIAN_DATA_DIR"}
env = root / ".env"
if env.is_file():
    for raw in env.read_text(encoding="utf-8-sig").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#") or "=" not in raw:
            continue
        name, value = raw.split("=", 1)
        if name.strip() in allowed and name.strip() not in os.environ:
            os.environ[name.strip()] = value.strip().strip("\"'")
os.chdir(root)
sys.path.insert(0, str(root / "apps/api"))
import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.gaussian_main:app", host="127.0.0.1", port=8030, ws_max_size=512*1024)
