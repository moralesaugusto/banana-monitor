import datetime

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime.datetime]):
    """DateTime that always round-trips as UTC-aware, even on SQLite.

    SQLite has no real timestamp type - SQLAlchemy just stores/reads an ISO
    string, and the driver hands back a naive datetime on read regardless of
    what was written. Without this, a datetime freshly assigned in Python
    (aware) and the same value re-fetched from the DB (naive) aren't
    comparable, which breaks any code doing `now - some_reloaded_timestamp`.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(
        self, value: datetime.datetime | None, dialect: object
    ) -> datetime.datetime | None:
        if value is not None and value.tzinfo is not None:
            value = value.astimezone(datetime.UTC).replace(tzinfo=None)
        return value

    def process_result_value(
        self, value: datetime.datetime | None, dialect: object
    ) -> datetime.datetime | None:
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=datetime.UTC)
        return value
