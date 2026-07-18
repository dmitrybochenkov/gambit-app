from dataclasses import dataclass
from math import ceil
from typing import TypeVar

Item = TypeVar("Item")


@dataclass(frozen=True)
class Page[Item]:
    items: list[Item]
    page: int
    page_size: int
    total_items: int

    @property
    def total_pages(self) -> int:
        return max(1, ceil(self.total_items / self.page_size))

    @property
    def has_previous(self) -> bool:
        return self.page > 0

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages - 1

    @property
    def previous_page(self) -> int:
        return max(0, self.page - 1)

    @property
    def next_page(self) -> int:
        return min(self.total_pages - 1, self.page + 1)


class PaginationService:
    def paginate[Item](
        self,
        items: list[Item],
        page: int,
        page_size: int,
    ) -> Page[Item]:
        if page_size < 1:
            raise ValueError("page_size must be positive")

        total_pages = max(1, ceil(len(items) / page_size))
        normalized_page = min(max(0, page), total_pages - 1)
        start = normalized_page * page_size
        end = start + page_size
        return Page(
            items=items[start:end],
            page=normalized_page,
            page_size=page_size,
            total_items=len(items),
        )


pagination_service = PaginationService()
