# Odbiór ról na wszystkich trasach

03.10.2026, kod aplikacji `3c53b4fed4ad2a67a8d6921cc388dd9ea806105d`.
Ten etap dodał testy i dowody; nie zmieniał kodu aplikacji ani schematu.
Zakres wynika z macierzy A1/A2/A3/A0 w specyfikacji i `config/urls.py`.

## Zakres i wynik

- Wszystkie **47 tras i 70 par trasa–dozwolona metoda** zostały objęte
  macierzą dla anonimowego użytkownika, A0, A3, A2 własnego urzędu
  i A2 obcego urzędu. Test przerywa się po dodaniu trasy/metody bez przypadku.
- 96 przypadków (w tym warianty nadawcy, modułu III, akcji API oraz
  niepasujących identyfikatorów) × 5 kontekstów = **480 scenariuszy ról**.
- Istniejące fikcyjne obiekty: szkic/złożony/zaakceptowany wniosek,
  przydzielony wpis, pule II/III, pisma w obu kierunkach, zaproszenie,
  lokalny testowy dowód i lokalny rekord dopasowanego wpływu EZD.
- 12/12 testów SQLite PASS w 3,463 s: macierz, obce listy/eksport/API
  i dziesięć regresji prezentacji audytu, w tym ukrycie wartości dla A0.
- Każdy przypadek testowy ma odrębną transakcję z rollbackiem. Odmowy
  nie zmieniają żadnego modelu rejestru poza wyłączonymi klasami technicznymi
  OTP, rate-limit i CAPTCHA. Logowanie testowe jest tu `force_login`;
  nie jest przedstawiane jako test rzeczywistego OTP.

Pozytywne dane sprawdzają między innymi utworzenie wniosku, złożenie,
wycofanie HTML/API, decyzję HTML/API, wydanie numeru z puli, przedłużenie,
korektę pojazdu przez PATCH oraz nową wersję pisma i zapis kolejki SMTP.
Formularze importu, administracji, podpisu i integracji mają także przypadki
dostępu do walidacji pustego formularza. **Dopuszczenie do walidacji nie
oznacza wykonania właściwej operacji**; jej wcześniejsze scenariusze pozytywne
opisują odpowiednie raporty funkcjonalne.

## Rzeczywisty HTTP i OTP

Na odrębnej kopii `var/route-roles-20261003`, serwer 8781, lokalna poczta
plikowa, oddzielne cookie sesji/CSRF. Każde z czterech kont przeszło
rzeczywiste OTP; sesję potwierdzono przez endpoint z kontekstem użytkownika.
Nie pomijano CSRF, przekierowania były odczytywane bez automatycznego śledzenia.

Wykonano **442 sprawdzenia HTTP**, w tym **276 odmów**. Każda odmowa zachowała
hash wszystkich 17 tabel rejestru porównywanych w tej kopii (poza tabelami
OTP/rate-limit/CAPTCHA). Obejmuje to dane, pisma, kolejki, konta, konfigurację
i audyt. Obcy powiat nie otrzymał obcych danych właścicieli ani spraw przez
listy, eksport i API. Publiczne API może wskazywać same wyróżniki i zajętość;
nie jest listą właścicieli.

38 dozwolonych zapisów HTTP **nie powtarzano** w tej serii: sprawdzono je
oddzielnie w macierzy testowej z rollbackiem lub ich wcześniejszych
scenariuszach funkcjonalnych. Raport wylicza każdy taki przypadek. Ta seria
HTTP sprawdza odczyty, odmowy i dostęp do walidacji; nie deklaruje 480
rzeczywistych operacji HTTP ani ponownego pełnego przebiegu Chrome.

## Potwierdzone granice dostępu

- A2: własne wnioski/wpisy/pule; obce obiekty 404, obce listy/eksport puste.
- A3: ewidencja województwa i decyzje; bez administracji kontami/urzędami.
- A0: administracja, diagnostyka i audyt bez wartości biznesowych;
  bez dostępu do kart danych/pism, przydziałów i decyzji.
- Pismo: odczyt nadawcy/adresata; podpis, wersja, wysyłka i zapis EZD
  wyłącznie urząd nadawcy. Sprawdzone oba kierunki pisma powiat↔UMP.
- Wpływ EZD: przypisany do urzędu; A3 nie czyta pliku wpływu powiatu
  przez cudzy identyfikator. Istniejąca pula III ma tę samą izolację co II.
- Dowód musi należeć do wskazanego pisma; znany ID dowodu innego pisma
  nadal daje 404. Zaproszenie musi należeć do wskazanego konta.
- API: anonimowy 401, A0 403, obce obiekty A2 404; decyzja i bezpośredni
  przydział pozostają wyłącznie A3. Sesja i jej przedłużanie obsługują
  poprawnie wszystkie role zalogowane z właściwym kontekstem konta.

## Dowody i ograniczenia

- `registry/test_route_roles.py`: przypadki i asercje pełności kontraktu.
- `evidence/route-role-tests.txt`: 12 testów z kompletnym wynikiem PASS.
- `evidence/route-role-matrix.json`: jawne oczekiwane statusy i zakresy.
- `evidence/route-role-http-proof.json`: 442 rzeczywiste odpowiedzi,
  276 porównań odmów i lista 38 niepowtarzanych zapisów.
- Prywatne skrypty, baza i lokalne wiadomości pozostają w `evidence/private/`
  i `var/`; nie commitowano OTP, sesji ani bazy.

Po próbie wszystkie 27 tabel głównej bazy zachowane. Ruff/format PASS.
Bez Dockera, migracji i nowego PostgreSQL. Dowód e-Doręczeń i rekord RPW są
**fikcyjnymi fixture'ami kontroli dostępu** — nie stanowią dowodów działania
operatorów. Nie uruchamiano workerów tej kopii ani zewnętrznego SMTP/API.

Nie jest to fuzzing wszystkich wartości wejściowych ani pomiar skali.
Warianty walidacji API opisują `API-KOREKTY.md` i `API-OPERACJE.md`;
metody niedozwolone `METODY-HTTP.md`; rzeczywiste procesy Chrome
`ODBIOR-TRZECH-MODULOW.md`. Publiczna dostępność i zewnętrzne integracje
zachowują swoje otwarte zakresy. Cały cel nadal aktywny.
