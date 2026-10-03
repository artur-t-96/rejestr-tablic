# Import historycznych pul II i III

Stan 03.10.2026. Dostęp: urzędnik UMP, **Pule numerów → Import historycznych pul**
lub **Import ewidencji → Import historycznych pul II i III**. Administrator
techniczny i urzędnik powiatowy nie mogą zatwierdzać historycznych przydziałów.

Import zapisuje fakty z wcześniejszej ewidencji. Nie podejmuje nowej decyzji,
nie tworzy wniosku, pisma PDF ani zadania wysyłki. Dane nie nadpisują istniejących
numerów, także niewydanych i należących do wygasłych pul. Kolizję trzeba wyjaśnić
przed przygotowaniem poprawionego pliku.

## Format

CSV UTF-8, opcjonalnie z BOM, separator średnik. Do 2 MB, 5000 numerów i 100 pul
w pojedynczym pliku. Obsługiwany jest także zwykły XLSX z tymi samymi
kolumnami. Nagłówki można pobrać z ekranu importu. Przygotowanie komórek,
wybór arkusza i daty Excela: [Import XLSX](IMPORT-XLSX.md). Starszy XLS
i pliki z makrami wymagają przygotowania zwykłego XLSX lub CSV.

| Kolumna | Znaczenie |
| --- | --- |
| `pool_ref` | Obowiązkowe oznaczenie grupy w tym pliku, do 100 znaków. |
| `kind` | II lub III. |
| `office_id` | Dokładny identyfikator istniejącego urzędu, np. `gni`. Akceptowane są też urzędy nieaktywne, bo wykaz może być historyczny. |
| `prefix` | II: P/M; roboczy profil III: P0–P9/M0–M9. |
| `number` | Jeden rzeczywiście przydzielony numer. Spacje usuwane, litery normalizowane do wielkich. |
| `valid_from` | Początek okresu, RRRR-MM-DD, nie późniejszy niż dzień importu. |
| `valid_until` | Koniec okresu; obowiązkowy dla III, nie wcześniejszy niż początek. |
| `station` | Opcjonalna stacja/przeznaczenie, do 180 znaków. |
| `issued_on` | Data historycznego wydania, tylko razem z numerem sprawy. Musi mieścić się w okresie puli i nie być przyszła. |
| `case_number` | Sprawa wydania, do 100 znaków; oba pola wydania puste oznaczają, że nie zapisano wydania. |
| `source_reference` | Obowiązkowe oznaczenie źródła przydziału, np. numer pisma lub zatwierdzonego wykazu, do 200 znaków. |

W każdym wierszu tej samej grupy powtórz identyczne metadane puli, urzędu,
okresu i źródła. Nie trzeba podawać technicznej pozycji: jest wyliczana z numeru
i sprawdzana przez wspólną walidację. Plik nie tworzy brakujących numerów między
pierwszą i ostatnią pozycją. Wykaz P031, P033 zapisuje dokładnie dwa numery;
P032 pozostaje poza tym wykazem. Widok szczegółów wyjaśnia tę różnicę.

Każda grupa pliku tworzy nową historyczną pulę z własnym UUID. Przy dzieleniu
większego wykazu na pliki trzeba oznaczyć części i zachować odniesienie do tego
samego dokumentu źródłowego. Nie jest to automatyczne dopisywanie do istniejącej
puli ani jej scalanie. Powtarzające się numery są odrzucane również między plikami.

## Zatwierdzanie

1. Zachowaj kopię zapasową bieżącej bazy i uzgodnij wykaz z dokumentami urzędu.
2. Wczytaj plik. Podgląd pokazuje podsumowanie każdej grupy, urząd, okres,
   źródło, liczbę numerów i wydanych oraz wszystkie numery na kolejnych stronach
   po 100. Nazwa pliku i SHA-256 identyfikują konkretne źródło.
3. Wyjaśnij każdy błąd. Jakikolwiek błąd blokuje zatwierdzenie całego pliku;
   poprawne wiersze nie są zapisywane częściowo.
4. Podaj uzasadnienie/podstawę importu i potwierdź zgodność wszystkich danych
   ze źródłami. Podgląd jest związany z kontem, sesją i wersją, ważny 15 minut.
   Nowy lub błędny podgląd unieważnia poprzedni; stara karta nie zatwierdzi
   innego pliku.
5. Zatwierdź cały wykaz. Serwer ponownie waliduje plik, sumę i bieżące kolizje.
   Wszystkie pule, numery i logi powstają w jednej transakcji. Równoczesne
   zajęcie numeru wycofuje cały import.

Źródłowy CSV/XLSX i dokumenty należy przechowywać w archiwum urzędu. Aplikacja
utrwala oznaczenie dokumentu, nazwę i sumę pliku, format, arkusz, metadane grupy oraz autora,
czas i podstawę importu w niezmiennym logu `pool.imported`. Nie archiwizuje
oryginalnych bajtów CSV/XLSX ani PDF źródłowego. Kopia bazy zawiera zapisane numery
i ten log; archiwum źródeł musi mieć własną kopię zapasową.

Data wydania jest zachowana z dokładnością do dnia. Techniczny czas w bazie
odpowiada północy w strefie urzędu; nie jest ustaloną godziną dawnej czynności.
`issued_by` pozostaje puste, bo plik nie ustala pierwotnego urzędnika. Autor
importu jest zapisany osobno i nie zostaje uznany za osobę wydającą tablicę.

## Związek z pojemnością i uprawnieniami

Import może wprowadzić dawne numery literowe lub M przy niepełnej historii P;
nie jest nowym przydziałem i nie wymaga tworzenia fikcyjnego bieżącego wniosku.
Nowe przydziały nadal przechodzą kontrole opisane w `docs/POJEMNOSCI-PUL.md`.
Liczy się faktycznie wprowadzony zbiór, więc import nie oznacza automatycznie
wyczerpania całej pojemności. Numerów historycznych nie usuwamy, aby odblokować
kolejny przydział.

Format III pozostaje roboczym profilem tymczasowym, wymagającym potwierdzenia
urzędu. Nieprawidłowe lub inaczej sklasyfikowane źródłowe numery trzeba wyjaśnić;
aplikacja ich nie poprawia ani nie zalicza do pojemności. Ten etap nie potwierdza
kompletności lub legalności rzeczywistej ewidencji UMP.

Powiat widzi własne historyczne pule i źródło ich przydziału. Inny powiat
otrzymuje 404. Poza okresem obowiązywania niewydany numer jest oznaczony jako
„Poza okresem puli”, bez przycisku wydania; serwer niezależnie blokuje wydanie.

## Weryfikacja wcześniejszego etapu CSV

Poniższe wyniki dotyczą wcześniejszego wdrożenia CSV. Bieżące rozszerzenie
XLSX i końcowe wyniki są opisane w [Import XLSX](IMPORT-XLSX.md).

- SQLite: **51 PASS / 1 SKIP PostgreSQL**, 52 testy, 2.115 s.
  `evidence/pool-import-tests.txt`. Import, podgląd, daty, dziury, historyczne
  M/litery, nowa decyzja po uzupełnieniu cyfrowej pojemności, konflikt po
  podglądzie, rollback po częściowym zapisie, hashe, limity, role, CSRF,
  stare/wygasłe podglądy, replay, paginacja i HTML oraz regresje pul/rdzenia.
- Native PostgreSQL: **26 PASS**, 1.636 s.
  `evidence/pool-import-postgres-tests.txt`. Oba importy skończyły podgląd
  przed zapisem; dwie odrębne transakcje i połączenia → jeden sukces, jedna
  kolizja, jedna pula, dwa numery, jeden audyt i zero pism. Także 11 testów
  pojemności oraz wcześniejszy wyścig dwóch wydań tego samego numeru.
- Zapis numerów w imporcie i nowym przydziale używa wspólnego porządku
  unikalnych kluczy, niezależnego od kolejności wierszy/grup CSV. Regresja
  przeszła po tej zmianie. Nie jest to test obciążeniowy ani dowód wszystkich
  możliwych przeplotów transakcji.
- Po dopracowaniu etykiet i wygasłego widoku: **10 PASS**, 0.347 s, cztery
  scenariusze importu HTTP i sześć regresji obsługi pul.
  `evidence/pool-import-ui-text-tests.txt`.
- Po zabezpieczeniu porównania wersji: **4 PASS**, 0.104 s.
  `evidence/pool-import-token-tests.txt`. Błędny token ASCII lub Unicode daje
  komunikat formularza bez zapisu i błędu 500; prawidłowe zatwierdzenie działa.
- Końcowa regresja całego importu po poprawce uszkodzonego nagłówka CSV:
  **13 PASS / 1 SKIP PostgreSQL**, 14 testów, 0.420 s.
  `evidence/pool-import-final-tests.txt`. Niepoprawny cudzysłów w nagłówku
  jest odrzucany w serwisie i formularzu bez zapisu, zamiast błędu serwera.
  Ruff, format, Django check i sprawdzenie braku nowych migracji przeszły.
- Chrome na osobnej kopii: OTP UMP, odrzucony wykaz z P001; podgląd poprawnego
  pliku bez zapisu w siedmiu tabelach biznesowych; jawne zatwierdzenie dwóch
  fikcyjnych pul/czterech numerów; OTP Gniezna, daty wydania i źródło, brak
  przycisku wydania wygasłej puli; odmowa wejścia do importu dla powiatu.
  Test HTTP osobno potwierdza 404 innego powiatu i odmowę administratora.
- P031 wydany 01.02.2025, P033 niewydany; P032 nie powstał. P60001 wydany
  01.03.2025, P60002 niewydany. Wszystkie oryginalne wiersze kopii zachowane,
  bez nowego pisma, wniosku, kolejki i numeracji kancelaryjnej.
- Rzeczywisty backup SQLite i odtworzenie do nowego katalogu: wszystkie
  wiersze sześciu tabel biznesowych oraz audytu identyczne, źródło i historyczne
  daty zachowane. Sesje unieważnione. Nie uruchamiano odtworzonej aplikacji.
- Główne sześć tabel biznesowych bez zmian. Dowody:
  `evidence/pool-import-ui-proof.json`; CSV i zrzuty 70–76 w
  `evidence/private/`. Końcowy widok powiatu sprawdzony wizualnie.

Bez migracji schematu i Dockera. Prywatny PostgreSQL zatrzymano po testach.
Repozytorium nie ma Git remote/hosted CI ani ścieżki produkcyjnego wdrożenia.
Pozostają rzeczywiste źródła urzędu, ich uzgodnienie i kompletność, odbiór
kategorii III, rzeczywiste API, pełna dostępność i końcowy odbiór systemu.
