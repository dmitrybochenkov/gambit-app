from pydantic import BaseModel


class PhotoDescriptorResponse(BaseModel):
    id: int
    position: int
    content_url: str

    @classmethod
    def tournament_photo(cls, *, photo_id: int, position: int) -> "PhotoDescriptorResponse":
        return cls(
            id=photo_id,
            position=position,
            content_url=f"/api/v1/media/tournament-photos/{photo_id}/content",
        )

    @classmethod
    def hall_of_fame_photo(
        cls,
        *,
        photo_id: int,
        position: int,
    ) -> "PhotoDescriptorResponse":
        return cls(
            id=photo_id,
            position=position,
            content_url=f"/api/v1/media/hall-of-fame-photos/{photo_id}/content",
        )
