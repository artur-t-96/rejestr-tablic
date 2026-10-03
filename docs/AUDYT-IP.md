# Adres IP operacji użytkownika w audycie

03.10.2026, zmiana po `98bb02bd0ff35cf7509405fc0735ce126302ede8`.
Specyfikacja §8 wymaga IP w AuditLog, a §9 pełnego audytu.

## Wykryte braki i poprawka

Operacja utworzenia wniosku lub decyzji przekazywała adres IP do głównego
zdarzenia, ale pomijała go przy automatycznie wygenerowanym piśmie.
Przekazywanie IP obejmuje teraz wniosek, zgodę, odmowę, przydział II/III
oraz bezpośredni przydział II. `letter.generated` zachowuje autora, numer
i sumę PDF oraz adres pochodzący z tej samej operacji.

Ręczne wznowienie niewysłanej operacji i obserwacji e-Doręczeń również
przyjmuje IP z żądania administratora. Błąd transportu kodu OTP zapisuje
IP żądania; nadal nie oznacza udanego logowania i ma systemowego aktora.

Adres pochodzi z istniejącego `REMOTE_ADDR`, nie z dowolnego nagłówka
X-Forwarded-For. Profil urzędowy ma osobny mechanizm zaufanego pośrednika
opisany w `WDROZENIE-URZEDOWE.md`. Ten etap nie uruchamiał tego profilu.
Polecenia CLI i zadania systemowe bez żądania HTTP zachowują puste IP.
Nie dopisujemy adresów do dawnych zdarzeń i nie zmieniamy archiwum.
Nie ma migracji ani zmian uprawnień, dokumentów lub deduplikacji wysyłki.

## Dowody

- Przed poprawką pięć testów dokumentów wykazało siedem brakujących IP
  w podprzypadkach; `evidence/letter-audit-ip-before-fix.txt`.
  Osobna próba wykazała brak parametru usług wznowienia oraz brak IP
  w formularzach i błędzie OTP; `evidence/user-audit-ip-before-fix.txt`.
- Końcowo **109/109 PASS**: nowe testy, numeracja i rollback PDF, rdzeń,
  walidacja operacji API, powiadomienia, e-Doręczenia, logowanie i role.
  `evidence/user-audit-ip-tests.txt`; Ruff, format, Django check i kontrola
  braku migracji również przeszły. Nie uruchamiano PostgreSQL ani Dockera.
- IPv4 i IPv6 w żądaniach klienta testowego; HTML i API, zgoda/odmowa,
  zagnieżdżony przydział II/III, bezpośrednia pula, brak kontekstu HTTP.
  Wznowienia mają rzeczywisty audyt bazy i transport MockTransport.
  Oba formularze wznowienia przechodzą CSRF, a obserwacja nie zwiększa
  liczby wysyłek. Polecenia bez IP pozostają obsługiwane.
- **14 rzeczywistych POST HTTP**, dwie sesje z rzeczywistym OTP zapisanym
  do plików, prawdziwy CSRF, osobna kopia SQLite na porcie 8785.
  Powstało dziesięć pism z audytami: APPLICATION, APPROVAL, REJECTION, POOL.
  Wszystkie mają właściwego autora, numer, SHA-256 i IP `127.0.0.1`, także
  przy podanym fałszywym X-Forwarded-For. Zachowano 58 starszych zdarzeń,
  12 dawnych archiwów PDF i wszystkie 27 tabel głównej bazy.
  Raport: `evidence/letter-audit-ip-http-proof.json`.

Próba HTTP dotyczy dokumentów po poprawce `services.py`, przed późniejszym
dodaniem przekazywania IP do wznowień i błędu OTP w `views.py`; raport
zachowuje hashe faktycznie testowanych plików. Te późniejsze ścieżki
sprawdzono w końcowych testach Django. HTTP nie testowało wznowienia
rzeczywistej usługi operatora, zewnętrznego SMTP ani gniazda IPv6.

Dwie dawne asercje e-Doręczeń obejmowały cały HTML: uznawały adres z URL
formularza przedłużenia sesji za ujawnienie zadania i przycisk tego formularza
za możliwość wznowienia wysyłki. Kontrola obejmuje teraz treść biznesową,
brak obiektu w kontekście odpowiedzi 403 i brak formularza operacji.
Niepewny wynik ma dodatkową próbę POST bez zmiany zadania lub audytu
i bez kolejnej wysyłki. Kontrola sesji pozostaje osobną funkcją.

To usunięcie konkretnych braków audytu, nie deklaracja potwierdzenia
wszystkich wymagań systemu. Publiczna dostępność i testy operatorów
zachowują jawne otwarte zakresy w `MACIERZ-ZGODNOSCI.md`.
