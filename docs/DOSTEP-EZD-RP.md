# Materiały do zgłoszenia dostępu do piaskownicy EZD RP

Stan: przygotowano treść; nie wysłano zgłoszenia i nie zaakceptowano regulaminu w imieniu firmy. Potrzebne są dane podmiotu i zatwierdzenie zgłoszenia przez użytkownika.

Źródło: [procedura NASK](https://podrecznik.ezdrp.gov.pl/dostep-do-srodowiska-api-ezd-rp/). Formularz: [wniosek o dostęp](https://ankieta.ezdrp.gov.pl/ankieta/747383/wniosek-o-dostep-do-piaskownicy-api-ezd-rp.html). Dostęp przydzielany jest po weryfikacji podmiotu; otrzymuje on własną instancję z użytkownikami testowymi.

## Pola wymagające rzeczywistych danych i zatwierdzenia

- Pełna nazwa prawna podmiotu, NIP, REGON i adres rejestrowy.
- Kontakt biznesowy: imię, nazwisko, telefon i e-mail.
- Kontakt techniczny: imię, nazwisko, telefon i e-mail.
- Typ podmiotu: producent oprogramowania / integrator, zgodnie z rzeczywistą działalnością.
- Rodzaj aplikacji: dziedzinowe — „Dyna Rejestr Tablic”.
- Akceptacja regulaminu i zgoda na przetwarzanie danych przez osobę upoważnioną.

Nie należy wpisywać danych UMP jako podmiotu wnioskującego bez jego upoważnienia. Formularz opublikowany przez NASK zawiera starszą datę retencji w informacji o danych osobowych; przed zatwierdzeniem należy wyjaśnić aktualność tej informacji z NASK.

## Gotowa treść planowanego zakresu integracji

> Dyna Rejestr Tablic jest systemem dziedzinowym do prowadzenia wojewódzkiej ewidencji numerów tablic rejestracyjnych oraz obsługi wniosków urzędów rejestrujących pojazdy. Pierwszy zakres produktu obejmuje Wielkopolskę, z urzędem głównym i wieloma urzędami wnioskującymi. Planujemy instalację na infrastrukturze jednostki publicznej. Prosimy o dostęp biznesowy i techniczny do piaskownicy API EZD RP w celu sprawdzenia uwierzytelniania użytkownika technicznego, tworzenia i powiązania spraw, przekazywania pism PDF, metadanych i identyfikatorów wniosków oraz przechodzenia z EZD do właściwego wniosku w aplikacji. Dalsze scenariusze obejmują obsługę zdarzeń wpływu korespondencji oraz powiązanie statusów korespondencji i dowodów doręczeń z ewidencją. Testy będą prowadzone na fikcyjnych danych, z weryfikacją uprawnień, obsługi błędów i ochrony przed powtórzeniem operacji. Potrzebujemy informacji o dostępnej wersji API v2, repozytorium plików, konfiguracji atrybutów metadanych, schemacie JRWA i zasadach subskrypcji zdarzeń.

To treść przygotowana przez projekt, a nie deklaracja uzyskanej zgody ani zawartej współpracy z UMP.

## Po przydzieleniu instancji

Poproś administratora środowiska o host aplikacji, endpoint Integratora, endpoint SSO, dane podmiotu, ID i wartość klucza API, SID użytkownika technicznego, dostęp do testowych spraw/JRWA i origin repozytorium plików. Ustal klucze atrybutów metadanych, uprawnienie podglądu spraw, regułę numeracji kancelaryjnej oraz sposób pobrania PDF z repozytorium.

Przechowuj klucz poza repozytorium w pliku prywatnym. Wprowadź konfigurację zgodnie z `docs/EZD-RP.md`. Następnie wykonaj scenariusze rzeczywistego testu; lokalne wyniki MockTransport nie zastępują tego etapu.
