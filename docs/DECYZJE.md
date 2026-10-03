# Założenia i rozbieżności

## Potwierdzone przez użytkownika

- Jedna instancja na województwo, teraz Wielkopolska.
- Uruchomienie docelowe na infrastrukturze urzędu.
- Wszystkie moduły i rzeczywiste integracje w zakresie celu.
- Pozostałe decyzje według rekomendacji; fikcyjne dane lokalnie, bez Dockera.

## Decyzje robocze

- Role technicznego administratora i merytorycznego UMP są oddzielone.
- Konto urzędnika powiązane z urzędem i dopuszczoną domeną, zakładane przez administratora.
- Jednorazowy kod e-mail: ważność 10 minut, 5 prób; limit wysyłek i sesja 60 minut.
- Rezerwacja 14 dni, UMP może przedłużyć z uzasadnieniem. Wygaśnięcie zwalnia wyłącznie rezerwacje i wnioski w toku, nigdy wydane numery.
- Sprzedaż pojazdu nie zwalnia numeru. Zwolnienie przydziału ustawia UMP z powodem; historia zostaje.
- Nie gromadzimy PESEL ani REGON. Właściciel: nazwa i adres; nabywca: nazwa.
- Pula III należy do urzędu, stacja opcjonalna, okres konfigurowalny.
- Pisma są roboczymi wzorami do zatwierdzenia, bez fikcyjnej informacji o podpisie.

## Numeracja: zweryfikowany alfabet i wybór województwa

Sprawdzono 03.10.2026: [Dz.U. 2024 poz. 1709](https://api.sejm.gov.pl/eli/acts/DU/2024/1709/text.html) oraz obie nowelizacje wskazane w aktualnych metadanych ELI: [2025 poz. 939](https://api.sejm.gov.pl/eli/acts/DU/2025/939/text.pdf) i [2026 poz. 891](https://api.sejm.gov.pl/eli/acts/DU/2026/891/text.pdf). Zakres, sumy źródeł, dowody i nierozstrzygnięte kwestie: `docs/NUMERACJA-PRZEPISY.md`.

- § 30 ust. 1: alfabet zawiera 25 liter, bez Q. Wspólna walidacja odrzuca Q także na dwóch ostatnich pozycjach. Litery B, D, I, O i Z pozostają dozwolone dla części indywidualnej; ograniczenie z § 31 ust. 1 dotyczy numerów określanych przez organ, z wyjątkiem § 32 ust. 2.
- § 30 ust. 2 pkt 4: część indywidualna 3–5 znaków, cyfry tylko na ostatnich dwóch pozycjach. Dopuszczono także układ z cyfrą na przedostatniej i literą na ostatniej pozycji. Front publiczny, API, wniosek i import używają walidacji serwera.
- Załącznik 13: Wielkopolska P i M. Od 30.07.2025 dla tablic indywidualnych właściciel może wybrać literę województwa; wyczerpanie P nie jest warunkiem wyboru M (§ 1 pkt 2–3 nowelizacji 2025/939). Formularz prezentuje oba jako Wielkopolskę. Ta zmiana nie znosi warunku wyczerpania pierwszej litery dla tablic innych kategorii.
- Tablice zmniejszone: litera województwa + 3 znaki (§ 30 ust. 2 pkt 2). Przykład P 1234 w specyfikacji nie jest poprawny. Zakresy w aplikacji oznaczają pozycje w uporządkowanej pojemności; pierwsze 999 to P001–P999.
- Moduł III nadal ma roboczy profil tymczasowy; wymaga wniosku i skończonego okresu. Rekomendację wspiera zestawienie kompetencji z art. 73a ust. 1 pkt 2 z procesem UMP. Nie jest to potwierdzenie kategorii używanej przez urząd. Specyfikacja nie podaje formatu III; P 123 B nie wolno przypisywać temu dokumentowi jako wymagania. Tablice profesjonalne mają inny format i nadawanie przez starostę.
- W profilu III pozycje 1–9999 dają serię cyfrową, 10000–29979 kontynuację 001A–999Y. Kontynuacja wymaga pełnej poprzedniej serii danego prefiksu. Nowe pule M wymagają rzeczywistych numerów zajmujących całą pojemność P danej kategorii; historyczne pule liczą się nadal. Dowody i zakres kontroli: `docs/POJEMNOSCI-PUL.md`; osobny import historycznych wykazów z podglądem i źródłem: `docs/IMPORT-PUL.md`.
- Treści obraźliwe ocenia UMP; automatyczna lista słów nie zastępuje oceny merytorycznej (§ 32 ust. 3).
- Unikalność zgodnie ze specyfikacją dotyczy całego numeru. Odczytany art. 73a ust. 4 mówi o identycznym wyróżniku indywidualnym, a § 32 ust. 1 o identycznych tablicach. Zakres porównania wymaga potwierdzenia urzędu przed zmianą zasady biznesowej i migracją danych. Nie uznano pełnej zgodności prawnej tego punktu.
- Dawne wpisy nie są automatycznie poprawiane ani usuwane. Złożenie/akceptacja wniosku, pierwsze wydanie oraz przywrócenie zwolnionego numeru ponownie sprawdzają format. Odmowa, wycofanie i zwolnienie pozostają możliwe z wymaganym uzasadnieniem.

## Integracje

[EZD RP - piaskownica](https://www.gov.pl/web/ezd-rp/piaskownica-api): publiczne demo udostępnia dokumentację, nie klucze ani wykonywanie API. Piaskownica wymaga zgłoszenia.

[e-Doręczenia - API](https://www.gov.pl/web/e-doreczenia/interfejsy-api): UA API v3, SE API v4/v3/v2; dokładne kontrakty i uwierzytelnianie trzeba odczytać z oficjalnych materiałów. [Dostęp INT](https://www.gov.pl/web/e-doreczenia/srodowisko-testowe-dla-podmiotow-publicznych-i-niepublicznych) wymaga zgłoszenia, a część dokumentacji dostępna po nadaniu dostępu.

Dotychczas nie uzyskano kluczy testowych ani potwierdzenia systemu EZD używanego przez UMP. Implementację należy kontynuować; te zależności nie uzasadniają zatrzymania całej budowy.

## Przekazanie wpisu między urzędami

UMP może zmienić urząd prowadzący po zakończeniu aktywnego procesu wniosku.
Pierwotny wniosek zachowuje urząd autora i jego dokumentację; dawne powiązanie
nie uprawnia do odczytu bieżących danych ewidencji innego urzędu. Zmiana urzędu
nie przerabia PDF korespondencji. Przekazanie DRAFT/SENT jest blokowane, cel musi
być aktywny. Jest to przyjęta rekomendacja ochrony danych i spójności procesu;
odbiór reguły biznesowej przez urząd pozostaje do wykonania. Dowody:
`docs/WERYFIKACJA-PRZEKAZANIA.md`.
