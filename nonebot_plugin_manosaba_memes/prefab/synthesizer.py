from pathlib import Path

from .composition import Composition, CompositionData
from .models import CharacterData, SpriteInfo
from .renderer import SketchbookRenderer
from .types import Coordinates, Scale, Translation
from .utils import get_png_size


class Prefab:
    """Prefab class for synthesizing images from a Naninovel character.

    Supports two modes of operation:
    1. Precise mode: Pass node IDs directly to synthesize_with_nodes()
    2. Convenient mode: Use composition keys with synthesize() or compose()

    Args:
        name (str): The name of the prefab/character.
        unit_per_pixel (float): The unit per pixel of prefab coordinates. Defaults to 100.0.
        asset_path (Path): The path to the prefabs' assets. Defaults to `assets/prefabs`.
        renderer_cls: Renderer implementation. Defaults to SketchbookRenderer.
    """

    def __init__(
        self,
        name: str,
        unit_per_pixel: float = 100.0,
        asset_path: Path = Path(__file__).parent.parent / "assets" / "prefabs",
        renderer_cls: type[SketchbookRenderer] = SketchbookRenderer,
    ):
        self.name = name
        self.unit_per_pixel = unit_per_pixel
        self.prefab_asset_path = asset_path / name

        self._character_data = self._load_character_data()

        # Load composition data if available
        self._composition: Composition = self._load_composition()

        self._available_image_ids = self._get_available_image_ids()
        self._image_sizes = self._get_image_sizes()

        self._layers = self._get_layers()
        self._layers = self._preprocess_layers(self._layers)

        self._sprite_size = self._get_sprite_size()

        # Initialize the configured renderer.
        self._renderer = renderer_cls(self)

    def _load_character_data(self) -> CharacterData:
        """Load the character data from character.json"""
        json_path = self.prefab_asset_path / "character.json"
        if json_path.exists():
            with open(json_path, "r", encoding="utf-8") as f:
                return CharacterData.model_validate_json(f.read())

        raise FileNotFoundError(f"No character.json found for {self.name}")

    def _load_composition(self) -> Composition:
        """Load composition data if available."""
        composition_path = self.prefab_asset_path / "composition.json"
        if composition_path.exists():
            composition_data = CompositionData.from_file(composition_path)
            return Composition(self._character_data, composition_data)
        # Return composition without data (still useful for path resolution)
        return Composition(self._character_data, None)

    def _get_sprite_info(self, node_id: int) -> SpriteInfo | None:
        """Get sprite info for a node by its ID."""
        if 0 <= node_id < len(self._character_data.nodes):
            return self._character_data.nodes[node_id].sprite
        return None

    def _get_sprite_path(self, node_name: str) -> Path:
        """Get the path to a sprite image."""
        return self.prefab_asset_path / "sprites" / f"{node_name}.png"

    def _get_layers(self) -> list[tuple[int, Scale, Coordinates]]:
        """Get the layers of the prefab by traversing the prefab tree with DFS."""
        nodes = self._character_data.nodes
        layers = []
        stack: list[tuple[int, Scale, Translation]] = []
        stack.append((0, nodes[0].scale, nodes[0].translation))

        while len(stack) > 0:
            node_id, scale, translation = stack.pop()
            if node_id in self._available_image_ids:
                layers.append(
                    (
                        node_id,
                        scale,
                        (
                            translation[0] * self.unit_per_pixel,
                            translation[1] * self.unit_per_pixel,
                            translation[2] * self.unit_per_pixel,
                        ),
                    )
                )

            if nodes[node_id].children is not None:
                for child_id in nodes[node_id].children:
                    stack.append(
                        (
                            child_id,
                            (
                                scale[0] * nodes[child_id].scale[0],
                                scale[1] * nodes[child_id].scale[1],
                                scale[2] * nodes[child_id].scale[2],
                            ),
                            (
                                translation[0]
                                + nodes[child_id].translation[0] * scale[0],
                                translation[1]
                                + nodes[child_id].translation[1] * scale[1],
                                translation[2]
                                + nodes[child_id].translation[2] * scale[2],
                            ),
                        )
                    )
        return layers

    def _preprocess_layers(
        self, layers: list[tuple[int, Scale, Coordinates]]
    ) -> list[tuple[int, Scale, Coordinates]]:
        """Make all the coordinates of the layers positive."""
        coordinates_min_x, coordinates_min_y, coordinates_min_z = (
            float("inf"),
            float("inf"),
            float("inf"),
        )
        for node_id, scale, coordinates in layers:
            coordinates_min_x = min(
                coordinates_min_x,
                coordinates[0] - self._image_sizes[node_id][0] * scale[0] / 2,
            )
            coordinates_min_y = min(
                coordinates_min_y,
                coordinates[1] - self._image_sizes[node_id][1] * scale[1] / 2,
            )
            coordinates_min_z = min(coordinates_min_z, coordinates[2])

        for i, (node_id, scale, coordinates) in enumerate(layers):
            layers[i] = (
                node_id,
                scale,
                (
                    coordinates[0] - coordinates_min_x,
                    coordinates[1] - coordinates_min_y,
                    coordinates[2] - coordinates_min_z,
                ),
            )
        return layers

    def _get_available_image_ids(self) -> set[int]:
        """Get the node ids whose corresponding images exist."""
        available_image_ids = set()
        for node_id, node in enumerate(self._character_data.nodes):
            image_path = self._get_sprite_path(node.name)
            if image_path.exists():
                available_image_ids.add(node_id)
        return available_image_ids

    def _get_image_sizes(self) -> dict[int, tuple[int, int]]:
        """Get the sizes of the images of the prefab."""
        image_sizes: dict[int, tuple[int, int]] = {}
        for node_id in self._available_image_ids:
            image_path = self._get_sprite_path(self._character_data.nodes[node_id].name)
            image_sizes[node_id] = get_png_size(image_path)
        return image_sizes

    def _get_sprite_size(self) -> tuple[int, int]:
        """Calculate the size of the sprite from the prefab."""
        max_width = -float("inf")
        max_height = -float("inf")
        for node_id, scale, coordinates in self._layers:
            max_width = max(
                max_width,
                coordinates[0] + self._image_sizes[node_id][0] * scale[0] / 2,
            )
            max_height = max(
                max_height,
                coordinates[1] + self._image_sizes[node_id][1] * scale[1] / 2,
            )
        return int(max_width), int(max_height)

    # =========================================================================
    # Composition-based convenience methods
    # =========================================================================

    def compose(self, *keys: str, use_defaults: bool = True) -> set[int]:
        """
        Resolve composition keys to node IDs.

        This method handles the composition map to convert human-readable
        keys like "Smile1", "ArmL2" to actual node IDs. It also applies
        default appearance fallback.

        Args:
            *keys: Composition keys (e.g., "Smile1", "ArmL2", "Default").
            use_defaults: Whether to apply default appearance for unspecified parts.

        Returns:
            Set of node IDs to render.

        Examples:
            >>> prefab = Prefab("Hanna")
            >>> nodes = prefab.compose("Smile1")  # Uses default arms
            >>> nodes = prefab.compose("Angry1", "ArmL2", "ArmR1")
        """
        if self._composition is None:
            raise RuntimeError(
                f"No composition data available for {self.name}. "
                "Use synthesize_with_nodes() with node IDs instead."
            )

        return self._composition.resolve(*keys, use_defaults=use_defaults)

    def apply(self, nodes: set[int], *keys: str) -> set[int]:
        """Apply composition patches to an existing concrete node snapshot."""
        return self._composition.apply(nodes, *keys)

    def affected_nodes(self, *keys: str) -> set[int]:
        """Return the sprite nodes assigned by the supplied patches."""
        return self._composition.affected_nodes(*keys)

    @property
    def sprite_nodes(self) -> set[int]:
        return self._composition.sprite_nodes

    @property
    def initially_enabled_nodes(self) -> set[int]:
        return self._composition.initially_enabled

    def node_names(self, nodes: set[int]) -> tuple[str, ...]:
        """Convert a concrete node snapshot to its stable serialized form."""
        return tuple(sorted(self._character_data.nodes[node].name for node in nodes))

    def nodes_from_names(self, names: list[str] | tuple[str, ...]) -> set[int]:
        """Resolve a serialized node snapshot, rejecting unknown or duplicate names."""
        by_name = {
            node.name: node_id
            for node_id, node in enumerate(self._character_data.nodes)
            if node.sprite
        }
        unknown = sorted(set(names) - by_name.keys())
        if unknown:
            raise ValueError(
                f"Unknown sprite nodes for {self.name}: {', '.join(unknown)}"
            )
        if len(names) != len(set(names)):
            raise ValueError(f"Duplicate sprite node names in snapshot for {self.name}")
        return {by_name[name] for name in names}

    def synthesize(
        self,
        *keys: str,
        use_defaults: bool = True,
    ) -> bytes:
        """
        Synthesize image using composition keys.

        This is the convenient method that accepts composition keys instead
        of node IDs. It handles default appearance fallback automatically.

        Args:
            *keys: Composition keys (e.g., "Smile1", "ArmL2").
            use_defaults: Whether to apply default appearance for unspecified parts.
        Returns:
            PNG bytes of the synthesized image.

        Examples:
            >>> prefab = Prefab("Hanna")
            >>> img = prefab.synthesize("Smile1")  # Uses default arms
            >>> img = prefab.synthesize("Angry1", "ArmL2")
        """
        nodes = self.compose("Body", *keys, use_defaults=use_defaults)
        return self.synthesize_with_nodes(nodes)

    def synthesize_with_nodes(self, nodes: set[int]) -> bytes:
        """
        Synthesize the image from the prefab using the configured renderer.

        Args:
            nodes (Set[int]): The node ids to be synthesized.
        Returns:
            bytes: The PNG bytes of the synthesized image.
        """
        return self._renderer.render(nodes)

    def synthesize_view_with_nodes(
        self,
        nodes: set[int],
        crop_box: tuple[int, int, int, int],
        target_size: tuple[int, int],
    ) -> bytes:
        """Render a cropped node composition directly at a target size."""
        return self._renderer.render_view(nodes, crop_box, target_size)

    @property
    def available_keys(self) -> list[str]:
        """Get all available composition keys."""
        if self._composition is None:
            return []
        return self._composition.get_available_keys()

    @property
    def composition_entries(self) -> dict[str, str]:
        """Get a copy of the prefab's composition map."""
        return self._composition.get_entries()

    @property
    def default_appearance(self) -> str:
        """Get the default appearance string."""
        if self._composition is None:
            return ""
        return self._composition.get_default_appearance()
