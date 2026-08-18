import asyncio
import hashlib
import json
import logging
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = 2
CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
CODE_LENGTH = 10
logger = logging.getLogger(__name__)
PickerKind = Literal["preset", "head", "expression", "eyes", "mouth", "detail", "arm"]


class SpriteRecipe(BaseModel):
    base_preset: str
    overrides: list[str] = Field(default_factory=list)


class StoredSprite(BaseModel):
    character: str
    recipe: SpriteRecipe


class MessageContext(BaseModel):
    kind: Literal["sprite", "picker"]
    character: str
    sprite: str | None = None
    base_sprite: str | None = None
    picker: PickerKind | None = None
    page: int = 0
    choices: list[str] = Field(default_factory=list)
    global_numbering: bool = False


class SpriteSessionData(BaseModel):
    schema_version: int = SCHEMA_VERSION
    sprites: dict[str, StoredSprite] = Field(default_factory=dict)
    messages: dict[str, MessageContext] = Field(default_factory=dict)


def canonical_recipe(recipe: SpriteRecipe) -> SpriteRecipe:
    """Normalize equivalent edit orders into one content identity."""
    category_order = {
        "arms": 0,
        "expression": 1,
        "eyes": 2,
        "mouth": 3,
        "cheeks": 4,
        "sweat": 5,
        "pale": 6,
    }
    categorized: dict[str, str] = {}
    uncategorized: set[str] = set()
    for override in recipe.overrides:
        category = override_category(override)
        if category is None:
            uncategorized.add(override)
        else:
            categorized[category] = override
    overrides = sorted(uncategorized)
    overrides.extend(
        value
        for category, value in sorted(
            categorized.items(), key=lambda item: category_order[item[0]]
        )
    )
    return SpriteRecipe(
        base_preset=recipe.base_preset,
        overrides=overrides,
    )


def sprite_code(character: str, recipe: SpriteRecipe) -> str:
    canonical = canonical_recipe(recipe)
    payload = json.dumps(
        {
            "character": character,
            "base_preset": canonical.base_preset,
            "overrides": canonical.overrides,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    value = int.from_bytes(hashlib.sha256(payload).digest(), "big")
    characters = []
    for _ in range(CODE_LENGTH):
        value, remainder = divmod(value, len(CODE_ALPHABET))
        characters.append(CODE_ALPHABET[remainder])
    return "".join(reversed(characters))


def parse_ref(value: str) -> str | None:
    code = value.strip().upper().removeprefix("#")
    if len(code) != CODE_LENGTH or any(char not in CODE_ALPHABET for char in code):
        return None
    return code


def replace_override(overrides: list[str], value: str) -> list[str]:
    """Replace an override in the same visual category, preserving the rest."""
    category = override_category(value)
    if category is None:
        return [*overrides, value]
    return [item for item in overrides if override_category(item) != category] + [value]


def replace_arm_override(overrides: list[str], value: str) -> list[str]:
    """Replace a complete, officially observed arm combination."""
    return [item for item in overrides if override_category(item) != "arms"] + [value]


def replace_expression_override(overrides: list[str], value: str) -> list[str]:
    """Replace a complete expression and its independent eye/mouth patches."""
    face_categories = {"expression", "eyes", "mouth"}
    return [
        item for item in overrides if override_category(item) not in face_categories
    ] + [value]


def replace_head_override(overrides: list[str], value: str) -> list[str]:
    """Switch head branch and reset overrides tied to the previous face."""
    head_categories = {"expression", "eyes", "mouth", "cheeks", "sweat", "pale"}
    return [
        item for item in overrides if override_category(item) not in head_categories
    ] + [value]


def override_category(value: str) -> str | None:
    lowered = value.lower()
    tokens = [token.strip() for token in lowered.split(",") if token.strip()]
    if tokens and all(_is_arm_token(token) for token in tokens):
        return "arms"
    for category in ("eyes", "mouth", "cheeks", "sweat", "pale"):
        if lowered.startswith(category):
            return category
    if any(token.startswith("eyes") or "/eyes" in token for token in tokens):
        return "eyes"
    if any(token.startswith("mouth") or "/mouth" in token for token in tokens):
        return "mouth"
    for expression in (
        "default",
        "normal",
        "smile",
        "angry",
        "determined",
        "pensive",
        "cry",
        "flushed",
        "surprised",
        "fearful",
    ):
        if lowered.startswith(expression):
            return "expression"
    return None


def _is_arm_token(token: str) -> bool:
    return (
        token.startswith("arm")
        or "/arm" in token
        or "/option_arm" in token
        or "/effect_back_arm" in token
    )


class SessionStore:
    """Atomic, indefinitely persistent storage for sprites and picker replies."""

    def __init__(self, path: Path):
        self.path = path
        self.data = SpriteSessionData()
        self.lock = asyncio.Lock()
        self._loaded = False

    async def load(self) -> SpriteSessionData:
        async with self.lock:
            if self._loaded:
                return self.data
            self.data = await asyncio.to_thread(self._load_sync)
            self._loaded = True
            return self.data

    def _load_sync(self) -> SpriteSessionData:
        if not self.path.exists():
            return SpriteSessionData()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            version = raw.get("schema_version")
            if version != SCHEMA_VERSION:
                raise ValueError(
                    f"unsupported sprite session schema {version!r}; "
                    f"expected {SCHEMA_VERSION}"
                )
            return SpriteSessionData.model_validate(raw)
        except Exception:
            logger.exception(
                "Failed to load sprite session data; preserving it as broken"
            )
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            broken = self.path.with_name(f"{self.path.name}.broken.{timestamp}")
            counter = 1
            while broken.exists():
                broken = self.path.with_name(
                    f"{self.path.name}.broken.{timestamp}.{counter}"
                )
                counter += 1
            os.replace(self.path, broken)
            return SpriteSessionData()

    async def save(self) -> None:
        async with self.lock:
            await self._save_locked()

    async def _save_locked(self) -> None:
        payload = self.data.model_dump_json(indent=2)
        await asyncio.to_thread(self._write_atomic, payload)

    def _write_atomic(self, payload: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(
            f".{self.path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
        )
        try:
            with temporary.open("w", encoding="utf-8") as file:
                file.write(payload)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    async def put_sprite(
        self,
        character: str,
        recipe: SpriteRecipe,
        *,
        code: str | None = None,
    ) -> str:
        await self.load()
        async with self.lock:
            recipe = canonical_recipe(recipe)
            if code is None:
                # Retained for callers and persisted shortcodes created before
                # the reversible codec was introduced.
                code = sprite_code(character, recipe)
            else:
                parsed = parse_ref(code)
                if parsed is None:
                    raise ValueError(f"invalid sprite code: {code}")
                code = parsed
            stored = StoredSprite(character=character, recipe=recipe)
            existing = self.data.sprites.get(code)
            if existing is not None and existing != stored:
                raise RuntimeError(f"sprite content-code collision: {code}")
            if existing is None:
                self.data.sprites[code] = stored
                await self._save_locked()
            return code

    async def get_sprite(self, code: str) -> StoredSprite | None:
        await self.load()
        sprite = self.data.sprites.get(code)
        return sprite.model_copy(deep=True) if sprite else None

    async def set_message(self, key: str, context: MessageContext) -> None:
        await self.load()
        async with self.lock:
            self.data.messages[key] = context.model_copy(deep=True)
            await self._save_locked()

    async def get_message(self, key: str) -> MessageContext | None:
        await self.load()
        context = self.data.messages.get(key)
        return context.model_copy(deep=True) if context else None
