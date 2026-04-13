"""Base repository with common async CRUD operations.

All entity-specific repositories inherit from this base.
"""

from __future__ import annotations

import uuid
from typing import Any, Generic, Sequence, TypeVar

from sqlalchemy import Select, select, func, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from data.base import Base

T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    """Generic async repository providing CRUD primitives.

    Subclasses set `model` to the SQLAlchemy model class and add
    domain-specific query methods.
    """

    model: type[T]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, id_: uuid.UUID) -> T | None:
        """Fetch a single record by primary key."""
        return await self.session.get(self.model, id_)

    async def get_all(
        self, *, offset: int = 0, limit: int = 100
    ) -> Sequence[T]:
        """Fetch records with pagination."""
        stmt = select(self.model).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def create(self, entity: T) -> T:
        """Add a new entity and flush to get its ID."""
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def create_many(self, entities: list[T]) -> list[T]:
        """Add multiple entities in batch."""
        self.session.add_all(entities)
        await self.session.flush()
        return entities

    async def update(self, entity: T, **values: Any) -> T:
        """Update an entity's attributes."""
        for key, value in values.items():
            setattr(entity, key, value)
        await self.session.flush()
        return entity

    async def delete(self, entity: T) -> None:
        """Remove an entity."""
        await self.session.delete(entity)
        await self.session.flush()

    async def count(self) -> int:
        """Return total row count for the model."""
        stmt = select(func.count()).select_from(self.model)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def exists(self, id_: uuid.UUID) -> bool:
        """Check if a record with the given ID exists."""
        entity = await self.get_by_id(id_)
        return entity is not None

    def _query(self) -> Select:
        """Return a base select statement for the model."""
        return select(self.model)
