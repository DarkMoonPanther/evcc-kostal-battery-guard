# Kurzanleitung (Deutsch) — v0.8.0-beta

**Achtung:** Experimentelle Software mit möglichem Schreibzugriff auf den Batteriespeicher-Wechselrichter. Die zusammengeführte Beta wurde am 10.11.2026 auf einem PLENTICORE G3 gestartet, aber noch nicht während einer tatsächlichen Fahrzeugladung vollständig validiert. Kein universeller Schutz und keine Herstellerfreigabe.

## Wozu dient sie?

EVCC entscheidet, wann das Fahrzeug lädt. Der Battery Control Guard begrenzt dabei die Entladeleistung des KOSTAL-Hausspeichers, damit er weiterhin den normalen Hausbedarf decken kann. Optional kann die Prognosefunktion begrenzte zusätzliche Speicherenergie für bereits von EVCC gestartete geeignete Ladevorgänge freigeben. Der Guard startet selbst keine Fahrzeugladung.

## Unterschied zum EVCC Optimizer

Der EVCC Optimizer plant das Energiesystem wirtschaftlich anhand von Prognosen, Tarifen, Hausakku und Fahrzeugladungen. Unser Guard begrenzt dagegen **gezielt die KOSTAL-Speicherentladung in Watt**, damit der Haushalt während einer Fahrzeugladung weiterhin Speicherstrom nutzen kann. Optional erlaubt er ein begrenztes, prognoseabhängiges Speicherbudget für bereits von EVCC gestartete Ladungen. **Er startet oder stoppt keine Autoladung und ersetzt nicht die Tarifoptimierung.**

**Wichtig:** EVCCs automatische Optimizer-Batteriesteuerung (`battery`/`full`) nicht parallel aktivieren; sie kann dieselben KOSTAL-Register steuern. Für den Guard die automatische Optimizer-Steuerung auf `off` belassen und andere Batterieschreiber ausschließen.

## Schnelllade-Hotfix und Praxistest

Der Hotfix schützt bereits beim bewusst gewählten Schnelllademodus mit verbundenem Auto – also **vor dem Hochlaufen der Ladeleistung**. Bei verzögertem Stoppen bleibt eine bestehende Begrenzung aktiv, bis die Ladung tatsächlich beendet ist. In einem echten Test auf einem PLENTICORE G3 wurde Register 1040 vor rund 9,8 kW Fahrzeugleistung auf 0 W gesetzt, während der Ladung dynamisch geregelt und nach dem Ladeende freigegeben. **Die intelligente zusätzliche Speicherfreigabe bei einer Planladung ist in der vereinten Beta weiterhin noch nicht separat real getestet.** Siehe [Praxistest](FIELD-VALIDATION.md).

## Voraussetzungen

Python ab 3.11, Linux mit systemd, EVCC mit plausiblen Messwerten, KOSTAL mit dokumentierter externer Modbus-Batteriesteuerung. Ein weiterer Modbus-Schreiber darf nicht gleichzeitig aktiv sein. Die intelligente Funktion unterstützt in der Beta nur einen EVCC-Ladepunkt. Home Assistant ist optional.

## Zuerst ausschließlich beobachten

~~~bash
cp config.example.toml config.toml
# In der Kopie application.state_dir auf einen für dich beschreibbaren
# absoluten Pfad einstellen. execution="observe", armed=false beibehalten.
python3 -m battery_control_guard.app --config config.toml --check-config
python3 -m battery_control_guard.app --config config.toml --observe
python3 -m unittest discover -s tests -v
sh install.sh --dry-run
~~~

Der Beobachtungsmodus liest EVCC, schreibt nicht auf KOSTAL und startet keine Autoladung. Diese Tests belegen keine physische Regelungsfunktion.

## Installation und Migration

Die Installationsroutine legt lediglich Dateien und einen deaktivierten systemd-Dienst an. Sie aktiviert nichts:

~~~bash
sudo sh install.sh --install
~~~

**Nicht direkt starten!** Zuerst die vollständige [Installationsanleitung](INSTALLATION.md), die [Konfiguration](CONFIGURATION.md), die [Sicherheitsgrenzen](SAFETY.md) und bei bisherigen Nutzern die [Migration](MIGRATION.md) lesen. Aktive Steuerung setzt ausdrückliche Freigabe, kontrollierte Deaktivierung der Altversion und nachgewiesene KOSTAL-Rückfalleigenschaften voraus.

Auf GitHub bleibt die frühere Version 0.4.0 über ihren Tag erreichbar. Es wird nur **eine** neue Anwendung installiert, keine zwei unabhängigen Controller.
