"""The model a workspace, task, chat or automation runs on. Always the owner's choice."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ProviderMode = Literal["cli", "api"]


class ModelSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(pattern=r"^[a-z][a-z0-9-]{1,31}$")
    mode: ProviderMode
    model: str = Field(min_length=1, max_length=128)
    effort: str = Field(pattern=r"^[a-z]{1,16}$")
