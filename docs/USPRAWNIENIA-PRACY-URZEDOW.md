# Usprawnienia pracy urzędów — 03.10.2026

Zmiany po przeglądzie funkcji względem `Specyfikacja_flow_tablice.html` i demo.
Dane w próbach są fikcyjne. Integracje EZD RP, e-Doręczeń i podpis kwalifikowany
pozostają bez zmian i bez potwierdzenia u operatora.

## Decyzja UMP

- **Weryfikacja numeru przy wniosku I** (spec. 4.4): UMP widzi wynik kontroli
  formatu, potwierdzenie braku innego aktywnego wpisu, wcześniejsze wpisy tego
  samego numeru w całym województwie oraz ostrzeżenia o treści. Urząd wnioskujący
  tego panelu nie dostaje, bo historia obejmuje inne urzędy.
- **Słownik ostrzeżeń o treści**: administrator prowadzi listę ciągów liter
  (2–5 znaków). Wyróżnik zawierający ciąg, także zapisany cyframi podobnymi do
  liter (0→O, 1→I, 3→E, 4→A, 5→S, 7→T, 8→B), dostaje ostrzeżenie. Słownik niczego
  nie blokuje; ocena należy do UMP (§ 32 ust. 3). Po wdrożeniu jest pusty.
- **Podpowiedź zakresu puli**: przy decyzji II/III formularz proponuje pierwsze
  pozycje za ostatnim numerem danego prefiksu. Reguły kolejności pojemności i
  kontrola kolizji działają jak dotąd.
- **Kolejka decyzji**: lista wniosków ma filtr modułu i urzędu; przy statusie
  „Oczekuje na decyzję" sortuje od najdłużej czekających i pokazuje czas
  oczekiwania oraz termin rezerwacji. Pulpit UMP zaczyna od tej kolejki.
- **Korekta nie zastępuje decyzji**: status wpisu z otwartym wnioskiem zmienia
  tylko decyzja albo wycofanie. Wcześniej ręczna zmiana na „Przydzielony"
  zostawiała wniosek bez rozstrzygnięcia i pisma. Wpisu zwolnionego odmową,
  wycofaniem lub wygaśnięciem nie da się przywrócić korektą; przywrócenie
  zwolnionego przydziału działa jak dotąd.

## Rezerwacje

- **Przypomnienie** na 3 dni przed terminem (`RESERVATION_REMINDER_DAYS`): do
  autora wniosku, a gdy wniosek czeka na decyzję — także na adres kontaktowy
  UMP. Jedno przypomnienie na termin; przedłużenie pozwala na kolejne.
  Wiadomość nie zawiera danych właściciela ani pojazdu. Wysyła je proces
  `expire_reservations --watch`, więc nie dochodzi nowy proces.
- **Przywrócenie wygasłego wniosku**: UMP, z powodem i terminem 1–90 dni, dopóki
  numeru nie zajął inny wniosek (pilnuje tego indeks `unique_active_plate`).
  Wniosek wraca do stanu sprzed wygaśnięcia. Zasada wygasania po 14 dniach się
  nie zmienia.

## Pisma i powiadomienia

- **Wysyłka pocztą**: urząd nadawcy odnotowuje przy piśmie datę i opcjonalny
  numer nadania. To oświadczenie urzędu, nie dowód doręczenia.
- **Powiadomienie autora o decyzji** obejmuje moduły I, II i III.
- **Ponowienie e-maila**: operacja w stanie „Wymaga sprawdzenia wyniku",
  „Wyczerpano próby", „Błąd konfiguracji" albo „Odrzucono operację" wraca do
  kolejki po świadomym ponownym „Wyślij" (pisma) lub „Ponów powiadomienie"
  (decyzja). Kolejka nadal nie ponawia sama. Jeśli pierwsza próba dotarła,
  adresat dostanie wiadomość drugi raz. Ekran pokazuje faktyczny stan operacji
  zamiast komunikatu o dodaniu do kolejki.

## Pule

- Lista ma filtr modułu i urzędu.
- Od 05.10.2026 wykorzystania puli nie śledzimy (licznik, próg 80%, alert e-mail
  i cofanie wydań usunięto) — zob. `UWAGI-UMP-20261005.md`.

## Przegląd województwa i eksporty

- Strona **Urzędy** (tylko UMP): dla każdego urzędu liczba aktywnych tablic,
  wniosków do decyzji, pojazdów zbytych i wykorzystanie pul II/III, z
  przejściem do odfiltrowanych list.
- Pulpit UMP liczy pojazdy zbyte, bo sprzedaż nie zwalnia numeru (`DECYZJE.md`).
- `/panel/eksport/?co=wnioski|pule|urzedy` obok dotychczasowej ewidencji.
  Eksport wniosków i pul respektuje filtry i zakres urzędu; zestawienie urzędów
  jest tylko dla UMP. Wnioski i pule nie zawierają danych właściciela.

## Konta i logowanie

- Żądanie kodu z innego urządzenia nie unieważnia już kodu zamówionego przez
  właściciela adresu i nie blokuje go limitem. Limit 5 żądań na 15 minut liczy
  się dla pary adres + IP (dla IPv6: sieć /64); łączny limit adresu to 30 na
  15 minut i ogranicza zalewanie skrzynki. Udane logowanie unieważnia pozostałe
  kody konta.
- Kod ma osiem cyfr. Równolegle może istnieć kilka ważnych kodów konta (każdy
  w innej sesji), więc dłuższy kod utrzymuje szansę zgadnięcia poniżej dawnego
  poziomu: najwyżej 150 prób na 15 minut przy 10^8 możliwości.
- Pozostaje: klient z wieloma adresami może wyczerpać łączny limit adresu i na
  15 minut zablokować zamawianie kodów dla tego konta, a administrator nadal
  może założyć konto merytoryczne na adres, który kontroluje. Oba przypadki
  zostawiają ślad w audycie; zamknięcie drugiego wymaga zasady dwóch osób.
- Administrator nie zmienia własnego adresu, roli, urzędu ani aktywności;
  robi to inny administrator.

## Świadomie poza zakresem

- **Pula jako lista numerów z lukami** (spec. 5): sprzeczna z regułą kolejności
  pojemności (`KOLEJNOSC-PUL-II.md`); listy wprowadza import historyczny.
- **Zwrot lub skrócenie puli**: brak reguły urzędu dla numerów niewydanych po
  okresie puli.
- **Zakładanie kont przez UMP**: w specyfikacji „do ustalenia"; zmienia granicę
  uprawnień, więc czeka na decyzję urzędu.

## Weryfikacja

- 518 testów SQLite (29 pominiętych przypadków PostgreSQL), w tym 40 nowych w
  `registry/test_workflow_improvements.py`; PostgreSQL sprawdza hosted CI.
- Poprawiono dwa testy migracji, które zostawiały bazę w starszym schemacie albo
  czytały starszy schemat aktualnym modelem.
- Lokalnie w przeglądarce (dane pokazowe, OTP z lokalnej skrzynki): odnotowanie
  wysyłki pocztą, wydanie i cofnięcie numeru z puli, pulpit i kolejka UMP,
  panel weryfikacji z ostrzeżeniem i wcześniejszym wpisem, strona Urzędy,
  polskie opisy nowych zdarzeń w dzienniku audytowym.
- Migracja `0011_workflow_improvements` dodaje tabelę słownika i pięć
  opcjonalnych kolumn; nie zmienia istniejących danych.
