# Odbiór pul II i III — 03.10.2026

Status całego celu: **W TOKU**. Weryfikacja technicznego przebiegu w Chrome
nie potwierdza kategorii prawnej ani numeracji modułu III.

## Środowisko

Osobna baza SQLite `var/business-ui-20261003`, Chrome użytkownika,
`http://localhost:8774/`, 35 urzędów, fikcyjne konta i dane. Sesje/CSRF mają
osobne nazwy ciasteczek. Backend poczty plikowy, brak transmisji do operatorów.
Bez Dockera. Główne sześć tabel biznesowych zachowane z tymi samymi hashami.

## Chrome i kontrola bazy

| Scenariusz | Potwierdzony wynik |
| --- | --- |
| Gniezno wnioskuje o pięć numerów II | W/2026/00007, szkic → oczekujący, rzeczywisty PDF |
| UMP próbuje przydzielić zajęte P001–P005 | Błąd kolizji, wniosek nadal oczekujący, brak przydziału |
| UMP wskazuje P031–P035 | Akceptacja, pula pięciu numerów, pismo zwrotne |
| Gniezno wydaje P031–P034 | Cztery oznaczone numery, sprawy i autor w bazie |
| Gniezno otwiera przegląd | Alert wykorzystania 80% z linkiem do właściwej puli |
| Gniezno wnioskuje o pięć numerów III | W/2026/00006, stacja i uzasadnienie, PDF |
| UMP wskazuje tylko cztery numery | Błąd liczby, wniosek nadal oczekujący |
| UMP przydziela P20001–P20005 | Akceptacja, stacja zachowana, okres 03.10–31.12.2026 |
| Gniezno wydaje P20001 | Numer i sprawa zapisane, wykorzystanie 1/5 |
| Piła otwiera oba bezpośrednie linki | HTTP 404, bez danych pul Gniezna |
| Piła otwiera formularz przydziału | Polski HTTP 403; powiat nie przydziela pul |
| UMP tworzy P036–P536 po poprawce | Data początkowa widoczna i zapisana bez ponownego wpisywania |
| UMP klika ostatnią stronę puli 501 numerów | Dostępny 501. numer P536, strona 6/6 |
| UMP wydaje P536 | Numer wydany, sprawa zapisana, strona 6 zachowana |

W bazie potwierdzono autorów, sześć wydań, liczby i procenty, powiązania
wniosek–pula–pisma oraz okres i stację III. Cztery PDF-y nowych wniosków
i przydziałów: hash zgodny z bazą, referencja i zakres w tekście. Nie wykonano
w tym etapie odrębnej wizualnej kontroli tych czterech dokumentów.

Dowody: `evidence/pool-browser-report.json`, prywatny wyciąg audytu oraz
screenshoty 53–57 w `evidence/private/`. Dane odbioru nie trafiły do głównej bazy.

## Zmiany i testy

Commit `0b6c384`:

- Format ISO w czterech natywnych polach dat PoolForm/DecisionForm. Wcześniej
  wartość początkowa `03.10.2026` była odrzucana przez pole `type=date` Chrome.
- Stronicowanie po 100 numerów, liczba wszystkich pozycji, pierwsza/poprzednia/
  następna/ostatnia strona i zachowanie strony po POST, także przy błędzie.
  Wcześniej widok ucinał pulę na 500 pozycjach bez dostępu do dalszych numerów.

34 PASS w `evidence/pool-browser-tests.txt`: sześć nowych testów, rdzeń
i dostępność formularzy. Nowe testy obejmują 501. numer, wydanie/duplikat,
zachowanie strony po błędzie, obcy urząd GET/POST, błędne parametry strony,
daty ISO przy języku polskim oraz odmowę wydania przed datą obowiązywania.
Ruff i diff PASS; testy host-native. Bez ponowienia PostgreSQL w tym etapie.
Nowa paginacja i data sprawdzone po restarcie prywatnego serwera w Chrome.

## Nadal otwarte

- Powiadomienie i skończony termin uzupełniono w kolejnym etapie:
  `POWIADOMIENIA-DECYZJI.md`. Powiadomienia lokalne nie potwierdzają SMTP
  urzędu; rzeczywisty transport i wznowienia wymagają dalszego odbioru.
- Kategoria prawna III i reguły numeracji pozostają robocze: DECYZJE.md.
- Ręczny odbiór pozostałych gałęzi odmowy, końca ważności, niedozwolonych
  operacji, administracji oraz importu/eksportu.
- Rzeczywiste API, podpisy kwalifikowane, pełne WCAG i odbiór infrastruktury
  urzędu. Stan zależności i dalszy zakres pozostają w STATUS.md.

Ten etap nie jest potwierdzeniem gotowości wszystkich funkcji modułów II/III
do eksploatacji urzędowej ani zamknięciem całego celu.
