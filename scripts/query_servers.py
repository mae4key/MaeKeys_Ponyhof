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
from opengsq.protocols.gamespy3 import GameSpy3
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

# Werte, die der Server selbst im "gameId"/"game_id"-Feld meldet (der
# +game-Parameter, mit dem er gestartet wurde). Achtung: BF1942 (GameSpy1)
# schickt den Schluessel als "gameId" (ohne Unterstrich), BFV (GameSpy2)
# dagegen als "game_id" (mit Unterstrich) - nach dem Kleinschreiben also
# zwei unterschiedliche Schluessel, beide noetig. Werte uebersetzt anhand
# eurer eigenen mod_registry.json (BFV + BF1942). Ein Mod, der hier nicht
# auftaucht, wird einfach unuebersetzt angezeigt statt zu fehlen.
MOD_LABELS = {
    # Vanilla
    "bf1942": "Vanilla",
    "bfvietnam": "Vanilla",
    "bf2": "Vanilla",
    "bf2142": "Vanilla",
    # Battlefield Vietnam
    "bfv_ww2mod": "WW2Mod",
    "eod_mod": "EoD",
    "dicecity_v_mod": "DiceCity_V",
    "poe_mod": "PoE",
    "poe": "PoE",
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
    zurueck, da GameSpy-Server je nach Protokollversion/Mod leicht
    unterschiedliche Feldnamen verwenden (z. B. 'gameId' vs. 'game_id')."""
    for key in keys:
        if key in info and str(info[key]).strip() != "":
            return str(info[key]).strip()
    return default


def _count_humans(info: dict, players: list) -> int:
    """Zaehlt echte Spieler statt Bots. Bei Coop-Servern (v. a. BF2) kann
    das vom Server gemeldete 'numplayers' auch Bots enthalten. Zwei Wege,
    bevorzugt der erste:
    1. Das Feld 'bf2_bots' (Anzahl Bots) wird direkt vom Abzug genutzt.
    2. Sonst: Bots melden durchgehend ping=0, echte Spieler nie - ein seit
       Jahren in Server-Browsern fuer diese Engine-Generation gebraeuchlicher
       Erkennungsweg."""
    numplayers = int(
        _first(info, "numplayers", "playercount", "numplayers_", default="0") or 0
    )
    bots = _first(info, "bf2_bots", "numbots", "bots")
    if bots:
        return max(0, numplayers - int(bots))
    if players:
        humans = [
            p
            for p in players
            if str(p.get("ping", p.get("ping_", "1"))).strip() not in ("0", "")
        ]
        return len(humans)
    return numplayers


def _extract_scoreboard(players: list) -> list:
    """Baut aus der rohen Spielerliste ein einheitliches Scoreboard (Name,
    Score, Kills, Deaths, Ping) - nur echte Spieler, Bots (ping=0)
    ausgeschlossen. Feldnamen unterscheiden sich leicht je nach
    Protokollversion, daher auch hier mehrere moegliche Schluessel."""
    board = []
    for p in players or []:
        p = {k.lower(): v for k, v in p.items()}
        ping = str(p.get("ping", "1")).strip()
        if ping == "0":
            continue  # Bot, nicht ins Scoreboard aufnehmen
        board.append(
            {
                "name": _first(p, "player", "playername", "name", default="?"),
                "score": _first(p, "score", default="0"),
                "kills": _first(p, "kills", "kill", default=""),
                "deaths": _first(p, "deaths", "death", default=""),
                "ping": ping,
            }
        )
    board.sort(key=lambda row: int(row["score"]) if str(row["score"]).lstrip("-").isdigit() else 0, reverse=True)
    return board


async def _try_protocol(protocol_cls, host, port, challenge_required=None):
    client = protocol_cls(host=host, port=port, timeout=TIMEOUT_SECONDS)
    if challenge_required is not None and hasattr(client, "challenge_required"):
        client.challenge_required = challenge_required
    return await client.get_status()


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
        "scoreboard": [],
    }

    protocol_name = entry.get("protocol", "")
    primary_cls = PROTOCOLS.get(protocol_name)
    if primary_cls is None:
        result["status"] = "fehlkonfiguriert"
        return result

    # Bei "battlefield2" (BF2 + BF2142) mehrere Varianten durchprobieren:
    # BF2142 braucht vermutlich (anders als BF2) den GameSpy3-Challenge-
    # Handshake, ausserdem als Netz GameSpy2/GameSpy3 generisch.
    candidates = [(primary_cls, None)]
    if protocol_name == "battlefield2":
        candidates += [
            (Battlefield2, True),  # mit Challenge-Handshake (BF2142-Verdacht)
            (GameSpy2, None),
            (GameSpy3, None),
        ]

    debug_errors = []
    for protocol_cls, challenge_required in candidates:
        try:
            status = await _try_protocol(
                protocol_cls, entry["host"], int(entry["port"]), challenge_required
            )
            info = {k.lower(): v for k, v in status.info.items()}

            result["status"] = "online"
            result["map"] = _first(info, "mapname", "map", "map_")
            result["mode"] = _first(info, "gametype", "mode", "gametype_")
            # Der Mod wird vom Server selbst im "gameId"/"game_id"-Feld
            # gemeldet - unabhaengig vom Port, da derselbe Port im Lauf der
            # Zeit unterschiedliche Mods tragen kann.
            raw_mod = _first(
                info, "game_id", "gameid", "gamevariant", "modname", "mod"
            )
            result["mod"] = _friendly_mod(raw_mod)
            result["players"] = _count_humans(info, status.players)
            result["max_players"] = int(
                _first(info, "maxplayers", "maxplayers_", default="0") or 0
            )
            result["scoreboard"] = _extract_scoreboard(status.players)
            if not result["mod"]:
                # TEMPORAER zur Fehlersuche: Mod-Feld weiterhin leer trotz
                # Fix - zeig die komplette Rohantwort, um den echten
                # Schluesselnamen zu finden.
                result["_debug_info"] = info
            break  # Erfolgreich -> nicht mehr den naechsten Kandidaten versuchen
        except Exception as exc:
            # Dieser Kandidat hat nicht geklappt -> naechsten probieren
            # (oder, falls keiner mehr uebrig ist, bleibt der Server "offline")
            debug_errors.append(f"{protocol_cls.__name__}: {type(exc).__name__}: {exc}")
            continue

    if result["status"] == "offline":
        # TEMPORAER zur Fehlersuche: zeigt, woran jeder einzelne Versuch
        # gescheitert ist (z. B. Timeout vs. falsches Antwortformat).
        result["_debug_errors"] = debug_errors

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
