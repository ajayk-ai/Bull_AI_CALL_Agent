from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# BCP-47 language tag as used across the platform, e.g. "ta-IN", "en-IN", "hi-IN".
LanguageCode = Annotated[str, StringConstraints(pattern=r"^[a-z]{2,3}-[A-Z]{2}$")]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Password = Annotated[str, StringConstraints(min_length=10, max_length=128)]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int


class PageParams(BaseModel):
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=200)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size
