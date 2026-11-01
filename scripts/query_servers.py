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

# Diese Namen meldet der Server selbst als "gamevariant" ueber den
# +game-Parameter, mit dem er gestartet wurde. Werte aus eurer eigenen
# mod_registry.json (BFV + BF1942) uebersetzt in lesbare Labels. Ein Mod,
# der hier nicht auftaucht, wird einfach unuebersetzt angezeigt.
MOD_LABELS = {
    # Vanilla (jeweils wie vom Server selbst als gamevariant gemeldet)
    "bf1942": "Vanilla",
    "bfvietnam": "Vanilla",
    "bf2": "Vanilla",
    "bf2142": "Vanilla",
    # Battlefield Vietnam
    "bfv_ww2mod": "WW2Mod",
    "eod_mod": "EoD",
    "dicecity_v_mod": "DiceCity_V",
    "poe_mod": "PoE",
    "forcepack_mod": "Forcepack",
    "onepointthree_mod": "OnePointThree",
    "op_remembrance_mod": "Op_Remembrance",
    "aiev_mod": "AIEV",
    "bfbalkan_mod": "BfBalkan",
    "battlegroup42_mod": "Battlegroup42",
    "bfv_arsenal_mod": "BfvArsenal",
    "bfv_ww2mod_x_mod": "BfvWw2modX",
    # Battlefield 1942
    "xpack1": "Xpack1",
    "xpack2": "Xpack2",
    "aie42": "AIE42",
    "bf1918": "BF1918",
    "bfheroes": "BfHeroes",
    "bg42": "Battlegroup42Mod",
    "dc_extended": "DC_Extended",
    "dc_final": "DC_Final",
    "dc_realism": "DC_Realism",
    "desertcombat": "DesertCombat",
    "eod": "EoD",
    "eod_mw": "EoD_MW",
    "fh": "ForgottenHope",
    "fhr": "ForgottenHopeRemastered",
    "fhsw": "FH_SecretWeapons",
    "fhsweurope": "FH_SW_Europe",
    "graphicsplus": "GraphicsPlus",
    "pirates": "Pirates",
    "pirates_sp": "Pirates_SP",
    "roadtoromeextra": "RoadToRomeExtra",
    "swextra": "SecretWeaponsExtra",
    "bf1942_inklzusatzmaps": "Vanilla_PlusKarten",
    "bf1942_weiterezusatzmaps": "Vanilla_WeitereKarten",
}


def _friendly_mod(raw: str) -> str:
    if not raw:
        return ""
    return MOD_LABELS.get(raw.lower(), raw)


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
            raw_mod = _first(info, "gamevariant", "modname", "mod", "gamevariant_")
            result["mod"] = _friendly_mod(raw_mod)
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

            # TEMPORAER zur Fehlersuche (Mod-Erkennung bei BF1942/BFV,
            # Bot- vs. Spieler-Unterscheidung bei BF2) - danach wieder raus:
            result["_debug_info"] = info
            result["_debug_first_player"] = status.players[0] if status.players else {}

            break  # Erfolgreich -> nicht mehr den naechsten Kandidaten versuchen
        except Exception as exc:
            # Dieser Kandidat hat nicht geklappt -> naechsten probieren
            # (oder, falls keiner mehr uebrig ist, bleibt der Server "offline")
            # TEMPORAER zur Fehlersuche bei BF2142:
            result.setdefault("_debug_errors", []).append(
                f"{protocol_cls.__name__}: {type(exc).__name__}: {exc}"
            )
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
