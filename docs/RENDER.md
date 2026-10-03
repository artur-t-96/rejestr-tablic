# Przygotowanie GitHub i Render

## Zgoda na publikację i bieżący dostęp (03.10.2026)

Użytkownik ponownie polecił uruchomić system na Renderze, przekazać link
i sprawdzić produkcję. Ta instrukcja uchyla wcześniejsze wstrzymanie
publikacji do zamknięcia B05. Odczyt VoiceOver nadal nie jest potwierdzony;
nie zmienia się ocena zgodności WCAG.

Panel Render jest dostępny w Chrome, workspace `My Workspace`.
Użytkownik wskazał `artur-t-96/rejestr-tablic`. Osobna instalacja
Dynaminds Codex Bot na koncie `artur-t-96` (146698772) pozwala zapisywać
w tym repozytorium. Wykonany zapis jedynie `.gitignore` potwierdził uprawnienia;
API permissions zwracało mylące false. Zdalny commit inicjalizacji:
`3669ef4b0bc5dff200c1f878fa08b17faff7def0`. Repozytorium jest publiczne;
przed wysłaniem pełnego kodu/specyfikacji oczekujemy odpowiedzi na pytanie
czy ustawić prywatność. Kod aplikacji jeszcze nie został wysłany.

Blueprint używa aktualnych identyfikatorów `0.5c-512mb` oraz `0.1c-256mb`,
jawnego dysku PostgreSQL 1 GB i wyłączonego autoskalowania storage.
Koszt dodatkowych zasobów sprawdzony w panelu/cenniku: WWW 7 USD/mies.,
PostgreSQL 6 USD + 0,30 USD za 1 GB, dysk dokumentów 0,25 USD za 1 GB;
razem 13,55 USD/mies. przed podatkami i ewentualnym ponadlimitowym użyciem.
Nie zwiększamy planu workspace. Użytkownik zaakceptował ten koszt,
podatki i ewentualne ponadlimitowe użycie. Płatne zasoby jeszcze nie powstały.
[Aktualny cennik](https://render.com/pricing) i
[aktualne pola Blueprint](https://render.com/docs/blueprint-spec).

Użytkownik polecił skonfigurować pocztę z własnego Microsoft 365.
Utworzono oddzielną skrzynkę współdzieloną `rejestr-tablic@dynaminds.eu`
w organizacji B2Bnet S.A. Odczyt Exchange potwierdził SharedMailbox oraz
AccountDisabled=true; skrzynka nie ma członków ani delegacji.
Formularz rejestracji `Dyna Rejestr Tablic Mail` jest przygotowany jako
single tenant; oczekuje potwierdzenia Microsoft Platform Policies.
Nie zarejestrowano jeszcze aplikacji/certyfikatu i nie nadano dostępu.
Docelowo Exchange Application RBAC: tylko Application Mail.Send na tej
jednej skrzynce, bez Mail.Read i bez nieograniczonego grantowania Entra.

Backend `registry.microsoft_mail.EmailBackend` obsługuje OTP, zaproszenia,
powiadomienia i PDF przez Graph MIME. Certyfikat RSA, assertion PS256
(5 minut), TLS, stałe endpointy Microsoft, ograniczony rozmiar i brak
automatycznego ponawiania POST po niepewnym wyniku. Render wymaga poprawnych
identyfikatorów organizacji/aplikacji/skrzynki i pasującego ważnego certyfikatu/klucza;
wartości MS_MAIL_PRIVATE_KEY i certyfikatu trafiają wyłącznie do chronionej
konfiguracji środowiska, nigdy Git. Przypięte zależności już zawierają PyJWT,
cryptography i httpx. Profil urzędowy zachowuje SMTP/TLS.
Lokalny certyfikat RSA 3072 jest tylko przygotowany, nie jest zarejestrowany.
Ważny do 03.10.2027; przed upływem wymaga zaplanowanej wymiany.

64 testy dotyczące poczty/Render/zaproszeń/powiadomień zakończyły się OK,
w tym 2 pominięte przypadki wymagające PostgreSQL. HTTP Microsoft jest
symulowane; test rzeczywistego nadawcy, zakresu RBAC i odbioru OTP pozostaje
wymagany po konfiguracji. 202 potwierdza przyjęcie, nie doręczenie.
[Graph sendMail](https://learn.microsoft.com/en-us/graph/api/user-sendmail?view=graph-rest-1.0),
[certyfikat aplikacji](https://learn.microsoft.com/en-us/entra/identity-platform/certificate-credentials),
[Exchange Application RBAC](https://learn.microsoft.com/en-us/exchange/permissions-exo/application-rbac).
Skrypt `deploy/microsoft-mail-rbac.ps1` przygotowuje ograniczenie do
niezmiennego ExternalDirectoryObjectId skrzynki. Wymaga właściwej aktywnej
organizacji Exchange, zgodnych identyfikatorów aplikacji i skrzynki,
zablokowanego logowania oraz osobno potwierdzonego braku nieograniczonych
grantów Entra. `-WhatIf` daje podgląd bez zmian. Skrypt odmawia zastąpienia
konfliktujących zakresów/grantów, nie usuwa uprawnień i nie wysyła poczty.
Po wykonaniu wymaga Mail.Send InScope=true dla nadawcy oraz false dla
wskazanej skrzynki kontrolnej. Test Exchange nie obejmuje grantów Entra ani
pamięci podręcznej Graph; rzeczywista wysyłka i odbiór nadal są konieczne.
14 scenariuszy skryptu PASS na natywnym PowerShell 7.6.6, ze wszystkimi
poleceniami Exchange zastąpionymi symulacją. Skrypt nie był zastosowany
w organizacji. Te same testy są dodane do przygotowanego hosted CI.

CIDR-y proxy nadal wymagają potwierdzenia podczas uruchomienia;
nie poszerzono zaufania do wszystkich adresów.

Przygotowane `.github/workflows/ci.yml`: SQLite oraz PostgreSQL 18
w hosted CI, pełne testy `registry`, migracje/check, statyczne zasoby,
narzędzia pg_dump/pg_restore 18. Akcje mają przypięte SHA sprawdzone przez
oficjalne API GitHub; workflow ma tylko contents:read i limit czasu.
Kontener PostgreSQL dotyczy wyłącznie hosted CI; na laptopie nie użyto Dockera.
YAML CI i oficjalny JSON Schema Render przechodzą lokalną walidację;
nie jest to wynik hosted CI. Przegląd 578 śledzonych plików nie znalazł
wykluczonych ścieżek ani markerów kluczy prywatnych/tokenów GitHub;
ten ograniczony skan nie jest formalnym audytem wszystkich sekretów.

Odbiór po usunięciu blokad: zielone CI → wdrożenie wskazanego SHA →
health i procesy/migracje → rzeczywista poczta/OTP → wszystkie role i trzy
moduły w Chrome na fikcyjnych danych → PDF/import/eksport → restart
i trwałość → spójna kopia/odtworzenie na odrębnej bazie → raport z linkiem.
API operatorów urzędu nadal wymagają własnych dostępów i osobnego dowodu.
Nie ma obecnie publicznego adresu Dyna ani dowodu odbioru produkcji.

## Historyczne przygotowanie lokalne

03.10.2026, kod `855358b7ab48059ff03d711c7d61b7eb4dd78e6c`. Użytkownik polecił najpierw zakończyć lokalny odbiór,
następnie opublikować prywatne repozytorium GitHub i wdrożyć aplikację na Render.
Na tym etapie przygotowano pliki lokalnie; nie utworzono usług ani repozytorium.
Otwarte B05 w `RAPORT-ODBIORU-LOKALNEGO.md` nadal blokuje publikację.

## Przygotowane pliki

`render.yaml` określa usługę Python we Frankfurcie, PostgreSQL 18 oraz
dysk `/var/data` na archiwum dokumentów. Plany starter/basic-256mb są
propozycją do sprawdzenia kosztu na koncie przed utworzeniem zasobów,
nie dokonanym zakupem ani potwierdzeniem docelowej wydajności.
Automatyczne wdrożenia są wyłączone do czasu odbioru pierwszej instancji.
Publiczny dostęp PostgreSQL jest wyłączony.
[Blueprint](https://render.com/docs/blueprint-spec) przeszedł lokalną
walidację według oficjalnego JSON Schema, nie walidację konta/API Render.

`config.settings_render` jest osobnym profilem: bez DEBUG, z HTTPS,
bezpiecznymi cookies, jedną domeną i pełnym `RENDER_GIT_COMMIT` w health.
Nie zmienia profilu `settings_onprem` ani konfiguracji lokalnej.
Połączenie z wewnętrznym PostgreSQL wymaga TLS (`sslmode=require`).
Render stosuje tu certyfikaty samopodpisane, bez obsługi verify-full;
nie jest to identyczny profil zaufania jak urzędowy zdalny PostgreSQL.
[Oficjalny opis TLS](https://render.com/docs/postgresql-creating-connecting).
Blueprint używa konta bazy wygenerowanego przez Render również do migracji.
Przed użyciem rzeczywistych danych urzędu należy rozdzielić konto migracji
od roli wykonawczej według `WDROZENIE-URZEDOWE.md`. Ten profil jest
przygotowaniem wskazanego hostingu, bez deklaracji gotowości urzędowej infrastruktury.

Publiczne static obsługuje WhiteNoise 6.12.0. Zastosowano kompresję bez zmiany
nazw plików, żeby zachować względne ścieżki workera ALTCHA i istniejące wersje
URL zasobów. Cache wynosi 60 s. Dokumenty prywatne nie są katalogiem static.
[Instrukcja WhiteNoise](https://whitenoise.readthedocs.io/en/stable/django.html).

`deploy/render-build.sh` instaluje przypięte wheel z kontrolą hashy i zbiera
publiczne zasoby do katalogu wydania. Build nie uruchamia migracji ani kolejek.
`deploy/render_start.py` najpierw sprawdza rzeczywisty mount `/var/data`,
konfigurację i migracje. Potem uruchamia Gunicorn, wygaszanie rezerwacji,
integracje i zaproszenia. Procesy współdzielą jeden dysk; wyjście dowolnego
procesu zatrzymuje całą usługę, żeby health WWW nie ukrywał zatrzymanej kolejki.
SIGTERM zatrzymuje grupy procesów z ograniczonym czasem oczekiwania.
Nie inicjalizuje kont ani nie kopiuje fikcyjnych danych automatycznie.

Dysk dostępny jest tylko jednej instancji i tylko podczas runtime, nie build
ani pre-deploy. Dlatego nie wybrano osobnego workera bez dostępu do PDF-ów.
Wdrożenie z dyskiem wymaga krótkiej przerwy, bez deklaracji zero downtime.
[Ograniczenia dysków Render](https://render.com/docs/disks).

## Wymagane ustawienia i odbiór po publikacji

1. Po odpowiedzi użytkownika o prywatność opublikować sprawdzony kod
   w wskazanym `artur-t-96/rejestr-tablic` przez właściwą instalację bota. Zweryfikować Git,
   wykluczenia sekretów/baz i skonfigurować hosted CI z PostgreSQL przed
   pierwszym wdrożeniem. Nie publikować `var/` ani `evidence/private/`.
2. Sprawdzić rzeczywisty plan/koszt i dostęp na wskazanym koncie Render.
   Zastosować Blueprint dopiero do gotowego wydania. Ustawić niezależny
   losowy `DJANGO_SECRET_KEY` o długości co najmniej 50 znaków, domenę HTTPS
   w APP_URL i dokładnie ten host w DJANGO_ALLOWED_HOSTS.
3. Po zatwierdzeniu rejestracji Microsoft utworzyć dedykowaną aplikację,
   skonfigurować jej certyfikat i potwierdzić dokładny zakres dostępu przed
   grantowaniem. Nie nadawać nieograniczonego Mail.Send w Entra.
   W oddzielnej sesji administratora Exchange wykonać podgląd skryptu RBAC:

   ```powershell
   ./deploy/microsoft-mail-rbac.ps1 -TenantId ORGANIZACJA_GUID `
     -AppId APLIKACJA_GUID -EnterpriseObjectId ENTERPRISE_PRINCIPAL_GUID `
     -MailboxObjectId SKRZYNKA_GUID -ControlMailboxObjectId KONTROLA_GUID `
     -Sender rejestr-tablic@dynaminds.eu -ConfirmedNoUnscopedEntraGrant -WhatIf
   ```

   Po zatwierdzeniu tego podglądu wykonanie bez `-WhatIf` wymaga świadomego
   potwierdzenia ShouldProcess. ENTERPRISE_PRINCIPAL_GUID pochodzi z
   Enterprise apps; Object ID z App registrations jest inną wartością.
   Ustawić EMAIL_BACKEND=registry.microsoft_mail.EmailBackend oraz
   MS_MAIL_TENANT_ID, MS_MAIL_CLIENT_ID, MS_MAIL_MAILBOX_ID,
   MS_MAIL_CERTIFICATE, MS_MAIL_PRIVATE_KEY i DEFAULT_FROM_EMAIL.
   Klucz pozostaje w chronionej konfiguracji Render. Po inicjalizacji pustej
   bazy przez `initialize_registry --admin-email ADRES` sprawdzić rzeczywisty
   OTP w skrzynce odbiorcy. Plikowa poczta lokalna nie dowodzi odbioru w chmurze.
   Alternatywny SMTP nadal wymaga dokładnie jednego transportu TLS/STARTTLS.
4. Ustalić i potwierdzić RENDER_PROXY_CIDRS: sieci rzeczywistych pośredników
   Render/edge. Nie wpisywać 0.0.0.0/0 ani ::/0. Middleware sprawdza peer,
   odczytuje X-Forwarded-For od prawej, pomija zaufanych pośredników i usuwa
   alternatywne nagłówki tożsamości. Nie ufa pierwszemu adresowi klienta.
   Brak/niepoprawna konfiguracja daje odmowę. Porównać rzeczywisty adres
   z obserwowaną trasą i wykonać próbę podszycia nagłówkami przed odbiorem.
   Testy z fikcyjnymi CIDR-ami nie potwierdzają topologii Render.
5. Sprawdzić health 200 i pełny SHA, migracje, wszystkie cztery procesy,
   restart i trwałość PDF-ów oraz danych. W Chrome wykonać OTP i pełny
   przebieg urzędu/UMP, odczyt archiwum i publiczną ochronę. Zweryfikować
   pamięć/limity wybranego planu; sam health nie wystarcza.
6. Sprawdzić narzędzia PostgreSQL 18 i rzeczywiste odtworzenie spójnej kopii
   bazy oraz dysku. Użyć procedur istniejącego backup/restore i zapisać
   osobny dowód Render. Sam snapshot dysku nie zastępuje kopii PostgreSQL.
   Rzeczywiste integracje pozostają zależne od opisanych dostępów operatorów.

## Wykonane sprawdzenia lokalne

Build instaluje klienty PostgreSQL 18.6 z oficjalnego repozytorium PGDG,
ponieważ [natywny runtime Render](https://render.com/docs/native-runtimes)
dokumentuje Debian 12 i domyślne klienty 12–14. Pakiety amd64 oraz `libpq`
mają przypięte rozmiary i SHA-256 w `deploy/render_postgres_tools.py`,
z pochodzeniem zapisanym w `third_party/render-postgresql-client-18.json`.
Ekstrakcja do `.render-postgres` nie wymaga sudo i nie wykonuje skryptów
instalacyjnych. Oddzielne wrappery zapewniają właściwą bibliotekę klienta;
start odmawia uruchomienia przed migracją, jeśli wersja/receipt są niepoprawne.
Hosted CI w Debian 12 wykonuje rzeczywisty dump i restore do nowej bazy.
Nie jest to jeszcze dowód odtworzenia danych na instancji Render.

17/17 testów profilu, proxy, granicy plików statycznych i regresji konfiguracji
on-prem PASS. Wśród prób: podszyty prefiks XFF, niezaufany peer, IPv6,
uszkodzony/długi łańcuch, brak mount przed migracją, zakaz wildcardów,
ochrona sekretu w wyjątku i nieudostępnianie sąsiedniego prywatnego PDF.
Wykonano collectstatic/kompresję, kontrole składni Python/shell i pip check.
Rzeczywisty moduł settings_render przeszedł check --deploy bez błędów,
z fikcyjną odizolowaną konfiguracją i bez połączenia z bazą. Pozostały
dwa jawne ostrzeżenia W005/W021: HSTS nie obejmuje subdomen i nie zgłasza
preload. Nie wyciszono ich; tych polityk dla przyszłej domeny nie zatwierdzano.
WhiteNoise pobrano i zainstalowano z przypiętym hashem; notices zachowano.
Pozostałe wersje runtime/QA zostały zachowane przy ponownym generowaniu locków.

Nie uruchamiano rzeczywistego Render, tamtejszego PostgreSQL/SMTP, mountu,
pełnego nadzorcy ani zamykania pracującego Gunicorna. Nie jest to odbiór
Linuxa ani symulacja całej chmury na laptopie.
Dowody: `../evidence/render-profile-tests.txt`,
`../evidence/render-profile-proof.json`, `../third_party/whitenoise-render-20261003.json`.
Directory CLI 1.53.0/plugin 0.3.5 odmówił wyszukiwania komunikatem o user agent;
nie omijano ograniczenia. Profil oparto na oficjalnych źródłach Render.
