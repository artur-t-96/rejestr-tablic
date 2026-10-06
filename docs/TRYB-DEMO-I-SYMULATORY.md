# Tryb demonstracyjny i symulatory integracji — 04.10.2026

Odpowiedź na uwagi recenzenta: nie dało się sprawdzić pracy urzędnika powiatu i UMP bez konta,
a EZD RP i e-Doręczenia były wyłączone, bo wymagają kluczy wydawanych urzędowi.
Dane w trybie demo są fikcyjne. Nic tutaj nie jest potwierdzeniem działania prawdziwego operatora.

## Włączenie

- Zmienna `DYNA_DEMO`. Lokalnie dowolna niepusta wartość (`DYNA_DEMO=1`). W profilu Render musi
  być równa domenie z `APP_URL` — flaga skopiowana na inną usługę nie włączy wejścia bez kodu e-mail.
- Profil urzędowy (`config/onprem.py`) odmawia startu z tą flagą.
- `deploy/render_start.py` po migracji uruchamia `manage.py prepare_demo` (idempotentne). Błąd
  przygotowania jest zgłaszany w logu i nie zatrzymuje usługi.
- Profil Render odmawia startu, gdy razem z flagą ustawiono `EZDRP_CONFIG_FILE`, `EDOR_CONFIG_FILE`
  albo `SIGNING_CONFIG_FILE`: konta demo nie mogą wysyłać przez prawdziwego operatora.
- Bez flagi: trasy demo zwracają 404, konta demo nie mają dostępu, profile symulatorów są odrzucane.

## Wejście demonstracyjne

`/logowanie/demo/` (link na stronie logowania):

1. Wspólny kod dostępu. Generuje się przy pierwszym przygotowaniu; rzeczywisty administrator widzi go
   w panelu „Urzędy, konta i szablony" i może wymienić („Wygeneruj nowy kod"). Limit 10 prób na
   15 minut z jednego adresu. Kod nie jest zmienną środowiskową i nie trafia do repozytorium.
   Zmiana kodu od razu kończy odblokowane i zalogowane sesje demo.
2. Wybór roli jednym kliknięciem: urzędnik powiatu (Gniezno), urzędnik powiatu (Piła), urzędnik UMP,
   administrator. Zalogowane konto demo zmienia rolę z banera bez ponownego kodu.

Konta demo mają adresy `@demo.invalid`, nie dostają kodów e-mail i nie przechodzą zwykłego logowania.
Konta rzeczywiste logują się kodem e-mail jak dotąd.

## Co widzi i może konto demo

- Urzędnik powiatu i UMP: pełna praca w swojej roli na danych instancji.
- Administrator demo: zakłada, edytuje i usuwa wyłącznie dodatkowe konta `@demo.invalid`. Cztery konta
  wejściowe są stałe. Urzędy, szablony pism i słownik ostrzeżeń są dla niego tylko do odczytu, bo są
  wspólne z kontami rzeczywistymi. Nie widzi kodu dostępu.
- Każde konto demo zamiast imienia, nazwiska i adresu konta rzeczywistego (także zamkniętego
  i autora importu) widzi „Konto urzędowe"; nie widzi adresów IP ani identyfikatorów kont w historii;
  dziennik audytowy pokazuje mu tylko zdarzenia kont demo i systemowe niedotyczące kont.
- „Skrzynka demo": cała korespondencja obiegu (powiadomienie o rozpatrzeniu wniosku, przypomnienie, informacja o przeniesieniu wpisu,
  pismo wysłane e-mailem) zostaje w aplikacji i nie wychodzi prawdziwą pocztą — także na rzeczywisty
  adres kontaktowy urzędu, bo jej treść mogą wpisać konta demo. Skrzynkę widzi każde zalogowane konto
  (swoje wiadomości i urzędu). Prawdziwą pocztą idą tylko kody logowania i zaproszenia do kont
  rzeczywistych.
- Limity kont demo: 200 nowych wniosków i 300 wiadomości symulatora na dobę; przy starcie usuwane są
  wiadomości skrzynki i stan symulatorów starsze niż 30 dni. Wnioski i pisma kont demo zostają,
  więc baza instancji pokazowej wymaga okresowego odtworzenia z czystej kopii.

## Symulatory

Konektory `registry/connectors/ezdrp.py` i `edor.py` nie zmieniły logiki. Profil wskazujący host
`*.symulator.invalid` dostaje transport `httpx` działający w procesie (`registry/simulators/`),
ze stanem w tabeli `SimulatorObject`, wspólnym dla serwera WWW i procesu kolejki. Symulator nie jest
endpointem HTTP aplikacji: usługa ma jednego workera, a część wywołań dzieje się w żądaniu.

| Symulator | Obsługiwane wywołania konektora |
|---|---|
| e-Doręczenia | token; `eda-confirmation`, `bae_search` (po adresach ADE urzędów); `POST /{ADE}/messages` → zadanie; status zadania i wiadomości („Doręczona"); lista dowodów A.1 i E.1 oraz ich treść |
| EZD RP | token; `GET/POST /sprawy`; `POST /sprawy/{id}/dokumenty`; `GET /dokumenty/{id}`, `/link`, pobranie pliku; `GET/PUT /metadane`; `GET /rpw/{n}/{rok}/metadane`; `POST /rpw/_search` |

- Przyjęta wiadomość e-Doręczeń wpisuje swój PDF do symulowanego rejestru przesyłek wpływających
  urzędu adresata — tak w demo pismo „wpływa do EZD".
- Ekran „Wpływy z EZD" ma przycisk **Odczytaj nowe wpływy** (ostatnie 7 dni, bez wpisywania numeru
  RPW). Działa tak samo z prawdziwym EZD RP.
- Podpis: tryb `DEMO` jest dopuszczony lokalnie i w trybie demonstracyjnym; etykieta pozostaje
  „Podpis testowy — niekwalifikowany". Certyfikat demo jest ważny rok i odnawiany przy starcie.
- Oznaczenia: „Symulator wbudowany — bez połączenia z operatorem" na ekranie Integracje, środowisko
  `SYMULATOR` przy operacji, identyfikatory `SIM-…`, nazwy urzędów z dopiskiem „(symulator)", treść
  dowodów zaczyna się od „SYMULACJA — to nie jest odpowiedź operatora".
- W demo obserwator e-Doręczeń ma odstępy 5 i 15 sekund (zwykle 60 s i 5 minut); kolejka na Render
  budzi się co 30 sekund, więc dowody pojawiają się w ciągu około minuty.
- „Odczytaj nowe wpływy" czyta najwyżej 25 przesyłek na kliknięcie; błąd jednej przesyłki nie
  zatrzymuje pozostałych i jest pokazany z numerem RPW.

## Przejście na prawdziwą usługę

Podmiana pliku profilu (`EZDRP_CONFIG_FILE`, `EDOR_CONFIG_FILE`, `SIGNING_CONFIG_FILE`) na dane
operatora. Kod konektorów jest ten sam. Dostępy opisują `DOSTEP-EZD-RP.md` i `DOSTEP-E-DORECZENIA.md`;
rozbieżności kontraktu z `E-DORECZENIA.md` nadal wymagają potwierdzenia na środowisku INT.

## Obieg do pokazania

Powiat: wniosek → PDF → podpis demo → „Wyślij: e-Doręczenia" → dowody nadania i odbioru w Integracjach.
UMP: „Wpływy z EZD" → „Odczytaj nowe wpływy" → link do wniosku → panel weryfikacji → decyzja →
pismo zwrotne tą samą drogą, opcjonalnie „Zapisz w EZD". Powiat: wpływ odpowiedzi i powiadomienie
w „Skrzynce demo".

## Prawdziwe konta dla recenzenta

Administrator dopisuje domenę recenzenta do wybranych urzędów i zakłada konta w panelu. Aliasy
`imie+ump@domena`, `imie+powiat@domena` działają: adres jest unikalny w całości, domena liczona po `@`.
Takie konto nie podpisuje pism podpisem demo (profil demo wymienia tylko konta demonstracyjne).

## Granice

- Symulator odwzorowuje wywołania używane przez konektory, nie całe API operatorów.
- Tryb demo to wejście bez uwierzytelnienia osoby: wolno go włączać wyłącznie na instancji z danymi
  fikcyjnymi. Kto ma kod, może zmieniać dane pokazowe.
- Wpisy testowe utworzone wcześniej przez konta rzeczywiste pozostają widoczne dla kont demo jako
  sprawy „konta urzędowego".

## Weryfikacja

- Testy: `registry/test_demo_mode.py`, `registry/test_simulators.py` (pełny obieg funkcjami
  produkcyjnymi: `sign_letter`, `enqueue`, `process_job`, `sync_incoming`, `publish_incoming_link`,
  `enqueue_ezd`), trasy demo w macierzy ról i kontrakcie metod.
- Lokalnie w przeglądarce (`DYNA_DEMO=1`): wejście kodem, trzy role, podpis, wysyłka z dowodami,
  odczyt wpływu z linkiem do wniosku, panel administratora demo, skrzynka demo.
