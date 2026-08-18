import math
from pathlib import Path

from sketchbook import (
    Align,
    Drawer,
    FontSet,
    Layer,
    ParseRule,
    Region,
    ScaleMode,
    StyleMod,
    TextStyle,
    VAlign,
)

from .models import Character, Option, Statement
from .utils import get_png_size

PLUGIN_PATH = Path(__file__).parent
TRIAL_ASSET_PATH = PLUGIN_PATH / "assets/trial"
TRIAL_CHARACTER_PATH = TRIAL_ASSET_PATH / "characters"
TRIAL_STATEMENT_PATH = TRIAL_ASSET_PATH / "statements"
TRIAL_UI_PATH = TRIAL_ASSET_PATH / "ui"


def get_anan_base_image(face: str | None = None) -> str:
    """Get the base image path for Anan's face

    Args:
        face (Optional[str], optional): The face type to be used. Available: 害羞, 生气, 病娇, 无语, 开心. Defaults to None.

    Returns:
        str: The path to the base image
    """
    if face is None:
        return str(PLUGIN_PATH / "assets/anan/base.png")
    else:
        available_faces = [
            p.stem
            for p in Path(PLUGIN_PATH / "assets/anan").glob("*.png")
            if not p.stem.startswith("base")
        ]
        if face not in available_faces:
            raise ValueError(
                f"Invalid face: {face}. Available faces: {available_faces}"
            )
        return str(PLUGIN_PATH / f"assets/anan/{face}.png")


def draw_anan(text: str, face: str | None = None) -> bytes:
    """Draw the image of what Anan says

    Args:
        text (str): The text to be drawn
        face (Optional[str], optional): The face type to be used. Available: 害羞, 生气, 病娇, 无语, 开心. Defaults to None.

    Returns:
        bytes: The image bytes of the drawn image
    """
    fonts = FontSet(str(PLUGIN_PATH / "assets/fonts/SourceHanSansSC-Bold.otf"))
    drawer = Drawer.from_image(get_anan_base_image(face), fonts)
    drawer.layer(
        Layer("text").text(
            text,
            Region(100, 432, 319, 204),
            TextStyle(color=(0, 0, 0, 255), align=Align.Center, valign=VAlign.Middle),
        )
    )
    drawer.overlay(str(PLUGIN_PATH / "assets/anan/base_overlay.png"))
    return drawer.render()


def get_statement_image(statement: Statement) -> str:
    """Get the image path for a statement type

    Args:
        statement (Statement): The statement type

    Returns:
        str: The path to the statement image
    """
    mapping = {
        Statement.AGREEMENT: "agreement.png",
        Statement.DOUBT: "doubt.png",
        Statement.PURJURY: "perjury.png",
        Statement.REFUTATION: "refutation.png",
        Statement.MAGIC_CHIYUSAISEI: "magic_chiyusaisei.png",
        Statement.MAGIC_EKITAISOUSA: "magic_ekitaisousa.png",
        Statement.MAGIC_FUYUU: "magic_fuyuu.png",
        Statement.MAGIC_GENSHI: "magic_genshi.png",
        Statement.MAGIC_HAKKA: "magic_hakka.png",
        Statement.MAGIC_IREKAWARI: "magic_irekawari.png",
        Statement.MAGIC_KAIRIKI: "magic_kairiki.png",
        Statement.MAGIC_MAJOGOROSHI: "magic_majogoroshi.png",
        Statement.MAGIC_MONOMANE: "magic_monomane.png",
        Statement.MAGIC_SENNOU: "magic_sennou.png",
        Statement.MAGIC_SENRIGAN: "magic_senrigan.png",
        Statement.MAGIC_SHINIMODORI: "magic_shinimodori.png",
        Statement.MAGIC_SHISENYUUDOU: "magic_shisenyuudou.png",
    }
    return str(TRIAL_STATEMENT_PATH / mapping[statement])


def get_option_coordinates(number: int) -> list[tuple[int, int]]:
    """Get the coordinates for drawing options based on the number of options

    Args:
        number (int): The number of options

    Returns:
        List[Tuple[int, int]]: A list of (x, y) coordinates for each option
    """
    if number % 2 == 1:
        padding = min(
            286,
            (1080 - 364 - 216) // math.floor(number / 2)
            if math.floor(number / 2) != 0
            else 286,
            (-364 + 47) // math.ceil(-number / 2)
            if math.ceil(-number / 2) != 0
            else 286,
        )
        return [
            (29, 364 + padding * i)
            for i in range(math.ceil(-number / 2), math.floor(number / 2) + 1)
        ]
    else:
        padding = min(
            286,
            (1080 - 364 - 216) // (math.floor(number / 2) - 0.5),
            (-364 + 47) // (math.ceil(-number / 2) + 0.5),
        )
        return [
            (29, int(364 + padding * (i + 0.5)))
            for i in range(math.ceil(-number / 2), math.floor(number / 2))
        ]


def draw_trial(character: Character, options: list[Option]) -> bytes:
    """Draw the trial image for a character saying an option

    Args:
        character (Character): The character who is speaking
        options (List[Option]): The options being spoken

    Returns:
        bytes: The image bytes of the drawn image
    """
    fonts = FontSet(str(PLUGIN_PATH / "assets/fonts/SourceHanSerifSC.otf"))
    drawer = Drawer.from_image(str(TRIAL_UI_PATH / "black.png"), fonts)
    drawer.layer(
        Layer("background").image_fit(
            str(TRIAL_UI_PATH / "background.png"),
            Region(0, 0, 1260, 1080),
            scale=ScaleMode.Stretch,
        )
    )

    character_image = TRIAL_CHARACTER_PATH / f"{character.value.lower()}.png"
    character_width, character_height = get_png_size(character_image)
    drawer.layer(
        Layer("character").image_fit(
            str(character_image),
            Region(1260 - character_width, 0, character_width, character_height),
            scale=ScaleMode.Stretch,
        )
    )

    coordinates = get_option_coordinates(len(options))
    for idx, (option, (x, y)) in enumerate(zip(options, coordinates)):
        # Option background
        drawer.layer(
            Layer(f"option_bg_{idx}").image_fit(
                str(TRIAL_UI_PATH / "option.png"),
                Region(x, y, 802, 216),
                scale=ScaleMode.Stretch,
            )
        )

        # Option text
        drawer.layer(
            Layer(f"option_text_{idx}").text(
                option.text,
                Region(x + 109, y + 32, 589, 150),
                TextStyle(
                    color=(39, 33, 30, 255),
                    max_font_size=32.0,
                    parse_rules=[
                        ParseRule(
                            "【文本】",
                            "【",
                            "】",
                            StyleMod.color(39, 33, 30, 255),
                            keep_delim=True,
                        )
                    ],
                ),
            )
        )

        # Statement icon
        drawer.layer(
            Layer(f"statement_{idx}").image_fit(
                get_statement_image(option.statement),
                Region(x + 21, y - 43, 146, 128),
                scale=ScaleMode.Stretch,
            )
        )

    return drawer.render()
