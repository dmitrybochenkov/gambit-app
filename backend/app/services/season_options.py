from datetime import date

from app.db.models import Season
from app.db.repositories.season_repository import SeasonRepository
from app.services.dto.seasons import SeasonOptionView


async def list_started_season_options(
    season_repository: SeasonRepository,
    today: date,
) -> list[SeasonOptionView]:
    return [season_option_view(season) for season in await season_repository.list_started(today)]


def season_option_view(season: Season) -> SeasonOptionView:
    return SeasonOptionView(
        id=season.id,
        name=season.name,
        starts_at=season.starts_at,
        ends_at=season.ends_at,
    )
