#!/usr/bin/env python3
"""Fragt die Server der Freunde (config/friends.json) ab und schreibt docs/friends.json.

Getrennt von status.json: Diese Server zaehlen weder fuer den Online-Zaehler noch fuer das Ranking.
Es werden bewusst keine Spielernamen gespeichert, nur Anzahl, Karte, Modus.
Wird im Workflow bei jedem Lauf gestartet, fragt aber hoechstens alle 4 Minuten (--force umgeht das).
"""
import asyncio
import json
import pathlib
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import query_servers  # noqa: E402

CONFIG = ROOT / "config" / "friends.json"
OUT = ROOT / "docs" / "friends.json"
MIN_AGE_SECONDS = 240


def _fresh() -> bool:
    try:
        old = json.loads(OUT.read_text(encoding="utf-8"))
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(old["generated_at"])).total_seconds()
        return age < MIN_AGE_SECONDS
    except Exception:
        return False


async def main_async() -> None:
    if "--force" not in sys.argv and _fresh():
        print("friends.json ist frisch (< %d s), keine Abfrage." % MIN_AGE_SECONDS)
        return
    entries = [e for e in json.loads(CONFIG.read_text(encoding="utf-8")) if e.get("enabled", True)]
    results = await asyncio.gather(*(query_servers.query_one(e) for e in entries), return_exceptions=True)
    servers = []
    for e, r in zip(entries, results):
        if isinstance(r, Exception) or not isinstance(r, dict):
            r = {}
        online = r.get("status") == "online"
        servers.append({
            "id": e["id"],
            "game": e["game"],
            "name": e.get("name", ""),
            "status": "online" if online else "offline",
            "server_name": r.get("server_name") or e.get("name", ""),
            "map": r.get("map", "") if online else "",
            "mode": r.get("mode", "") if online else "",
            "mod": r.get("mod", "") if online else "",
            "players": r.get("players", 0) if online else 0,
            "max_players": r.get("max_players", 0) if online else 0,
        })
    payload = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "servers": servers}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Geschrieben: %s (%d Server, %d online)" % (OUT, len(servers), sum(1 for s in servers if s["status"] == "online")))


if __name__ == "__main__":
    asyncio.run(main_async())
