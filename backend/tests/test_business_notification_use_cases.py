from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage

from app.bot.telegram.business_notifications import TelegramTournamentCancellationDelivery
from app.db.models.enums import UserRole, UserStatus
from app.services.business_notification_use_cases import (
    CheckInUseCases,
    TournamentPlanningUseCases,
    TournamentRewardUseCases,
)
from app.services.dto.check_in import CheckInGenderDecision
from app.services.dto.tournaments import TournamentCancellationNotificationView, TournamentView
from app.services.dto.users import UserView


class RecordingDelivery:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def deliver(self, payload: object) -> None:
        self.calls.append(("deliver", payload))

    async def deliver_issued(self, payload: object) -> None:
        self.calls.append(("issued", payload))

    async def deliver_corrections(self, payload: object) -> None:
        self.calls.append(("corrections", payload))


class FailingDelivery(RecordingDelivery):
    async def deliver(self, payload: object) -> None:
        raise ConnectionError("network unavailable")

    async def deliver_issued(self, payload: object) -> None:
        raise ConnectionError("network unavailable")

    async def deliver_corrections(self, payload: object) -> None:
        raise ConnectionError("network unavailable")


@pytest.mark.asyncio
async def test_check_in_delivery_runs_after_service_and_skips_idempotent_result() -> None:
    created = SimpleNamespace(created=True, tournament=SimpleNamespace(id=10))
    existing = SimpleNamespace(created=False, tournament=SimpleNamespace(id=10))
    service = SimpleNamespace(complete_user_check_in=AsyncMock(side_effect=[created, existing]))
    delivery = RecordingDelivery()
    use_cases = CheckInUseCases(service)

    first = await use_cases.complete_user_check_in(
        actor_user_id=1,
        tournament_id=10,
        user_id=2,
        gender_decision=CheckInGenderDecision.KEEP,
        delivery=delivery,
    )
    second = await use_cases.complete_user_check_in(
        actor_user_id=1,
        tournament_id=10,
        user_id=2,
        gender_decision=CheckInGenderDecision.KEEP,
        delivery=delivery,
    )

    assert first is created
    assert second is existing
    assert delivery.calls == [("deliver", created)]


@pytest.mark.asyncio
async def test_notification_failure_does_not_replace_successful_mutation_result() -> None:
    check_in = SimpleNamespace(created=True)
    close = SimpleNamespace(newly_issued_rewards=(SimpleNamespace(reward_id=1),))
    correction = SimpleNamespace(player_notifications=(SimpleNamespace(player_id=2),))
    check_in_service = SimpleNamespace(complete_user_check_in=AsyncMock(return_value=check_in))
    result_service = SimpleNamespace(close_tournament=AsyncMock(return_value=close))
    correction_service = SimpleNamespace(
        apply_closed_tournament_correction=AsyncMock(return_value=correction)
    )
    delivery = FailingDelivery()

    assert (
        await CheckInUseCases(check_in_service).complete_user_check_in(
            actor_user_id=1,
            tournament_id=10,
            user_id=2,
            gender_decision=CheckInGenderDecision.KEEP,
            delivery=delivery,
        )
        is check_in
    )
    reward_use_cases = TournamentRewardUseCases(result_service, correction_service)
    assert (
        await reward_use_cases.close_tournament(
            actor_user_id=1,
            tournament_id=10,
            tournament_fund=1000,
            delivery=delivery,
        )
        is close
    )
    draft = SimpleNamespace(tournament_id=10)
    assert (
        await reward_use_cases.apply_closed_tournament_correction(
            actor_user_id=1,
            draft=draft,
            delivery=delivery,
        )
        is correction
    )


@pytest.mark.asyncio
async def test_cancellation_delivery_receives_all_committed_recipients() -> None:
    tournament = SimpleNamespace(id=10)
    recipients = (SimpleNamespace(user_id=2), SimpleNamespace(user_id=3))
    service = SimpleNamespace(
        delete_calendar_tournament=AsyncMock(return_value=(tournament, recipients))
    )
    delivery = RecordingDelivery()

    result = await TournamentPlanningUseCases(service).delete_calendar_tournament(
        actor_user_id=1,
        tournament_id=10,
        delivery=delivery,
    )

    assert result is tournament
    assert delivery.calls == [("deliver", recipients)]


@pytest.mark.asyncio
async def test_reward_delivery_only_runs_for_nonempty_service_outcomes() -> None:
    close = SimpleNamespace(newly_issued_rewards=())
    correction = SimpleNamespace(player_notifications=())
    result_service = SimpleNamespace(close_tournament=AsyncMock(return_value=close))
    correction_service = SimpleNamespace(
        apply_closed_tournament_correction=AsyncMock(return_value=correction)
    )
    delivery = RecordingDelivery()
    use_cases = TournamentRewardUseCases(result_service, correction_service)

    await use_cases.close_tournament(
        actor_user_id=1,
        tournament_id=10,
        tournament_fund=1000,
        delivery=delivery,
    )
    await use_cases.apply_closed_tournament_correction(
        actor_user_id=1,
        draft=SimpleNamespace(tournament_id=10),
        delivery=delivery,
    )

    assert delivery.calls == []


@pytest.mark.asyncio
async def test_cancellation_telegram_failure_does_not_block_later_recipient() -> None:
    users = SimpleNamespace(
        get_by_id=AsyncMock(
            side_effect=[
                UserView(2, 102, "First", UserStatus.ACTIVE, UserRole.PLAYER),
                UserView(3, 103, "Second", UserStatus.ACTIVE, UserRole.PLAYER),
            ]
        )
    )
    bot = SimpleNamespace(
        send_message=AsyncMock(
            side_effect=[
                TelegramBadRequest(
                    method=SendMessage(chat_id=102, text="x"),
                    message="blocked",
                ),
                None,
            ]
        )
    )
    tournament = TournamentView(10, date(2026, 10, 1), 1, "Классика")
    notifications = (
        TournamentCancellationNotificationView(2, tournament),
        TournamentCancellationNotificationView(3, tournament),
    )

    await TelegramTournamentCancellationDelivery(bot, users).deliver(notifications)

    assert bot.send_message.await_count == 2
    assert [call.kwargs["chat_id"] for call in bot.send_message.await_args_list] == [102, 103]
