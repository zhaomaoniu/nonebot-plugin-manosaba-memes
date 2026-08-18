import hashlib
import math
import re
import shlex
from collections import Counter, defaultdict
from pathlib import Path

from pydantic import BaseModel, Field

from ..models import Character
from ..prefab import Prefab

PRESET_SCHEMA_VERSION = 2
PRESET_PATH = (
    Path(__file__).parent.parent / "assets" / "presets" / "official_presets.json"
)
CHARACTERS = tuple(character.value for character in Character)
EXPRESSION_RE = re.compile(
    r"^(?:Normal|Smile|Angry|Pensive|Cry|Flushed|Surprised|Fearful)\d+$",
    re.IGNORECASE,
)
DETAIL_RE = re.compile(r"^(Cheeks|Sweat|Pale)", re.IGNORECASE)
FACE_PART_RE = {
    "eyes": re.compile(r"(?:^Eyes|/Eyes[^/>]*>Eyes)", re.IGNORECASE),
    "mouth": re.compile(r"(?:^Mouth|/Mouth[^/>]*>Mouth)", re.IGNORECASE),
}
FIRST_PAGE_SIZE = 9
_MAX_FEATURE_DISTANCE = 12
_POPULARITY_WEIGHT = 0.65
PresetFeatures = tuple[
    frozenset[str],
    frozenset[str],
    frozenset[str],
    frozenset[str],
]


class OfficialPreset(BaseModel):
    id: str
    nodes: list[str]
    appearance: list[str]
    frequency: int = 0


class OfficialPresetCatalog(BaseModel):
    schema_version: int = PRESET_SCHEMA_VERSION
    source_digest: str
    characters: dict[str, list[OfficialPreset]] = Field(default_factory=dict)


class ExtractionReport(BaseModel):
    scanned_files: int = 0
    parsed_char_commands: int = 0
    accepted_commands: int = 0
    stateful_commands: int = 0
    invalid: list[str] = Field(default_factory=list)
    character_counts: dict[str, int] = Field(default_factory=dict)


class PresetCatalog:
    def __init__(self, path: Path = PRESET_PATH, asset_root: Path | None = None):
        self.path = path
        self.asset_root = asset_root
        self.data = OfficialPresetCatalog.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        if self.data.schema_version != PRESET_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported preset schema {self.data.schema_version}; "
                f"expected {PRESET_SCHEMA_VERSION}"
            )
        self._by_id = {
            preset.id: preset
            for presets in self.data.characters.values()
            for preset in presets
        }
        self._ranked: dict[str, list[OfficialPreset]] = {}
        self._feature_groups: dict[str, dict[str, PresetFeatures]] = {}
        self._arm_choices: dict[str, list[str]] = {}
        self._face_part_choices: dict[tuple[str, str], list[str]] = {}
        self._head_choices: dict[str, list[str]] = {}

    def presets(self, character: str) -> list[OfficialPreset]:
        if character not in self._ranked:
            self._ranked[character] = self._rank_presets(character)
        return self._ranked[character]

    def preset(self, preset_id: str) -> OfficialPreset:
        return self._by_id[preset_id]

    def _rank_presets(self, character: str) -> list[OfficialPreset]:
        """Diversify the first page while retaining frequency order afterwards."""
        presets = self.data.characters.get(character, [])
        if len(presets) <= 1:
            return list(presets)

        features = {preset.id: self._preset_features(preset) for preset in presets}
        self._feature_groups[character] = features
        groups: dict[
            tuple[frozenset[str], frozenset[str], frozenset[str]],
            list[OfficialPreset],
        ] = defaultdict(list)
        for preset in presets:
            core, arms, _, details = features[preset.id]
            groups[(core, arms, details)].append(preset)

        representatives = [
            min(items, key=lambda item: (-item.frequency, item.id))
            for items in groups.values()
        ]
        group_features = [
            (
                features[preset.id][0],
                features[preset.id][1],
                features[preset.id][3],
            )
            for preset in representatives
        ]
        group_frequencies = [
            sum(item.frequency for item in groups[feature])
            for feature in group_features
        ]
        max_popularity = max(
            1.0,
            max(math.log1p(value) for value in group_frequencies),
        )
        selected_indexes: list[int] = []

        for _ in range(min(FIRST_PAGE_SIZE, len(representatives))):

            def score(candidate: int) -> float:
                popularity = math.log1p(group_frequencies[candidate]) / max_popularity
                novelty = (
                    1.0
                    if not selected_indexes
                    else min(
                        self._feature_distance(
                            group_features[candidate], group_features[selected]
                        )
                        for selected in selected_indexes
                    )
                    / _MAX_FEATURE_DISTANCE
                )
                return (
                    _POPULARITY_WEIGHT * popularity + (1 - _POPULARITY_WEIGHT) * novelty
                )

            best_index = min(
                (
                    index
                    for index in range(len(representatives))
                    if index not in selected_indexes
                ),
                key=lambda candidate: (
                    -score(candidate),
                    -group_frequencies[candidate],
                    -representatives[candidate].frequency,
                    representatives[candidate].id,
                ),
            )
            selected_indexes.append(best_index)

        selected = [representatives[index] for index in selected_indexes]
        selected_ids = {preset.id for preset in selected}
        return selected + [
            preset for preset in presets if preset.id not in selected_ids
        ]

    @staticmethod
    def _preset_features(preset: OfficialPreset) -> PresetFeatures:
        """Split the preset's resolved nodes into user-editable dimensions."""
        core: set[str] = set()
        arms: set[str] = set()
        expression: set[str] = set()
        details: set[str] = set()
        for name in preset.nodes:
            lowered = name.lower()
            if lowered.startswith("arm") or "_arm" in lowered:
                arms.add(name)
            elif lowered.startswith(("eyes", "mouth")):
                expression.add(name)
            elif lowered.startswith(("cheeks", "sweat", "pale")):
                details.add(name)
            else:
                core.add(name)
        return (
            frozenset(core),
            frozenset(arms),
            frozenset(expression),
            frozenset(details),
        )

    @staticmethod
    def _feature_distance(
        left: tuple[frozenset[str], frozenset[str], frozenset[str]],
        right: tuple[frozenset[str], frozenset[str], frozenset[str]],
    ) -> int:
        return (
            8 * (left[0] != right[0])
            + 3 * (left[1] != right[1])
            + (left[2] != right[2])
        )

    def arm_choices(self, character: str) -> list[str]:
        """Return official arm patches proven independent of prior arm state."""
        if character in self._arm_choices:
            return self._arm_choices[character]

        prefab = (
            Prefab(character, asset_path=self.asset_root)
            if self.asset_root is not None
            else Prefab(character)
        )
        arm_nodes = {
            node_id
            for node_id in prefab.sprite_nodes
            if self._is_arm_node(prefab.node_names({node_id})[0])
        }
        frequencies: Counter[tuple[str, ...]] = Counter()
        for preset in self.presets(character):
            arms: list[str] = []
            for token in preset.appearance:
                try:
                    if prefab.affected_nodes(token) & arm_nodes:
                        arms.append(token)
                except (RuntimeError, ValueError):
                    continue
            if not arms:
                continue
            disabled = prefab.apply(set(), *arms) & arm_nodes
            enabled = prefab.apply(set(arm_nodes), *arms) & arm_nodes
            if disabled == enabled:
                frequencies[tuple(arms)] += preset.frequency
        choices = [
            ",".join(arms)
            for arms, _ in sorted(
                frequencies.items(),
                key=lambda item: (-item[1], len(item[0]), item[0]),
            )
        ]
        self._arm_choices[character] = choices
        return choices

    @staticmethod
    def _is_arm_node(name: str) -> bool:
        lowered = name.lower()
        return lowered.startswith("arm") or "_arm" in lowered

    @staticmethod
    def expression_choices(prefab: Prefab) -> list[str]:
        return [key for key in prefab.available_keys if EXPRESSION_RE.match(key)]

    def editor_expression_choices(self, character: str, prefab: Prefab) -> list[str]:
        """Return complete expressions for every head without visual duplicates."""
        choices = self.expression_choices(prefab)
        seen = {frozenset(prefab.apply(set(), choice)) for choice in choices}
        for choice in self.head_choices(character, prefab):
            selected = frozenset(prefab.apply(set(), choice))
            if selected not in seen:
                seen.add(selected)
                choices.append(choice)
        return choices

    def head_choices(self, character: str, prefab: Prefab) -> list[str]:
        """Return one officially used complete face for each available head."""
        if character in self._head_choices:
            return self._head_choices[character]

        nodes = prefab._character_data.nodes
        scores: dict[tuple[str, ...], Counter[str]] = defaultdict(Counter)

        def head_signature(choice: str) -> tuple[str, ...] | None:
            try:
                selected = prefab.apply(set(), choice)
            except (RuntimeError, ValueError):
                return None
            names = [nodes[node_id].name for node_id in selected]
            heads = tuple(sorted(name for name in names if name.startswith("HeadBase")))
            has_eyes = any(name.lower().startswith("eyes") for name in names)
            has_mouth = any(name.lower().startswith("mouth") for name in names)
            return heads if len(heads) == 1 and has_eyes and has_mouth else None

        available = set(prefab.available_keys)
        for preset in self.presets(character):
            for token in preset.appearance:
                if token not in available:
                    continue
                signature = head_signature(token)
                if signature is not None:
                    scores[signature][token] += max(1, preset.frequency)

        for key in prefab.available_keys:
            signature = head_signature(key)
            if signature is not None:
                scores[signature][key] += 0

        if len(scores) < 2:
            self._head_choices[character] = []
            return []

        choices = [
            min(
                candidates,
                key=lambda key: (
                    -candidates[key],
                    not key.lower().startswith("normal"),
                    key,
                ),
            )
            for _, candidates in sorted(scores.items())
        ]
        self._head_choices[character] = choices
        return choices

    def face_part_choices(self, character: str, prefab: Prefab, part: str) -> list[str]:
        """Return eye or mouth patches, with official usage ranked first.

        Most prefabs expose only a few complete expression keys. Expanding those
        keys and the appearances observed in official scripts reveals the raw,
        independently selectable eye and mouth patches behind them.
        """
        if part not in FACE_PART_RE:
            raise ValueError(f"unsupported face part: {part}")
        cache_key = (character, part)
        if cache_key in self._face_part_choices:
            return self._face_part_choices[cache_key]

        entries = prefab.composition_entries
        pattern = FACE_PART_RE[part]
        choices: list[str] = []
        seen: set[str] = set()

        def expand(token: str, stack: frozenset[str] = frozenset()) -> list[str]:
            if token not in entries or token in stack:
                return [token]
            expanded: list[str] = []
            next_stack = stack | {token}
            for nested in entries[token].split(","):
                nested = nested.strip()
                if nested:
                    expanded.extend(expand(nested, next_stack))
            return expanded

        def collect(tokens: list[str]) -> None:
            for token in tokens:
                for expanded in expand(token):
                    if pattern.search(expanded) and expanded not in seen:
                        try:
                            prefab.affected_nodes(expanded)
                        except (RuntimeError, ValueError):
                            continue
                        seen.add(expanded)
                        choices.append(expanded)

        for preset in self.presets(character):
            collect(preset.appearance)
        for key in entries:
            collect([key])

        # A character can have several eye/mouth groups for alternate heads.
        # Clear every discovered group before selecting one layer so a choice
        # cannot accidentally leave the base preset's other face layer enabled.
        groups = sorted(
            {choice.split(">", 1)[0] for choice in choices if ">" in choice}
        )
        complete_choices = [
            ",".join([*(f"{group}-" for group in groups), choice]) for choice in choices
        ]
        self._face_part_choices[cache_key] = complete_choices
        return complete_choices

    @staticmethod
    def compatible_face_part_choices(
        prefab: Prefab,
        part: str,
        choices: list[str],
        active_nodes: set[int],
    ) -> list[str]:
        """Keep face patches belonging to the active head branch.

        Some prefabs contain alternate heads whose eye and mouth layers occupy
        different render branches. Those sprite files are valid but can be
        occluded when applied to another head. A compatible target shares the
        deepest ancestry with the active non-face layers.
        """
        nodes = prefab._character_data.nodes
        parents = {
            child: parent
            for parent, node in enumerate(nodes)
            for child in (node.children or [])
        }

        def path(node_id: int) -> tuple[int, ...]:
            result = [node_id]
            while node_id in parents:
                node_id = parents[node_id]
                result.append(node_id)
            return tuple(reversed(result))

        def shared_depth(left: tuple[int, ...], right: tuple[int, ...]) -> int:
            return next(
                (
                    index
                    for index, (left_id, right_id) in enumerate(zip(left, right))
                    if left_id != right_id
                ),
                min(len(left), len(right)),
            )

        references = [
            path(node_id)
            for node_id in active_nodes
            if not nodes[node_id].name.lower().startswith(("eyes", "mouth"))
        ]
        if not references:
            return choices

        active_targets = [
            path(node_id)
            for node_id in active_nodes
            if nodes[node_id].name.lower().startswith(part)
        ]
        active_score = max(
            (
                shared_depth(target, reference)
                for target in active_targets
                for reference in references
            ),
            default=0,
        )

        scored: list[tuple[str, int]] = []
        for choice in choices:
            selected = prefab.apply(set(), choice)
            targets = [
                path(node_id)
                for node_id in selected
                if nodes[node_id].name.lower().startswith(part)
            ]
            if targets:
                scored.append(
                    (
                        choice,
                        max(
                            shared_depth(target, reference)
                            for target in targets
                            for reference in references
                        ),
                    )
                )
        if not scored:
            return choices
        best_score = max(score for _, score in scored)
        if best_score < active_score:
            return []
        return [choice for choice, score in scored if score == best_score]

    @staticmethod
    def compatible_detail_choices(
        prefab: Prefab,
        choices: list[str],
        active_nodes: set[int],
    ) -> list[str]:
        """Keep cheeks, sweat, and pale patches on the active head branch."""
        nodes = prefab._character_data.nodes
        parents = {
            child: parent
            for parent, node in enumerate(nodes)
            for child in (node.children or [])
        }

        def path(node_id: int) -> tuple[int, ...]:
            result = [node_id]
            while node_id in parents:
                node_id = parents[node_id]
                result.append(node_id)
            return tuple(reversed(result))

        def shared_depth(left: tuple[int, ...], right: tuple[int, ...]) -> int:
            return next(
                (
                    index
                    for index, (left_id, right_id) in enumerate(zip(left, right))
                    if left_id != right_id
                ),
                min(len(left), len(right)),
            )

        active_heads = [
            path(node_id)
            for node_id in active_nodes
            if nodes[node_id].name.lower().startswith("headbase")
        ]
        if not active_heads:
            return choices

        scored: list[tuple[str, str, int]] = []
        best_by_category: dict[str, int] = {}
        for choice in choices:
            match = DETAIL_RE.match(choice)
            if match is None:
                continue
            category = match.group(1).lower()
            targets = [
                path(node_id)
                for node_id in prefab.affected_nodes(choice)
                if nodes[node_id].name.lower().startswith(category)
            ]
            if not targets:
                continue
            score = max(
                shared_depth(target, active_head)
                for target in targets
                for active_head in active_heads
            )
            scored.append((choice, category, score))
            best_by_category[category] = max(score, best_by_category.get(category, -1))

        return [
            choice
            for choice, category, score in scored
            if score == best_by_category[category]
        ]

    @staticmethod
    def detail_choices(prefab: Prefab) -> list[str]:
        return [key for key in prefab.available_keys if DETAIL_RE.match(key)]


def parse_char_line(line: str) -> tuple[str, tuple[str, ...]] | None:
    """Parse the first supported positional actor argument of a Naninovel @char."""
    stripped = line.lstrip()
    if not stripped.startswith("@char"):
        return None
    command = stripped[5:].strip()
    if not command or command.startswith(";"):
        return None
    try:
        parts = shlex.split(command, posix=True)
    except ValueError:
        return None
    supported = set(CHARACTERS)
    for part in parts:
        if ":" in part and part.split(":", 1)[0].isidentifier():
            continue
        actor, dot, appearance = part.partition(".")
        if actor not in supported:
            continue
        if not dot or not appearance or any(char in appearance for char in "{}[]$"):
            return None
        tokens = tuple(
            token.strip() for token in appearance.split(",") if token.strip()
        )
        return (actor, tokens) if tokens else None
    return None


def is_standalone_appearance(tokens: tuple[str, ...]) -> bool:
    """Cheap syntax prefilter for obviously partial script patches.

    This is not the extraction safety check. Composition keys are patches too,
    so the extractor proves state independence against the actual prefab.
    """
    has_expression = any(EXPRESSION_RE.match(token) for token in tokens)
    has_raw_eyes = any(
        token.startswith("Eyes") or "/Eyes>" in token for token in tokens
    )
    has_raw_mouth = any(
        token.startswith("Mouth") or "/Mouth>" in token for token in tokens
    )
    has_joined_arms = any(token.lower().startswith("arms") for token in tokens)
    has_left = any(token.lower().startswith("arml") for token in tokens)
    has_right = any(token.lower().startswith("armr") for token in tokens)
    complete_face = has_expression or (has_raw_eyes and has_raw_mouth)
    return complete_face and (has_joined_arms or (has_left and has_right))


def standalone_snapshot(
    prefab: Prefab,
    appearance: tuple[str, ...],
    mutable_nodes: set[int],
) -> set[int] | None:
    """Resolve a patch only when its result is independent of prior actor state.

    Layer composition is a transfer function that can only set, clear, or
    preserve sprite bits. Equal results from the lower and upper bounds of all
    mutable bits therefore prove equality for every possible previous state.
    """
    fixed = prefab.initially_enabled_nodes - mutable_nodes
    disabled_state = prefab.apply(fixed, "Body", *appearance)
    enabled_state = prefab.apply(fixed | mutable_nodes, "Body", *appearance)
    return disabled_state if disabled_state == enabled_state else None


def _source_kind(path: Path, root: Path) -> str:
    relative = path.relative_to(root)
    first = relative.parts[0]
    if first.startswith(("Act", "Common")):
        return "rank"
    if first.startswith("Debug"):
        return "validate"
    return "ignore"


def extract_official_presets(
    script_root: Path,
    *,
    asset_root: Path | None = None,
) -> tuple[OfficialPresetCatalog, ExtractionReport]:
    files = sorted(script_root.rglob("*.nani"))
    report = ExtractionReport(scanned_files=len(files))
    digest = hashlib.sha256()
    counts: dict[str, Counter[tuple[str, ...]]] = defaultdict(Counter)
    validation_only: dict[str, set[tuple[str, ...]]] = defaultdict(set)

    for path in files:
        kind = _source_kind(path, script_root)
        relative = path.relative_to(script_root).as_posix()
        content = path.read_bytes()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content)
        if kind == "ignore":
            continue
        for line in content.decode("utf-8-sig", errors="replace").splitlines():
            parsed = parse_char_line(line)
            if not parsed:
                continue
            report.parsed_char_commands += 1
            character, appearance = parsed
            if kind == "rank":
                counts[character][appearance] += 1
            else:
                validation_only[character].add(appearance)

    output: dict[str, list[OfficialPreset]] = {}
    for character in CHARACTERS:
        prefab = (
            Prefab(character, asset_path=asset_root)
            if asset_root
            else Prefab(character)
        )
        signatures: dict[tuple[str, ...], list[tuple[tuple[str, ...], int]]] = (
            defaultdict(list)
        )
        candidates = set(counts[character]) | validation_only[character]
        mutable_nodes: set[int] = set()
        mutation_tokens = set(prefab.available_keys)
        mutation_tokens.update(
            token for appearance in candidates for token in appearance
        )
        for token in sorted(mutation_tokens):
            try:
                mutable_nodes.update(prefab.affected_nodes(token))
            except (RuntimeError, ValueError):
                # The full candidate is reported below with useful context.
                pass

        for appearance in sorted(candidates):
            try:
                nodes = standalone_snapshot(prefab, appearance, mutable_nodes)
            except (RuntimeError, ValueError) as error:
                report.invalid.append(f"{character}.{','.join(appearance)}: {error}")
                continue
            if nodes is None:
                if appearance in counts[character]:
                    report.stateful_commands += counts[character][appearance]
                continue
            signature = prefab.node_names(nodes)
            if appearance in counts[character]:
                signatures[signature].append(
                    (appearance, counts[character][appearance])
                )

        # A newly created actor has one engine-defined, context-free state even
        # when every script command for that character is incremental. Keep that
        # official prefab default as a low-ranked fallback; unlike ``@char
        # Character.Default``, this is explicitly evaluated as actor creation.
        default_appearance = tuple(
            token.strip()
            for token in prefab.default_appearance.split(",")
            if token.strip()
        )
        default_nodes = prefab.compose("Body", use_defaults=True)
        signatures[prefab.node_names(default_nodes)].append((default_appearance, 0))

        presets: list[OfficialPreset] = []
        for signature, appearances in signatures.items():
            total_frequency = sum(frequency for _, frequency in appearances)
            representative, _ = min(
                appearances,
                key=lambda item: (
                    -item[1],
                    len(",".join(item[0])),
                    ",".join(item[0]),
                ),
            )
            signature_hash = hashlib.sha1(
                "\0".join(signature).encode("utf-8")
            ).hexdigest()[:8]
            presets.append(
                OfficialPreset(
                    id=f"{character.lower()}-{signature_hash}",
                    nodes=list(signature),
                    appearance=list(representative),
                    frequency=total_frequency,
                )
            )
        presets.sort(key=lambda item: (-item.frequency, item.id))
        output[character] = presets
        report.character_counts[character] = len(presets)
        report.accepted_commands += sum(item.frequency for item in presets)

    return (
        OfficialPresetCatalog(source_digest=digest.hexdigest(), characters=output),
        report,
    )


def write_catalog(catalog: OfficialPresetCatalog, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(catalog.model_dump_json(indent=2) + "\n", encoding="utf-8")


def write_report(report: ExtractionReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
