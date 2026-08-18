import re
from collections import defaultdict

from nonebot import on_regex, require
from nonebot.internal.adapter import Bot, Event
from nonebot.plugin import PluginMetadata, inherit_supported_adapters

require("nonebot_plugin_alconna")
require("nonebot_plugin_localstore")

from nonebot_plugin_alconna import (
    Alconna,
    Args,
    Arparma,
    CommandMeta,
    OriginalUniMsg,
    UniMessage,
    on_alconna,
)

from .drawer import draw_anan, draw_trial
from .models import Option
from .sprite_editor.interaction import (
    FOLLOWUP_RE,
    SPRITE_HELP,
    handle_sprite,
    handle_sprite_followup,
)
from .utils import CHARACTER_NAMES, get_character, get_statement

CHARACTER_NAMES_TEXT = ", ".join(CHARACTER_NAMES)

usage = f"""
安安说 [文本] [表情]
    表情可选：害羞, 生气, 病娇, 无语, 开心
切换角色 [角色名]
    角色名可选：{CHARACTER_NAMES_TEXT}
发送格式如下的消息以生成审判表情包：
【疑问/反驳/伪证/赞同/魔法:[角色名]】这是一个选项文本
    角色名可选：{CHARACTER_NAMES_TEXT}
    可发送多行以添加多个选项
立绘 [角色名]
    从官方预设开始生成立绘，并通过回复消息精细调整
    发送 立绘 -h 查看完整帮助
""".strip()

__plugin_meta__ = PluginMetadata(
    name="魔裁 Memes",
    description="生成「魔法少女的魔法审判」的表情包",
    usage=usage,
    type="application",
    homepage="https://github.com/zhaomaoniu/nonebot-plugin-manosaba-memes",
    supported_adapters=inherit_supported_adapters("nonebot_plugin_alconna"),
)

CHARACTER_MAP = defaultdict(lambda: get_character("艾玛"))


anan_says_handler = on_alconna(
    Alconna(
        "安安说",
        Args["text", str]["face", str, None],
        meta=CommandMeta(
            description="让安安说话的插件",
            usage="安安说 [文本] [表情]\n表情可选：害羞, 生气, 病娇, 无语, 开心",
            example="安安说 吾辈现在不想说话",
        ),
    ),
    aliases={"anan说", "anansays"},
    use_cmd_start=True,
)
trail_handler = on_regex(
    r"^【(疑问|反驳|伪证|赞同|魔法)(?:[:：]([^】]*))?】(.+)$", flags=re.MULTILINE
)
switch_character_handler = on_alconna(
    Alconna(
        "切换角色",
        Args["character", str],
        meta=CommandMeta(
            description="切换审判选择中的角色",
            usage=f"切换角色 [角色名]\n角色名可选：{CHARACTER_NAMES_TEXT}",
            example="切换角色 希罗",
        ),
    ),
    use_cmd_start=True,
)
sprite_handler = on_alconna(
    Alconna(
        "立绘",
        Args["character", str, None],
        meta=CommandMeta(
            description="从官方预设创建并精细调整角色立绘",
            usage=SPRITE_HELP,
            example=(
                "立绘 梅露露\n"
                "P1\n"
                "#CFAMVMR9LZ\n"
                "#CFAMVMR9LZ 眼睛"
            ),
        ),
    ),
    use_cmd_start=True,
)
sprite_followup_handler = on_regex(
    FOLLOWUP_RE.pattern,
    flags=re.IGNORECASE,
    priority=12,
    block=False,
)


@anan_says_handler.handle()
async def handle_anan_says(result: Arparma):
    user_result = result["text"]
    face = result["face"]
    text = user_result.replace("\\n", "\n")
    image_bytes = draw_anan(text, face)
    await anan_says_handler.finish(
        UniMessage.image(raw=image_bytes, mimetype="image/png")
    )


@trail_handler.handle()
async def handle_trail(bot: Bot, event: Event):
    matches = re.findall(
        r"^【(疑问|反驳|伪证|赞同|魔法)(?:[:：]([^】]*))?】(.+)$",
        event.get_message().extract_plain_text(),
        flags=re.MULTILINE,
    )

    options = []
    for statement_type, arg, text in matches:
        try:
            statement_enum = get_statement(statement_type, arg)
        except KeyError:
            if arg:
                await trail_handler.finish(
                    f"角色 {arg} 无效，请从以下选项中选择：{CHARACTER_NAMES_TEXT}"
                )
            else:
                await trail_handler.finish(
                    "魔法类型无效，请输入【魔法:角色】格式。可选的角色有："
                    f"{CHARACTER_NAMES_TEXT}"
                )
        options.append(Option(statement_enum, text))

    try:
        image_bytes = draw_trial(CHARACTER_MAP[event.get_user_id()], options)
    except OverflowError:
        await trail_handler.finish("选项过多，请减少选项数量")
    await trail_handler.finish(
        await UniMessage.image(raw=image_bytes, mimetype="image/png").export(bot)
    )


@switch_character_handler.handle()
async def handle_switch_character(evemt: Event, result: Arparma):
    character_name = result["character"]
    try:
        CHARACTER_MAP[evemt.get_user_id()] = get_character(character_name)
        await switch_character_handler.finish(f"已切换角色为 {character_name}")
    except KeyError:
        await switch_character_handler.finish(
            f"角色名 {character_name} 无效，请选择：{CHARACTER_NAMES_TEXT}"
        )


@sprite_handler.handle()
async def handle_sprite_entry(bot: Bot, event: Event, result: Arparma) -> None:
    await handle_sprite(bot, event, result)


@sprite_followup_handler.handle()
async def handle_sprite_followup_entry(
    bot: Bot, event: Event, message: OriginalUniMsg
) -> None:
    await handle_sprite_followup(bot, event, message)
