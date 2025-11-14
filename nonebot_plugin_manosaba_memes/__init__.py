import re
from collections import defaultdict

from nonebot import require, on_regex
from nonebot.internal.adapter import Bot, Event
from nonebot.plugin import PluginMetadata, inherit_supported_adapters

require("nonebot_plugin_alconna")

from nonebot_plugin_alconna import (  # noqa: E402
    Args,
    Alconna,
    Arparma,
    on_alconna,
    UniMessage,
    CommandMeta,
)

from .models import Option  # noqa: E402
from .drawer import draw_anan, draw_trial  # noqa: E402
from .utils import get_statement, get_character  # noqa: E402


usage = """
安安说 [文本] [表情]
    表情可选：害羞, 生气, 病娇, 无语, 开心
切换角色 [角色名]
    角色名可选：艾玛, 希罗
发送格式如下的消息以生成审判表情包：
【疑问/反驳/伪证/赞同】这是一个选项文本
可发送多行以添加多个选项
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
trail_handler = on_regex(r"^【(疑问|反驳|伪证|赞同)】(.+)$", flags=re.MULTILINE)
switch_character_handler = on_alconna(
    Alconna(
        "切换角色",
        Args["character", str],
        meta=CommandMeta(
            description="切换审判选择中的角色",
            usage="切换角色 [角色名]\n角色名可选：艾玛, 希罗",
            example="切换角色 希罗",
        ),
    ),
    use_cmd_start=True,
)


@anan_says_handler.handle()
async def handle_anan_says(result: Arparma):
    user_result = result["text"]
    face = result["face"]
    text = user_result.replace("\\n", "\n")
    image_bytes = draw_anan(text, face)
    await anan_says_handler.finish(UniMessage.image(raw=image_bytes))


@trail_handler.handle()
async def handle_trail(bot: Bot, event: Event):
    matches = re.findall(
        r"^【(疑问|反驳|伪证|赞同)】(.+)$",
        event.get_message().extract_plain_text(),
        flags=re.M,
    )

    options = []
    for statement_type, text in matches:
        statement_enum = get_statement(statement_type)
        options.append(Option(statement_enum, text))

    try:
        image_bytes = draw_trial(CHARACTER_MAP[event.get_user_id()], options)
    except OverflowError:
        await trail_handler.finish("选项过多，请减少选项数量")
    await trail_handler.finish(await UniMessage.image(raw=image_bytes).export(bot))


@switch_character_handler.handle()
async def handle_switch_character(evemt: Event, result: Arparma):
    global CHARACTER_MAP
    character_name = result["character"]
    try:
        CHARACTER_MAP[evemt.get_user_id()] = get_character(character_name)
        await switch_character_handler.finish(f"已切换角色为 {character_name}")
    except KeyError:
        await switch_character_handler.finish(
            f"角色名 {character_name} 无效，请选择 艾玛 或 希罗"
        )
