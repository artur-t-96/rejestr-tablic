# Weryfikacja pierwszego etapu - 03.10.2026

Status całego celu: **W TOKU**. Raport potwierdza wyłącznie wymienione poniżej sprawdzenia.

## Środowisko

- Lokalny Django 5.2.17, Python 3.12.14, SQLite plikowy z transakcjami IMMEDIATE.
- Aplikacja: http://127.0.0.1:8765/.
- 35 urzędów i cztery fikcyjne konta. Adresy e-mail example.invalid; brak prawdziwych ADE.
- Brak Dockera, połączeń z urzędem, PR, CI i wdrożenia produkcyjnego. Przedmiotem celu jest teraz lokalna budowa.

## Testy automatyczne

`python manage.py test registry.tests --noinput -v 1`: **23/23 PASS**, wynik zapisany w `evidence/core-tests.txt`.

Sprawdzone: walidacja numerów, prywatność wyniku publicznego, cykl przydział-wydanie-zbycie-zwolnienie, duplikat rezerwacji, uprawnienia A0/A2/A3, izolacja urzędów, odmowa z uzasadnieniem, konflikt wersji, wygaśnięcie, przedłużenie, wycofanie, kolizje pul, podwójne wydanie, wniosek III, generowanie PDF z polskimi znakami, podgląd i zapis importu, eksport z izolacją i ochroną przed formułami, CSRF, jednorazowość OTP, blokada nieaktywnego urzędu, niezmienność modelu audytu oraz renderowanie paneli.

Dwa testy współbieżności uruchomiły operacje w oddzielnych połączeniach i wątkach, jednocześnie na tej samej bazie plikowej. Potwierdziły jeden sukces i jeden konflikt dla tego samego numeru oraz nakładających się pul. Pierwsza próba na testowej bazie w pamięci kończyła się SQLITE_LOCKED; konfigurację testów zmieniono na plik odpowiadający lokalnemu uruchomieniu. Nie ukrywano błędów jako sukcesów.

Ruff: PASS. `manage.py check`: PASS. `check --deploy` w lokalnym HTTP wskazuje cztery spodziewane ostrzeżenia dotyczące HTTPS/secure cookies/HSTS; nie jest to potwierdzenie wdrożenia urzędowego.

## Ręcznie w Chrome użytkownika

- Sprawdzenie DYNA: P0DYNA niedostępny, pozostałe warianty dostępne, bez danych właściciela.
- Logowanie powiatu Gniezno kodem z lokalnej wiadomości; urząd wynika z konta.
- Utworzenie P8 UIQA z fikcyjnym właścicielem; rezerwacja i pismo PDF zapisane w bazie.
- Złożenie wniosku W/2026/00004 do UMP; status oczekujący, historia operacji.
- Wylogowanie, logowanie UMP, otwarcie wniosku i akceptacja z uzasadnieniem.
- Status zaakceptowany, pismo zwrotne dostępne, rezerwacja usunięta z zaakceptowanego przydziału.
- Kontrola wizualna widoku publicznego, formularza i szczegółów wniosku.

Dowody: `evidence/01-wniosek-powiatu.jpg`, `evidence/02-zgoda-ump.jpg`.

Pełny cykl wydania, zbycia, korekty i wszystkie role wymagają jeszcze ręcznego przejścia w Chrome. Testy backendu nie zastępują tego sprawdzenia.

## PDF

Wyeksportowano istniejące przykłady z lokalnej bazy do `evidence/pdf/`. Pismo zgody dla P8 UIQA wyrenderowano Popplerem i obejrzano. Polskie znaki, tytuł, dane, UUID, numeracja strony i oznaczenie „niepodpisany” są czytelne. Pozostałe typy i przypadki wielostronicowe pozostają do kontroli wizualnej.

## Backup i odtworzenie

Wykonano spójny snapshot działającej lokalnej bazy: `var/backups/2026-10-03-first.zip`. SHA-256 snapshotu: `431f76237cf543b70dee851c9312a4048cf947a1082930fe54aa92181af3b7a5`.

Odtworzono do osobnego katalogu `var/restore-check-2026-10-03`, bez nadpisywania działającej bazy. Potwierdzono `integrity_check`, `foreign_key_check`, liczby rekordów według manifestu i SHA-256 wszystkich zapisanych PDF. Odtworzenie unieważnia sesje i kody logowania. Uruchomienie aplikacji na odtworzonej bazie oraz dalsze scenariusze awaryjne pozostają do sprawdzenia.

## Integracje

- Poczta: logowanie używa rzeczywistego backendu wiadomości Django; lokalnie plikowego. Brak testu SMTP z serwerem zewnętrznym.
- EZD RP: kod konektora nadal do wykonania; brak dostępów piaskownicy.
- e-Doręczenia: kod konektora nadal do wykonania; brak dostępów INT.
- Podpis: implementacja nadal do wykonania; nie wygenerowano fikcyjnego podpisu kwalifikowanego.

## Kolejne prace

Rzeczywiste kontrakty i konektory integracji, podpisywanie, rozwinięcie administracji i powiadomień, CAPTCHA, pozostałe reguły prawne, kontrola dostępności, pełne scenariusze UI, odtworzona aplikacja i dokumentacja wdrożenia. Lista w `docs/STATUS.md` zachowuje pełny zakres celu.
