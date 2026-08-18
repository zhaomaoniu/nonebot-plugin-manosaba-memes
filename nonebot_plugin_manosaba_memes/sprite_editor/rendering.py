import hashlib
import json
import math
import os
import secrets
from functools import cache
from pathlib import Path
from struct import unpack_from

from sketchbook import (
    Align,
    Bitmap,
    Drawer,
    FontSet,
    Layer,
    Region,
    SpriteMode,
    TextStyle,
    VAlign,
)

from ..prefab import Prefab
from .presets import PresetCatalog
from .state import (
    PickerKind,
    SpriteRecipe,
    replace_arm_override,
    replace_expression_override,
    replace_head_override,
    replace_override,
)

FONT_PATH = Path(__file__).parent.parent / "assets" / "fonts" / "PickerLabels.otf"


@cache
def picker_fonts() -> FontSet:
    """Load the small picker-label font once per process."""
    return FontSet(str(FONT_PATH))


@cache
def picker_font_digest() -> str:
    """Identify the bundled font so font updates invalidate picker previews."""
    return hashlib.sha256(FONT_PATH.read_bytes()).hexdigest()


class SpriteRenderer:
    def __init__(
        self,
        catalog: PresetCatalog,
        cache_dir: Path | None = None,
        asset_root: Path | None = None,
    ):
        self.catalog = catalog
        self.cache_dir = cache_dir
        self.asset_root = asset_root
        self._prefabs: dict[str, Prefab] = {}
        self._node_bounds: dict[tuple[str, int], tuple[float, float, float, float]] = {}

    def prefab(self, character: str) -> Prefab:
        if character not in self._prefabs:
            self._prefabs[character] = (
                Prefab(character, asset_path=self.asset_root)
                if self.asset_root is not None
                else Prefab(character)
            )
        return self._prefabs[character]

    def render_recipe(self, character: str, recipe: SpriteRecipe) -> bytes:
        return self.prefab(character).synthesize_with_nodes(
            self.compose_recipe(character, recipe)
        )

    def compose_recipe(self, character: str, recipe: SpriteRecipe) -> set[int]:
        """Apply user overrides to an immutable official node snapshot."""
        preset = self.catalog.preset(recipe.base_preset)
        prefab = self.prefab(character)
        nodes = prefab.nodes_from_names(preset.nodes)
        return prefab.apply(nodes, *recipe.overrides)

    def recipe_with_choice(
        self, recipe: SpriteRecipe | None, picker: PickerKind, choice: str
    ) -> SpriteRecipe:
        if picker == "preset":
            return SpriteRecipe(base_preset=choice)
        if recipe is None:
            raise ValueError(f"{picker} picker requires a base sprite")
        if picker == "arm":
            return SpriteRecipe(
                base_preset=recipe.base_preset,
                overrides=replace_arm_override(recipe.overrides, choice),
            )
        if picker == "head":
            return SpriteRecipe(
                base_preset=recipe.base_preset,
                overrides=replace_head_override(recipe.overrides, choice),
            )
        if picker == "expression":
            return SpriteRecipe(
                base_preset=recipe.base_preset,
                overrides=replace_expression_override(recipe.overrides, choice),
            )
        return SpriteRecipe(
            base_preset=recipe.base_preset,
            overrides=replace_override(recipe.overrides, choice),
        )

    def render_picker(
        self,
        character: str,
        picker: PickerKind,
        choices: list[str],
        recipe: SpriteRecipe | None,
        *,
        labels: list[str],
    ) -> bytes:
        descriptor = json.dumps(
            {
                "character": character,
                "picker": picker,
                "choices": choices,
                "recipe": recipe.model_dump() if recipe else None,
                "labels": labels,
                "catalog": self.catalog.data.source_digest,
                "font": picker_font_digest(),
                "layout": 12,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        cache_path = None
        if self.cache_dir:
            key = hashlib.sha256(descriptor.encode("utf-8")).hexdigest()
            cache_path = self.cache_dir / f"{key}.png"
            if cache_path.exists():
                return cache_path.read_bytes()

        recipes = [
            self.recipe_with_choice(recipe, picker, choice) for choice in choices
        ]
        if picker in {"head", "expression", "eyes", "mouth", "detail"}:
            crop_boxes = [self._face_crop_box(character, item) for item in recipes]
        elif picker == "arm":
            crop_boxes = [self._arm_crop_box(character, item) for item in recipes]
        else:
            crop_boxes = [
                self._composition_crop_box(character, item) for item in recipes
            ]
        prefab = self.prefab(character)
        nodes = [self.compose_recipe(character, item) for item in recipes]
        _, _, _, _, x_edges, y_edges = self._contact_sheet_layout(len(recipes))
        images = []
        for index, (selected, crop_box) in enumerate(
            zip(nodes, crop_boxes, strict=True)
        ):
            column, row = index % (len(x_edges) - 1), index // (len(x_edges) - 1)
            cell_width = x_edges[column + 1] - x_edges[column]
            cell_height = y_edges[row + 1] - y_edges[row]
            images.append(
                prefab.synthesize_view_with_nodes(
                    selected,
                    crop_box or (0, 0, *prefab._sprite_size),
                    (cell_width - 24, cell_height - 24),
                )
            )
        result = self._contact_sheet(
            images,
            labels,
            crop_boxes=[None] * len(images),
        )
        if cache_path:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = cache_path.with_name(
                f".{cache_path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
            )
            try:
                temporary.write_bytes(result)
                os.replace(temporary, cache_path)
            finally:
                temporary.unlink(missing_ok=True)
        return result

    def _face_crop_box(
        self, character: str, recipe: SpriteRecipe
    ) -> tuple[int, int, int, int] | None:
        """Calculate a face viewport from active eye and mouth sprite geometry."""
        prefab = self.prefab(character)
        active = self.compose_recipe(character, recipe)
        anchors: list[tuple[float, float, float, float]] = []
        eye_widths: list[float] = []
        for node_id in active:
            name = prefab._character_data.nodes[node_id].name.lower()
            if not name.startswith(("eyes", "mouth")):
                continue
            bounds = self._rendered_node_bounds(prefab, node_id)
            if bounds is None:
                continue
            anchors.append(bounds)
            if name.startswith("eyes"):
                eye_widths.append(bounds[2] - bounds[0])

        if not anchors:
            return None

        anchor_left = min(item[0] for item in anchors)
        anchor_top = min(item[1] for item in anchors)
        anchor_right = max(item[2] for item in anchors)
        anchor_bottom = max(item[3] for item in anchors)
        anchor_width = max(
            anchor_right - anchor_left,
            max(eye_widths, default=0.0),
        )
        crop_width = max(1.0, anchor_width * 1.85)
        crop_height = crop_width / 0.82
        center_x = (anchor_left + anchor_right) / 2
        center_y = (anchor_top + anchor_bottom) / 2

        left = center_x - crop_width / 2
        top = center_y - crop_height * 0.46
        right = left + crop_width
        bottom = top + crop_height
        canvas_width, canvas_height = prefab._sprite_size

        if left < 0:
            right -= left
            left = 0
        if right > canvas_width:
            left -= right - canvas_width
            right = canvas_width
        if top < 0:
            bottom -= top
            top = 0
        if bottom > canvas_height:
            top -= bottom - canvas_height
            bottom = canvas_height

        return (
            max(0, round(left)),
            max(0, round(top)),
            min(canvas_width, round(right)),
            min(canvas_height, round(bottom)),
        )

    def _arm_crop_box(
        self, character: str, recipe: SpriteRecipe
    ) -> tuple[int, int, int, int] | None:
        """Calculate an upper-body viewport from active arm sprite geometry."""
        prefab = self.prefab(character)
        active = self.compose_recipe(character, recipe)
        anchors = []
        for node_id in active:
            name = prefab._character_data.nodes[node_id].name.lower()
            if not (name.startswith("arm") or "_arm" in name):
                continue
            bounds = self._rendered_node_bounds(prefab, node_id)
            if bounds is not None:
                anchors.append(bounds)
        if not anchors:
            return None

        anchor_left = min(item[0] for item in anchors)
        anchor_top = min(item[1] for item in anchors)
        anchor_right = max(item[2] for item in anchors)
        anchor_bottom = max(item[3] for item in anchors)
        anchor_width = anchor_right - anchor_left
        anchor_height = anchor_bottom - anchor_top
        crop_width = max(anchor_width * 1.14, anchor_height * 0.75 * 1.08)
        crop_height = crop_width / 0.75
        center_x = (anchor_left + anchor_right) / 2
        center_y = (anchor_top + anchor_bottom) / 2
        left = center_x - crop_width / 2
        top = center_y - crop_height * 0.48
        right = left + crop_width
        bottom = top + crop_height
        canvas_width, canvas_height = prefab._sprite_size

        if left < 0:
            right -= left
            left = 0
        if right > canvas_width:
            left -= right - canvas_width
            right = canvas_width
        if top < 0:
            bottom -= top
            top = 0
        if bottom > canvas_height:
            top -= bottom - canvas_height
            bottom = canvas_height

        return (
            max(0, round(left)),
            max(0, round(top)),
            min(canvas_width, round(right)),
            min(canvas_height, round(bottom)),
        )

    def _rendered_node_bounds(
        self, prefab: Prefab, node_id: int
    ) -> tuple[float, float, float, float] | None:
        cache_key = (prefab.name, node_id)
        if cache_key in self._node_bounds:
            return self._node_bounds[cache_key]
        if node_id not in prefab._image_sizes:
            return None

        layer = next(
            (
                (scale, coordinates)
                for current_id, scale, coordinates in prefab._layers
                if current_id == node_id
            ),
            None,
        )
        if layer is None:
            return None
        scale, coordinates = layer
        image_width, image_height = prefab._image_sizes[node_id]
        left = prefab._sprite_size[0] - coordinates[0] - image_width * scale[0] / 2
        top = prefab._sprite_size[1] - coordinates[1] - image_height * scale[1] / 2
        bounds = (
            left,
            top,
            left + image_width * scale[0],
            top + image_height * scale[1],
        )
        self._node_bounds[cache_key] = bounds
        return bounds

    def _composition_crop_box(
        self, character: str, recipe: SpriteRecipe
    ) -> tuple[int, int, int, int] | None:
        """Calculate a viewport containing the active sprite geometry."""
        prefab = self.prefab(character)
        bounds = [
            item
            for node_id in self.compose_recipe(character, recipe)
            if (item := self._rendered_node_bounds(prefab, node_id)) is not None
        ]
        if not bounds:
            return None

        canvas_width, canvas_height = prefab._sprite_size
        return (
            max(0, math.floor(min(item[0] for item in bounds))),
            max(0, math.floor(min(item[1] for item in bounds))),
            min(canvas_width, math.ceil(max(item[2] for item in bounds))),
            min(canvas_height, math.ceil(max(item[3] for item in bounds))),
        )

    @staticmethod
    def _png_size(payload: bytes) -> tuple[int, int]:
        if len(payload) < 24 or not payload.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("contact sheet images must be PNG data")
        return unpack_from(">II", payload, 16)

    @classmethod
    def _contact_sheet(
        cls,
        images: list[bytes],
        labels: list[str],
        *,
        crop_boxes: list[tuple[int, int, int, int] | None],
    ) -> bytes:
        count = len(images)
        if count == 0:
            raise ValueError("a picker must contain at least one image")
        columns, _, width, height, x_edges, y_edges = cls._contact_sheet_layout(count)

        fonts = picker_fonts()
        image_layer = Layer("contact-sheet-images").fill(
            Region.full(width, height), (255, 255, 255, 255)
        )
        decoration_layer = Layer("contact-sheet-decorations")
        opaque_pixel: Bitmap | None = None

        for index, (payload, label, crop_box) in enumerate(
            zip(images, labels, crop_boxes, strict=True)
        ):
            column, row = index % columns, index // columns
            left, right = x_edges[column], x_edges[column + 1]
            top, bottom = y_edges[row], y_edges[row + 1]
            cell_width, cell_height = right - left, bottom - top

            image_width, image_height = cls._png_size(payload)
            if crop_box is None:
                scale = min(
                    1.0,
                    (cell_width - 24) / image_width,
                    (cell_height - 24) / image_height,
                )
                visible_width = image_width * scale
                visible_height = image_height * scale
                image_layer = image_layer.sprite_exact(
                    Bitmap.load(payload),
                    position=(
                        left + (cell_width - visible_width) / 2,
                        top + (cell_height - visible_height) / 2,
                    ),
                    target_size=(visible_width, visible_height),
                )
            else:
                crop_left, crop_top, crop_right, crop_bottom = crop_box
                crop_left = max(0, min(crop_left, image_width - 1))
                crop_top = max(0, min(crop_top, image_height - 1))
                crop_right = max(crop_left + 1, min(crop_right, image_width))
                crop_bottom = max(crop_top + 1, min(crop_bottom, image_height))
                crop_width = crop_right - crop_left
                crop_height = crop_bottom - crop_top
                scale = min(
                    1.0,
                    (cell_width - 24) / crop_width,
                    (cell_height - 24) / crop_height,
                )
                visible_width = crop_width * scale
                visible_height = crop_height * scale
                visible_left = left + (cell_width - visible_width) / 2
                visible_top = top + (cell_height - visible_height) / 2
                if opaque_pixel is None:
                    opaque_pixel = Bitmap.load(
                        Drawer(1, 1, FontSet())
                        .layer(
                            Layer("pixel").fill(Region.full(1, 1), (255, 255, 255, 255))
                        )
                        .render()
                    )
                stencil_ref = index + 1
                image_layer = image_layer.sprite_exact(
                    opaque_pixel,
                    position=(visible_left, visible_top),
                    target_size=(visible_width, visible_height),
                    mode=SpriteMode.Multiply,
                    stencil_write=stencil_ref,
                ).sprite_exact(
                    Bitmap.load(payload),
                    position=(
                        visible_left - crop_left * scale,
                        visible_top - crop_top * scale,
                    ),
                    target_size=(image_width * scale, image_height * scale),
                    stencil_read=stencil_ref,
                )

            decoration_layer = decoration_layer.fill(
                Region(left + 8, top + 6, 58, 42),
                (255, 255, 255, 224),
            )
            label_region = Region(left + 14, top + 10, cell_width - 28, 48)
            label_style = TextStyle(
                color=(30, 30, 32, 255),
                max_font_size=30,
                align=Align.Left,
                valign=VAlign.Top,
                antialias=True,
                parse_rules=[],
            )
            decoration_layer = decoration_layer.text(label, label_region, label_style)

        divider = (218, 218, 221)
        for x in x_edges[1:-1]:
            decoration_layer = decoration_layer.fill(
                Region(x, 0, 1, height), (*divider, 255)
            )
        for y in y_edges[1:-1]:
            decoration_layer = decoration_layer.fill(
                Region(0, y, width, 1), (*divider, 255)
            )

        return (
            Drawer(width, height, fonts)
            .layer(image_layer)
            .layer(decoration_layer)
            .render()
        )

    @staticmethod
    def _contact_sheet_layout(
        count: int,
    ) -> tuple[int, int, int, int, list[int], list[int]]:
        if count <= 0:
            raise ValueError("a picker must contain at least one image")
        columns = 2 if count == 4 else min(3, count)
        rows = math.ceil(count / columns)
        width = columns * 400
        height = round(rows * 1600 / 3)
        x_edges = [round(index * width / columns) for index in range(columns + 1)]
        y_edges = [round(index * height / rows) for index in range(rows + 1)]
        return columns, rows, width, height, x_edges, y_edges
