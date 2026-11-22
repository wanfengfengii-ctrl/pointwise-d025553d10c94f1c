import sqlite3
from contextlib import contextmanager
from os import PathLike


@contextmanager
def open_database(path: str | PathLike):
    connection = sqlite3.connect(path)
    try:
        connection.execute('PRAGMA foreign_keys = ON')
        yield connection
    finally:
        connection.close()


@contextmanager
def transaction(connection: sqlite3.Connection):
    if connection.in_transaction:
        raise sqlite3.ProgrammingError('connection already has an open transaction')
    connection.execute('BEGIN')
    try:
        yield
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
