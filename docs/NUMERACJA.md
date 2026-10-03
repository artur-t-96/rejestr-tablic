# Numery systemowe dokumentów

## Reguły

- Wnioski: `W/rok/kolejny-numer`, wspólny licznik roczny instancji. Przykład: `W/2026/00005`.
- Pisma: `DRT/kod-urzędu/rok/kolejny-numer`, osobny licznik roczny nadawcy. Przykład: `DRT/gni/2026/000001`.
- Wszystkie rodzaje pism nadawcy i nowe wersje korzystają z tego samego licznika. UUID pozostaje identyfikatorem technicznym i podstawą głębokich linków.
- Rok nowych numerów jest wyznaczany w strefie Europe/Warsaw podczas nadania numeru. Zmiana roku rozpoczyna nową serię. Szerokość 5/6 cyfr jest minimalna, nie ogranicza zakresu licznika.
- Znak sprawy wpisany przez urząd pozostaje osobnym polem i występuje w piśmie. Numer systemowy nie zastępuje JRWA, znaku sprawy EZD ani kancelaryjnej numeracji urzędu.

Liczniki są zapisane w bazie. Unikalny indeks chroni parę zakres–rok, a blokada wiersza chroni zwiększenie wartości. Indeksy dokumentów chronią również powtórzenie numeru porządkowego w danej serii. Licznik, dokument, rezerwacja i historia zapisują się w transakcji; błąd generowania PDF wycofuje całą operację. Wartość jest porównywana z najwyższym już zapisanym numerem, więc brak lub cofnięcie licznika nie powoduje ponownego użycia numeru obecnego w bazie.

Historycznych pism nie renumerujemy. Migracja 0005 utrwala dotychczasowe identyfikatory wniosków dokładnie według poprzedniej reguły UTC/PK i zaczyna nową serię powyżej istniejącego maksimum. Zachowuje numery pism, oryginalne i podpisane PDF, raporty, sprawy i powiązania. Nowa wersja pisma otrzymuje nowy numer oraz relację do poprzednika; nie zmienia wcześniejszej decyzji ani nie anuluje jej doręczenia.

## Kopia i odtworzenie

Backup obejmuje liczniki wraz z dokumentami. Sprawdza zgodność zapisanych numerów z ich metadanymi i odrzuca cofnięte liczniki. Po odtworzeniu sesje są unieważnione, a kolejka pozostaje wstrzymana do uzgodnienia.

Przed przełączeniem urzędu na odtworzoną bazę trzeba uzgodnić dokumenty i wysyłki powstałe po dacie kopii. Sam snapshot nie zawiera późniejszych zdarzeń i nie dowodzi, że jego licznik jest aktualny względem działającej wcześniej instancji. Nie uruchamiaj dwóch produkcyjnych instancji zapisujących do odrębnych kopii tego samego rejestru.

## Dowody

`registry/test_numbering.py` obejmuje 12 testów: pierwsze równoczesne zapisy, kolejne wersje, oddzielne urzędy, nowy rok i jego granicę UTC, rollback po błędzie PDF, utratę/cofnięcie licznika, ograniczenia bazy, migrację archiwum, backup i jego odmowę przy niespójności.

- 12/12 testów numeracji: `evidence/numbering-focused-tests.txt`.
- 91/91 testów całej aplikacji: `evidence/numbering-and-core-tests.txt`.
- Porównanie działającej bazy przed i po migracji: `evidence/numbering-migration-proof.json` — zachowano 9 dokumentów i 4 identyfikatory wniosków.
- Chrome: wniosek powiatu, złożenie, decyzja UMP, podpis demonstracyjny i nowa wersja. Dowody: `evidence/08-numeracja-wniosek.jpg`, `evidence/09-numeracja-nowa-wersja.jpg`, `evidence/numbering-ui-proof.json`.
- Trzy PDF sprawdzone po renderowaniu wszystkich stron: wniosek, podpisana odpowiedź i nowa wersja. Przykład: `evidence/numeracja-decyzja.pdf`. Pisma są wzorami na fikcyjnych danych, wymagającymi zatwierdzenia przez urząd.
- Rzeczywisty snapshot i odtworzenie do osobnego katalogu; kontynuacja wyłącznie w tej kopii dała `W/2026/00006` i `DRT/gni/2026/000002`. Dowód: `evidence/numbering-backup-proof.json`.

Testy współbieżności wykonano na plikowej SQLite z transakcjami IMMEDIATE, a następnie na osobnej bazie PostgreSQL 18.6. PostgreSQL przeszedł test czterech równoczesnych pierwszych numerów wniosków oraz dwóch równoczesnych wersji pisma. Dowody: `docs/POSTGRESQL-LOKALNIE.md`, `evidence/postgres-tests.txt`. Nie wykonano testu na infrastrukturze urzędu. Według [dokumentacji Django](https://docs.djangoproject.com/en/5.2/ref/models/querysets/#select-for-update) SQLite nie wykonuje blokady `SELECT FOR UPDATE`; lokalna serializacja opiera się na transakcji zapisu.
