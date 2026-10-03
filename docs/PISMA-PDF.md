# Pisma PDF i szablony — weryfikacja lokalna

Stan: 03.10.2026. Etap obejmuje wygląd i powiązanie nowych dokumentów, walidację szablonów oraz zachowanie archiwum. Nie stanowi odbioru całego systemu.

## Zachowanie aplikacji

- PDF A4 zawiera nadawcę, adresata, numer systemowy pisma, datę utworzenia, treść, identyfikator sprawy, klikalny link i wektorowy QR. Data jest datą utworzenia pisma w strefie Europe/Warsaw, również na granicy roku.
- Link prowadzi do konkretnego wniosku, a przy bezpośrednim przydziale puli do konkretnej puli. Nie zawiera danych właściciela. Otwarcie wymaga zalogowania i odpowiednich uprawnień; kod QR nie omija kontroli dostępu.
- Marginesy boczne 22 mm, górny 20 mm, dolny 24 mm; polska czcionka, stopka i numer strony. Długie akapity są dzielone na kolejne strony. Identyfikator, link i QR pozostają jednym blokiem.
- Nowe domyślne wzory mają opis brakujących danych, adres wnioskodawcy i przeznaczenie puli. Nie dodają kropki do adresu URL. Pismo nie deklaruje podpisu na podstawie samego wydruku.
- Znaczniki HTML pochodzące od użytkownika są drukowane jako dosłowny tekst, bez zewnętrznych odnośników.

## Edytowalne wzory i aktualizacja

Administrator może używać zmiennych: `${sender}`, `${recipient}`, `${subject}`, `${case_number}`, `${owner}`, `${owner_address}`, `${vehicle}`, `${justification}`, `${reason}`, `${request_id}`, `${reference}`, `${request_url}`, `${period}`, `${station}`. Dosłowny dolar wymaga `$$`. Nieznana zmienna i niepoprawna składnia są odrzucane w formularzu oraz podczas generowania dokumentu. Błąd generowania wycofuje rezerwację, wniosek i licznik w tej samej transakcji.

Migracja `0008_refresh_builtin_templates` aktualizuje wyłącznie cztery wzory o dokładnej oryginalnej treści, tytule i rewizji 1. Zapisuje rewizję 2 oraz audyt przed/po. Własne tytuły, treści lub rewizje urzędu są zachowane. Powtórne wykonanie nie tworzy następnych aktualizacji. Cofnięcie obejmuje wyłącznie niezmienione wzory rewizji 2.

Zmiana wzoru dotyczy nowych pism. Archiwalne treści, PDF-y, podpisane PDF-y i ich SHA-256 nie są przepisywane. Nowa wersja archiwalnego pisma zachowuje jego zapisaną treść; nie służy do automatycznej zamiany historycznej treści na nowy wzór. Jeśli urząd potrzebuje nowej treści, wymaga to osobnego procesu z zachowaniem poprzednika.

Przed migracją głównej lokalnej bazy wykonano `backup_registry`. Po migracji wszystkie sześć tabel biznesowych zachowało identyczne sumy: 5 wniosków, 5 wpisów, 12 pism, jedna pula, 30 numerów i trzy liczniki. Zmieniono cztery domyślne wzory i dodano cztery wpisy audytu. Dowód: `evidence/pdf-primary-migration.json`.

## Dowody

- `evidence/pdf-regression-tests.txt`: 36/36 PASS SQLite — osiem testów dokumentów, numeracja, współbieżne wersje i podpisy. Odtworzenie SQLite jest rzeczywiste.
- `evidence/pdf-postgres-tests.txt`: 37/37 PASS PostgreSQL — ten sam zakres oraz dodatkowe rzeczywiste pg_dump/pg_restore z podpisanym dokumentem, dowodami, wpływem EZD, kolejką i licznikami. Dane i API operatora w testach są fikcyjne; baza, blokady, podpis DEMO oraz narzędzia kopii są rzeczywiste.
- Rozszerzono dawny test numeracji i odtworzenia o PostgreSQL. Test historycznej migracji przywraca teraz najnowszy schemat, żeby następne testy nie działały na schemacie sprzed wpływów EZD.
- `evidence/pdf-layout-report.json`: dziesięć PDF-ów z rzeczywistych usług tworzenia i rozpatrywania wniosków na oddzielnej bazie; łącznie 12 stron. Poppler 120 DPI, kontrola granic każdego znaku i rzeczywisty odczyt QR przez zxing-cpp. Obejrzano każdą stronę, również długie dane i uzasadnienia.
- Chrome na oddzielnej bazie `var/pdf-ui-20261003-v2`: logowanie OTP urzędnika, otwarcie PDF z wniosku, kliknięcie linku w PDF i właściwy wniosek po przejściu. Podgląd wydruku zawiera jedną kompletną stronę; zamknięto go bez wysyłania na drukarkę. Zrzuty zapisano prywatnie w `evidence/private/27-*`, `28-*`, `29-*`.

Odtworzenie powyższych próbek wymaga nowych katalogów i pliku raportu:

```sh
.venv/bin/python -m pip --isolated install --index-url https://pypi.org/simple --require-hashes --only-binary=:all: -r requirements-qa.txt
.venv/bin/python scripts/verify-document-layout.py \
  --data-dir var/pdf-qa-nowy \
  --output output/pdf/qa-nowy \
  --render-dir tmp/pdfs/qa-nowy \
  --report evidence/private/pdf-qa-nowy.json
```

Skrypt odmawia nadpisania istniejących katalogów i nie pracuje na głównej bazie ani PostgreSQL. Wynik automatyczny wymaga osobnego obejrzenia wszystkich stron. Biblioteki QA nie są zależnością procesu serwera; do renderowania potrzeba Popplera. Podgląd i wydruk wykorzystują czytnik PDF przeglądarki.

## Granice

Nie zweryfikowano PDF/UA, pełnego tagowania ani obsługi czytników ekranu. Widoczność tekstu i poprawne polskie znaki nie dowodzą dostępności PDF. Nie sprawdzono fizycznej drukarki ani skanowania QR telefonem. Wzory i numeracja kancelaryjna wymagają zatwierdzenia przez urząd. Podpis DEMO nie dowodzi podpisu kwalifikowanego, pieczęci kwalifikowanej, QSCD ani LTV. Testy operatorów EZD i e-Doręczeń oraz pełny odbiór urzędowy pozostają otwarte.
