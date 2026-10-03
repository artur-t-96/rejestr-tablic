# Historia zmian i dziennik audytowy — odbiór 03.10.2026

Wniosek, wpis i dziennik pokazują polskie opisy zdarzeń, czas, autora,
powód oraz rodzaj i identyfikator obiektu. Przy istniejącym office_id pokazują
urząd. Konto bez imienia/nazwiska jest oznaczone e-mailem; brak aktora to System.
Identyfikator autora pozostaje w szczegółach technicznych. Oryginalne kody,
identyfikatory, JSON i daty w bazie nie są przepisywane.

Tabela „Wartości przed i po” pokazuje nazwę pola i obie zapisane wartości.
Status SENT ma osobne znaczenie dla wpisu („Wniosek w toku”) i wniosku
(„Oczekuje na decyzję”). Statusy transportu i zaproszenia są rozpoznawane
również wtedy, gdy zdarzenie jest powiązane z pismem lub kontem, nie zadaniem.
Podpis testowy pozostaje oznaczony jako testowy. Nieznany przyszły kod ma opis
„Zdarzenie systemowe” i dostępny oryginał w szczegółach.

## Wierność zapisanym wartościom

- „Nie podano”: zapisana pusta wartość lub null.
- „Nie zapisano”: brak klucza po danej stronie zdarzenia. Nie oznacza usunięcia.
- 0, False, pusty tekst i oznaczenia z zerami są rozróżniane. JSON porównywany
  jest wraz z typem wartości; zagnieżdżone metadane i dawne listy są zachowane.
- Daty kalendarzowe są wyświetlane po polsku. Znaczniki czasu ze strefą są
  przeliczane do strefy instancji; strefa jest widoczna. Dawny czas bez strefy
  otrzymuje takie oznaczenie, bez domyślnego przypisywania mu UTC.
- Tabela nie odczytuje obecnego właściciela lub VIN w celu odtworzenia dawnej
  historii. Identyfikatory FK pozostają identyfikatorami, nie wymyśloną dawną
  nazwą. Nazwy kont i urzędów są bieżącymi nazwami wskazanych rekordów.
- HTML i nieznane pola są escapowane. Surowe wartości pozostają w szczegółach
  dla uprawnionych użytkowników; tabela nie zastępuje oryginalnego audytu.

## Dostęp i starsza historia

A0 nadal ma metadane audytu, autora i powód, bez biznesowych wartości przed/po
lub JSON. Reguły dostępu do wpisów pozostają bez zmian. Dziennik A2 obejmuje
wyłącznie jego operacje; historia własnej sprawy może zawierać decyzje UMP
i działania systemu. Zakres obiektów jest ustalany przed stronicowaniem,
także po przekazaniu wpisu do innego urzędu.

Wcześniej ekran wpisu/wniosku pokazywał tylko ostatnie 100 zdarzeń, a dziennik
300. Teraz każda historia ma po 50 zdarzeń na stronę, łączną liczbę, numer
strony oraz linki do starszych/nowszych. Porządek: czas malejąco, następnie ID
malejąco, również przy równym czasie. Błędny parametr strony otwiera pierwszą.
To zwykłe stronicowanie żywego dziennika, nie zamrożony snapshot wielu stron.

Wspólny szablon używa pobranych relacji actor/office. Dwadzieścia zdarzeń
renderuje się jednym zapytaniem zamiast dodatkowych zapytań dla każdego autora.
Odczyt samej prezentacji nie dopisuje zdarzeń. Istniejące wygaszenie rezerwacji
przy wejściu do sprawy jest odrębną operacją opisaną w REZERWACJE-I-ODMOWA.md.

## Weryfikacja

`evidence/audit-presentation-final-tests.txt`: **42 testy, 41 PASS/1 SKIP**,
1.362 s. Dziesięć testów prezentacji i regresje historii cyklu, czynności,
przekazania urzędu, wygasania oraz dostępności HTML. Pominięty test wymaga
blokad PostgreSQL; poprzedni etap miał rzeczywisty odbiór tych blokad.
W tym etapie nie uruchamiano PostgreSQL, nie zmieniano schematu/transakcji.

Po dodaniu identyfikatora autora w szczegółach technicznych ponowiono
prezentację i dostępność HTML: **17/17 PASS**, 0.778 s,
`evidence/audit-presentation-final-html-tests.txt`.

Testy obejmują rzeczywistą korektę wpisu, niezmienność zapisanych zdarzeń,
różne statusy, XSS w danych/powodzie/kodzie, zagnieżdżone wartości, dawne listy,
zero/false, A0 bez wartości biznesowych i izolację urzędów. Dla ponad 100 zdarzeń
przechodzą wszystkie trzy strony wniosku, wpisu i dziennika, bez pominięć
w badanym nieruchomym zestawie i bez danych obcego urzędu. Ruff, Django check,
kontrola migracji i diffu przeszły.

Chrome w profilu użytkownika, osobna fikcyjna kopia na 8776:

1. Gniezno przez OTP otworzyło własny wygasły wniosek P6TERM. Zdarzenia mają
   polskie opisy. Enter otworzył obie tabele statusów wniosku i numeru.
2. Historia wpisu pokazuje autora UMP, powód i przedłużenie z 17.10 na 24.10
   z prawidłową godziną oraz CEST. Kod jest dostępny w szczegółach.
3. 320 px ujawniło rozszerzanie całej karty (414 px). Minimalną szerokość
   kart poprawiono: dokument 320/320 px, tabela we własnym regionie 220/330 px.
   Region ma tabindex=0; ArrowRight przesunął go o 40 px. Override przywrócono.
4. A0 przez OTP otworzył dziennik i techniczne szczegóły wygaszenia: zero tabel
   wartości, zero pre z JSON, brak właściciela P6TERM w DOM. Odczytał drugą
   stronę rzeczywistego dziennika: 25 starszych z 75 zdarzeń.
5. Siedem tabel biznesowych kopii i wszystkie dawne wiersze audytu zachowały
   sumy. Dodano wyłącznie dwa logowania. Nie tworzono danych ani pism.

`evidence/audit-presentation-browser-report.json` zawiera pomiary i sumy;
zrzuty 102–108 pozostają prywatne. Obrazy 106 (desktop) i 105 (320 px)
odczytano wizualnie. Obraz 104 pokazuje wcześniejszy błąd, nie wynik końcowy.

## Pozostałe granice

Nie wykonano w tym etapie nowego backup/restore, odczytu czytnikiem ekranu,
całego audytu WCAG, eksportu audytu, testów operatorów ani Linuxa/systemd.
Nie zmieniano retencji dokumentów i zdarzeń. Pełny raport zgodności i pozostały
zakres systemu opisuje STATUS.md; cały cel pozostaje aktywny.
