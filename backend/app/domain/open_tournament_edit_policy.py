from datetime import date

from app.db.models.enums import TournamentStatus, UserRole


def can_edit_open_tournament_for_actor(
    *,
    actor_role: UserRole,
    tournament_status: TournamentStatus,
    tournament_date: date,
    business_date: date,
    admin_current_day_only: bool,
) -> bool:
    if tournament_status != TournamentStatus.ACTIVE:
        return False
    if tournament_date > business_date:
        return False
    if actor_role == UserRole.SUPERADMIN:
        return True
    if admin_current_day_only:
        return tournament_date == business_date
    return True


def is_superadmin_late_open_tournament_override(
    *,
    actor_role: UserRole,
    tournament_status: TournamentStatus,
    tournament_date: date,
    business_date: date,
) -> bool:
    return (
        actor_role == UserRole.SUPERADMIN
        and tournament_status == TournamentStatus.ACTIVE
        and tournament_date < business_date
    )
