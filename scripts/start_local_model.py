"""Start a CPU-only local Qwen test API; contest deployment stays unchanged."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from urllib.error import URLError
from urllib.request import Request, urlopen


def _docker(*arguments: str, capture: bool = False) -> str:
    result = subprocess.run(["docker", *arguments], check=True, text=True,
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else ""


def start(model: str, port: int, container: str, knowledge_base: Path | None = None,
          host_network: bool = False) -> Path:
    root = Path(__file__).resolve().parents[1]
    if knowledge_base is not None:
        knowledge_base = knowledge_base.resolve()
        if not knowledge_base.is_file() or knowledge_base.suffix.lower() != ".zip":
            raise ValueError("--kb must point to the private knowledge-base ZIP")
    cache = root / "data" / "ollama"
    cache.mkdir(parents=True, exist_ok=True)
    existing = subprocess.run(["docker", "inspect", container], capture_output=True, text=True)
    if existing.returncode == 0:
        info = json.loads(existing.stdout)[0]
        if (info["Config"].get("Labels") or {}).get("energytool.local-model") != "true":
            raise RuntimeError("container name is occupied by an unmanaged container")
        if (info["HostConfig"]["NetworkMode"] == "host") != host_network:
            raise RuntimeError("existing model container uses a different network mode")
        if host_network and f"OLLAMA_HOST=127.0.0.1:{port}" not in info["Config"].get("Env", []):
            raise RuntimeError("existing model container uses a different host port")
        if not info["State"]["Running"]:
            _docker("start", container)
    else:
        network_args = ["--network", "host"] if host_network else ["-p", f"127.0.0.1:{port}:11434"]
        listen = f"127.0.0.1:{port}" if host_network else "0.0.0.0:11434"
        _docker(
            "run", "-d", "--name", container,
            "--label", "energytool.local-model=true",
            "--cpus", "8", "--memory", "12g",
            *network_args,
            "-v", f"{cache}:/root/.ollama",
            "-e", f"OLLAMA_HOST={listen}",
            "-e", "OLLAMA_NO_CLOUD=1",
            "-e", "OLLAMA_NUM_PARALLEL=1",
            "-e", "OLLAMA_MAX_LOADED_MODELS=1",
            "-e", "OLLAMA_CONTEXT_LENGTH=16384",
            "-e", "OLLAMA_KEEP_ALIVE=10m",
            "ollama/ollama:latest",
        )
    if not host_network:
        network = "energytool-local-model"
        network_info = subprocess.run(["docker", "network", "inspect", network], capture_output=True, text=True)
        if network_info.returncode:
            _docker("network", "create", "--label", "energytool.local-model=true", network)
        elif (json.loads(network_info.stdout)[0].get("Labels") or {}).get("energytool.local-model") != "true":
            raise RuntimeError("local model network name is occupied by another project")
        info = json.loads(_docker("inspect", container, capture=True))[0]
        bindings = info["NetworkSettings"]["Ports"].get("11434/tcp") or []
        if not any(item.get("HostIp") == "127.0.0.1" and item.get("HostPort") == str(port) for item in bindings):
            raise RuntimeError("existing model container uses a different host port")
        if network not in info["NetworkSettings"]["Networks"]:
            _docker("network", "connect", network, container)
    base = f"http://127.0.0.1:{port}"
    for attempt in range(60):
        try:
            with urlopen(base + "/api/version", timeout=2) as response:
                version = json.load(response)["version"]
            print(f"Local Ollama ready: {version}", flush=True)
            break
        except (URLError, OSError):
            if attempt == 59:
                raise RuntimeError("local model API did not become ready") from None
            time.sleep(1)
    request = Request(base + "/api/pull", data=json.dumps({"model": model, "stream": True}).encode(),
                      headers={"Content-Type": "application/json"})
    previous_status = ""
    progress = {}
    with urlopen(request, timeout=120) as response:
        for raw in response:
            event = json.loads(raw)
            if event.get("error"):
                raise RuntimeError("local model download failed; inspect the Ollama container")
            status = event.get("status", "")
            if event.get("total"):
                digest = event.get("digest", "weights")
                percent = int(100 * event.get("completed", 0) / event["total"])
                if percent >= progress.get(digest, -10) + 10:
                    print(f"Model download {digest[:16]}: {percent}%", flush=True)
                    progress[digest] = percent
            elif status != previous_status:
                print(status, flush=True)
            previous_status = status
    # 'ollama' is a deliberately non-secret placeholder. The local API ignores
    # authentication; contest credentials are supplied by its proxy at runtime.
    config = root / "data" / "local_model.env"
    config.write_text(
        "AI_MODE=llm\n"
        f"LOCAL_LLM_MODEL={model}\n"
        f"LOCAL_LLM_PORT={port}\n"
        f"LLM_BASE_URL={base}/v1\n"
        f"LLM_MODEL={model}\n"
        "LLM_API_KEY=ollama\n"
        "AI_LLM_TIMEOUT_SECONDS=120\n"
        "MAX_TOKENS=768\n"
        "TEMPERATURE=0\n"
        "TOP_K=8\n",
        encoding="utf-8",
    )
    os.chmod(config, 0o600)
    if knowledge_base is not None:
        destination = root / "data" / "local-model-knowledge-base.zip"
        if knowledge_base != destination:
            shutil.copyfile(knowledge_base, destination)
        print("Private knowledge base prepared for the existing backend data volume", flush=True)
    print(f"Local model configured: {model}", flush=True)
    print(f"Environment: {config.relative_to(root)}", flush=True)
    return config


def main() -> None:
    parser = argparse.ArgumentParser(description="Download and start a local model for real AI testing")
    parser.add_argument("--model", default="qwen3:4b-instruct-2507-q4_K_M")
    parser.add_argument("--port", type=int, default=11435)
    parser.add_argument("--container", default="energytool-llm-local")
    parser.add_argument("--host-network", action="store_true", help="Linux: use host networking if Docker bridge is blocked")
    parser.add_argument("--kb", type=Path, help="Copy a private KB ZIP into the existing backend data volume")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be in [1, 65535]")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./:-]*", args.model):
        parser.error("model must be an Ollama model name/tag")
    start(args.model, args.port, args.container, args.kb, args.host_network)


if __name__ == "__main__":
    main()
