from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.services.dto.statistics.rating import KnockoutsRatingView, PointsRatingView


class RatingPlayerResponse(BaseModel):
    id: int
    display_name: str


class PointsRatingRowResponse(BaseModel):
    position: int
    player: RatingPlayerResponse
    points: Decimal
    tournaments_count: int
    champion_titles_count: int


class PointsRatingResponse(BaseModel):
    title: str
    items: list[PointsRatingRowResponse]

    model_config = ConfigDict(json_schema_extra={"description": "Player-facing points rating."})

    @classmethod
    def from_rows(cls, title: str, rows: list[PointsRatingView]) -> "PointsRatingResponse":
        return cls(
            title=title,
            items=[
                PointsRatingRowResponse(
                    position=position,
                    player=RatingPlayerResponse(
                        id=row.player_id,
                        display_name=row.display_name,
                    ),
                    points=row.total_points,
                    tournaments_count=row.tournaments_count,
                    champion_titles_count=row.season_champion_titles_count,
                )
                for position, row in enumerate(rows, start=1)
            ],
        )


class KnockoutsRatingRowResponse(BaseModel):
    position: int
    player: RatingPlayerResponse
    knockouts_count: int
    big_knockouts_count: int
    total_knockouts_count: int
    tournaments_with_knockouts: int
    knockout_titles_count: int


class KnockoutsRatingResponse(BaseModel):
    title: str
    items: list[KnockoutsRatingRowResponse]

    model_config = ConfigDict(json_schema_extra={"description": "Player-facing knockouts rating."})

    @classmethod
    def from_rows(
        cls,
        title: str,
        rows: list[KnockoutsRatingView],
    ) -> "KnockoutsRatingResponse":
        return cls(
            title=title,
            items=[
                KnockoutsRatingRowResponse(
                    position=position,
                    player=RatingPlayerResponse(
                        id=row.player_id,
                        display_name=row.display_name,
                    ),
                    knockouts_count=row.knockouts_count,
                    big_knockouts_count=row.big_knockouts_count,
                    total_knockouts_count=row.total_knockouts_count,
                    tournaments_with_knockouts=row.knockout_tournaments_count,
                    knockout_titles_count=row.season_knockout_leader_titles_count,
                )
                for position, row in enumerate(rows, start=1)
            ],
        )
