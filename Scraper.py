"""
Modulo: Scraper.py
Descrizione:
    Pipeline di estrazione orari accademici LIUC e generazione feed conforme
    allo standard iCalendar (RFC 5545).
    
    Il modulo esegue chiamate dirette all'endpoint asincrono JSON di EasyAcademy,
    aggrega le lezioni dell'anno/corso specificato, calcola i blocchi di studio
    per le giornate feriali prive di attività e inietta eventi persistenti definiti
    dall'utente tramite file JSON locale ('custom_events.json').

Autore: Andrea
Data aggiornamento: Settembre 2026
"""

import os
import re
import json
from datetime import timedelta
import requests
import pendulum
from icalendar import Calendar, Event, vText, vUri


# ==============================================================================
# 1. COSTANTI E CONFIGURAZIONE DI SISTEMA
# ==============================================================================

# Determinazione del path assoluto della directory di lavoro dello script
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Endpoint e coordinate del backend EasyAcademy (piattaforma orari d'ateneo)
URL_API = "https://orari.liuc.it/agendaweb/grid_call.php"
BASE_URL = "https://orari.liuc.it/agendaweb/"

# File di input per gli eventi manuali persistenti e output del feed compilato
CUSTOM_EVENTS_FILE = os.path.join(BASE_DIR, "custom_events.json")
OUTPUT_ICS_FILE = os.path.join(BASE_DIR, "orario_liuc_completo.ics")

# Configurazione del fuso orario accademico
TIMEZONE = "Europe/Rome"

# Data limite superiore dell'intervallo temporale di estrazione (fine anno/semestre accademico)
END_DATE_STR = "01-07-2027"

# Parametri POST per l'interrogazione dell'endpoint grid_call.php
PAYLOAD_TEMPLATE = {
    "view": "easycourse",
    "form-type": "corso",
    "include": "corso",
    "anno": "2026",
    "scuola": "AccademiaLIUC",
    "corso": "L09A",
    "anno2[]": "IG|2",  # Specifica Anno / Canale / Curriculum (es. Ingegneria Gestionale II anno)
    "_lang": "en",
    "list": "0",
    "week_grid_type": "-1",
    "all_events": "0"
}


# ==============================================================================
# 2. LOGICA DI ACQUISIZIONE DATI (API EASYACADEMY)
# ==============================================================================

def fetch_schedule_week(start_date: pendulum.DateTime) -> list:
    """
    Esegue l'interrogazione HTTP POST verso l'endpoint backend per una specifica settimana.

    Parametri:
        start_date (pendulum.DateTime): Oggetto data corrispondente al lunedì di inizio settimana.

    Ritorna:
        list: Lista di dizionari rappresentanti le celle orario restituite dal server.
              Restituisce una lista vuota in caso di timeout, mancata connessione o errore di decoding.
    """
    date_str = start_date.format("DD-MM-YYYY")
    payload = PAYLOAD_TEMPLATE.copy()
    payload["date"] = date_str

    print(f"-> Richiesta dati settimana: {date_str}...")

    try:
        response = requests.post(URL_API, data=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
        return data.get("celle", [])

    except requests.RequestException as exc:
        print(f"⚠️ ATTENZIONE: Errore di connessione HTTP per la settimana {date_str}: {exc}")
        return []
    except json.JSONDecodeError:
        print(f"⚠️ ATTENZIONE: Risposta non conforme (non JSON) per la settimana {date_str}. Settimana saltata.")
        return []


# ==============================================================================
# 3. GESTIONE EVENTI SPECIALI (CUSTOM & GIORNI LIBERI)
# ==============================================================================

def add_custom_permanent_events(cal: Calendar):
    """
    Carica eventi custom definiti in CUSTOM_EVENTS_FILE e li appende al calendario.
    Supporta link web sia come location che come proprietà nativa URL.
    """
    if not os.path.exists(CUSTOM_EVENTS_FILE):
        print(f"-> Info: File eventi manuali '{CUSTOM_EVENTS_FILE}' non presente.")
        return

    try:
        with open(CUSTOM_EVENTS_FILE, "r", encoding="utf-8") as f:
            custom_list = json.load(f)

        if not isinstance(custom_list, list):
            print(f"❌ ERRORE: '{CUSTOM_EVENTS_FILE}' non contiene una lista JSON [ ... ].")
            return

        added_count = 0
        domain_part = BASE_URL.split("/")[2] if "/" in BASE_URL else "liuc.it"

        for idx, item in enumerate(custom_list):
            titolo = item.get("titolo")
            data_str = item.get("data")
            ora_ini = item.get("ora_inizio")
            ora_fin = item.get("ora_fine")

            if not all([titolo, data_str, ora_ini, ora_fin]):
                print(f"⚠️ Elemento #{idx+1} privo di campi obbligatori. Skippato.")
                continue

            ora_ini_clean = str(ora_ini).strip().zfill(5)
            ora_fin_clean = str(ora_fin).strip().zfill(5)
            data_clean = str(data_str).strip()

            try:
                dtstart = pendulum.from_format(f"{data_clean} {ora_ini_clean}", "DD-MM-YYYY HH:mm", tz=TIMEZONE)
                dtend = pendulum.from_format(f"{data_clean} {ora_fin_clean}", "DD-MM-YYYY HH:mm", tz=TIMEZONE)
            except Exception as pe:
                print(f"⚠️ Errore parsing data/ora per '{titolo}': {pe}")
                continue

            event = Event()
            event.add("summary", vText(titolo))
            event.add("dtstart", dtstart)
            event.add("dtend", dtend)
            
            aula_val = item.get("aula", "").strip()
            if aula_val:
                event.add("location", vText(aula_val))
                if aula_val.startswith("http"):
                    try:
                        event.add("url", vUri(aula_val))
                    except Exception:
                        pass

            event.add("description", vText(item.get("descrizione", "Evento inserito manualmente.")))

            # UID alfanumerico pulito
            clean_title = re.sub(r"[^a-zA-Z0-9]", "", titolo)[:20]
            uid_str = f"CUSTOM-{clean_title}-{data_clean.replace('-', '')}-{ora_ini_clean.replace(':', '')}@{domain_part}"
            event.add("uid", uid_str)

            cal.add_component(event)
            added_count += 1
            print(f"-> Aggiunto evento manuale: {titolo} ({data_clean} {ora_ini_clean}-{ora_fin_clean})")

        print(f"✅ Inseriti con successo {added_count} eventi manuali permanenti da {CUSTOM_EVENTS_FILE}.")

    except Exception as exc:
        print(f"❌ ERRORE caricamento {CUSTOM_EVENTS_FILE}: {exc}")



def add_free_time_events(cal: Calendar, all_lessons: list):
    """
    Rileva le date feriali (Lunedì-Venerdì) prive di impegni didattici compresi tra la prima
    e l'ultima data attiva rilevata, generando blocchi promemoria per studio/tempo libero.

    Parametri:
        cal (icalendar.Calendar): Oggetto calendario di destinazione.
        all_lessons (list): Insieme aggregato delle lezioni universitarie estratte.
    """
    occupied_dates = set()
    for lesson in all_lessons:
        data_str = lesson.get("data", "")
        if data_str:
            try:
                occupied_dates.add(pendulum.from_format(data_str, "DD-MM-YYYY", tz=TIMEZONE).date())
            except Exception:
                continue

    if not occupied_dates:
        return

    min_date = min(occupied_dates)
    max_date = max(occupied_dates)
    domain_part = BASE_URL.split("/")[2] if "/" in BASE_URL else "liuc.it"

    current_day = min_date
    while current_day <= max_date:
        # Se è un giorno feriale (0 = Lunedì, 4 = Venerdì) e non compaiono lezioni
        if current_day.weekday() < 5 and current_day not in occupied_dates:
            dtstart = pendulum.datetime(current_day.year, current_day.month, current_day.day, 8, 0, tz=TIMEZONE)
            dtend = dtstart.add(hours=12)

            event = Event()
            event.add("summary", vText("GIORNO LIBERO / STUDIO"))
            event.add("dtstart", dtstart)
            event.add("dtend", dtend)
            event.add("location", vText(""))
            event.add("description", vText("Nessuna lezione o esame programmato a calendario per questa giornata."))
            event.add("uid", f"LIUC-FREE-{current_day.strftime('%Y%m%d')}@{domain_part}")

            cal.add_component(event)

        current_day += timedelta(days=1)


# ==============================================================================
# 4. COMPILATORE ICALENDAR (RFC 5545) & CORE RUNNER
# ==============================================================================

def generate_ical_file_full():
    """
    Flusso principale di orchestrazione:
        1. Esegue il ciclo temporale settimanale ed estrae le lezioni via API.
        2. Configura metadati, intestazioni e timezone del contenitore VCALENDAR.
        3. Esegue parsing, sanitizzazione e creazione componenti VEVENT per le lezioni.
        4. Inietta i blocchi studio/giorni liberi.
        5. Inietta gli eventi permanenti manuali definiti nel file JSON locale.
        6. Serializza ed esporta il file finale conforme a standard RFC 5545.
    """
    try:
        today = pendulum.today(TIMEZONE)
        start_date = today.start_of("week")
        end_date = pendulum.from_format(END_DATE_STR, "DD-MM-YYYY", tz=TIMEZONE)
    except ValueError:
        print("❌ ERRORE FATALE: Il formato di END_DATE_STR deve essere 'DD-MM-YYYY'.")
        return

    current_date = start_date
    all_lessons = []

    # Iterazione settimana per settimana lungo tutto il semestre/anno
    while current_date <= end_date:
        lessons_in_week = fetch_schedule_week(current_date)
        all_lessons.extend(lessons_in_week)
        current_date = current_date.add(days=7)

    print("-" * 60)
    print(f"✅ Estrazione completata. Rilevati {len(all_lessons)} eventi grezzi da EasyAcademy.")

    # Inizializzazione e configurazione dell'oggetto Calendar conforme a RFC 5545
    cal = Calendar()
    cal.add("prodid", vText("-//LIUC Schedule Exporter//IT"))
    cal.add("version", "2.0")
    cal.add("x-wr-calname", vText(f"Orario LIUC {PAYLOAD_TEMPLATE['anno']} - {PAYLOAD_TEMPLATE['corso']}"))
    cal.add("x-wr-timezone", vText(TIMEZONE))

    domain_part = BASE_URL.split("/")[2] if "/" in BASE_URL else "liuc.it"

    # Elaborazione delle lezioni didattiche universitarie
    for lesson in all_lessons:
        data_evento = lesson.get("data")
        ora_inizio = lesson.get("ora_inizio")
        ora_fine = lesson.get("ora_fine")

        # Filtro per record privi dei dati orari essenziali
        if not data_evento or not ora_inizio or not ora_fine:
            continue

        try:
            dtstart = pendulum.from_format(f"{data_evento} {ora_inizio}", "DD-MM-YYYY HH:mm", tz=TIMEZONE)
            dtend = pendulum.from_format(f"{data_evento} {ora_fine}", "DD-MM-YYYY HH:mm", tz=TIMEZONE)
        except Exception:
            continue

        # Estrazione e pulizia dati descrittivi
        is_cancelled = str(lesson.get("Annullato", "")).strip() == "1"
        nome_lezione = lesson.get("nome_insegnamento", "Attività Didattica")
        tipo_lezione = lesson.get("tipo", "Lezione")
        docente = lesson.get("docente", "N/D")
        codice = lesson.get("CodiceGenerale", "N/D")
        location_raw = lesson.get("aula", "Aula non assegnata")
        location_clean = location_raw.split("[")[0].strip()

        # Generazione ID univoco deterministico per non creare duplicati sul client
        lesson_id = lesson.get("id", lesson.get("timestamp", str(hash(f"{data_evento}{nome_lezione}{ora_inizio}"))))

        # Configurazione VEVENT
        event = Event()
        summary_prefix = "[ANNULLATO] " if is_cancelled else ""
        event.add("summary", vText(f"{summary_prefix}{nome_lezione}"))
        event.add("dtstart", dtstart)
        event.add("dtend", dtend)
        event.add("location", vText(location_clean))

        description = (
            f"Stato: {'ANNULLATO' if is_cancelled else 'Confermato'}\n"
            f"Tipologia: {tipo_lezione}\n"
            f"Docente: {docente}\n"
            f"Codice Corso: {codice}\n"
            f"Curriculum: {PAYLOAD_TEMPLATE['corso']} ({PAYLOAD_TEMPLATE['anno2[]']})"
        )
        event.add("description", vText(description))
        event.add("uid", f"LIUC-{lesson_id}-{data_evento.replace('-', '')}@{domain_part}")

        cal.add_component(event)

    # Iniezione placeholder giornate libere da impegni
    print("-> Aggiunta blocchi 'GIORNO LIBERO' per le date prive di lezioni...")
    add_free_time_events(cal, all_lessons)

    # Iniezione impegni manuali persistenti da file JSON
    add_custom_permanent_events(cal)

    # Esportazione e persistenza del file .ics binario
    with open(OUTPUT_ICS_FILE, "wb") as f:
        f.write(cal.to_ical())

    print("-" * 60)
    print(f"🎉 Pipeline conclusa. File esportato: '{OUTPUT_ICS_FILE}'.")


# ==============================================================================
# 5. ENTRY POINT PRINCIPALE
# ==============================================================================

if __name__ == "__main__":
    generate_ical_file_full()
