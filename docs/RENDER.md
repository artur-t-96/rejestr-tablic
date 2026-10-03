# Dyna Rejestr Tablic na Render

## Stan wdrożenia — 03.10.2026

Aplikacja działa pod adresem **https://dyna-rejestr-tablic.onrender.com**.
Kod jest w prywatnym repozytorium `artur-t-96/rejestr-tablic`.
PR #1–#5 zostały scalone. Poprawka publicznej walidacji w PR #5 została
wdrożona i sprawdzona w Chrome na `f88a82403438dd5cf6bfb44ab7f94c1dedfebf7f`;
[odbiór czytnika](ODBIOR-CZYTNIKA-20261003.md) zachowuje jawny częściowy stan.
Odbiór procesów produkcyjnych wykonano na
`59c6ce90ad68566da140c7647e3a4c8cde6bd9b3`; późniejsze wydanie dokumentacji
nie zmienia kodu aplikacji. `/api/health/` podaje pełny SHA aktualnego wydania.

[Raport odbioru Render](ODBIOR-RENDER-20261003.md) opisuje realne operacje
Chrome, API, sześć PDF, pocztę, import/eksport i odtworzenie osobnej bazy.
Prywatne dowody i dane testowe pozostają lokalnie poza Git.

Zasoby w `My Workspace`, Frankfurt:

- WWW `srv-db0gjjk9v7es73bbojpg`, plan `0.5c-512mb`, 7 USD/mies.;
- PostgreSQL 18 `dpg-db0g07u0tbcc73fm96e0-a`, plan `0.1c-256mb`,
  6 USD/mies. oraz 0,30 USD/mies. za 1 GB;
- trwały dysk `/var/data`, 1 GB, 0,25 USD/mies.

Zaakceptowany koszt: 13,55 USD/mies. plus podatki i użycie ponad limity.
Automatyczne wdrożenia, autoskalowanie dysku PostgreSQL i publiczny dostęp
bazy są wyłączone. Pojedyncza instancja nie ma HA; te zasoby i testy
na danych fikcyjnych nie potwierdzają pojemności docelowego urzędu.

Poczta jest skonfigurowana przez dedykowaną aplikację single tenant
`Dyna Rejestr Tablic Mail`, certyfikat RSA 3072 i Graph MIME.
Nadawca `rejestr-tablic@dynaminds.eu` jest skrzynką współdzieloną ze
zablokowanym logowaniem, bez delegacji. Exchange Application RBAC ogranicza
`Application Mail.Send` do tej skrzynki: dodatnia kontrola nadawcy i ujemna
kontrola innej skrzynki przeszły. Nie przyznano szerokiego Entra Mail.Send
ani Mail.Read. Faktyczny odbiór OTP oraz powiadomienia o decyzji III został
potwierdzony we własnym Outlooku użytkownika. Certyfikat wygasa
03.10.2027; procedura przygotowania dostępu znajduje się w
`deploy/microsoft-mail-rbac.ps1`. Sekrety są poza repozytorium.

Konfiguracja proxy wymaga zaufania do prywatnej sieci Render `10.0.0.0/8`
i oficjalnych sieci Cloudflare. `RENDER_EDGE_CIDRS` wymusza publiczny węzeł
brzegowy Cloudflare w łańcuchu X-Forwarded-For. Nie ustawiono zaufania `/0`.
Rzeczywiste logowania zapisują publiczne IP klienta; alternatywne nagłówki
nie są źródłem tożsamości. To profil Render, odrębny od on-premise.

Hosted CI na rewizji odbioru jest zielone: PostgreSQL 478 testów bez SKIP,
SQLite 478 testów z 29 SKIP dotyczącymi PostgreSQL oraz rzeczywisty
pg_dump/pg_restore klientem 18.6 w pakiecie dla Render.
[CI PR #3](https://github.com/artur-t-96/rejestr-tablic/actions/runs/37128964010),
[CI main](https://github.com/artur-t-96/rejestr-tablic/actions/runs/37129212494).
Nie używano lokalnego Dockera.

## Aktualizacja

1. Utworzyć skupiony PR przez Dynaminds Codex Bot (`codex-gh` dla zapisów),
   wykonać odpowiednią małą kontrolę natywną, zaczekać na pełne hosted CI.
2. Scalić zielony PR do `main`. Auto-deploy jest wyłączony: uruchomić
   wdrożenie **konkretnego pełnego SHA** przez istniejącą usługę Render.
3. Poczekać na `live`, porównać SHA `/api/health/` z oczekiwanym commitem.
4. Sprawdzić cztery procesy, brak oczekujących migracji, właściwy mount,
   integralność dokumentów i adekwatny rzeczywisty proces w Chrome.
5. Przy zmianach danych/migracji wykonać wcześniej kopię i odtworzenie
   do osobnej bazy według [procedury](BACKUP-POSTGRESQL.md).

Render przechowuje dane tego wdrożenia demonstracyjnego; instalacja urzędu
pozostaje niezależna: [WDROZENIE-URZEDOWE.md](WDROZENIE-URZEDOWE.md).
EZD RP, e-Doręczenia, kwalifikowany podpis, odbiór infrastruktury urzędu
oraz pełny odbiór WCAG pozostają osobnymi, jawnie niewykonanymi etapami.
Użytkownik zatwierdził publikację mimo niepotwierdzonego odczytu VoiceOver.
Poniższe sekcje są historycznym zapisem przygotowania, nie bieżącą listą blokad.

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
   Dodatkowo ustawić RENDER_EDGE_CIDRS na aktualne oficjalne
   [zakresy Cloudflare](https://www.cloudflare.com/ips/). Muszą być publiczne
   i zawarte w RENDER_PROXY_CIDRS. Każde żądanie publiczne musi mieć na
   końcu X-Forwarded-For adres z tego zbioru. Sam prywatny peer nie wystarcza.
   Podczas pierwszego wdrożenia zaobserwowano różne prywatne adresy ingress
   dla strony, plików i POST; pojedyncze /32 dają okresowe błędy 400.
   Render nie publikuje tu stałego zbioru prywatnych adresów ingress.
   Zaufanie do sieci prywatnej platformy jest osobną decyzją operatora:
   obejmuje także inne usługi w tym samym workspace/regionie, zgodnie z
   [granicą sieci prywatnej Render](https://render.com/docs/private-network).
   Nie zastępuje to autoryzacji kont, CSRF ani kontroli ról. Nie akceptować
   wszystkich publicznych peerów i nie używać 0.0.0.0/0 ani ::/0.
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
