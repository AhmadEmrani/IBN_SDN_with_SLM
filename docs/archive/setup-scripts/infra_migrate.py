#!/usr/bin/env python3
"""One-time, non-destructive cutover to unified compose.yaml.

No Docker volumes, containers, images, model weights, or passwords are modified.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OLD = ["docker-compose.yml", "compose.stage5c.yml", "compose.stage5d.yml"]
EXPECTED_PROJECT = "sdn-mininet-ryu"


def configured(files):
    result = subprocess.run(
        ["docker", "compose", *sum((["-f", f] for f in files), []), "config", "--format", "json"],
        cwd=ROOT, text=True, capture_output=True,
    )
    if result.returncode:
        # Output may include interpolated URLs/secrets. Do not print it.
        raise RuntimeError("Docker Compose could not validate configuration (check .env and Compose files)")
    return json.loads(result.stdout)


def names_and_ports(config):
    return {
        "project": config.get("name"),
        "services": set(config.get("services", {})),
        "volumes": set(config.get("volumes", {})),
        "networks": set(config.get("networks", {})),
        "ports": {
            name: sorted((str(p.get("published")), str(p.get("target")), p.get("host_ip", ""))
                         for p in srv.get("ports", []))
            for name, srv in config.get("services", {}).items()
        },
    }


def main():
    if os.environ.get("COMPOSE_FILE"):
        raise RuntimeError("COMPOSE_FILE is exported in your shell; unset COMPOSE_FILE first")
    if os.environ.get("COMPOSE_PROJECT_NAME") and os.environ["COMPOSE_PROJECT_NAME"] != EXPECTED_PROJECT:
        raise RuntimeError("COMPOSE_PROJECT_NAME differs from existing project; aborting")
    if not all((ROOT / p).is_file() for p in OLD + ["compose.yaml"]):
        raise RuntimeError("Old and new Compose files must coexist for safety comparison")
    env_file = ROOT / ".env"
    if not env_file.exists():
        raise RuntimeError(".env is missing; migration cannot proceed")
    data = env_file.read_text()
    lines = data.splitlines(keepends=True)
    if any(l.strip().startswith("COMPOSE_PROJECT_NAME=") and l.split("=", 1)[1].strip().strip('"\'') != EXPECTED_PROJECT for l in lines):
        raise RuntimeError(".env project name mismatch; aborting")

    baseline = configured(OLD)
    replacement = configured(["compose.yaml"])
    before, after = names_and_ports(baseline), names_and_ports(replacement)
    if before != after or before["project"] != EXPECTED_PROJECT:
        raise RuntimeError("Compose project/services/volumes/networks/published ports differ; refusing cutover")
    # Ensure key runtime state mounts and image sharing have not been renamed.
    for key in ("postgres", "airflow-db", "intent-retriever", "phi-inference"):
        a = baseline["services"][key]
        b = replacement["services"][key]
        if a.get("volumes", []) != b.get("volumes", []):
            raise RuntimeError(f"Volume/bind mounts differ for {key}; aborting")

    filtered = [l for l in lines if not l.lstrip().startswith("COMPOSE_FILE=")]
    if filtered != lines:
        temp = env_file.with_name(".env.cutover-temp")
        temp.write_text("".join(filtered))
        temp.chmod(0o600)
        temp.replace(env_file)
        env_file.chmod(0o600)
    print("PASS: legacy/new Compose configurations preserve project, services, volumes, and ports")
    print("PASS: COMPOSE_FILE removed from .env if present; secrets unchanged")
    print("PASS: ready to use plain docker compose")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print("MIGRATION BLOCKED:", str(exc), file=sys.stderr)
        sys.exit(1)
