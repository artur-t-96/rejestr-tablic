# Czynności dostępne przy wpisie — 03.10.2026

Panel powiatu pokazuje formularz pojazdu wyłącznie przy ALLOCATED, ISSUED
lub SOLD. W stanach RESERVED, SENT i RELEASED pokazuje dane oraz historię
bez formularza zapisu. Bezpośredni POST powiatu w tych trzech stanach daje
HTTP 403, bez zmiany wpisu lub audytu. Niezależna kontrola statusu w usłudze
`update_record` pozostaje w mocy.

Zwolniony wpis opisuje dawną historię; kolejna rezerwacja powstaje przez nowy
wniosek. Oczekujący wpis wyjaśnia, że dane pojazdu można uzupełnić po akceptacji.
Dane pojazdu, daty, nabywca i uwaga pozostają widoczne jako zwykły opis, jeśli
istnieją w rekordzie. Administrator techniczny nadal nie ma dostępu do wpisu,
a inny powiat otrzymuje 404.

UMP nadal może korygować wpis z uzasadnieniem we wszystkich sześciu stanach.
Przycisk przedłużenia dotyczy wyłącznie niewygasłych RESERVED/SENT, nie dawnych
terminów pozostających przy już przydzielonych lub zwolnionych wpisach.
Aktualizacja odbioru: bezpośredni widok wpisu i wniosku wygasza przeterminowane
rezerwacje przed renderowaniem. Stały proces lokalny i pełny audyt wygasania
są opisane w `REZERWACJE-I-ODMOWA.md`.

Importowany wpis pokazuje czytelny opis pochodzenia: nazwę pliku, SHA-256,
autora, czas i podstawę importu. Data importu nie jest datą dawnego przydziału.
Oryginalny log i jego wartości przed/po nadal są dostępne. Dawne importy bez
metadanych źródła nie otrzymują wymyślonego pliku lub sumy.

## Dowody

- **37/37 PASS**, 1.312 s, `evidence/record-actions-tests.txt`: trzy stany
  tylko do odczytu i odmowy POST, trzy stany edytowalne dla powiatu, sześć
  formularzy UMP i granica ważności przedłużenia, pochodzenie, role i 404;
  także regresja importu HTTP, dostępności HTML i rdzenia.
- Chrome na istniejącej fikcyjnej kopii: Gniezno odczytuje zwolniony P4PAST
  bez przycisku/pól edycji, z danymi źródła; oczekujący P5ANNA także bez
  edycji, przydzielony P7NUMRA z formularzem. Piła miała 404 przy zwolnionym
  wpisie przed przełączeniem konta. Screenshot 87 odczytano wizualnie.
- Siedem tabel biznesowych głównej bazy i kopii bez zmian. Logowania OTP
  dodają właściwe zdarzenia uwierzytelnienia; nie tworzono wpisów/pism ani
  nie zapisywano korekt. `evidence/record-actions-browser-report.json`.
- Ruff, Django check i kontrola diffu przeszły. Bez migracji schematu, Dockera
  lub zewnętrznych operacji. Nie ponowiono PostgreSQL, backupu ani pełnego
  WCAG; nie wykonano zapisu w Chrome w tym etapie.

Cel całego systemu nadal jest aktywny. Pozostają pełny odbiór pozostałych
ról/statusów, czytników, API operatorów i infrastruktury urzędu.

Aktualizacja prezentacji historii i dostępu do starszych stron:
`AUDYT-I-HISTORIA.md`. Przy odczycie nie przepisywano zapisanych zdarzeń.
