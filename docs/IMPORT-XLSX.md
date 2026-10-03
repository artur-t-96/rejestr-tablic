# Bezpośredni import XLSX — 03.10.2026

UMP może wczytać zwykły plik XLSX bez wcześniejszego eksportu do CSV.
Dotyczy historycznej ewidencji indywidualnej i wykazów pul II/III. Obowiązują
te same kolumny, reguły danych, uprawnienia i atomowe zatwierdzanie opisane
w [imporcie ewidencji](IMPORT-EWIDENCJI.md) oraz [imporcie pul](IMPORT-PUL.md).
Import nie tworzy nowej decyzji, pisma, numeracji kancelaryjnej ani wysyłki.

## Przygotowanie arkusza

1. Pobierz nagłówki CSV z właściwego ekranu importu i użyj tych nazw jako
   pierwszego wiersza arkusza. Kolumny mogą występować w innej kolejności.
   Zachowaj obowiązkowe nagłówki; nie dodawaj kolumn spoza wzoru.
2. Jeden wiersz oznacza jeden wpis indywidualny lub jeden numer puli.
   Nie dodawaj tytułów, sum, pustych wierszy wewnątrz danych ani komentarzy
   jako dodatkowych wierszy. Usuń formatowanie daleko poza wykazem, jeśli
   powoduje przekroczenie dozwolonych wierszy lub kolumn.
3. Numery, identyfikatory urzędów, oznaczenia pism/spraw i inne teksty zapisz
   jako **tekst**. Liczbowa komórka z formatem wyświetlania `00000` nie jest
   tekstem; import ją odrzuci. Nie odtwarzamy zer utraconych wcześniej przez
   arkusz. Porównaj oznaczenia z dokumentami źródłowymi.
4. Daty zapisz jako daty Excela bez godziny albo tekst `RRRR-MM-DD`.
   Obsługiwane są kalendarze arkusza 1900 i 1904; nieistniejąca data
   1900-02-29 i daty z godziną są odrzucane. Reguły przyszłych dat, chronologii
   i okresów pul obowiązują również dla XLSX.
5. Formuły zastąp zweryfikowanymi wartościami. Nie odczytujemy ich ostatniego
   wyniku ani nie wykonujemy obliczeń. Tekst zaczynający się od `=` pozostaje
   tekstem, jeśli komórka źródła rzeczywiście ma typ tekstowy.
6. Rozłącz scalone komórki i pokaż ukryte wiersze/kolumny wybranego arkusza.
   Usuń makra, osadzone obiekty, połączenia zewnętrzne i zewnętrzne odsyłacze,
   w tym hiperłącza. Zostaw potrzebny tekst lub adres jako zwykły tekst.
   Zaszyfrowany XLSX, starszy XLS i XLSM wymagają przygotowania zwykłego XLSX
   lub CSV; zmiana samego rozszerzenia nie konwertuje pliku.

Przy jednym arkuszu pole nazwy może być puste. Przy kilku wpisz dokładną
nazwę widocznego arkusza. Aplikacja importuje **tylko ten arkusz**: nie scala
automatycznie pozostałych i nie wybiera pierwszego bez potwierdzenia.
Podgląd pokazuje wybrany arkusz, format, nazwę pliku i jego SHA-256.

Limity: 2 MB pliku, 500 wpisów indywidualnych albo 5000 numerów i 100 pul.
Pakiet XLSX może zawierać do 256 części, 16 MB danych po rozpakowaniu i 8 MB
w jednej części. Wybrany arkusz ma najwyżej 13 kolumn modułu I albo 11 kolumn
pul. Wewnętrzna reprezentacja CSV także musi mieścić się w 2 MB. Puste,
ukryte, dodatkowo sformatowane komórki mogą wymagać uporządkowania źródła.

## Podgląd, pochodzenie i archiwum

Podgląd i jego błędy nie zapisują ewidencji ani audytu biznesowego. Oryginalne
bajty pliku są przechowywane w sesji serwera na czas podglądu; ważność
zatwierdzenia wynosi 15 minut. Po zatwierdzeniu podgląd jest usuwany z sesji.
Upływ ważności blokuje zapis; pozostałości sesji podlegają jej retencji.
Nie jest to trwałe archiwum źródłowego XLSX.

Zatwierdzenie wymaga uzasadnienia i potwierdzenia zgodności całego wykazu.
Serwer ponownie odczytuje ten sam plik i arkusz, kontroluje sumę oraz aktualne
kolizje. Błąd blokuje lub wycofuje cały import. Starsze podglądy sprzed
aktualizacji należy wczytać ponownie.

Audyt i karta wpisu/puli zawierają SHA-256 **oryginalnego pliku XLSX**, format,
wybrany arkusz, nazwę, autora, czas i podstawę importu. Techniczny audyt
zawiera też osobną sumę znormalizowanej reprezentacji CSV; nie zastępuje ona
sumy źródła. Daty historyczne nie są datami wykonania importu.

W module I drugi import tych samych bajtów i tego samego arkusza jest
odrzucany, także dla zwolnionej historii. Inny arkusz tego skoroszytu może
być importowany osobno po sprawdzeniu. Zmieniony lub ponownie zapisany XLSX
może mieć inną sumę mimo podobnej treści: kontrola SHA-256 nie rozpoznaje
wszystkich semantycznych duplikatów. W pulach powtórzone numery blokuje
ewidencja numerów niezależnie od nazwy pliku i arkusza.

Oryginalny plik i dokumenty źródłowe zachowaj w archiwum urzędu z własną
kopią zapasową. Backup aplikacji zawiera zapisane dane i audyt pochodzenia,
lecz nie zastępuje archiwum tych oryginałów. Eksport CSV nadal zabezpiecza
teksty mogące uruchomić formułę prefiksem apostrofu; nie usuwamy go
automatycznie podczas ponownego importu.

## Odczyt i zależności

Używamy openpyxl 3.1.5 w trybie odczytu, z jawnym zamknięciem skoroszytu
i ponownym ustaleniem wymiarów danych. Dokumentacja opisuje zależność trybu
odczytu od poprawnie zapisanych wymiarów i ich resetowanie:
[openpyxl — optimized modes](https://openpyxl.readthedocs.io/en/stable/optimized.html).
Przed odczytem kontrolujemy części ZIP, XML, współrzędne i niedozwolone
elementy. XML parsuje defusedxml 0.7.1 z odrzuceniem DTD i encji zewnętrznych;
autorzy openpyxl wskazują potrzebę tej ochrony:
[openpyxl — security](https://openpyxl.readthedocs.io/en/stable/).

Locki runtime/QA zawierają dokładne wersje i hashe; dodano openpyxl,
defusedxml oraz et-xmlfile 2.0.0. Instalacja wheel i `pip check` przeszły
w środowisku CPython 3.12.14/macOS ARM64. Spisy 36 paczek dla macOS i Linux
x86-64/ARM64 oraz 56 notices są w `third_party/*-excel-20261003.json`.
To nie jest wykonanie aplikacji na Linuxie ani pełny audyt podatności.

## Dowody i granice

- Końcowe testy SQLite: **42 PASS / 3 SKIP PostgreSQL**, 45 testów, 0.798 s.
  PostgreSQL: **45 PASS**, 1.213 s. Pliki
  `evidence/excel-import-tests-final-sqlite.txt` i
  `evidence/excel-import-tests-final-postgres.txt`.
- Zakres: dane/datowanie 1900 i 1904, zera w tekście, 13 pól, jawny wybór
  arkusza, sumy oryginalnych bajtów, duplikaty, formuły z zachowanym wynikiem,
  encje XML, ukryte/scalone komórki, odsyłacze, limity, błędne współrzędne,
  kolizje i rollback, role/CSRF, stara karta, uszkodzony zapis sesji,
  długie nazwy plików oraz import III przez formularz HTTP.
- PostgreSQL obejmuje także trzy wcześniejsze rzeczywiste wyścigi importów
  CSV: aktywna ewidencja, ta sama zwolniona historia i kolidujące pule.
  Nowy dekoder XLSX sprawdzono na PostgreSQL; nie wykonano osobnego wyścigu
  dwóch binarnych XLSX ani testu obciążenia.
- Chrome, osobna kopia SQLite: wieloarkuszowy plik wymaga nazwy; arkusz
  Ewidencja zapisuje dwa fikcyjne wpisy, arkusz Archiwum pozostaje bez zapisu.
  Wszystkie 13 pól porównano ze źródłem. Daty i `00008` zachowane.
- Chrome, pula II: pojedynczy arkusz zapisuje tylko P700/P703, bez P701/P702;
  wydanie 01.02.2025 i sprawa `00011` zachowane. Pula wygasła, brak wydania
  pozostałego numeru. Karty wpisu i puli sprawdzono wizualnie.
- Rzeczywisty backup/restore do nowego katalogu: siedem tabel biznesowych
  i audyt identyczne, źródła i daty zachowane, sesje/OTP unieważnione.
  Odtworzonej aplikacji nie uruchamiano. Wszystkie wcześniejsze wpisy kopii
  zachowane; brak nowych wniosków, pism, kolejki lub numeracji.
- Siedem tabel głównej bazy pozostało bez zmian. Maszynowy raport:
  `evidence/excel-import-ui-proof.json`; zrzuty 93–96 w `evidence/private/`.
  Początkowe nieudane testy zachowano: poprawiono obsługę uszkodzonej sesji
  oraz testową strefę daty i niekompletny syntetyczny styl daty. Wynikiem
  końcowym są raporty `final`, nie te wcześniejsze przebiegi.

Bez migracji schematu, lokalnego Dockera i korespondencji zewnętrznej.
Repozytorium nie ma remote, hosted CI ani skonfigurowanego wdrożenia
produkcyjnego. Rzeczywista ewidencja urzędu i kompletność jej migracji,
kategoria III, pełna dostępność, API operatorów, infrastruktura urzędu
i końcowy odbiór całego systemu nadal wymagają pracy. Cel pozostaje aktywny.
