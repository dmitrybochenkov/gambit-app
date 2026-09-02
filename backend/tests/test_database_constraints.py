from datetime import date
from decimal import Decimal

import pytest
from conftest import seed_tournament_types, tournament_type_id
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.factories import create_user
from app.db.models import (
    ScoringConfig,
    Season,
    SeasonHallOfFame,
    Tournament,
    TournamentResult,
    User,
)
from app.db.models.enums import TournamentResultSource, TournamentStatus, UserGender, UserStatus


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        yield session

    engine.dispose()


def test_player_requires_display_name(session: Session) -> None:
    session.add(User(telegram_id=1, display_name_normalized="test"))

    with pytest.raises(IntegrityError):
        session.commit()


def test_admin_prompts_table_is_removed(session: Session) -> None:
    tables = {
        row[0]
        for row in session.execute(
            text("SELECT name FROM sqlite_master WHERE type = 'table'")
        ).all()
    }

    assert "admin_prompts" not in tables


def test_new_season_defaults_to_statistics_visible(session: Session) -> None:
    scoring_config = ScoringConfig()
    session.add(scoring_config)
    session.flush()
    session.add(
        Season(
            name="Visible season",
            scoring_config_id=scoring_config.id,
            starts_at=date(2026, 1, 1),
        )
    )

    session.commit()

    season = session.query(Season).filter_by(name="Visible season").one()
    assert season.is_statistics_visible is True


def test_user_gender_is_nullable_and_accepts_known_values(session: Session) -> None:
    unknown = create_user(display_name="Unknown")
    female = create_user(display_name="Female", gender=UserGender.FEMALE)
    male = create_user(display_name="Male", gender=UserGender.MALE)
    session.add_all([unknown, female, male])

    session.commit()

    assert unknown.gender is None
    assert female.gender == UserGender.FEMALE
    assert male.gender == UserGender.MALE


@pytest.mark.parametrize(
    ("table_name", "column_name", "invalid_value", "insert_sql"),
    [
        (
            "users",
            "role",
            "root",
            """
            INSERT INTO users (
                display_name, display_name_normalized, role, status, created_at, updated_at
            )
            VALUES (
                'Invalid', 'invalid', :invalid_value, 'active',
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """,
        ),
        (
            "users",
            "status",
            "weird",
            """
            INSERT INTO users (
                display_name, display_name_normalized, role, status, created_at, updated_at
            )
            VALUES (
                'Invalid', 'invalid', 'player', :invalid_value,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """,
        ),
        (
            "users",
            "gender",
            "other",
            """
            INSERT INTO users (
                display_name, display_name_normalized, role, status, gender, created_at, updated_at
            )
            VALUES (
                'Invalid', 'invalid', 'player', 'active', :invalid_value,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """,
        ),
        (
            "tournaments",
            "status",
            "weird",
            """
            INSERT INTO tournaments (
                season_id, tournament_type_id, date, status, tournament_fund, created_at, updated_at
            )
            VALUES (1, 1, '2026-07-20', :invalid_value, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
        ),
        (
            "tournament_types",
            "status",
            "weird",
            """
            INSERT INTO tournament_types (
                code, name, short_name, is_creatable, status, created_at, updated_at
            )
            VALUES (
                'invalid_status', 'Invalid', 'Invalid', 0, :invalid_value,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """,
        ),
        (
            "tournament_type_rules",
            "knockout_mode",
            "weird",
            """
            INSERT INTO tournament_type_rules (
                tournament_type_id, points_multiplier, prize_place_multiplier,
                knockout_mode, supports_bonus_points, created_at, updated_at
            )
            VALUES (1, 1, 1, :invalid_value, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
        ),
        (
            "registration_requests",
            "request_type",
            "weird",
            """
            INSERT INTO registration_requests (
                telegram_id, request_type, status, requested_display_name,
                requested_display_name_normalized, requested_link_name,
                candidate_user_id, reviewed_at, created_at, updated_at
            )
            VALUES (
                1000, :invalid_value, 'pending', 'Игрок', 'игрок',
                NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """,
        ),
        (
            "registration_requests",
            "status",
            "weird",
            """
            INSERT INTO registration_requests (
                telegram_id, request_type, status, requested_display_name,
                requested_display_name_normalized, requested_link_name,
                candidate_user_id, reviewed_at, created_at, updated_at
            )
            VALUES (
                1001, 'new_player', :invalid_value, 'Игрок', 'игрок',
                NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """,
        ),
        (
            "tournament_results",
            "source",
            "weird",
            """
            INSERT INTO tournament_results (
                tournament_id, player_id, source, checked_in_by_user_id, checked_in_at,
                place, knockouts_count, big_knockouts_count, tournament_points,
                knockout_points, bonus_points, created_at, updated_at
            )
            VALUES (
                1, 1, :invalid_value, NULL, CURRENT_TIMESTAMP, NULL, 0, 0, 0, 0, 0,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """,
        ),
    ],
)
def test_persisted_enums_reject_unknown_values(
    session: Session,
    table_name: str,
    column_name: str,
    invalid_value: str,
    insert_sql: str,
) -> None:
    if table_name in {"tournaments", "tournament_results"}:
        session.add(scoring_config := ScoringConfig())
        session.commit()
        session.add(
            Season(
                name="Enum season",
                scoring_config_id=scoring_config.id,
                starts_at=date(2026, 7, 1),
            )
        )
        session.commit()
        session.execute(
            text(
                """
                INSERT OR IGNORE INTO tournament_types (
                    id, code, name, short_name, is_creatable, status, created_at, updated_at
                )
                VALUES (
                    1, 'enum_type', 'Enum type', 'Enum type', 0, 'active',
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """
            )
        )
        session.commit()
        if table_name == "tournament_results":
            session.execute(
                text(
                    """
                    INSERT INTO tournaments (
                        id, season_id, tournament_type_id, date, status, tournament_fund,
                        created_at, updated_at
                    )
                    VALUES (
                        1, 1, 1, '2026-07-20', 'active', NULL,
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            session.execute(
                text(
                    """
                    INSERT OR IGNORE INTO users (
                        id, display_name, display_name_normalized, role, status,
                        created_at, updated_at
                    )
                    VALUES (1, 'Enum player', 'enum player', 'player', 'active',
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """
                )
            )
            session.commit()
    elif table_name == "tournament_type_rules":
        session.execute(
            text(
                """
                INSERT OR IGNORE INTO tournament_types (
                    id, code, name, short_name, is_creatable, status, created_at, updated_at
                )
                VALUES (
                    1, 'enum_rule_type', 'Enum rule type', 'Enum rule type', 0, 'active',
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """
            )
        )
        session.commit()

    with pytest.raises(IntegrityError):
        session.execute(text(insert_sql), {"invalid_value": invalid_value})


def test_tournament_registration_has_only_created_at_timestamp(session: Session) -> None:
    columns = {
        row[1] for row in session.execute(text("PRAGMA table_info(tournament_registrations)")).all()
    }

    assert "created_at" in columns
    assert "updated_at" not in columns


def test_registration_request_telegram_id_is_required(session: Session) -> None:
    columns = {
        row[1]: row[3]
        for row in session.execute(text("PRAGMA table_info(registration_requests)")).all()
    }

    assert columns["telegram_id"] == 1


def test_registration_request_rejects_null_telegram_id(session: Session) -> None:
    with pytest.raises(IntegrityError):
        session.execute(
            text(
                """
                INSERT INTO registration_requests (
                    telegram_id, request_type, status, requested_display_name,
                    requested_display_name_normalized, requested_link_name,
                    candidate_user_id, reviewed_at, created_at, updated_at
                )
                VALUES (
                    NULL, 'new_player', 'pending', 'Игрок', 'игрок', NULL,
                    NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """
            )
        )


def test_registration_request_rejection_reason_is_absent(session: Session) -> None:
    columns = {
        row[1] for row in session.execute(text("PRAGMA table_info(registration_requests)")).all()
    }

    assert "rejection_reason" not in columns


def test_imported_closed_tournament_allows_null_fund(session: Session) -> None:
    scoring_config = ScoringConfig()
    session.add(scoring_config)
    session.flush()
    seed_tournament_types(session)

    season = Season(
        name="Season 1",
        scoring_config_id=scoring_config.id,
        starts_at=date(2026, 1, 1),
        ends_at=None,
    )
    session.add(season)
    session.commit()

    session.add(
        Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("bounty"),
            date=date(2026, 7, 4),
            tournament_fund=None,
            status=TournamentStatus.CLOSED,
        )
    )

    session.commit()


def test_tournament_date_must_be_unique(session: Session) -> None:
    scoring_config = ScoringConfig()
    session.add(scoring_config)
    session.flush()
    seed_tournament_types(session)

    season = Season(
        name="Season 1",
        scoring_config_id=scoring_config.id,
        starts_at=date(2026, 1, 1),
        ends_at=None,
    )
    session.add(season)
    session.flush()
    session.add_all(
        [
            Tournament(
                season_id=season.id,
                tournament_type_id=tournament_type_id("bounty"),
                date=date(2026, 7, 4),
                status=TournamentStatus.ACTIVE,
            ),
            Tournament(
                season_id=season.id,
                tournament_type_id=tournament_type_id("classic"),
                date=date(2026, 7, 4),
                status=TournamentStatus.ACTIVE,
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_scoring_coefficients_must_total_one(session: Session) -> None:
    session.add(
        ScoringConfig(
            place_1_coefficient=Decimal("0.40"),
            place_2_coefficient=Decimal("0.25"),
            place_3_coefficient=Decimal("0.15"),
            place_4_coefficient=Decimal("0.10"),
            place_5_coefficient=Decimal("0.05"),
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_season_may_have_valid_end_date(session: Session) -> None:
    scoring_config = ScoringConfig()
    session.add(scoring_config)
    session.flush()

    session.add(
        Season(
            name="Season 1",
            scoring_config_id=scoring_config.id,
            starts_at=date(2026, 1, 1),
            ends_at=date(2026, 12, 31),
        )
    )

    session.commit()


def test_season_may_be_open_ended(session: Session) -> None:
    scoring_config = ScoringConfig()
    session.add(scoring_config)
    session.flush()

    session.add(
        Season(
            name="Season 1",
            scoring_config_id=scoring_config.id,
            starts_at=date(2026, 1, 1),
            ends_at=None,
        )
    )

    session.commit()


def test_closed_season_end_date_must_not_precede_start_date(session: Session) -> None:
    scoring_config = ScoringConfig()
    session.add(scoring_config)
    session.flush()

    session.add(
        Season(
            name="Season 1",
            scoring_config_id=scoring_config.id,
            starts_at=date(2026, 1, 2),
            ends_at=date(2026, 1, 1),
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_database_rejects_multiple_open_ended_seasons(
    session: Session,
) -> None:
    scoring_config = ScoringConfig()
    session.add(scoring_config)
    session.flush()

    session.add_all(
        [
            Season(
                name="Season 1",
                scoring_config_id=scoring_config.id,
                starts_at=date(2026, 1, 1),
                ends_at=None,
            ),
            Season(
                name="Season 2",
                scoring_config_id=scoring_config.id,
                starts_at=date(2026, 6, 1),
                ends_at=None,
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_tournament_result_bonus_points_must_be_nonnegative(
    session: Session,
) -> None:
    scoring_config = ScoringConfig()
    player = create_user(
        telegram_id=1,
        display_name="Игрок Первый",
        status=UserStatus.ACTIVE,
    )
    session.add_all([scoring_config, player])
    session.flush()
    seed_tournament_types(session)

    season = Season(
        name="Season 1",
        scoring_config_id=scoring_config.id,
        starts_at=date(2026, 1, 1),
        ends_at=None,
    )
    session.add(season)
    session.flush()
    tournament = Tournament(
        season_id=season.id,
        tournament_type_id=tournament_type_id("bounty"),
        date=date(2026, 7, 4),
        status=TournamentStatus.ACTIVE,
    )
    session.add(tournament)
    session.flush()

    session.add(
        TournamentResult(
            tournament_id=tournament.id,
            player_id=player.id,
            place=1,
            knockouts_count=0,
            big_knockouts_count=0,
            tournament_points=Decimal("0"),
            knockout_points=Decimal("0"),
            bonus_points=-1,
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_tournament_result_bonus_points_must_be_integer(
    session: Session,
) -> None:
    tournament, player, _other = _seed_result_context(session)

    with pytest.raises(IntegrityError):
        session.execute(
            text(
                """
                INSERT INTO tournament_results (
                    tournament_id, player_id, source, checked_in_at,
                    place, knockouts_count, big_knockouts_count,
                    tournament_points, knockout_points, bonus_points,
                    created_at, updated_at
                )
                VALUES (
                    :tournament_id, :player_id, 'walk_in_existing', CURRENT_TIMESTAMP,
                    NULL, 0, 0, 0, 0, 1.5, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """
            ),
            {"tournament_id": tournament.id, "player_id": player.id},
        )


def _seed_result_context(session: Session, tournament_date: date = date(2026, 7, 4)):
    telegram_offset = int(tournament_date.strftime("%m%d"))
    scoring_config = ScoringConfig()
    player = create_user(
        telegram_id=telegram_offset * 10 + 1,
        display_name=f"Игрок {tournament_date.isoformat()}",
        status=UserStatus.ACTIVE,
    )
    other = create_user(
        telegram_id=telegram_offset * 10 + 2,
        display_name=f"Другой {tournament_date.isoformat()}",
        status=UserStatus.ACTIVE,
    )
    session.add_all([scoring_config, player, other])
    session.flush()
    if not session.info.get("tournament_types_seeded"):
        seed_tournament_types(session)
        session.info["tournament_types_seeded"] = True
    season = Season(
        name=f"Season {tournament_date.isoformat()}",
        scoring_config_id=scoring_config.id,
        starts_at=date(2026, 1, 1),
        ends_at=None,
    )
    session.add(season)
    session.flush()
    tournament = Tournament(
        season_id=season.id,
        tournament_type_id=tournament_type_id("bounty"),
        date=tournament_date,
        status=TournamentStatus.ACTIVE,
    )
    session.add(tournament)
    session.flush()
    return tournament, player, other


def _result(tournament_id: int, player_id: int, place: int | None = None) -> TournamentResult:
    return TournamentResult(
        tournament_id=tournament_id,
        player_id=player_id,
        source=TournamentResultSource.WALK_IN_EXISTING,
        place=place,
        knockouts_count=0,
        big_knockouts_count=0,
        tournament_points=Decimal("0"),
        knockout_points=Decimal("0"),
        bonus_points=0,
    )


@pytest.mark.parametrize(
    "source",
    [
        TournamentResultSource.REGISTERED,
        TournamentResultSource.WALK_IN_EXISTING,
        TournamentResultSource.WALK_IN_NEW,
    ],
)
def test_tournament_result_source_accepts_enum_values(
    session: Session,
    source: TournamentResultSource,
) -> None:
    tournament, player, _other = _seed_result_context(session)

    result = _result(tournament.id, player.id)
    result.source = source
    session.add(result)

    session.commit()


def test_tournament_result_source_rejects_invalid_raw_value(session: Session) -> None:
    tournament, player, _other = _seed_result_context(session)

    with pytest.raises(IntegrityError):
        session.execute(
            text(
                """
                INSERT INTO tournament_results (
                    tournament_id, player_id, source, checked_in_at,
                    knockouts_count, big_knockouts_count,
                    tournament_points, knockout_points, bonus_points,
                    created_at, updated_at
                )
                VALUES (
                    :tournament_id, :player_id, 'invalid', CURRENT_TIMESTAMP,
                    0, 0, 0, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """
            ),
            {"tournament_id": tournament.id, "player_id": player.id},
        )


@pytest.mark.parametrize("place", [1, 2, 3, 4, 5, None])
def test_tournament_result_place_accepts_valid_range(session: Session, place: int | None) -> None:
    tournament, player, _other = _seed_result_context(session)

    session.add(_result(tournament.id, player.id, place=place))

    session.commit()


@pytest.mark.parametrize("place", [0, -1, 6])
def test_tournament_result_place_rejects_invalid_range(session: Session, place: int) -> None:
    tournament, player, _other = _seed_result_context(session)

    session.add(_result(tournament.id, player.id, place=place))

    with pytest.raises(IntegrityError):
        session.commit()


def test_tournament_result_place_allows_ties_inside_tournament(session: Session) -> None:
    tournament, player, other = _seed_result_context(session)
    session.add_all(
        [
            _result(tournament.id, player.id, place=1),
            _result(tournament.id, other.id, place=1),
        ]
    )

    session.commit()


def test_tournament_result_player_is_unique_inside_tournament(session: Session) -> None:
    tournament, player, _other = _seed_result_context(session)
    session.add_all(
        [
            _result(tournament.id, player.id, place=1),
            _result(tournament.id, player.id, place=2),
        ]
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_tournament_result_same_place_is_allowed_in_different_tournaments(session: Session) -> None:
    first, player, _other = _seed_result_context(session, date(2026, 7, 4))
    other = create_user(
        telegram_id=7052,
        display_name="Другой турнир",
        status=UserStatus.ACTIVE,
    )
    session.add(other)
    session.flush()
    second = Tournament(
        season_id=first.season_id,
        tournament_type_id=tournament_type_id("classic"),
        date=date(2026, 7, 5),
        status=TournamentStatus.ACTIVE,
    )
    session.add(second)
    session.flush()
    session.add_all(
        [
            _result(first.id, player.id, place=1),
            _result(second.id, other.id, place=1),
        ]
    )

    session.commit()


@pytest.mark.parametrize("fund", [100, 1250])
def test_closed_tournament_accepts_valid_integer_fund(session: Session, fund: int) -> None:
    scoring_config = ScoringConfig()
    session.add(scoring_config)
    session.flush()
    seed_tournament_types(session)
    season = Season(
        name=f"Fund {fund}",
        scoring_config_id=scoring_config.id,
        starts_at=date(2026, 1, 1),
        ends_at=None,
    )
    session.add(season)
    session.flush()
    session.add(
        Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("bounty"),
            date=date(2026, 8, 1),
            tournament_fund=fund,
            status=TournamentStatus.CLOSED,
        )
    )

    session.commit()


@pytest.mark.parametrize("fund", [0, -10, 105])
def test_tournament_rejects_invalid_fund(session: Session, fund: int) -> None:
    scoring_config = ScoringConfig()
    session.add(scoring_config)
    session.flush()
    seed_tournament_types(session)
    season = Season(
        name=f"Bad fund {fund}",
        scoring_config_id=scoring_config.id,
        starts_at=date(2026, 1, 1),
        ends_at=None,
    )
    session.add(season)
    session.flush()
    session.add(
        Tournament(
            season_id=season.id,
            tournament_type_id=tournament_type_id("bounty"),
            date=date(2026, 8, 1),
            tournament_fund=fund,
            status=TournamentStatus.CLOSED,
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_cancelled_tournament_status_is_rejected(session: Session) -> None:
    scoring_config = ScoringConfig()
    session.add(scoring_config)
    session.flush()
    seed_tournament_types(session)
    season = Season(
        name="Cancelled date",
        scoring_config_id=scoring_config.id,
        starts_at=date(2026, 1, 1),
        ends_at=None,
    )
    session.add(season)
    session.flush()
    with pytest.raises(IntegrityError):
        session.execute(
            text(
                """
                INSERT INTO tournaments (
                    season_id, tournament_type_id, date, status, tournament_fund,
                    created_at, updated_at
                )
                VALUES (:season_id, :type_id, '2026-08-01', 'cancelled', NULL,
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            ),
            {
                "season_id": season.id,
                "type_id": tournament_type_id("bounty"),
            },
        )


def test_season_hall_of_fame_allows_partial_and_same_winner(session: Session) -> None:
    scoring_config = ScoringConfig()
    user = create_user(telegram_id=1, display_name="Winner")
    session.add_all([scoring_config, user])
    session.flush()
    season = Season(
        name="Hall season",
        scoring_config_id=scoring_config.id,
        starts_at=date(2026, 1, 1),
        ends_at=date(2026, 3, 31),
    )
    session.add(season)
    session.flush()
    session.add(
        SeasonHallOfFame(
            season_id=season.id,
            champion_player_id=user.id,
            knockout_player_id=user.id,
            updated_by_user_id=user.id,
        )
    )

    session.commit()


def test_season_hall_of_fame_requires_unique_season(session: Session) -> None:
    scoring_config = ScoringConfig()
    user = create_user(telegram_id=1, display_name="Winner")
    session.add_all([scoring_config, user])
    session.flush()
    season = Season(
        name="Hall season unique",
        scoring_config_id=scoring_config.id,
        starts_at=date(2026, 1, 1),
        ends_at=date(2026, 3, 31),
    )
    session.add(season)
    session.flush()
    session.add_all(
        [
            SeasonHallOfFame(
                season_id=season.id,
                champion_player_id=None,
                knockout_player_id=None,
                updated_by_user_id=user.id,
            ),
            SeasonHallOfFame(
                season_id=season.id,
                champion_player_id=user.id,
                knockout_player_id=None,
                updated_by_user_id=user.id,
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        session.commit()
