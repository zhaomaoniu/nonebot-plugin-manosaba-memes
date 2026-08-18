import asyncio
import math
import re

import nonebot_plugin_localstore as localstore
from nonebot.internal.adapter import Bot, Event
from nonebot_plugin_alconna import (
    Arparma,
    OriginalUniMsg,
    Reply,
    UniMessage,
    get_target,
)

from ..utils import CHARACTER_NAME_MAP, CHARACTER_NAMES
from .assets import (
    prefab_asset_root,
    prefab_asset_status,
    prefab_unavailable_message,
)
from .codec import RecipeCodec
from .presets import PresetCatalog
from .rendering import SpriteRenderer
from .state import (
    CODE_ALPHABET,
    CODE_LENGTH,
    MessageContext,
    PickerKind,
    SessionStore,
    SpriteRecipe,
    StoredSprite,
    parse_ref,
    replace_override,
)

PAGE_SIZE = 9
CHARACTER_BY_VALUE = {
    character.value: name for name, character in CHARACTER_NAME_MAP.items()
}
SPRITE_HELP = f"""创建立绘
  立绘 <角色名>
  支持角色：{"、".join(CHARACTER_NAMES)}
  创建后会先发送官方预设选择表，不会直接生成默认立绘。

选择图片
  回复选择表发送 P、H、E、I、M、A 或 D 加图片编号，例如 H2、I12。
  P：初始官方预设；H：头型；E：表情；I：眼睛；M：嘴巴；A：手臂组合；D：脸红、汗等细节。
  编号跨页连续：第一页 1～9、第二页 10～18；在后续页可直接回复前面页的编号。
  熟悉编号后，也可以直接回复立绘发送 H1、H2、M1 等快速修改。
  回复 上一页 / 下一页 可以翻页。

编辑立绘
  回复一张已生成的立绘发送以下命令：
  头型  切换角色的备用头型；重置表情、眼嘴和头部细节，保留手臂
  表情  打开表情选择表；保留当前预设和细节
  眼睛 / 嘴巴  分开调整五官；选项也来自官方组合中的底层素材
  手臂  打开官方手臂组合选择表；保留表情和细节
  细节  打开脸红、汗、苍白等细节选择表；保留其他设置
  +脸红 / -脸红 / +汗 / -汗  直接切换对应细节
  配方  查看角色、官方组合、覆盖项和内容短码

回复与短码
  选择编号可以回复选择表或立绘；翻页必须回复对应的选择表。
  每个短码都固定编码了角色和完整配方，不依赖本机保存记录。
  例如梅露露 P1 的固定短码是 #CFAMVMR9LZ，可以发送：
  #CFAMVMR9LZ 表情
  #CFAMVMR9LZ 配方
  只发送该短码会直接生成立绘，随后可回复该图继续编辑。
  普通聊天中的 P1、表情 等文字不会启动编辑。

内容与历史
  每张生成结果都是可以直接使用的完整立绘。
  资源不变时，相同组合永远得到相同短码；换机器或清空记录后仍可解码。
  回复旧图即可从旧组合继续编辑，不需要撤销或完成操作。
  回复上下文仍会在本机永久保存，不设过期时间。"""
REF_PATTERN = rf"#[{CODE_ALPHABET}]{{{CODE_LENGTH}}}"
PICKER_CHOICE_PATTERN = r"[PHEIMAD][1-9][0-9]{0,3}"
COMMAND_PATTERN = (
    rf"(?:{PICKER_CHOICE_PATTERN}|上一页|下一页|头型|表情|眼睛|嘴巴|手臂|细节|配方|"
    r"\+脸红|-脸红|\+汗|-汗)"
)
FOLLOWUP_RE = re.compile(
    rf"^(?:(?P<ref>{REF_PATTERN})(?:\s+(?P<ref_command>{COMMAND_PATTERN}))?"
    rf"|(?P<reply_command>{COMMAND_PATTERN}))$",
    re.IGNORECASE,
)


_CATALOG: PresetCatalog | None = None
_SESSION_STORE: SessionStore | None = None
_RENDERER: SpriteRenderer | None = None
_CODEC: RecipeCodec | None = None


def _initialize_runtime() -> None:
    global _CATALOG, _SESSION_STORE, _RENDERER, _CODEC
    if _SESSION_STORE is not None:
        return

    asset_root = prefab_asset_root()
    _CATALOG = PresetCatalog(asset_root=asset_root)
    _SESSION_STORE = SessionStore(
        localstore.get_plugin_data_file("sprite_sessions.json")
    )
    _RENDERER = SpriteRenderer(
        _CATALOG,
        localstore.get_plugin_cache_dir() / "sprite_previews",
        asset_root=asset_root,
    )
    _CODEC = RecipeCodec(_CATALOG, _RENDERER.prefab)


def _catalog() -> PresetCatalog:
    _initialize_runtime()
    assert _CATALOG is not None
    return _CATALOG


def _session_store() -> SessionStore:
    _initialize_runtime()
    assert _SESSION_STORE is not None
    return _SESSION_STORE


def _renderer() -> SpriteRenderer:
    _initialize_runtime()
    assert _RENDERER is not None
    return _RENDERER


def _recipe_codec() -> RecipeCodec:
    _initialize_runtime()
    assert _CODEC is not None
    return _CODEC


def _target_key(bot: Bot, event: Event) -> str:
    target = get_target(event, bot)
    kind = "private" if target.private else "channel"
    return "|".join(
        (
            bot.adapter.get_name(),
            str(bot.self_id),
            kind,
            str(target.parent_id),
            str(target.id),
        )
    )


def _message_key(bot: Bot, event: Event, message_id: str) -> str:
    return f"{_target_key(bot, event)}|{message_id}"


def _receipt_ids(receipt: object) -> list[str]:
    replies = getattr(receipt, "get_reply", lambda: None)()
    if replies:
        return [str(reply.id) for reply in replies]
    return [
        str(value) for value in getattr(receipt, "msg_ids", []) if value is not None
    ]


async def _send_tracked(
    bot: Bot,
    event: Event,
    message: UniMessage,
    context: MessageContext,
) -> None:
    receipt = await message.send(target=event, bot=bot)
    for message_id in _receipt_ids(receipt):
        await _session_store().set_message(
            _message_key(bot, event, message_id), context
        )


def _page(values: list[str], page: int) -> tuple[list[str], int, int]:
    total_pages = max(1, math.ceil(len(values) / PAGE_SIZE))
    page = min(max(page, 0), total_pages - 1)
    start = page * PAGE_SIZE
    return values[start : start + PAGE_SIZE], page, total_pages


def _picker_prefix(picker: PickerKind) -> str:
    return {
        "preset": "P",
        "head": "H",
        "expression": "E",
        "eyes": "I",
        "mouth": "M",
        "arm": "A",
        "detail": "D",
    }[picker]


def _picker_from_prefix(prefix: str) -> PickerKind:
    return {
        "P": "preset",
        "H": "head",
        "E": "expression",
        "I": "eyes",
        "M": "mouth",
        "A": "arm",
        "D": "detail",
    }[prefix.upper()]


def _picker_title(picker: PickerKind) -> str:
    return {
        "preset": "官方预设",
        "head": "头型",
        "expression": "表情",
        "eyes": "眼睛",
        "mouth": "嘴巴",
        "arm": "手臂",
        "detail": "细节",
    }[picker]


def _choices_for_picker(character: str, picker: PickerKind) -> list[str]:
    if picker == "preset":
        return [preset.id for preset in _catalog().presets(character)]
    if picker == "arm":
        return _catalog().arm_choices(character)
    prefab = _renderer().prefab(character)
    if picker == "head":
        return _catalog().head_choices(character, prefab)
    if picker == "expression":
        return _catalog().editor_expression_choices(character, prefab)
    if picker in {"eyes", "mouth"}:
        return _catalog().face_part_choices(character, prefab, picker)
    return _catalog().detail_choices(prefab)


def _compatible_picker_choices(
    character: str,
    picker: PickerKind,
    choices: list[str],
    recipe: SpriteRecipe | None,
) -> list[str]:
    if recipe is None or picker not in {"expression", "eyes", "mouth", "detail"}:
        return choices
    renderer = _renderer()
    prefab = renderer.prefab(character)
    active_nodes = renderer.compose_recipe(character, recipe)
    if picker == "detail":
        return _catalog().compatible_detail_choices(prefab, choices, active_nodes)
    return _catalog().compatible_face_part_choices(
        prefab,
        "eyes" if picker == "expression" else picker,
        choices,
        active_nodes,
    )


async def _sprite_from_ref(value: str | None) -> tuple[str, StoredSprite] | None:
    if not value:
        return None
    code = parse_ref(value)
    if not code:
        return None
    sprite = await _session_store().get_sprite(code)
    if sprite is not None:
        return code, sprite

    decoded = await asyncio.to_thread(_recipe_codec().decode, code)
    if decoded is None:
        return None
    character, recipe = decoded
    await _session_store().put_sprite(character, recipe, code=code)
    return code, StoredSprite(character=character, recipe=recipe)


async def _send_picker(
    bot: Bot,
    event: Event,
    *,
    character: str,
    picker: PickerKind,
    choices: list[str],
    page: int,
    base_sprite: str | None,
) -> None:
    base = await _sprite_from_ref(base_sprite)
    recipe = base[1].recipe if base else None
    choices = _compatible_picker_choices(character, picker, choices, recipe)
    shown, page, total_pages = _page(choices, page)
    if not shown:
        await UniMessage.text(f"当前角色没有可用的{_picker_title(picker)}选项。").send(
            target=event, bot=bot
        )
        return
    prefix = _picker_prefix(picker)
    first_number = page * PAGE_SIZE + 1
    last_number = first_number + len(shown) - 1
    labels = [f"{prefix}{index}" for index in range(first_number, last_number + 1)]
    image = await asyncio.to_thread(
        _renderer().render_picker,
        character,
        picker,
        shown,
        recipe,
        labels=labels,
    )
    code_prefix = f"#{base_sprite} · " if base_sprite else ""
    if page == 0:
        selection_help = f"请回复 {prefix}1～{prefix}{last_number} 选择；"
    else:
        selection_help = (
            f"图中为 {prefix}{first_number}～{prefix}{last_number}；"
            f"可回复 {prefix}1～{prefix}{last_number} 选择本页或之前的选项；"
        )
    caption = (
        f"{code_prefix}{_picker_title(picker)} {page + 1}/{total_pages}\n"
        f"{selection_help}回复 上一页 / 下一页 翻页。"
    )
    context = MessageContext(
        kind="picker",
        character=character,
        base_sprite=base_sprite,
        picker=picker,
        page=page,
        # Keep the entire numbered list stable so later pages can select earlier
        # entries without paging backwards. Old contexts retain page-local choices.
        choices=choices,
        global_numbering=True,
    )
    await _send_tracked(
        bot,
        event,
        UniMessage.image(raw=image, mimetype="image/png").text(f"\n{caption}"),
        context,
    )


async def _send_sprite(bot: Bot, event: Event, code: str) -> None:
    stored = await _session_store().get_sprite(code)
    if stored is None:
        return
    image = await asyncio.to_thread(
        _renderer().render_recipe, stored.character, stored.recipe
    )
    caption = (
        f"#{code} · {CHARACTER_BY_VALUE.get(stored.character, stored.character)}\n"
        "回复：头型 / 表情 / 眼睛 / 嘴巴 / 手臂 / 细节 / 配方"
    )
    await _send_tracked(
        bot,
        event,
        UniMessage.image(raw=image, mimetype="image/png").text(f"\n{caption}"),
        MessageContext(kind="sprite", character=stored.character, sprite=code),
    )


async def _context_from_input(
    bot: Bot,
    event: Event,
    message: OriginalUniMsg,
    explicit_ref: str | None,
) -> MessageContext | None:
    if explicit_ref:
        resolved = await _sprite_from_ref(explicit_ref)
        if not resolved:
            return None
        code, stored = resolved
        return MessageContext(kind="sprite", character=stored.character, sprite=code)

    reply = next((segment for segment in message if isinstance(segment, Reply)), None)
    if reply is None:
        return None
    return await _session_store().get_message(_message_key(bot, event, str(reply.id)))


def _base_sprite(context: MessageContext) -> str | None:
    return context.sprite if context.kind == "sprite" else context.base_sprite


async def _apply_recipe(
    bot: Bot,
    event: Event,
    character: str,
    recipe: SpriteRecipe,
) -> None:
    code = await asyncio.to_thread(_recipe_codec().encode, character, recipe)
    await _session_store().put_sprite(character, recipe, code=code)
    await _send_sprite(bot, event, code)


async def _picker_choice(
    bot: Bot, event: Event, context: MessageContext, command: str
) -> None:
    if context.kind == "picker":
        assert context.picker is not None
        picker = context.picker
        expected = _picker_prefix(picker)
        if command[0].upper() != expected:
            await UniMessage.text(f"请使用 {expected} 加编号选择这张选择表。 ").send(
                target=event, bot=bot
            )
            return
        choices = context.choices
        base_code = context.base_sprite
    else:
        picker = _picker_from_prefix(command[0])
        base_code = context.sprite
        choices = _choices_for_picker(context.character, picker)

    base = await _sprite_from_ref(base_code)
    base_recipe = base[1].recipe if base else None
    if context.kind == "sprite":
        choices = _compatible_picker_choices(
            context.character, picker, choices, base_recipe
        )

    index = int(command[1:]) - 1
    if index >= len(choices):
        location = "当前立绘" if context.kind == "sprite" else "这张选择表"
        await UniMessage.text(f"这个编号不在{location}的选项中。 ").send(
            target=event, bot=bot
        )
        return
    recipe = _renderer().recipe_with_choice(base_recipe, picker, choices[index])
    await _apply_recipe(bot, event, context.character, recipe)


def _modifier_choice(character: str, recipe: SpriteRecipe, command: str) -> str | None:
    choices = _catalog().detail_choices(_renderer().prefab(character))
    choices = _compatible_picker_choices(character, "detail", choices, recipe)
    checks = {
        "+脸红": lambda key: (
            key.lower().startswith("cheeks") and "flushed" in key.lower()
        ),
        "-脸红": lambda key: key.lower().startswith("cheeks") and "off" in key.lower(),
        "+汗": lambda key: key.lower().startswith("sweat") and "off" not in key.lower(),
        "-汗": lambda key: key.lower().startswith("sweat") and "off" in key.lower(),
    }
    predicate = checks[command]
    return next((key for key in choices if predicate(key)), None)


async def handle_sprite(bot: Bot, event: Event, result: Arparma) -> None:
    character_name = result["character"]
    if not character_name:
        await UniMessage.text("用法：立绘 <角色名>\n发送 立绘 -h 查看完整帮助。").send(
            target=event, bot=bot
        )
        return
    try:
        character = CHARACTER_NAME_MAP[character_name].value
    except KeyError:
        await UniMessage.text(
            f"角色名 {character_name} 无效。支持角色：" + "、".join(CHARACTER_NAMES)
        ).send(target=event, bot=bot)
        return
    asset_status = prefab_asset_status()
    if not asset_status.available:
        await UniMessage.text(prefab_unavailable_message(asset_status)).send(
            target=event, bot=bot
        )
        return
    presets = _catalog().presets(character)
    if not presets:
        await UniMessage.text(f"{character_name} 暂无可用的官方预设。").send(
            target=event, bot=bot
        )
        return
    await _send_picker(
        bot,
        event,
        character=character,
        picker="preset",
        choices=[preset.id for preset in presets],
        page=0,
        base_sprite=None,
    )


async def handle_sprite_followup(
    bot: Bot, event: Event, message: OriginalUniMsg
) -> None:
    await _session_store().load()
    text = event.get_message().extract_plain_text().strip()
    match = FOLLOWUP_RE.fullmatch(text)
    if not match:
        return
    explicit_ref = match.group("ref")
    command = match.group("ref_command") or match.group("reply_command")
    if command and re.fullmatch(PICKER_CHOICE_PATTERN, command, re.IGNORECASE):
        command = command.upper()

    asset_status = prefab_asset_status()
    if not asset_status.available:
        await UniMessage.text(prefab_unavailable_message(asset_status)).send(
            target=event, bot=bot
        )
        return

    context = await _context_from_input(bot, event, message, explicit_ref)
    if context is None:
        if explicit_ref:
            await UniMessage.text("没有找到这个立绘短码。 ").send(target=event, bot=bot)
        return

    if command is None:
        assert context.sprite is not None
        await _send_sprite(bot, event, context.sprite)
        return

    if re.fullmatch(PICKER_CHOICE_PATTERN, command):
        await _picker_choice(bot, event, context, command)
        return

    if command in {"上一页", "下一页"}:
        if context.kind != "picker" or context.picker is None:
            await UniMessage.text("请回复一张选择表进行翻页。 ").send(
                target=event, bot=bot
            )
            return
        all_choices = (
            context.choices
            if context.global_numbering
            else _choices_for_picker(context.character, context.picker)
        )
        next_page = context.page + (1 if command == "下一页" else -1)
        _, bounded, _ = _page(all_choices, next_page)
        if bounded == context.page:
            await UniMessage.text(
                "已经是最后一页。" if command == "下一页" else "已经是第一页。"
            ).send(target=event, bot=bot)
            return
        await _send_picker(
            bot,
            event,
            character=context.character,
            picker=context.picker,
            choices=all_choices,
            page=next_page,
            base_sprite=context.base_sprite,
        )
        return

    base_code = _base_sprite(context)
    base = await _sprite_from_ref(base_code)
    if base is None:
        await UniMessage.text("请先从预设选择表中选出第一版立绘。 ").send(
            target=event, bot=bot
        )
        return

    code, stored = base
    recipe = stored.recipe
    if command in {"头型", "表情", "眼睛", "嘴巴", "手臂", "细节"}:
        picker_by_command: dict[str, PickerKind] = {
            "头型": "head",
            "表情": "expression",
            "眼睛": "eyes",
            "嘴巴": "mouth",
            "手臂": "arm",
            "细节": "detail",
        }
        picker = picker_by_command[command]
        choices = _choices_for_picker(stored.character, picker)
        if not choices:
            title = _picker_title(picker)
            await UniMessage.text(f"当前角色没有可用的{title}选项。 ").send(
                target=event, bot=bot
            )
            return
        await _send_picker(
            bot,
            event,
            character=stored.character,
            picker=picker,
            choices=choices,
            page=0,
            base_sprite=code,
        )
    elif command in {"+脸红", "-脸红", "+汗", "-汗"}:
        choice = _modifier_choice(stored.character, recipe, command)
        if choice is None:
            await UniMessage.text("当前角色没有对应的细节素材。 ").send(
                target=event, bot=bot
            )
            return
        await _apply_recipe(
            bot,
            event,
            stored.character,
            SpriteRecipe(
                base_preset=recipe.base_preset,
                overrides=replace_override(recipe.overrides, choice),
            ),
        )
    elif command == "配方":
        preset = _catalog().preset(recipe.base_preset)
        overrides = "、".join(recipe.overrides) if recipe.overrides else "无"
        appearance = ",".join(preset.appearance)
        await UniMessage.text(
            f"短码：#{code}\n角色：{CHARACTER_BY_VALUE.get(stored.character, stored.character)}\n"
            f"基础预设：{recipe.base_preset}\n官方组合：{appearance}\n覆盖项：{overrides}"
        ).send(target=event, bot=bot)
