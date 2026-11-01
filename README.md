# MaeKeys Ponyhof – Server-Status

Kostenlose Status-Seite für die eigenen Retrogame-Server. Fragt die Server
**direkt** per GameSpy-Query-Protokoll ab (keine Abhängigkeit von OpenSpy,
BF2Hub o. ä.) und zeigt, welches Spiel gerade läuft, auf welcher Map, in
welchem Modus und mit wie vielen Spielern.

Läuft komplett auf GitHub (Actions + Pages) – kein eigenes Gerät, keine
Kosten.

## 1. Repository anlegen

1. Neues **öffentliches** GitHub-Repository erstellen (muss öffentlich sein,
   damit GitHub Pages im kostenlosen Plan funktioniert).
2. Alle Dateien aus diesem Ordner in das Repository hochladen (z. B. per
   Drag & Drop im Browser auf `github.com/<dein-name>/<repo>`, oder per Git).

## 2. Workflow-Schreibrechte aktivieren

Der Workflow muss `docs/status.json` selbst committen können:

- **Settings → Actions → General → Workflow permissions**
- **„Read and write permissions"** auswählen → **Save**

Ohne diesen Schritt schlägt der `git push` im Workflow fehl.

## 3. GitHub Pages aktivieren

- **Settings → Pages**
- **Source**: „Deploy from a branch"
- **Branch**: `main`, Ordner **`/docs`**
- Speichern. Die Seite ist danach unter
  `https://<dein-name>.github.io/<repo>/` erreichbar (kann ein paar Minuten
  dauern, bis sie beim ersten Mal live ist).

## 4. Eigene Server eintragen

In `config/servers.json`:

- `host`: deine **MyFRITZ!-Adresse** (kostenloser DynDNS-Dienst der FRITZ!Box
  5530 – falls noch nicht aktiv: FRITZ!Box-Oberfläche → Internet → MyFRITZ!-Konto)
- `port`: der **Query-Port**, über den der jeweilige Server am hEX
  nach außen weitergeleitet ist (die bereits bestehenden Portfreigaben für
  die laufenden Spiele verwenden) – bitte die Werte in der Datei vor dem
  ersten Einsatz gegen deine tatsächliche hEX-Konfiguration prüfen, die
  eingetragenen Ports sind nur typische Standardwerte
- `enabled`: `true`, sobald der jeweilige Server wirklich läuft/bereit ist –
  so kannst du BF1942, BF2, MOHAA, MOHPA, BF2142 einzeln freischalten, sobald
  sie fertig eingerichtet sind

Änderungen an `config/servers.json` committen – der Workflow läuft dann
automatisch (dank `push`-Trigger) direkt einmal durch.

## 5. Testen

- **Actions**-Tab im Repository → Workflow „Status aktualisieren" →
  **Run workflow** (manueller Test, ohne auf den nächsten 5-Minuten-Takt zu
  warten)
- Anschließend `docs/status.json` im Repo prüfen und die Pages-URL aufrufen

## Hinweise

- Der 5-Minuten-Takt (`cron: "*/5 * * * *"`) ist eine Ziel-, keine
  Garantiezeit – GitHub kann geplante Workflows bei hoher Auslastung um ein
  paar Minuten verzögern. Die Seite zeigt den Zeitstempel des letzten
  erfolgreichen Durchlaufs an und warnt, wenn er älter als 20 Minuten ist.
- Ist ein Server aus oder nicht erreichbar, erscheint er einfach nicht in
  der Liste. Läuft gar kein Server, zeigt die Seite „Aktuell läuft kein
  Spiel".
- Die Zuordnung Spiel → Protokoll (`gamespy1` / `gamespy2` / `battlefield2`)
  ist in `scripts/query_servers.py` über die `opengsq`-Bibliothek fest
  hinterlegt und muss nicht angepasst werden.
