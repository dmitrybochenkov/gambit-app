from enum import StrEnum

from sqlalchemy import Enum as SqlEnum


class UserStatus(StrEnum):
    ACTIVE = "active"
    BLOCKED = "blocked"


class UserRole(StrEnum):
    PLAYER = "player"
    ADMIN = "admin"
    SUPERADMIN = "superadmin"


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


class TournamentParticipantSource(StrEnum):
    PRE_REGISTERED = "pre_registered"
    DATABASE_WALK_IN = "database_walk_in"
    ADMIN_CREATED = "admin_created"
    MIGRATED_RESULT = "migrated_result"


class TournamentParticipantResultStatus(StrEnum):
    ACTIVE = "active"
    NO_RESULT = "no_result"


class TournamentTypeStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class RegistrationRequestType(StrEnum):
    NEW_PLAYER = "new_player"
    LINK_EXISTING_PLAYER = "link_existing_player"
    ADMIN_CREATED_PLAYER_REVIEW = "admin_created_player_review"


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
