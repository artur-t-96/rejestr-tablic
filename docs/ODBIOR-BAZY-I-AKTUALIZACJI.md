# Odbiór kopii, współbieżności i aktualizacji

03.10.2026, rewizja aplikacji `dc3d6dfb15c3f27412850425d1f0bac3c016a8ec`.
Natywnie: macOS, CPython 3.12.14, Django 5.2.17, PostgreSQL 18.6 i SQLite.
Dane fikcyjne, bez Dockera i zewnętrznych transportów. To nie jest pełny odbiór systemu.

## Współbieżność i kopie PostgreSQL

18/18 PASS, bez pominięć, 3,788 s samych testów. Django utworzyło i usunęło
osobną bazę `test_drt_pg_local`. Przed uruchomieniem przeczytano scenariusze:

- dwie rezerwacje tego samego numeru przez różne urzędy i nakładające się pule;
- konkurujące zatwierdzenie/wycofanie oraz jedno wydanie numeru puli;
- wygaszanie z rzeczywiście oczekującym na blokadę wycofaniem i dwa procesy
  wygaszania, bez podwójnego audytu;
- blokady pism i równoczesna numeracja wniosków oraz wersji pisma;
- dwa procesy kolejki: jedno wywołanie symulowanego transportu;
- rzeczywiste pg_dump/pg_restore podpisanego PDF, dowodów, kolejki i liczników;
- równoległy zapis podczas snapshotu, odrzucenie uszkodzonej kopii, dokumentu,
  cofniętego licznika, niezgodnego manifestu i istniejącego celu.

Z ustawieniami prywatnego klastra z `POSTGRESQL-LOKALNIE.md` wykonano:

```sh
var/dependency-clean-20261003/bin/python manage.py test \
  registry.tests.ConcurrencyTests \
  registry.test_database_concurrency \
  registry.test_reservation_completion.ReservationExpiryConcurrencyTests \
  registry.test_numbering.NumberingConcurrencyTests.test_simultaneous_first_request_numbers_are_unique \
  registry.test_numbering.NumberingConcurrencyTests.test_simultaneous_letter_revisions_preserve_original_and_get_unique_numbers \
  registry.test_postgres_backup --noinput --verbosity=2
```

Podany interpreter jest lokalnym środowiskiem z locka; na innym komputerze
utwórz `.venv` zgodnie z README. Log: `evidence/final-postgres-tests.txt`.
Symulowany transport nie dowodzi działania rzeczywistych SMTP/EZD/e-Doręczeń.

## Rzeczywiste odtworzenie obu baz

Poza test runnerem wykonano `backup_registry` i `restore_registry` na istniejących
bazach. Prywatne archiwa 0600: `var/backups/final-sqlite-dc3d6df.zip` i
`var/backups/final-postgres-dc3d6df.zip`. Nie dodano danych ani sekretów do Git.

SQLite odtworzono do nowego `var/restores/final-sqlite-dc3d6df`. Porównano
każdy wiersz i kolumnę wszystkich tabel ze źródłem. Jedynymi zmianami były
udokumentowane unieważnienia sesji i kodów. Ta kopia nie miała oczekującej wysyłki.

PostgreSQL odtworzono do nowej bazy `drt_restore_final_dc3d6df`. Źródło
`drt_pg_local` miało starszy schemat registry 0005. Przed aktualizacją porównano
wiersze i kolumny wszystkich tabel. Sesja została usunięta, a jedno zadanie SMTP
wstrzymane w `REVIEW_REQUIRED`. Dokument, suma, identyfikatory i liczba prób
zostały zachowane. Nie uruchomiono wysyłki.

Sumy dokumentów, integralność SQLite i liczniki sprawdziły rzeczywiste polecenia.
Raport zawiera hashe tabel i manifesty, bez treści wierszy. Wszystkie 27 tabel
głównej SQLite i wszystkie 23 tabele źródłowej PostgreSQL pozostały identyczne
przed i po całej próbie, również po interakcjach Chrome na odtworzonej bazie.

## Aktualizacja odtworzonej PostgreSQL

Na nowej bazie wykonano `migrate --plan`, następnie `migrate --noinput`.
Pięć migracji 0006–0010 przeszło. Zmiany objęły nowe tabele, metadane Django,
ograniczenie okresu III i cztery niezmienione wzory systemowe. Zachowano wszystkie
dotychczasowe audyty; doszły dokładnie cztery zdarzenia aktualizacji wzorów.
Wnioski, ewidencja, pula, wydania, liczniki, kolejka oraz wszystkie oryginalne
i podpisane pisma pozostały takie same jak po odtworzeniu, przed migracjami.

Ponownie zweryfikowano kryptograficznie istniejący podpisany PDF: integralność,
podpis, skonfigurowane zaufanie DEMO, pełne pokrycie pliku i zachowanie oryginału.
To nie dowodzi kwalifikowanego podpisu lub znacznika czasu urzędu.

Logi: `evidence/final-postgres-upgrade-plan.txt`, `evidence/final-postgres-upgrade.txt`.
Ta baza nie miała starej puli III bez końcowej daty. Próba nie dowodzi migracji
dowolnego historycznego zbioru; warunek migracji 0009 wymaga wcześniejszego rozstrzygnięcia.

## Chrome i kolejka

Odtworzoną aplikację uruchomiono na 8778 z osobnymi nazwami ciasteczek.
Health wskazał PostgreSQL i rewizję dc3d6df. W Chrome wykonano nowe OTP UMP,
wejście do panelu, integracji i archiwum podpisu. Widoczny był status wymagający
sprawdzenia wyniku u operatora, z zerową liczbą prób. Jednorazowe
`process_integrations` nie przetworzyło wstrzymanego zadania; jego wiersz pozostał
identyczny po poleceniu i po Chrome.

Podpisany PDF pobrano przez widoczny link. SHA-256 pobranego pliku jest identyczny
z archiwum. Obejrzano zrzuty `evidence/126-final-restored-queue.png` i
`evidence/127-final-restored-signature.png`. Nie wykonano nowego podpisu ani
przekazania pisma. Osiem tabel biznesowych/kolejki zachowało hashe.
Nowe logowanie dotyczy wyłącznie odtworzonej instancji.

Serwer 8778 i prywatny PostgreSQL następnie zatrzymano. Kopie pozostały na dysku.
Główna SQLite na 8765 działa dalej. Raport: `evidence/final-backup-upgrade-proof.json`.

## Granice odbioru

Dowody nie obejmują pełnego aktualnego przebiegu trzech modułów w Chrome,
wszystkich endpointów, WCAG, kwalifikowanych podpisów, rzeczywistych API,
Linux/systemd/TLS, WAL/PITR, awarii zasilania, dużej bazy ani obciążenia.
Cały cel pozostaje aktywny.
