# Odbiór trzech głównych procesów w Chrome

03.10.2026, kod aplikacji `4321275c2374d53045e00b8935a29d4fb086467d`.
Odrębna kopia SQLite `var/final-processes-20261003`, adres testowy
`http://127.0.0.1:8779/`, Chrome użytkownika, rzeczywiste logowanie OTP i CSRF.
Wszystkie nowe dane są fikcyjne. Główna aplikacja pozostaje na porcie 8765.
Kod aplikacji jest identyczny z bazą `dc3d6df` odebraną w raporcie baz.

## Przebiegi wykonane przez interfejs

| Moduł | Czynności | Potwierdzony wynik |
|---|---|---|
| I | Publiczne sprawdzenie META/8 → wniosek Gniezna → złożenie → akceptacja UMP → pobranie pisma → pojazd i wydanie → zbycie → korekta UMP → zwolnienie UMP | W/2026/00006; P8META; siedem zdarzeń historii, końcowy RELEASED, wersja 7 |
| II | Wniosek o pięć numerów → złożenie → próba kolidującego zakresu → poprawny przydział → cztery wydania przez Gniezno → panel alertów | W/2026/00007; P031–P035; 4/5, alert 80% i odsyłacz do tej puli |
| III | Wniosek o dwa numery i stację → złożenie → przydział UMP z okresem → lokalne powiadomienie → wydanie numeru przez Gniezno | W/2026/00008; P30001–P30002; 1/2, stacja, okres 03.10–31.12.2026 |

Po utworzeniu I karta pokazuje termin 17.10.2026 09:06 dla utworzenia
03.10.2026 09:06, czyli 14 dni. Dowód ekranowy: `evidence/128-final-individual-submitted.png`.
Po zbyciu publiczny wynik wskazywał niedostępność, bez właściciela, VIN
i nabywcy. Korekta UMP zmieniła właściciela i notatkę z uzasadnieniem;
historia pokazała wartości przed i po, zachowując SOLD. Dopiero kolejne
zwolnienie przez UMP z uzasadnieniem dało publiczny wynik „Dostępny”.
Pojazd i zbycie pozostały w ewidencji i historii.

## Próby niedozwolone

- Kolidująca decyzja II dla P001–P005 pokazała błąd i zachowała SENT.
  Porównanie przed/po potwierdziło niezmienność ośmiu tabel: wnioski,
  wpisy, pisma, pule, numery pul, sekwencje, kolejka i audyt.
- Piła po własnym OTP zobaczyła pusty panel. Próby otwarcia trzech
  nowych wniosków Gniezna, jego wpisu oraz obu pul dały sześć HTTP 404.
- Administrator bez urzędu po własnym OTP został skierowany do administracji;
  te same sześć adresów biznesowych dało HTTP 403.
- Każda seria sześciu odmów zachowała powyższe osiem tabel. Stan UI
  oraz kody odpowiedzi potwierdzono w logu natywnego serwera.

To odbiór tych dwunastu GET i kolizji decyzji. Nie zastępuje macierzy
wszystkich endpointów, metod, działań administracyjnych i wariantów API.

## Pisma i lokalna poczta

Sześć nowych archiwalnych PDF, po dwie sztuki na moduł:

| Wniosek | Pismo wniosku | Pismo odpowiedzi |
|---|---|---|
| W/2026/00006 | DRT/gni/2026/000002 | DRT/ump/2026/000003 |
| W/2026/00007 | DRT/gni/2026/000003 | DRT/ump/2026/000004 |
| W/2026/00008 | DRT/gni/2026/000004 | DRT/ump/2026/000005 |

Każdy PDF ma prawidłowy SHA-256 archiwum, numer pisma i powiązanie W/2026/…;
wnioski i indywidualna zgoda zawierają też znak sprawy ODBIOR/2026/….
Informacje o puli wskazują zakres, okres oraz stację. QR wszystkich sześciu
odczytano z renderów: prowadzą do odpowiadających im wniosków na adresie
próby 8779. Po zatrzymaniu serwera ten adres próby nie pozostaje usługą.

Poppler wyrenderował sześć stron, wszystkie obejrzano. Tekst mieści się
w sprawdzonych granicach; brak widocznych ucięć, nakładania i uszkodzonych
polskich znaków. Dwa pliki pobrane w Chrome (wniosek i zgoda I) są identyczne
bajtowo z archiwum, także po późniejszej korekcie i zwolnieniu wpisu.
W tym etapie nie wykonywano fizycznego wydruku, nowego podpisu ani PDF/UA.

Powiadomienie autora decyzji III przeszło raz przez natywne polecenie
`process_integrations --provider SMTP --operation DECISION_NOTICE`.
Ma LOCAL_SAVED, jedną próbę i `delivery_confirmed=false`. Rzeczywisty lokalny
plik MIME jest skierowany do `gniezno@example.invalid`, zawiera numer
wniosku, wynik decyzji i właściwy link; brak załączników odpowiada
powiadomieniu informacyjnemu. Chrome pokazał zapis lokalny bez wysyłki
do adresata. Nie jest to potwierdzenie SMTP zewnętrznego ani doręczenie pisma.

## Dowody i zachowanie danych

- Zbiorczy dowód: `evidence/final-three-module-proof.json`.
- Obejrzane zrzuty Chrome: `evidence/128-*.png` do `134-*.png`.
- Prywatnie, bez commitowania OTP i bazy: obserwacje Chrome, log serwera,
  porównania tabel przed/po, skrypty odczytowej kontroli, PDF i ich rendery
  w `evidence/private/`; baza i poczta w `var/final-processes-20261003`.
- Po przebiegach wszystkie 27 tabel głównej SQLite miały dokładnie te same
  liczby wierszy i hashe danych jak przed próbą. Oba źródłowe HTML zachowane.
- Nie było migracji, Dockera, wywołań operatorów EZD/e-Doręczeń ani
  rzeczywistego SMTP. Ten etap nie uruchamiał ponownie PostgreSQL;
  jego odbiór opisuje `ODBIOR-BAZY-I-AKTUALIZACJI.md`.

Cel pozostaje aktywny. Do domknięcia lokalnego odbioru pozostają pełna
macierz tras/metod/ról i pozostałe kroki publicznej dostępności. Zakres
testów operatorów, urzędowego certyfikatu i docelowej infrastruktury jest
nadal oddzielnie niepotwierdzony, z opisem wymaganych dostępów w dokumentacji.
