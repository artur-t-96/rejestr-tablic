"""Restore a test snapshot into an isolated database of the current backend."""

import sqlite3
import uuid
from contextlib import closing, contextmanager
from io import StringIO

import psycopg
from django.core.management import call_command
from django.db import connection
from psycopg import sql

from .postgres_backup import connection_parameters


@contextmanager
def restored_database(archive, target):
    if connection.vendor == "sqlite":
        call_command("restore_registry", str(archive), target=str(target), stdout=StringIO())
        with closing(sqlite3.connect(target / "registry.sqlite3")) as restored:
            yield restored, "?"
        return
    if connection.vendor != "postgresql":
        raise AssertionError("Unsupported restore test backend")
    name = "dytest_restore_" + uuid.uuid4().hex
    with psycopg.connect(**connection_parameters("postgres")) as admin:
        if admin.execute("SELECT 1 FROM pg_database WHERE datname=%s", [name]).fetchone():
            raise AssertionError("Generated restore target already exists")
    try:
        call_command(
            "restore_registry", str(archive), target=str(target), target_database=name, stdout=StringIO()
        )
        with psycopg.connect(**connection_parameters(name)) as restored:
            yield restored, "%s"
    finally:
        # Only the fresh random target of this test; never source or FORCE.
        with psycopg.connect(**connection_parameters("postgres"), autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))
