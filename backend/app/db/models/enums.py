from enum import StrEnum

from sqlalchemy import Enum as SqlEnum


class UserStatus(StrEnum):
    ACTIVE = "active"
    BLOCKED = "blocked"


class UserRole(StrEnum):
    PLAYER = "player"
    ADMIN = "admin"
    SUPERADMIN = "superadmin"


class TournamentStatus(StrEnum):
    ACTIVE = "active"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class TournamentResultSource(StrEnum):
    REGISTERED = "registered"
    WALK_IN_EXISTING = "walk_in_existing"
    WALK_IN_NEW = "walk_in_new"


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
