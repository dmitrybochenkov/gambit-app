from app.db.models.enums import HallOfFameAchievementKind

SINGLETON_ACHIEVEMENT_KINDS = frozenset(
    {
        HallOfFameAchievementKind.RATING_WINNER,
        HallOfFameAchievementKind.KO_RATING_WINNER,
        HallOfFameAchievementKind.GRAND_SEASON,
    }
)

REPEATABLE_ACHIEVEMENT_KINDS = frozenset(
    {
        HallOfFameAchievementKind.GRAND_MONTH,
        HallOfFameAchievementKind.GRAND_KNOCKOUT,
    }
)
