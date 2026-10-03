from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connection
from django.db.migrations.executor import MigrationExecutor


class Command(BaseCommand):
    help = "Sprawdza profil urzędowy, migracje i ograniczenia roli PostgreSQL; nie zapisuje danych."

    def add_arguments(self, parser):
        parser.add_argument("--database", action="store_true")

    def handle(self, database, **options):
        if settings.LOCAL or settings.SETTINGS_MODULE != "config.settings_onprem":
            raise CommandError("Wybierz profil config.settings_onprem oraz DYNA_ENV=onprem.")
        if database:
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT rolsuper,rolcreatedb,rolcreaterole,rolbypassrls,"
                        "has_schema_privilege(current_user,'public','CREATE'),"
                        "EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                        "WHERE n.nspname='public' AND pg_has_role(c.relowner,'USAGE')),"
                        "EXISTS(SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member "
                        "WHERE r.rolname=current_user) "
                        "FROM pg_roles WHERE rolname=current_user"
                    )
                    permissions = cursor.fetchone()
                if not permissions or any(permissions):
                    raise CommandError("Rola wykonawcza ma uprawnienia administratora, DDL lub właściciela.")
                executor = MigrationExecutor(connection)
                if executor.migration_plan(executor.loader.graph.leaf_nodes()):
                    raise CommandError("Baza wymaga migracji; wykonaj je osobną rolą właściciela.")
            except DatabaseError as exc:
                raise CommandError(
                    "Nie można sprawdzić bazy; szczegóły połączenia nie są wypisywane."
                ) from exc
        self.check(display_num_errors=True, include_deployment_checks=True)
        self.stdout.write(
            self.style.SUCCESS("Profil urzędowy sprawdzony. Nie potwierdza to działania integracji.")
        )
