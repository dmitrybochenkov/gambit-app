from enum import StrEnum

from sqlalchemy import Enum as SqlEnum
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator


class UserStatus(StrEnum):
    ACTIVE = "active"
    BLOCKED = "blocked"


class UserRole(StrEnum):
    PLAYER = "player"
    ADMIN = "admin"
    SUPERADMIN = "superadmin"


class SeasonStatus(StrEnum):
    ACTIVE = "active"
    CLOSED = "closed"


class AdminPromptStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    NEEDS_CHANGES = "needs_changes"


class TournamentStatus(StrEnum):
    ACTIVE = "active"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class RegistrationStatus(StrEnum):
    REGISTERED = "registered"
    CANCELLED = "cancelled"


class TournamentTypeStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class RegistrationRequestType(StrEnum):
    NEW_PLAYER = "new_player"
    LINK_EXISTING_PLAYER = "link_existing_player"


class RegistrationRequestStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class KnockoutMode(StrEnum):
    NONE = "none"
    SMALL = "small"
    SMALL_BIG = "small_big"


def database_enum[EnumType: StrEnum](enum_class: type[EnumType], name: str) -> SqlEnum:
    return SqlEnum(
        enum_class,
        name=name,
        native_enum=False,
        values_callable=lambda items: [item.value for item in items],
        validate_strings=True,
    )


class SeasonStatusType(TypeDecorator[SeasonStatus]):
    impl = String(6)
    cache_ok = True

    def process_bind_param(self, value: SeasonStatus | str | None, dialect) -> str | None:
        del dialect
        if value is None:
            return None
        return SeasonStatus(value).value

    def process_result_value(self, value: str | None, dialect) -> SeasonStatus | None:
        del dialect
        if value is None:
            return None
        return SeasonStatus(value)
