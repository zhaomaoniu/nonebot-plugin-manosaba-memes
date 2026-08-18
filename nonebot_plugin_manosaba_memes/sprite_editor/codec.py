import hashlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from ..models import Character
from ..prefab import Prefab
from .presets import PresetCatalog
from .state import (
    CODE_ALPHABET,
    CODE_LENGTH,
    SpriteRecipe,
    canonical_recipe,
    override_category,
    parse_ref,
)

CODE_PREFIX = "C"
CHECKSUM_BITS = 6
INDEX_BITS = (CODE_LENGTH - 1) * 5 - CHECKSUM_BITS
CATEGORY_ORDER = ("arms", "expression", "eyes", "mouth", "cheeks", "sweat", "pale")
_CHECKSUM_SALT = b"manosaba-sprite-recipe-v1"
_INDEX_MASK = int.from_bytes(
    hashlib.sha256(_CHECKSUM_SALT + b"-mask").digest()[:5], "big"
) & ((1 << INDEX_BITS) - 1)


@dataclass(frozen=True)
class CharacterRecipeRegistry:
    character: str
    presets: tuple[str, ...]
    choices: tuple[tuple[str, tuple[str, ...]], ...]
    space: int


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(values)))


class RecipeCodec:
    """Reversible ten-character recipe codes for the fixed prefab catalog."""

    def __init__(
        self,
        catalog: PresetCatalog,
        prefab_loader: Callable[[str], Prefab],
    ):
        self.catalog = catalog
        self.prefab_loader = prefab_loader
        self._registries: tuple[CharacterRecipeRegistry, ...] | None = None

    @property
    def registries(self) -> tuple[CharacterRecipeRegistry, ...]:
        if self._registries is None:
            self._registries = tuple(
                self._build_registry(character.value) for character in Character
            )
            total_space = sum(registry.space for registry in self._registries)
            if len(CODE_ALPHABET) != 32 or total_space > 1 << INDEX_BITS:
                raise RuntimeError("sprite recipe registry exceeds shortcode capacity")
        return self._registries

    def _build_registry(self, character: str) -> CharacterRecipeRegistry:
        prefab = self.prefab_loader(character)
        # Encoding indexes must not inherit presentation/ranking order. Sorting
        # makes the codebook depend only on the fixed resource names.
        presets = tuple(sorted(preset.id for preset in self.catalog.presets(character)))
        expressions = _unique(
            [
                *self.catalog.expression_choices(prefab),
                *self.catalog.head_choices(character, prefab),
            ]
        )
        details = self.catalog.detail_choices(prefab)
        values = {
            "arms": tuple(sorted(self.catalog.arm_choices(character))),
            "expression": expressions,
            "eyes": tuple(
                sorted(self.catalog.face_part_choices(character, prefab, "eyes"))
            ),
            "mouth": tuple(
                sorted(self.catalog.face_part_choices(character, prefab, "mouth"))
            ),
            **{
                category: tuple(
                    sorted(
                        choice
                        for choice in details
                        if override_category(choice) == category
                    )
                )
                for category in ("cheeks", "sweat", "pale")
            },
        }
        choices = tuple((category, values[category]) for category in CATEGORY_ORDER)
        space = len(presets)
        for _, category_choices in choices:
            space *= len(category_choices) + 1
        return CharacterRecipeRegistry(
            character=character,
            presets=presets,
            choices=choices,
            space=space,
        )

    def encode(self, character: str, recipe: SpriteRecipe) -> str:
        canonical = canonical_recipe(recipe)
        offset = 0
        registry = None
        for candidate in self.registries:
            if candidate.character == character:
                registry = candidate
                break
            offset += candidate.space
        if registry is None:
            raise ValueError(f"unsupported sprite character: {character}")

        try:
            value = registry.presets.index(canonical.base_preset)
        except ValueError as error:
            raise ValueError(
                f"preset is not encodable for {character}: {canonical.base_preset}"
            ) from error

        by_category: dict[str, str] = {}
        for override in canonical.overrides:
            category = override_category(override)
            if category not in CATEGORY_ORDER:
                raise ValueError(f"override is not encodable: {override}")
            by_category[category] = override

        multiplier = len(registry.presets)
        for category, choices in registry.choices:
            override = by_category.get(category)
            try:
                digit = 0 if override is None else choices.index(override) + 1
            except ValueError as error:
                raise ValueError(
                    f"{category} override is not encodable for {character}: {override}"
                ) from error
            value += multiplier * digit
            multiplier *= len(choices) + 1

        global_index = offset + value
        encoded_index = global_index ^ _INDEX_MASK
        body = (encoded_index << CHECKSUM_BITS) | self._checksum(global_index)
        return CODE_PREFIX + self._encode_integer(body, CODE_LENGTH - 1)

    def decode(self, value: str) -> tuple[str, SpriteRecipe] | None:
        code = parse_ref(value)
        if code is None or not code.startswith(CODE_PREFIX):
            return None
        body = self._decode_integer(code[1:])
        global_index = (body >> CHECKSUM_BITS) ^ _INDEX_MASK
        if body & ((1 << CHECKSUM_BITS) - 1) != self._checksum(global_index):
            return None

        offset = 0
        registry = None
        for candidate in self.registries:
            if global_index < offset + candidate.space:
                registry = candidate
                break
            offset += candidate.space
        if registry is None:
            return None

        local = global_index - offset
        preset_index = local % len(registry.presets)
        local //= len(registry.presets)
        overrides: list[str] = []
        for _, choices in registry.choices:
            radix = len(choices) + 1
            digit = local % radix
            local //= radix
            if digit:
                overrides.append(choices[digit - 1])
        if local:
            return None
        return (
            registry.character,
            canonical_recipe(
                SpriteRecipe(
                    base_preset=registry.presets[preset_index],
                    overrides=overrides,
                )
            ),
        )

    @staticmethod
    def _checksum(global_index: int) -> int:
        payload = global_index.to_bytes(8, "big") + _CHECKSUM_SALT
        return hashlib.sha256(payload).digest()[0] & ((1 << CHECKSUM_BITS) - 1)

    @staticmethod
    def _encode_integer(value: int, length: int) -> str:
        characters = []
        for _ in range(length):
            value, remainder = divmod(value, len(CODE_ALPHABET))
            characters.append(CODE_ALPHABET[remainder])
        if value:
            raise ValueError("value exceeds shortcode capacity")
        return "".join(reversed(characters))

    @staticmethod
    def _decode_integer(value: str) -> int:
        result = 0
        for character in value:
            result = result * len(CODE_ALPHABET) + CODE_ALPHABET.index(character)
        return result
