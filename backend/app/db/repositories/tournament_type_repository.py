from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    TournamentEconomyConfig,
    TournamentRebuyConfig,
    TournamentType,
    TournamentTypeRule,
)
from app.db.models.enums import TournamentTypeStatus


@dataclass(frozen=True)
class TournamentTypeConfigRecord:
    tournament_type: TournamentType
    economy: TournamentEconomyConfig | None
    rebuys: list[TournamentRebuyConfig]
    rule: TournamentTypeRule | None


class TournamentTypeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, tournament_type_id: int) -> TournamentType | None:
        return await self.session.get(TournamentType, tournament_type_id)

    async def get_rule(self, tournament_type_id: int) -> TournamentTypeRule | None:
        result = await self.session.execute(
            select(TournamentTypeRule).where(
                TournamentTypeRule.tournament_type_id == tournament_type_id
            )
        )
        return result.scalar_one_or_none()

    async def get_rule_capabilities(self, tournament_type_id: int):
        result = await self.session.execute(
            select(
                TournamentTypeRule.knockout_mode,
                TournamentTypeRule.supports_bonus_points,
            ).where(TournamentTypeRule.tournament_type_id == tournament_type_id)
        )
        return result.one_or_none()

    async def list_active_real_types(self) -> list[TournamentType]:
        result = await self.session.execute(
            select(TournamentType)
            .where(
                TournamentType.status == TournamentTypeStatus.ACTIVE,
                TournamentType.code != "legacy_unknown",
            )
            .order_by(TournamentType.id)
        )
        return list(result.scalars())

    async def list_creatable_real_types(self) -> list[TournamentType]:
        result = await self.session.execute(
            select(TournamentType)
            .where(
                TournamentType.status == TournamentTypeStatus.ACTIVE,
                TournamentType.is_creatable.is_(True),
                TournamentType.code != "legacy_unknown",
            )
            .order_by(TournamentType.id)
        )
        return list(result.scalars())

    async def get_active_real_config(
        self,
        tournament_type_id: int,
        *,
        legacy_unknown_code: str,
    ) -> TournamentTypeConfigRecord | None:
        config = await self.get_config(tournament_type_id)
        if config is None:
            return None
        if (
            config.tournament_type.status != TournamentTypeStatus.ACTIVE
            or not config.tournament_type.is_creatable
            or config.tournament_type.code == legacy_unknown_code
            or config.economy is None
        ):
            return None
        return config

    async def get_config(self, tournament_type_id: int) -> TournamentTypeConfigRecord | None:
        tournament_type = await self.get_by_id(tournament_type_id)
        if tournament_type is None:
            return None
        economy_result = await self.session.execute(
            select(TournamentEconomyConfig).where(
                TournamentEconomyConfig.tournament_type_id == tournament_type_id
            )
        )
        rebuys_result = await self.session.execute(
            select(TournamentRebuyConfig)
            .where(TournamentRebuyConfig.tournament_type_id == tournament_type_id)
            .order_by(TournamentRebuyConfig.rebuy_order)
        )
        return TournamentTypeConfigRecord(
            tournament_type=tournament_type,
            economy=economy_result.scalar_one_or_none(),
            rebuys=list(rebuys_result.scalars()),
            rule=await self.get_rule(tournament_type_id),
        )

    async def list_rebuys_by_type_ids(
        self,
        tournament_type_ids: tuple[int, ...],
    ) -> dict[int, list[TournamentRebuyConfig]]:
        if not tournament_type_ids:
            return {}
        result = await self.session.execute(
            select(TournamentRebuyConfig)
            .where(TournamentRebuyConfig.tournament_type_id.in_(tournament_type_ids))
            .order_by(
                TournamentRebuyConfig.tournament_type_id,
                TournamentRebuyConfig.rebuy_order,
            )
        )
        rebuys_by_type_id: dict[int, list[TournamentRebuyConfig]] = {}
        for rebuy in result.scalars():
            rebuys_by_type_id.setdefault(rebuy.tournament_type_id, []).append(rebuy)
        return rebuys_by_type_id
