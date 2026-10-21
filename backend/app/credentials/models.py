import datetime
import enum

from sqlalchemy import Enum as SAEnum
from sqlalchemy import LargeBinary
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.domain.enums import CredentialType
from app.domain.types import UTCDateTime


class CredentialsBase(DeclarativeBase):
    pass


def sa_enum(enum_cls: type[enum.Enum]) -> SAEnum:
    return SAEnum(enum_cls, values_callable=lambda e: [member.value for member in e], native_enum=False)


def utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class Credential(CredentialsBase):
    __tablename__ = "credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str]
    credential_type: Mapped[CredentialType] = mapped_column(sa_enum(CredentialType))
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime(), default=utcnow)
    rotated_at: Mapped[datetime.datetime | None] = mapped_column(UTCDateTime())
    last_used_at: Mapped[datetime.datetime | None] = mapped_column(UTCDateTime())
