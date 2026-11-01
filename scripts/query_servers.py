#!/usr/bin/env python3
"""
MaeKeys Ponyhof - Server-Status-Abfrage
-----------------------------------------
Fragt alle in config/servers.json aktivierten Retrogame-Server direkt per
GameSpy-Query-Protokoll ab (keine externen Listen wie OpenSpy/BF2Hub nötig)
und schreibt das Ergebnis nach docs/status.json, das von der Webseite
(docs/index.html) angezeigt wird.

Ist ein Server nicht erreichbar (ausgeschaltet, Netzwerkproblem, Timeout),
wird er schlicht als "offline" markiert - kein Fehler, kein Absturz.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
from datetime import datetime, timezone

from opengsq.protocols.gamespy1 import GameSpy1
from opengsq.protocols.gamespy2 import GameSpy2
from opengsq.protocols.battlefield2 import Battlefield2

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "servers.json"
OUTPUT_PATH = ROOT / "docs" / "status.json"

TIMEOUT_SECONDS = 4.0

PROTOCOLS = {
    "gamespy1": GameSpy1,
    "gamespy2": GameSpy2,
    "battlefield2": Battlefield2,
}


def _first(info: dict, *keys: str, default: str = "") -> str:
    """Gibt den ersten vorhandenen Wert aus mehreren möglichen Schlüsselnamen
    zurueck, da GameSpy-Server je nach Spiel/Mod leicht unterschiedliche
    Feldnamen verwenden (z. B. 'mapname' vs. 'map')."""
    for key in keys:
        if key in info and str(info[key]).strip() != "":
            return str(info[key]).strip()
    return default


async def query_one(entry: dict) -> dict:
    result = {
        "id": entry["id"],
        "game": entry["game"],
        "name": entry["name"],
        "status": "offline",
        "map": "",
        "mode": "",
        "mod": "",
        "players": 0,
        "max_players": 0,
    }

    primary_cls = PROTOCOLS.get(entry.get("protocol", ""))
    if primary_cls is None:
        result["status"] = "fehlkonfiguriert"
        return result

    # Bei "battlefield2" zusaetzlich "gamespy2" als Fallback versuchen:
    # BF2142 nutzt eine abgewandelte GameSpy2-Variante, bei der nicht
    # sicher ist, ob die eigens fuer BF2 gebaute Klasse 1:1 passt.
    candidates = [primary_cls]
    if entry.get("protocol") == "battlefield2":
        candidates.append(GameSpy2)

    for protocol_cls in candidates:
        try:
            client = protocol_cls(
                host=entry["host"], port=int(entry["port"]), timeout=TIMEOUT_SECONDS
            )
            status = await client.get_status()
            info = {k.lower(): v for k, v in status.info.items()}

            result["status"] = "online"
            result["map"] = _first(info, "mapname", "map", "map_")
            result["mode"] = _first(info, "gametype", "mode", "gametype_")
            # Der Mod wird vom Server selbst gemeldet (z. B. "bf1942" fuer
            # Vanilla, oder ein Mod-Kuerzel) - unabhaengig vom Port, da der
            # gleiche Port im Lauf der Zeit unterschiedliche Mods tragen kann.
            result["mod"] = _first(
                info, "gamevariant", "modname", "mod", "gamevariant_"
            )
            result["players"] = int(
                _first(info, "numplayers", "playercount", "numplayers_", default="0")
                or 0
            )
            result["max_players"] = int(
                _first(info, "maxplayers", "maxplayers_", default="0") or 0
            )
            # Fallback: Spielerzahl notfalls aus der tatsaechlichen Player-Liste zaehlen
            if result["players"] == 0 and status.players:
                result["players"] = len(status.players)
            break  # Erfolgreich -> nicht mehr den naechsten Kandidaten versuchen
        except Exception:
            # Dieser Kandidat hat nicht geklappt -> naechsten probieren
            # (oder, falls keiner mehr uebrig ist, bleibt der Server "offline")
            continue

    return result


async def main_async() -> None:
    entries = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    active = [e for e in entries if e.get("enabled", False)]

    results = await asyncio.gather(*(query_one(e) for e in active))

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "servers": results,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Geschrieben: {OUTPUT_PATH} ({len(results)} Server abgefragt)")


if __name__ == "__main__":
    asyncio.run(main_async())
