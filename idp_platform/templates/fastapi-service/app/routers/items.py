from threading import Lock
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/items", tags=["items"])


class ItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class Item(ItemIn):
    id: UUID


class ItemStore:
    """Thread-safe in-memory store (sync endpoints run in a thread pool).

    Data is lost on restart and not shared between replicas: swap this for a real
    database before relying on it.
    """

    def __init__(self) -> None:
        self._items: dict[UUID, Item] = {}
        self._lock = Lock()

    def page(self, offset: int, limit: int) -> list[Item]:
        with self._lock:
            return list(self._items.values())[offset : offset + limit]

    def add(self, payload: ItemIn) -> Item:
        item = Item(id=uuid4(), **payload.model_dump())
        with self._lock:
            self._items[item.id] = item
        return item

    def get(self, item_id: UUID) -> Item | None:
        with self._lock:
            return self._items.get(item_id)

    def replace(self, item_id: UUID, payload: ItemIn) -> Item | None:
        with self._lock:
            if item_id not in self._items:
                return None
            item = Item(id=item_id, **payload.model_dump())
            self._items[item_id] = item
            return item

    def delete(self, item_id: UUID) -> bool:
        with self._lock:
            return self._items.pop(item_id, None) is not None

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


store = ItemStore()


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")


@router.get("")
def list_items(
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[Item]:
    return store.page(offset, limit)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_item(payload: ItemIn) -> Item:
    return store.add(payload)


@router.get("/{item_id}")
def get_item(item_id: UUID) -> Item:
    item = store.get(item_id)
    if item is None:
        raise _not_found()
    return item


@router.put("/{item_id}")
def replace_item(item_id: UUID, payload: ItemIn) -> Item:
    item = store.replace(item_id, payload)
    if item is None:
        raise _not_found()
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(item_id: UUID) -> None:
    if not store.delete(item_id):
        raise _not_found()
