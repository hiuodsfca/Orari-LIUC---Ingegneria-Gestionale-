import requests
import json
import pendulum
from icalendar import Calendar, Event, vText
from datetime import date, timedelta
import re

# ==============================================================================
# 1. CONFIGURAZIONE RICHIESTA (Verifica i tuoi parametri)
# ==============================================================================
# Quest'anno: {anno: "2026", corso: "L09B", anno2[]: ["IG|2"]}
# URL per la richiesta POST dei dati orari (il server dei dati)
URL_API = "https://orari.liuc.it/agendaweb/grid_call.php"
BASE_URL = "https://orari.liuc.it/agendaweb/"

# PARAMETRI DEL TUO CORSO (Questi sono i dati che il server si aspetta nella richiesta POST)
PAYLOAD_TEMPLATE = {
    "view": "easycourse",
    "form-type": "corso",
    "include": "corso",
    "anno": "2026",
    "scuola": "AccademiaLIUC",
    "corso": "L09A",
    "anno2[]": "IG|2",  # Codice specifico Anno/Curriculum
    "_lang": "en",

    # Parametri necessari per la chiamata di griglia
    "list": "0",
    "week_grid_type": "-1",
    "all_events": "0"
}

# La data di fine è fissa: la fine del semestre
END_DATE_STR = "01-07-2027"

TIMEZONE = 'Europe/Rome'


# ==============================================================================
# 2. FUNZIONI DI ESECUZIONE E CONVERSIONE
# ==============================================================================

def fetch_schedule_week(start_date: pendulum.DateTime) -> list:
    """Esegue la richiesta POST per una specifica settimana e restituisce le lezioni."""

    date_str = start_date.format('DD-MM-YYYY')

    payload = PAYLOAD_TEMPLATE.copy()
    payload['date'] = date_str

    print(f"-> Richiesta dati per la settimana che inizia il: {date_str}...")

    try:
        response = requests.post(URL_API, data=payload, timeout=15)
        response.raise_for_status()

        data = response.json()

        return data.get('celle', [])

    except requests.RequestException as e:
        print(f"ERRORE di rete o HTTP durante la richiesta per {date_str}: {e}")
        # In caso di errore HTTP, la funzione restituisce una lista vuota e lo script continua
        return []
    except json.JSONDecodeError:
        print(f"ERRORE: Risposta non JSON per {date_str}. Salto la settimana.")
        return []


def add_free_time_events(cal: Calendar, all_lessons: list):
    """Aggiunge eventi 'Tempo Libero' nei giorni lavorativi senza lezioni."""

    occupied_dates = set()
    for lesson in all_lessons:
        data_str = lesson.get('data', '')
        if data_str:
            try:
                occupied_dates.add(pendulum.from_format(data_str, 'DD-MM-YYYY', tz=TIMEZONE).date())
            except Exception:
                continue

    if not occupied_dates:
        return

    min_date = min(occupied_dates)
    max_date = max(occupied_dates)

    current_day = min_date
    while current_day <= max_date:

        # Lunedì (0) a Venerdì (4)
        if current_day.weekday() < 5 and current_day not in occupied_dates:
            # Crea evento "Tempo Libero"
            dtstart = pendulum.datetime(current_day.year, current_day.month, current_day.day, 8, 0, tz=TIMEZONE)
            dtend = dtstart.add(hours=12)

            event = Event()
            event.add('summary', vText('GIORNO LIBERO / STUDIO'))
            event.add('dtstart', dtstart)
            event.add('dtend', dtend)
            event.add('location', vText(''))
            event.add('description', vText('Nessuna lezione o esame programmato in questo giorno.'))
            event.add('uid', f"LIUC-FREE-{current_day.strftime('%Y%m%d')}@{BASE_URL.split('/')[2]}")

            cal.add_component(event)

        current_day += timedelta(days=1)


def generate_ical_file_full():
    """Cicla tutte le settimane, genera il file ICS combinato e aggiunge giorni liberi."""

    try:
        # Imposta l'inizio dalla settimana corrente
        today = pendulum.today(TIMEZONE)
        start_date = today.start_of('week')

        end_date = pendulum.from_format(END_DATE_STR, 'DD-MM-YYYY', tz=TIMEZONE)
    except ValueError:
        print("ERRORE FATALE: Controlla che la data END_DATE_STR sia nel formato DD-MM-YYYY.")
        return

    current_date = start_date
    all_lessons = []

    # Ciclo settimana per settimana
    while current_date <= end_date:
        lessons_in_week = fetch_schedule_week(current_date)
        all_lessons.extend(lessons_in_week)

        # Sposta la data in avanti di 7 giorni
        current_date = current_date.add(days=7)

    print("-" * 50)
    print(f"✅ Estrazione completata. Trovate {len(all_lessons)} eventi in totale (incluse lezioni annullate).")

    # --- CONVERSIONE E SALVATAGGIO ICS ---
    cal = Calendar()
    cal.add('prodid', vText('-//Orario LIUC Automazione//IT'))
    cal.add('version', '2.0')
    cal.add('x-wr-calname', vText(f"Orario LIUC {PAYLOAD_TEMPLATE['anno']} - {PAYLOAD_TEMPLATE['corso']}"))

    for lesson in all_lessons:

        # 1. ESTRAZIONE DATI SICURA
        is_cancelled = lesson.get('Annullato') == '1'

        nome_lezione = lesson.get('nome_insegnamento', 'Evento Generico')
        tipo_lezione = lesson.get('tipo', 'Evento')
        docente = lesson.get('docente', 'N/D')
        codice = lesson.get('CodiceGenerale', 'N/D')
        location_raw = lesson.get('aula', 'Aula Sconosciuta')
        data_evento = lesson.get('data', current_date.format('DD-MM-YYYY'))

        # L'ID usa il timestamp come fallback
        lesson_id = lesson.get('id', lesson.get('timestamp', str(hash(data_evento + nome_lezione))))

        location_clean = location_raw.split('[')[0].strip()

        # 2. PARSING DATA E ORA
        try:
            start_dt_str = f"{data_evento} {lesson['ora_inizio']}"
            end_dt_str = f"{data_evento} {lesson['ora_fine']}"

            dtstart = pendulum.from_format(start_dt_str, 'DD-MM-YYYY HH:mm', tz=TIMEZONE)
            dtend = pendulum.from_format(end_dt_str, 'DD-MM-YYYY HH:mm', tz=TIMEZONE)
        except Exception:
            print(f"ATTENZIONE: Impossibile parsare data/ora per {nome_lezione}. Salto l'evento.")
            continue

        # 3. CREAZIONE EVENTO ICAL
        event = Event()

        # Aggiunge il prefisso [ANNULLATO] se necessario
        summary_prefix = "[ANNULLATO] " if is_cancelled else ""
        event.add('summary', vText(f"{summary_prefix}{nome_lezione}"))

        event.add('dtstart', dtstart)
        event.add('dtend', dtend)
        event.add('location', vText(location_clean))

        description = (
            f"STATO: {'ANNULLATO' if is_cancelled else 'ATTIVO'}\n"
            f"Tipo: {tipo_lezione}\n"
            f"Docente: {docente}\n"
            f"Codice: {codice}\n"
            f"Corso di Studi: {PAYLOAD_TEMPLATE['corso']}\n"
        )
        event.add('description', vText(description))

        event.add('uid', f"LIUC-{lesson_id}-{data_evento.replace('-', '')}@{BASE_URL.split('/')[2]}")

        cal.add_component(event)

    # 4. Aggiunge i giorni senza lezioni come eventi "Tempo Libero"
    print("-> Aggiunta eventi 'GIORNO LIBERO' per i giorni senza lezioni...")
    add_free_time_events(cal, all_lessons)

    ics_filename = 'orario_liuc_completo.ics'
    with open(ics_filename, 'wb') as f:
        f.write(cal.to_ical())

    print("-" * 50)
    print(f"🎉 File '{ics_filename}' generato nella cartella del progetto.")


# ==============================================================================
# ENTRY POINT PRINCIPALE (per esecuzione locale e GitHub Actions)
# ==============================================================================

if __name__ == "__main__":
    generate_ical_file_full()
