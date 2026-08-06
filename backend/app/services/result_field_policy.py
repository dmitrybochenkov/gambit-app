from app.services.result_fields import ResultField


def is_result_field_allowed(
    *,
    field: ResultField,
    knockout_mode: str,
    supports_bonus_points: bool,
) -> bool:
    if field == ResultField.PLACE:
        return True
    if field == ResultField.BONUS:
        return supports_bonus_points
    if field == ResultField.KNOCKOUTS:
        return knockout_mode in {"small", "small_big"}
    if field == ResultField.BIG_KNOCKOUTS:
        return knockout_mode == "small_big"
    return False
