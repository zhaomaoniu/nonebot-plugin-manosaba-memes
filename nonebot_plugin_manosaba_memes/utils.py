from typing import Optional

from .models import Statement, Character


def get_magic_statement(text: str) -> Statement:
    """Convert a string magic statement type to a Statement enum

    Args:
        text (str): The string representation of the magic statement type

    Returns:
        Statement: The corresponding Statement enum
    """
    mapping = {
        "梅露露": Statement.MAGIC_CHIYUSAISEI,
        "诺亚": Statement.MAGIC_EKITAISOUSA,
        "汉娜": Statement.MAGIC_FUYUU,
        "奈叶香": Statement.MAGIC_GENSHI,
        "亚里沙": Statement.MAGIC_HAKKA,
        "米莉亚": Statement.MAGIC_IREKAWARI,
        "雪莉": Statement.MAGIC_KAIRIKI,
        "艾玛": Statement.MAGIC_MAJOGOROSHI,
        "玛格": Statement.MAGIC_MONOMANE,
        "安安": Statement.MAGIC_SENNOU,
        "可可": Statement.MAGIC_SENRIGAN,
        "希罗": Statement.MAGIC_SHINIMODORI,
        "蕾雅": Statement.MAGIC_SHISENYUUDOU,
    }
    return mapping[text]


def get_statement(statement: str, arg: Optional[str] = None) -> Statement:
    """Convert a string statement type to a Statement enum

    Args:
        statement (str): The string representation of the statement type
        arg (Optional[str]): Extra argument for the magic statement types

    Returns:
        Statement: The corresponding Statement enum
    """
    match statement:
        case "赞同":
            return Statement.AGREEMENT
        case "疑问":
            return Statement.DOUBT
        case "伪证":
            return Statement.PURJURY
        case "反驳":
            return Statement.REFUTATION
        case "魔法":
            return get_magic_statement(arg)
        case _:
            assert False, "Invalid statement type"


def get_character(character: str) -> Character:
    """Convert a string character name to a Character enum

    Args:
        character (str): The string representation of the character name

    Returns:
        Character: The corresponding Character enum
    """
    mapping = {
        "艾玛": Character.EMA,
        "希罗": Character.HIRO,
    }
    return mapping[character]
