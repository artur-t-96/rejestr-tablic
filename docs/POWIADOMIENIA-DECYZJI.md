# Moduł III — okres puli i powiadomienia o decyzji

Stan: 03.10.2026. Implementacja `cadcce794de4ce4a51451deacb79b562128ff198`.
Cały cel pozostaje **W TOKU**. Ten etap nie potwierdza kategorii prawnej III,
rzeczywistego SMTP urzędu, zewnętrznych API ani pełnej zgodności produktu.

## Zachowanie aplikacji

Akceptacja III wymaga daty początkowej i końcowej. Formularz wskazuje błąd
przy polu daty końca; usługa sprawdza model, a baza egzekwuje
`pool_iii_finite_period` oraz istniejące ograniczenie kolejności dat.
Data początku i końca są włącznie: wydanie poza tym okresem jest blokowane.
Odmowa wymaga uzasadnienia i nie wymaga okresu ani przydziału numerów.
Moduł II nadal pozwala przydzielić pulę bez daty końca.

Zapis decyzji III tworzy automatyczne powiadomienie dla **autora wniosku**,
zarówno przy akceptacji, jak i odmowie. Decyzja, pismo, pula i rekord kolejki
powstają w jednej transakcji. Błąd zapisu powiadomienia wycofuje całą decyzję.
Wysyłka odbywa się później, poza transakcją i obsługą żądania użytkownika.

Kolejka `IntegrationJob`, provider `SMTP`, operacja `DECISION_NOTICE`, zawiera
stały adres autora, nadawcę, temat i treść w JSON z SHA-256. Późniejsza zmiana
e-maila autora lub dokumentu nie zmienia zapisanej wiadomości. Unikalny klucz
wniosku zapobiega utworzeniu drugiego powiadomienia przy powtórnej operacji.

E-mail zawiera referencję, wynik oraz link wymagający zalogowania. Nie zawiera
PDF, danych właściciela lub pojazdu, nazwy stacji, znaku sprawy ani uzasadnienia.
Doręczenie urzędowego pisma urzędowi pozostaje osobną operacją. Powiadomienie
nie blokuje podpisania pisma zwrotnego; załączniki wysyłki dokumentu nadal
podlegają dotychczasowej blokadzie podpisu po utworzeniu kolejki dokumentu.

W panelu wniosku i Integracjach widać stan powiadomienia. `LOCAL_SAVED` oznacza
plik lokalny bez wysyłki do adresata. `ACCEPTED` oznacza przyjęcie przez backend
poczty; dla SMTP nie jest to dowód odbioru przez urzędnika. Niepewny wynik
transportu lub przerwany proces przechodzi do `REVIEW_REQUIRED`, bez
automatycznego ponowienia. Stały Message-ID nie gwarantuje deduplikacji SMTP.
Błąd zapisanej treści lub brak konfiguracji SMTP ma status `CONFIG_ERROR`.

## Uruchomienie i utrzymanie

`sh scripts/run-local.sh` uruchamia aplikację oraz osobny proces powiadomień
III co 30 sekund. Zakończenie skryptu zatrzymuje jego oba procesy.
Pozostałe kanały korespondencji przetwarza się osobno po ich konfiguracji.
W trybie lokalnym domyślny backend zapisuje wiadomości w `var/mail`.

Przy uruchamianiu aplikacji ręcznie w drugiej powłoce z tą samą konfiguracją:

```sh
.venv/bin/python manage.py process_integrations --watch --interval 30 --provider SMTP --operation DECISION_NOTICE
```

Bez `--watch` polecenie wykonuje jedną partię, co zachowuje współpracę z
istniejącym `deploy/dyna-jobs.timer`. Timer urzędowy uruchamia całą kolejkę.
SMTP urzędu wymaga konfiguracji opisanej w `WDROZENIE-URZEDOWE.md`.
Należy monitorować błędy procesu i stany wymagające kontroli.

Nie zmieniaj ręcznie payloadu ani nie ustawiaj niepewnego lub odtworzonego
zadania na `QUEUED` bez uzgodnienia wyniku. Nie dodano w tym etapie formularza
wznowienia powiadomień SMTP; procedura wznowienia po naprawie konfiguracji
i uzgodnieniu operatora pozostaje do uzupełnienia.

## Aktualizacja danych i kopia

Migracja 0009 najpierw sprawdza istniejące pule III. Gdy termin końca jest
pusty, zatrzymuje się z liczbą i maksymalnie pięcioma UUID. Nie przypisuje
arbitralnego okresu, nie usuwa puli i nie zmienia dokumentów. Terminy trzeba
ustalić z dokumentacji urzędu i zapisać z udokumentowaną decyzją przed ponowną
migracją. Przed aktualizacją wykonaj kopię i zatrzymaj procesy aplikacji/kolejki.

Przed lokalną migracją: główna baza nie miała pul III; jedyna pula III w
prywatnej bazie odbioru miała koniec 31.12.2026. Obie bazy mają zastosowaną
migrację 0009. Kopie przed aktualizacją zachowano w ignorowanym `var/backups/`.
Hash i liczba wszystkich rekordów sześciu głównych tabel biznesowych nie
zmieniły się wskutek migracji. Nie dopisano powiadomień dla dawnych decyzji.

Backup sprawdza również SHA-256 treści powiadomienia. Odtworzenie aktywnej
kolejki ustawia `REVIEW_REQUIRED`, aby snapshot sprzed wysyłki nie spowodował
jej ponowienia. Kopia nie zawiera sekretów konfiguracyjnych.

## Dowody

62 testy SQLite PASS (4,977 s), w tym 16 nowych scenariuszy dat, powiadomień,
procesu stałego i migracji oraz nowy test rzeczywistego podpisu DEMO pisma
zwrotnego po powiadomieniu. Zestaw obejmuje również rdzeń, paginację pul,
odtworzenie kolejki i pozostałe testy podpisów.

15 skupionych testów PostgreSQL PASS (1,042 s): decyzje i powiadomienia,
ograniczenie bazy, zatrzymanie migracji z historycznym brakiem terminu,
rzeczywisty podpis DEMO po powiadomieniu. Nie powtarzano pełnej bramki
integracyjnej, obciążeniowej ani wszystkich testów współbieżności. Prywatny
klaster zatrzymano i potwierdzono `pg_ctl: no server running`.

Ruff, Django check, brak niezapisanych migracji, diff i składnia skryptu PASS.
Nie uruchamiano Dockera. Nie wykonano w tym etapie pełnego testu nadzoru
procesów skryptu `run-local.sh` ani docelowego systemd na Linuxie.

Chrome użytkownika, prywatna baza `var/business-ui-20261003`, localhost:8774:

| Scenariusz | Potwierdzony wynik |
| --- | --- |
| Gniezno tworzy i składa dwa wnioski III | W/2026/00008 i W/2026/00009, rzeczywiste pisma PDF |
| UMP akceptuje bez końca puli | Błąd przy polu, SENT zachowany; 4 stare pule, 0 powiadomień |
| UMP akceptuje z terminem 31.12.2026 | P30001–P30002, okres 03.10–31.12.2026, pismo i kolejka |
| Stały worker pracuje niezależnie | Akceptacja przetworzona do LOCAL_SAVED |
| UMP odrzuca bez uzasadnienia | Błąd, wniosek nadal oczekuje |
| UMP odrzuca z uzasadnieniem, bez końca puli | REJECTED, brak puli, pismo odmowy i powiadomienie |
| Worker pozostaje uruchomiony przy drugiej decyzji | Odmowa przetworzona automatycznie do LOCAL_SAVED |
| Gniezno otwiera swój zaakceptowany wniosek | Pismo i jawna informacja o lokalnej wiadomości |
| UMP otwiera Integracje | Dwa powiadomienia, po jednej próbie, oba LOCAL_SAVED |

Kontrola bajtów: dla każdej decyzji dokładnie jeden MIME z właściwym Message-ID,
adresem autora, tematem i pełną treścią zapisanej wiadomości; bez załączników.
Kontrola SHA-256 czterech nowych PDF PASS. W tym etapie nie oceniano ponownie
układu PDF. Główna baza zachowała sześć hashy biznesowych; dane odbioru są osobne.

Dowody: `evidence/decision-notification-tests.txt`,
`evidence/decision-notification-postgres-tests.txt`,
`evidence/decision-notification-report.json`, prywatne screenshoty 58–61,
MIME `notice-00008.eml` i `notice-00009.eml` oraz dowód pustej daty w
`evidence/private/`. Screenshot 61 obejrzano wizualnie.

Rzeczywiste SMTP i odbiór e-maila, urzędowe e-Doręczenia, EZD, kwalifikowany
podpis, kategoria prawna III i pozostałe wymagania całego celu pozostają
niepotwierdzone lub wymagają dalszych prac: `STATUS.md` i `DECYZJE.md`.
