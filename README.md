# LIUC Timetable to iCalendar (.ics) Sync

Strumento open source in Python per l'estrazione automatizzata degli orari accademici e la generazione di un feed di calendario conforme allo standard internazionale **iCalendar (RFC 5545)**.

Il progetto consente agli studenti di sincronizzare lezioni, aule, docenti ed eventuali variazioni d'orario direttamente sulle principali applicazioni di calendario (Apple Calendar, Google Calendar, Microsoft Outlook) tramite sottoscrizione URL o importazione statica.

---

## ⚠️ Disclaimer e Limitazione di Responsabilità
Questo software è un progetto studentesco indipendente e non ufficiale, non affiliato, autorizzato, sponsorizzato o formalmente approvato da LIUC – Università Cattaneo.
Dati as-is: Il software viene fornito "così com'è" (senza garanzie di alcun tipo, esplicite o implicite). L'autore non si assume alcuna responsabilità per errori, omissioni, mancate sincronizzazioni, modifiche dell'ultimo minuto o disallineamenti tra i dati generati da questo script e le comunicazioni ufficiali.
Riferimento vincolante: Gli unici orari, canali e sedi didattiche vincolanti e ufficiali restano esclusivamente quelli pubblicati e aggiornati sul portale web d'Ateneo e comunicati tramite i canali istituzionali.
Uso responsabile: L'utente è l'unico responsabile della verifica della correttezza delle informazioni ricevute prima di pianificare esami o impegni accademici.

---

## 🚀 Caratteristiche principali

- **Parsing nativo via API:** Interroga direttamente l'endpoint asincrono di EasyAcademy, riducendo a zero l'overhead di scraping HTML e garantendo risposte rapide e pulite.
- **Conformità RFC 5545:** Genera componenti `VEVENT` strutturati, completi di UID deterministici (per evitare eventi duplicati a ogni aggiornamento), coordinate di aula, tipologia di attività e stato (confermata o annullata).
- **Zero credenziali richieste:** L'elaborazione non richiede autenticazione né memorizza dati personali o sessioni utente; accede unicamente alle informazioni pubbliche sull'orario delle lezioni.
- **Supporto a eventi custom:** Consente di iniettare impegni e lezioni manuali persistenti tramite configurazione JSON locale (`custom_events.json`).
- **Rilevamento giorni liberi:** Genera blocchi informativi promemoria per le giornate feriali prive di attività didattiche a calendario.

---

## 🛠️ Architettura e Funzionamento

La pipeline esegue i seguenti passaggi:
1. **Fetch dei dati:** Esegue richieste HTTP POST settimanali all'endpoint accademico per l'intervallo temporale specificato (es. intero semestre/anno accademico).
2. **Normalizzazione:** Converte le risposte JSON in oggetti orario gestiti tramite fuso orario di Ateneo (`Europe/Rome`).
3. **Serializzazione:** Costruisce un contenitore `VCALENDAR` valido e compila i dettagli di ogni sessione didattica.
4. **Esportazione:** Produce il file binario `.ics` pronto per l'hosting statico (es. GitHub Pages) o l'uso locale.

---

## ⚙️ Installazione ed Esecuzione Locale

### Prerequisiti
- Python 3.10 o versioni successive
- Gestore pacchetti `pip`

---

## 📲 Sottoscrizione del Calendario (.ics)

Per mantenere il calendario costantemente sincronizzato con gli orari aggiornati:

* **Apple Calendar (iOS / macOS):** File > Nuova sottoscrizione calendario > Incolla l'URL del feed .ics generato.
* **Google Calendar:** Accanto ad Altri calendari, clicca + > Da URL > Incolla l'URL e conferma.
* **Outlook:** Aggiungi calendario > Da Internet > Incolla l'URL del file.
