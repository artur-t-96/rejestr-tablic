# Dyna Rejestr Tablic

System wojewódzki dla Wielkopolski. Dokument źródłowy: `Specyfikacja_flow_tablice.html`. Interfejs referencyjny: `Demo_Rejestr_Tablic.html`. Pliki źródłowe są zachowane.

## Stan prac

Działająca instancja: **https://dyna-rejestr-tablic.onrender.com**.
[Odbiór produkcyjny na danych fikcyjnych](docs/ODBIOR-RENDER-20261003.md)
uzupełnia historyczne raporty lokalne. Kod i hosted CI są na prywatnym GitHub.

Aktualna macierz wymagań, dowodów i pozostałego odbioru:
[MACIERZ-ZGODNOSCI.md](docs/MACIERZ-ZGODNOSCI.md). Walidacja dat, pól i wersji
korekty API: [API-KOREKTY.md](docs/API-KOREKTY.md).
Inwentaryzacja i retencja danych: [RETENCJA-DANYCH.md](docs/RETENCJA-DANYCH.md).
Aktualny odbiór kopii, współbieżności i aktualizacji PostgreSQL:
[ODBIOR-BAZY-I-AKTUALIZACJI.md](docs/ODBIOR-BAZY-I-AKTUALIZACJI.md).
Aktualny odbiór trzech głównych procesów w Chrome, sześciu PDF i izolacji
wybranych kart: [ODBIOR-TRZECH-MODULOW.md](docs/ODBIOR-TRZECH-MODULOW.md).
Odbiór publicznej dostępności: [WCAG-PUBLICZNY.md](docs/WCAG-PUBLICZNY.md).
Wnioski, decyzje i wydawanie przez API: [API-OPERACJE.md](docs/API-OPERACJE.md).
Kontrakt metod wszystkich tras i rzeczywisty HTTP: [METODY-HTTP.md](docs/METODY-HTTP.md).
Macierz ról wszystkich tras: [ROLE-I-TRASY.md](docs/ROLE-I-TRASY.md).
Uprawnienia tworzenia i złożenia II/III: [ROLE-WNIOSKOW-PUL.md](docs/ROLE-WNIOSKOW-PUL.md).
Status własnej rezerwacji w sprawdzarce HTML/API:
[REZERWACJE-W-SPRAWDZARCE.md](docs/REZERWACJE-W-SPRAWDZARCE.md).
Różnorodne wolne sugestie: [SUGESTIE-WYROZNIKOW.md](docs/SUGESTIE-WYROZNIKOW.md).
IP generowania pism, wznowień i błędu OTP: [AUDYT-IP.md](docs/AUDYT-IP.md).
Paginacja list, filtry i pełny eksport: [PAGINACJA-LIST.md](docs/PAGINACJA-LIST.md).
Przegląd 67 wymagań, konta i otwarte czynności:
[RAPORT-ODBIORU-LOKALNEGO.md](docs/RAPORT-ODBIORU-LOKALNEGO.md).
Kolejka decyzji, weryfikacja numeru, przypomnienia, wysyłka pocztą, przegląd
urzędów i ochrona logowania:
[USPRAWNIENIA-PRACY-URZEDOW.md](docs/USPRAWNIENIA-PRACY-URZEDOW.md).
Wejście demonstracyjne bez konta, symulatory EZD RP i e-Doręczeń, podpis demo:
[TRYB-DEMO-I-SYMULATORY.md](docs/TRYB-DEMO-I-SYMULATORY.md).

System wdrożono na Renderze. Przebiegi trzech modułów i lokalne testy dokumentów, importów,
uprawnień oraz kopii opisują powyższe raporty. CAPTCHA ukończono w rzeczywistym
Chrome: [ODBIOR-CAPTCHA.md](docs/ODBIOR-CAPTCHA.md). Odczyt komunikatów przez
czytnik i pełny odbiór AA pozostają niepotwierdzone. Konektory EZD RP i
e-Doręczeń mają kod oraz lokalne testy kontraktowe; nie wykonano pełnego
scenariusza z prawdziwym operatorem. Podpisy PAdES DEMO nie są podpisami
kwalifikowanymi. Brakujące dostępy i kolejne kroki opisuje raport 67 wymagań.
Tryb lokalny nie oznacza odbioru do eksploatacji w urzędzie.

## Uruchomienie lokalne

Sprawdzony profil: CPython 3.12, bez Dockera. Inne wersje Pythona wymagają
osobnej kwalifikacji. Instalacja korzysta z przypiętych wersji i hashy:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip --isolated install --index-url https://pypi.org/simple --require-hashes --only-binary=:all: -r requirements.txt
.venv/bin/python -m pip check
sh scripts/run-local.sh
```

Adres: http://127.0.0.1:8765/. Dane trwałe: `var/registry.sqlite3`. Klucz sesji jest generowany lokalnie i zapisywany w `var/secret-key` z uprawnieniami 0600. Nie commituj katalogu `var`.

Konta fikcyjne: `admin@example.invalid`, `ump@example.invalid`, `gniezno@example.invalid`, `pila@example.invalid`. Konto obywatela nie jest wymagane. Urzędnik wybiera adres e-mail, następnie podaje kod z wiadomości.

Lokalne wiadomości są zapisywane do `var/mail`. Po zamówieniu kodu w przeglądarce odczytaj go:

```sh
.venv/bin/python manage.py local_mail ump@example.invalid
```

Konta mają nieużywalne hasła; logowanie odbywa się wyłącznie kodem. Przy ponownym uruchomieniu dane pokazowe nie są usuwane.

Lokalny skrypt uruchamia też automatyczne powiadomienia autora o decyzjach.
Przy ręcznym starcie serwera uruchom osobno `manage.py process_integrations
--watch --interval 30 --provider SMTP --operation DECISION_NOTICE`.
Okres puli, odbiór powiadomień, migracja 0009 i ograniczenia transportu:
`docs/POWIADOMIENIA-DECYZJI.md`.

Skrypt uruchamia również wygaszanie rezerwacji co 30 sekund. Przy ręcznym
starcie serwera uruchom osobno `manage.py expire_reservations --watch
--interval 30`. Rezerwacja trwa 14 dni; UMP przedłuża ją z uzasadnieniem.
Odmowa, przedłużenie, wygasanie bez wejścia do panelu, zachowanie dokumentów
i dowody odbioru: `docs/REZERWACJE-I-ODMOWA.md`.

## Architektura

Django 5.2 LTS, interfejs renderowany po stronie serwera, responsywne CSS, niewielki JavaScript, SQLite w lokalnym trybie transakcyjnym IMMEDIATE. Obsługa konfiguracji PostgreSQL dla wdrożenia urzędowego. Uprawnienia w usługach i API; częściowy unikalny indeks aktywnych tablic oraz unikalne numery w pulach. PDF generowany ReportLab i przechowywany w bazie z SHA-256.

## Dokumentacja i dowody

Działający dodatkowy hosting: [GitHub i Render](docs/RENDER.md).
Instalacja na infrastrukturze urzędu zachowuje własny profil i instrukcję.

Plan i status: `docs/STATUS.md`. Założenia numeracji: `docs/DECYZJE.md`.
Historia z polskimi opisami, tabela zmian, dostęp do starszych stron i granice
uprawnień audytu: `docs/AUDYT-I-HISTORIA.md`.
Źródła przepisów, poprawka alfabetu bez Q i wybór P/M dla indywidualnych:
`docs/NUMERACJA-PRZEPISY.md`. Wyniki testów i kontroli UI są w katalogu `evidence/`.
Kontynuacja serii tymczasowej po 9999 i kontrola wyczerpania P przed nową pulą M:
`docs/POJEMNOSCI-PUL.md`. Import historycznych wykazów II/III:
`docs/IMPORT-PUL.md`. Kategoria III i rzeczywiste dane historyczne nadal
wymagają uzgodnienia przed wdrożeniem urzędowym.
Kontrola wszystkich przejść układów tablic zmniejszonych i odbiór równoczesnego
przydziału na granicy: `docs/KOLEJNOSC-PUL-II.md`.

Import ewidencji indywidualnej: `docs/IMPORT-EWIDENCJI.md`. Podgląd wszystkich
pól, konkretna wersja źródła, podstawa importu i ochrona przed ponownym zapisem
tego samego źródła. Bezpośredni import XLSX modułów I/II/III, wybór arkusza
oraz daty Excela: `docs/IMPORT-XLSX.md`.

Ręczny przebieg indywidualny w Chrome: wniosek, decyzja, wydanie, zbycie,
korekta, zwolnienie, ponowna rezerwacja i wycofanie oraz poprawki znalezione
podczas odbioru: `docs/WERYFIKACJA-PROCESOW.md`.

Wnioski i wydawanie z pul II/III, kolizje, alert 80%, izolacja urzędów oraz
stronicowanie większych pul: `docs/WERYFIKACJA-PUL.md`.

Konfiguracja i ograniczenia EZD: `docs/EZD-RP.md`. Gotowe materiały do zgłoszenia piaskownicy: `docs/DOSTEP-EZD-RP.md`. Testy lokalne: `.venv/bin/python manage.py test registry --noinput`. Kolejka: `.venv/bin/python manage.py process_integrations`.

Konfiguracja e-Doręczeń: `docs/E-DORECZENIA.md`. Materiały do uzyskania dostępu INT: `docs/DOSTEP-E-DORECZENIA.md`. Dowody i ograniczenia testów: `docs/WERYFIKACJA-E-DORECZENIA.md`.

Podpisy i certyfikaty: `docs/PODPISY.md`. Zakres rzeczywistych testów lokalnych: `docs/WERYFIKACJA-PODPISOW.md`.

Podpis i kolejka przy dwóch rzeczywistych transakcjach PostgreSQL oraz kontrola
załącznika lokalnej poczty: `docs/WSPOLBIEZNOSC-PODPISU.md`.

Roczna numeracja systemowa wniosków i pism oraz zasady zachowania archiwum: `docs/NUMERACJA.md`.

PDF-y, kody QR, aktualizacja domyślnych szablonów bez zmiany archiwum i zakres kontroli wydruku: `docs/PISMA-PDF.md`.

Dostępność, obsługa błędów klawiaturą, reflow 320 px i granice weryfikacji WCAG: `docs/DOSTEPNOSC.md`.

Osobna baza PostgreSQL uruchamiana bez kontenerów, instrukcja i wyniki weryfikacji: `docs/POSTGRESQL-LOKALNIE.md`.

Kopia PostgreSQL z manifestem i odtworzenie do nowej bazy, z unieważnieniem sesji oraz wstrzymaniem kolejki: `docs/BACKUP-POSTGRESQL.md`.

Izolacja aktualnych danych po zmianie urzędu prowadzącego oraz zachowanie pierwotnego wniosku i pism: `docs/WERYFIKACJA-PRZEKAZANIA.md`.

Publiczny limit zapytań i CAPTCHA ALTCHA działają na własnej instancji: konfiguracja, API, retencja i dowody w `docs/OCHRONA-PUBLICZNA.md`.

Wznowienie niewysłanej operacji e-Doręczeń i obserwacji znanego zadania, z kontrolą odtworzonej kopii: `docs/WZNOWIENIE-E-DORECZEN.md`.

Odczyt RPW, archiwum wpływów, linki do wniosków i zapis linku w metadanych EZD: `docs/WPLYWY-EZD.md`.

Profil instalacji na serwerze urzędu, rozdział kont PostgreSQL, Gunicorn, Nginx, systemd, inicjalizacja bez danych pokazowych i procedura aktualizacji: `docs/WDROZENIE-URZEDOWE.md`. Rzeczywisty odbiór Linuxa/HTTPS pozostaje otwarty.

Powrót do sprawy po OTP, ochrona nieaktualnych formularzy i zakres kontroli sesji: `docs/LOGOWANIE-I-SESJE.md`.

Konta, kontrola domen przy OTP i sesjach, trwałe zaproszenia i uzgadnianie wyniku SMTP: `docs/KONTA-I-ZAPROSZENIA.md`.

Lock zależności, instalacja offline, spis paczek i dostarczone teksty licencji:
`docs/ZALEZNOSCI.md` i `THIRD-PARTY-NOTICES.md`. Wersje w `requirements.in`
służą do planowanych aktualizacji; nie są instrukcją instalacji wydania.
