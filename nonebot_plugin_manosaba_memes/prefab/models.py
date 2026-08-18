import json
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .types import Color, Scale, Translation


class BlendMode(str, Enum):
    NORMAL = "normal"
    MULTIPLY = "multiply"
    SOFT_LIGHT = "soft_light"
    OVERLAY = "overlay"


class SpriteInfo(BaseModel):
    """Material/rendering information for a sprite."""

    blend_mode: BlendMode = BlendMode.NORMAL
    stencil_write: int | None = None
    stencil_read: int | None = None
    cutoff: float = 0.0
    color: Color = (1.0, 1.0, 1.0, 1.0)
    enabled: bool = False


class Node(BaseModel):
    """A node in the character hierarchy with optional sprite info."""

    name: str
    children: list[int] | None = None
    scale: Scale = (1.0, 1.0, 1.0)
    translation: Translation = (0.0, 0.0, 0.0)
    sprite: SpriteInfo | None = None  # Embedded sprite/material info


class CharacterData(BaseModel):
    """Complete character data from character.json."""

    character: str
    nodes: list[Node]

    model_config = ConfigDict(extra="allow")


class CompositionEntry(BaseModel):
    """A single composition map entry."""

    key: str = Field(..., alias="Key")
    composition: str = Field(..., alias="Composition")

    model_config = ConfigDict(populate_by_name=True)


class CompositionData(BaseModel):
    """Parsed composition data."""

    entries: dict[str, str] = Field(default_factory=dict)
    default_appearance: str = ""

    @classmethod
    def from_file(cls, path: Path) -> "CompositionData":
        """Load composition data from a JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        entries = {}
        for item in data.get("compositionMap", []):
            key = item.get("Key", "")
            composition = item.get("Composition", "")
            if key:
                entries[key] = composition

        return cls(
            entries=entries,
            default_appearance=data.get("defaultAppearance", ""),
        )
