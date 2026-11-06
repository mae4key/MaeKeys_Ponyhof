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
import re
import socket
from datetime import datetime, timezone

from opengsq.protocols.gamespy1 import GameSpy1
from opengsq.protocols.gamespy2 import GameSpy2
from opengsq.protocols.gamespy3 import GameSpy3
from opengsq.protocols.battlefield2 import Battlefield2

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "servers.json"
OUTPUT_PATH = ROOT / "docs" / "status.json"

TIMEOUT_SECONDS = 4.0


# Feste Bot-Namenslisten aus botnames.ai (aiSettings.addBotName <Name>),
# fuer die Namens-basierte Bot-Erkennung bei BF2142 (ping=0 dort nicht
# zuverlaessig). TODO: mit dem tatsaechlichen Inhalt von
# mods/bf2/ai/botnames.ai bzw. mods/bf2142/ai/botnames.ai befuellen.
BF2_BOT_NAMES: set[str] = {
    "T. Karlsson",
    "R. Edgren",
    "P.K. Johansson",
    "J. Jonsson",
    "S. Wallberg",
    "A. Andersson",
    "H. Karlsson",
    "K. Bergqvist",
    "M. Hornlund",
    "R. Lopez",
    "D. Gothberg",
    "P. Hoyles",
    "M. Kopparhed",
    "C. Cyreus",
    "T. Dahl",
    "M. Bagge",
    "T. Laedre",
    "L. Martensson",
    "D. Mod",
    "M. Eriksson",
    "D. Sundberg",
    "N. Goksu",
    "N. Fegraeus",
    "F. Lindblom",
    "J. Stenkvist",
    "J. Lord",
    "L. Fujita",
    "E. Sjovold",
    "T. Holmsten",
    "J. Ostman",
    "T. Soderman",
    "D. Wiksten",
    "J. Sanick",
    "J. Salt",
    "M. Doran",
    "S. Lindgren",
    "M. Sjoberg",
    "D. Votypka",
    "B. Pajor",
    "J. Andersson",
    "P. Lindholm",
    "P. OShaughnessy",
    "N. Stromquist",
    "S. Strandberg",
    "M. Fritze",
    "J. Norberg",
    "B. Hedberg",
    "O. Carlen",
    "K. Hegethorn",
    "D. Sirland",
    "J. Dawsari",
    "L. Gustavsson",
    "C. Bergqvist",
    "J. Kjellstrom",
    "P. Soderlund",
    "H. Andersson",
    "J. Gonzales",
    "M. Crabtree",
    "C. Tou",
    "G. Pigula",
    "M. Le",
    "R. Pace",
    "K. Lee",
    "R. Walton",
    "D. King",
    "F. Morales",
    "L. Castillo",
    "J. Persson",
    "U. Rask",
    "J. Dohl",
    "M. Kylmamaa",
    "S. Parkinson",
    "J. Newton",
    "A. Papasavas",
    "L. Josephson",
    "S. Decker",
    "M. Rudberg",
    "M. Hedlund",
    "C. Grass",
    "J. Aberg",
    "R. Smedberg",
    "P. Osterblom",
    "S. Evans",
    "S. Abdey",
    "D. Aberin",
    "M. Belanger",
    "J. Biro",
    "M. Brassard",
    "J. Ceron",
    "M. Choy",
    "R. Davey",
    "E. Douridas",
    "C. Elliott",
    "J. Evans",
    "R. Gimbel",
    "R. Hallwood",
    "M. Hart",
    "K. Hoang",
    "D. Kerr",
    "F. Liliegren",
    "R. Linde",
    "M. Livesey",
    "R. Love",
    "A. Marini",
    "S. North",
    "S. Pinkerton",
    "J. Price",
    "D. Rickard",
    "J. Ross",
    "E. Smith",
    "N. White",
    "K. Yip",
    "W. Young",
    "D. Yee",
    "J. Vifian",
    "B. Smith",
    "L. Brown",
    "S. Flyte",
    "C. Barnett",
    "M. Cassidy",
    "T. Kingston",
    "I. Ackworth",
    "J. VanRooyen",
    "J. Hartling",
    "J. Hargelid",
    "C. Clarke",
}

BF2142_BOT_NAMES: set[str] = {
    "S. Wallberg",
    "T. Karlsson",
    "A. Gyllenberg",
    "H. Andersson",
    "K. Bergqvist",
    "D. Gothberg",
    "L. Martensson",
    "D. Mod",
    "M. Eriksson",
    "D. Sundberg",
    "N. Goksu",
    "J. Stenkvist",
    "L. Fujita",
    "T. Holmsten",
    "J. Ostman",
    "J. Salt",
    "B. Pajor",
    "P. OShaughnessy",
    "M. Fritze",
    "J. Dawsari",
    "L. Gustavsson",
    "P. Soderlund",
    "L. Josephson",
    "S. Decker",
    "J. Aberg",
    "R. Smedberg",
    "B. Johnson",
    "G. Brunmar",
    "A. Peters",
    "M. Lokner",
    "A. Kertz",
    "T. Eriksson",
    "M. Nilsson",
    "P. Skude",
    "O. Sundberg",
    "R. Gustafsson",
    "A. Carlsson",
    "J. Hargelid",
    "D. Thiger",
    "S. Juhlin",
    "F. Karlsson",
    "K. Nilsson",
    "K. Reutersward",
    "N. Clay",
    "A. Dale",
    "B. Wallis",
    "S. Dugan",
    "D. Holliday",
    "N. Grover",
    "K. Chirewa",
    "C. Carter",
    "J. Soderqvist",
    "S. Vukanovic",
    "C. Bennison",
    "A. Hansevi",
    "A. Wiegert",
    "A. Brattberg",
    "W. Young",
    "T. Kingston",
    "M. Bagge",
    "M. Choy",
    "M. Andersson",
    "K. Magnusson",
    "J. Levin",
    "J. Sanick",
    "J. Lutze",
    "J. Skoglund",
    "J. Lingmark",
    "J. HerasCordon",
    "J. Ross",
    "J. Evans",
    "G. Tilleby",
    "F. Lindblom",
    "B. Humbe",
    "D. Mollerstedt",
    "T. Sjogren",
    "P. Osterblom",
    "B. Sundell",
    "G. VanDyke",
    "I. Holberg",
    "N. Nolby",
    "N. Astrand",
    "R. Eden",
    "A. Tjernblom",
    "J. Biro",
    "J. Yveborg",
    "M. Kylmamaa",
    "M. Kalms",
    "S. Abdey",
    "D. Cooper",
    "D. Barron",
    "J. Bull",
    "P. Sandberg",
    "B. Tingle",
    "S. Woollard",
    "S. Holman",
    "G. Cover",
    "J. Hopkin",
    "A. Zoghob",
    "C. Wahlfors",
}

BOT_NAMES_BY_GAME = {
    "Battlefield 2": BF2_BOT_NAMES,
    "Battlefield 2142": BF2142_BOT_NAMES,
}

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


def _extract_teams(teams: list, info: dict) -> list:
    """Team-Name + Ticket-/Punktestand aus status.teams. Bestaetigt durch
    die offiziellen Testdaten der opengsq-Bibliothek: das Ticket-Feld heisst
    schlicht "score" (nicht "tickets"), der Teamname liegt im "name"-Feld
    der Teams-Liste. Zusaetzlich info["bf2_team1"/"bf2_team2"] als
    Rueckfall fuer den Namen (liegt im einfacher aufgebauten Info-Block,
    unabhaengig von der positionsbasierten Teams-Liste)."""
    info_names = [info.get("bf2_team1", ""), info.get("bf2_team2", "")]
    result = []
    for i, t in enumerate(teams or []):
        t = {k.lower(): v for k, v in t.items()}
        name = _first(t, "name", "team", default="")
        if not name and i < len(info_names):
            name = info_names[i]
        score = _first(t, "score", "tickets", "teamscore", default="")
        result.append({"name": name, "score": score})
    # BF1942 (GameSpy1) meldet die Tickets als tickets1/tickets2 im
    # Info-Block und die Teamnamen als teamname_0/teamname_1.
    for i, key in enumerate(("tickets1", "tickets2")):
        val = str(info.get(key, "")).strip()
        if not val:
            continue
        while len(result) <= i:
            result.append({"name": "", "score": ""})
        if not result[i]["score"]:
            result[i]["score"] = val
        if not result[i]["name"]:
            result[i]["name"] = str(info.get("teamname_" + str(i), "")).strip()
    return result

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


def _extract_scoreboard(
    players: list, trust_team: bool = True, bot_names: set | None = None
) -> list:
    """Baut aus der rohen Spielerliste ein Scoreboard (Name, Team, Rang,
    Score, Kills, Deaths, Ping) - echte Spieler UND Bots, Bots ueber
    "is_bot" markiert.

    Bot-Erkennung: primaer ping=0 (funktioniert zuverlaessig bei BF2).
    Zusaetzlich/alternativ ein Namensabgleich gegen die feste Bot-
    Namensliste des Spiels (botnames.ai) - noetig bei BF2142, wo ping=0
    nicht zuverlaessig ist.

    trust_team=False (fuer "battlefield2"/BF2/BF2142): Nur das Team-Feld
    ist bei dieser Protokollfamilie dokumentiert unzuverlaessig (liefert
    kaputte Platzhalterwerte statt echter Team-Nummern - ein Fehler auf
    Server-/Protokollebene, nicht in unserer Abfrage). Name, Score, Kills,
    Deaths und Ping sind davon nicht betroffen und bleiben zuverlaessig."""
    bot_names = bot_names or set()
    board = []
    for p in players or []:
        p = {k.lower(): v for k, v in p.items()}
        ping = str(p.get("ping", "1")).strip()
        name = _first(p, "player", "playername", "name", default="?")
        is_bot = ping == "0" or name in bot_names
        board.append(
            {
                "name": name,
                "team": _first(p, "team", "team_t", default="") if trust_team else "",
                "rank": _first(p, "rank", "skill", default=""),
                "score": _first(p, "score", default="0"),
                "kills": _first(p, "kills", "kill", "frags", "skill", default=""),
                "deaths": _first(p, "deaths", "death", default=""),
                "ping": ping,
                "is_bot": is_bot,
            }
        )
    board.sort(
        key=lambda row: (
            row["is_bot"],
            -(int(row["score"]) if str(row["score"]).lstrip("-").isdigit() else 0),
        )
    )
    return board


def _bf2_raw_teams(host, port):
    """BF2 verschickt grosse Antworten (viele Bots) in mehreren UDP-Paketen,
    die opengsq falsch zusammensetzt. Der Team-Block (team_t / score_t) steht
    im letzten Paket und wird hier direkt aus den Rohdaten gelesen."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(TIMEOUT_SECONDS)
        s.sendto(b"\xfe\xfd\x00\x10\x20\x30\x40\xff\xff\xff\x01", (host, port))
        data = b""
        try:
            data += s.recv(65535)
            s.settimeout(0.7)
            while True:
                data += s.recv(65535)
        except Exception:
            pass
        s.close()
        m = re.search(rb"team_t\x00\x00(.*?)\x00\x00score_t\x00\x00(.*?)\x00\x00", data, re.S)
        if not m:
            return []
        names = [x.decode("latin1") for x in m.group(1).split(b"\x00")]
        scores = [x.decode("latin1") for x in m.group(2).split(b"\x00")]
        return [{"name": n, "score": scores[i] if i < len(scores) else ""} for i, n in enumerate(names)]
    except Exception:
        return []


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
        "tickets": [],
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
            result["scoreboard"] = _extract_scoreboard(
                status.players,
                trust_team=(protocol_name != "battlefield2"),
                bot_names=BOT_NAMES_BY_GAME.get(entry.get("game", "")),
            )
            result["tickets"] = _extract_teams(getattr(status, "teams", []), info)
            if protocol_name == "battlefield2":
                raw_teams = await asyncio.to_thread(_bf2_raw_teams, entry["host"], int(entry["port"]))
                if raw_teams:
                    result["tickets"] = raw_teams
            # Spielerzahl bevorzugt direkt aus dem Scoreboard ableiten
            # (dieselbe Quelle wie die Detailansicht), damit Kachel und
            # Scoreboard nie auseinanderlaufen koennen. Nur wenn gar keine
            # Einzeldaten vorliegen, auf das Summenfeld zurueckfallen.
            if result["scoreboard"]:
                result["players"] = sum(
                    1 for row in result["scoreboard"] if not row["is_bot"]
                )
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
    # "internet": true = oeffentlich gestartet (Standard, falls Feld fehlt),
    # false = bewusst nur lokal/LAN gestartet (Testbetrieb) - wird trotz
    # technischer Erreichbarkeit nie angezeigt.
    active = [
        e
        for e in entries
        if e.get("enabled", False) and e.get("internet", True)
    ]

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
