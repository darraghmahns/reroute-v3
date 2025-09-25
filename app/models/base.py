from typing import Any

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    def as_dict(self) -> dict[str, Any]:
        return {column.key: getattr(self, column.key) for column in self.__table__.columns}
