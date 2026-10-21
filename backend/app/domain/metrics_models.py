import datetime
import enum

from sqlalchemy import Enum as SAEnum
from sqlalchemy import Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.domain.enums import EntityType
from app.domain.types import UTCDateTime


class MetricsBase(DeclarativeBase):
    pass


class Granularity(enum.StrEnum):
    RAW = "raw"
    FIVE_MINUTE = "5m"
    ONE_HOUR = "1h"
    ONE_DAY = "1d"


def sa_enum(enum_cls: type[enum.Enum]) -> SAEnum:
    return SAEnum(enum_cls, values_callable=lambda e: [member.value for member in e], native_enum=False)


def utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class CheckResult(MetricsBase):
    __tablename__ = "check_results"
    __table_args__ = (Index("ix_check_results_entity_ts", "entity_type", "entity_id", "ts"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[EntityType] = mapped_column(sa_enum(EntityType))
    entity_id: Mapped[int]
    ts: Mapped[datetime.datetime] = mapped_column(UTCDateTime(), default=utcnow)
    success: Mapped[bool]
    latency_ms: Mapped[float | None]
    error_message: Mapped[str | None]
    checked_by_integration_id: Mapped[int | None]


class MetricSample(MetricsBase):
    __tablename__ = "metric_samples"
    __table_args__ = (
        Index("ix_metric_samples_lookup", "entity_type", "entity_id", "metric_name", "ts"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[EntityType] = mapped_column(sa_enum(EntityType))
    entity_id: Mapped[int]
    metric_name: Mapped[str]
    ts: Mapped[datetime.datetime] = mapped_column(UTCDateTime(), default=utcnow)
    value: Mapped[float]
    unit: Mapped[str | None]


class MetricRollup(MetricsBase):
    __tablename__ = "metric_rollups"
    __table_args__ = (
        Index(
            "ix_metric_rollups_lookup",
            "entity_type",
            "entity_id",
            "metric_name",
            "granularity",
            "bucket_start",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[EntityType] = mapped_column(sa_enum(EntityType))
    entity_id: Mapped[int]
    metric_name: Mapped[str]
    bucket_start: Mapped[datetime.datetime] = mapped_column(UTCDateTime())
    granularity: Mapped[Granularity] = mapped_column(sa_enum(Granularity))
    avg_value: Mapped[float]
    min_value: Mapped[float]
    max_value: Mapped[float]
    sample_count: Mapped[int]
