from app.db.models.enums import HallOfFameAchievementKind

ACHIEVEMENT_KIND_ORDER = (
    HallOfFameAchievementKind.GRAND_SEASON,
    HallOfFameAchievementKind.RATING_WINNER,
    HallOfFameAchievementKind.KO_RATING_WINNER,
    HallOfFameAchievementKind.GRAND_MONTH,
    HallOfFameAchievementKind.GRAND_KNOCKOUT,
)

ACHIEVEMENT_KIND_PRIORITY = {kind: index for index, kind in enumerate(ACHIEVEMENT_KIND_ORDER)}

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
