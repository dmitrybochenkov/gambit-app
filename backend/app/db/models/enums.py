from enum import StrEnum

from sqlalchemy import Enum as SqlEnum


class PlayerStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    BLOCKED = "blocked"


class PlayerRole(StrEnum):
    USER = "user"
    ADMIN = "admin"
    SUPERADMIN = "superadmin"


class SeasonStatus(StrEnum):
    UPCOMING = "upcoming"
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


class RegistrationMatchStatus(StrEnum):
    CANDIDATE = "candidate"


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
