from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.services.dto.statistics.profile import PlayerProfileView


class ProfilePlaceStatsResponse(BaseModel):
    first: int
    second: int
    third: int
    fourth: int
    fifth: int


class ProfileAchievementResponse(BaseModel):
    id: int
    season_id: int
    season_name: str
    season_starts_at: date
    kind: str
    awarded_at: date
    title: str
    emoji: str
    custom_emoji_id: str | None


class ProfileCombinationTotalsResponse(BaseModel):
    royal_flush: int
    straight_flush: int
    four_of_a_kind: int


class PlayerProfileResponse(BaseModel):
    id: int
    display_name: str
    gender: str | None
    title: str
    points: Decimal
    tournaments_count: int
    knockouts_count: int
    big_knockouts_count: int
    total_knockouts_count: int
    rating_position: int | None
    rating_participants_count: int
    prize_percent: int | None
    places: ProfilePlaceStatsResponse
    champion_titles_count: int
    knockout_titles_count: int
    achievements: list[str]
    achievement_occurrences: list[ProfileAchievementResponse]
    combination_totals: ProfileCombinationTotalsResponse

    model_config = ConfigDict(json_schema_extra={"description": "Current player profile."})

    @classmethod
    def from_view(
        cls,
        *,
        user_id: int,
        gender: str | None,
        title: str,
        view: PlayerProfileView,
    ) -> "PlayerProfileResponse":
        return cls(
            id=user_id,
            display_name=view.display_name,
            gender=gender,
            title=title,
            points=view.total_points,
            tournaments_count=view.tournaments_count,
            knockouts_count=view.knockouts_count,
            big_knockouts_count=view.big_knockouts_count,
            total_knockouts_count=view.total_knockouts_count,
            rating_position=view.rating_position,
            rating_participants_count=view.rating_participants_count,
            prize_percent=view.prize_percent,
            places=ProfilePlaceStatsResponse(
                first=view.first_places_count,
                second=view.second_places_count,
                third=view.third_places_count,
                fourth=view.fourth_places_count,
                fifth=view.fifth_places_count,
            ),
            champion_titles_count=sum(
                1 for honour in view.honours if honour.kind == "rating_winner"
            ),
            knockout_titles_count=sum(
                1 for honour in view.honours if honour.kind == "ko_rating_winner"
            ),
            achievements=[honour.kind for honour in view.honours],
            achievement_occurrences=[
                ProfileAchievementResponse(
                    id=honour.achievement_id,
                    season_id=honour.season_id,
                    season_name=honour.season_name,
                    season_starts_at=honour.season_starts_at,
                    kind=honour.kind,
                    awarded_at=honour.awarded_at,
                    title=honour.title,
                    emoji=honour.emoji,
                    custom_emoji_id=honour.custom_emoji_id,
                )
                for honour in view.honours
            ],
            combination_totals=ProfileCombinationTotalsResponse(
                royal_flush=view.royal_flush_count,
                straight_flush=view.straight_flush_count,
                four_of_a_kind=view.four_of_a_kind_count,
            ),
        )
