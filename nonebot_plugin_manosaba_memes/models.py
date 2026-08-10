from enum import Enum


class StrEnum(str, Enum):
    """String Enum base class"""


class Character(StrEnum):
    """Characters available for trail drawing"""

    MERURU = "Meruru"
    NOAH = "Noah"
    HANNA = "Hanna"
    NANOKA = "Nanoka"
    ALISA = "Alisa"
    MIRIA = "Miria"
    SHERRY = "Sherry"
    EMA = "Ema"
    MARGO = "Margo"
    ANAN = "AnAn"
    COCO = "Coco"
    HIRO = "Hiro"
    LEIA = "Leia"


class Statement(StrEnum):
    """Types of statements for the trail drawing"""

    AGREEMENT = "Agreement"
    DOUBT = "Doubt"
    PURJURY = "Perjury"
    REFUTATION = "Refutation"
    MAGIC_CHIYUSAISEI = "Magic Chiyu & Saisei"
    MAGIC_EKITAISOUSA = "Magic Ekitai Sousa"
    MAGIC_FUYUU = "Magic Fuyuu"
    MAGIC_GENSHI = "Magic Genshi"
    MAGIC_HAKKA = "Magic Hakka"
    MAGIC_IREKAWARI = "Magic Irekawari"
    MAGIC_KAIRIKI = "Magic Kairiki"
    MAGIC_MAJOGOROSHI = "Magic Majo Goroshi"
    MAGIC_MONOMANE = "Magic Monomane"
    MAGIC_SENNOU = "Magic Sennou"
    MAGIC_SENRIGAN = "Magic Senrigan"
    MAGIC_SHINIMODORI = "Magic Shini Modori"
    MAGIC_SHISENYUUDOU = "Magic Shisen Yuudou"


class Option:
    """A trial option for a character to say"""

    def __init__(self, statement: Statement, text: str) -> None:
        """Initialize a trail option

        Args:
            statement (Statement): The type of statement this option represents
            text (str): The text content of the option
        """
        self.statement = statement
        self.text = text
