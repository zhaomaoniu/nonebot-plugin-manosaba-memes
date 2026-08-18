import struct
from pathlib import Path


def get_png_size(file_path: Path) -> tuple[int, int]:
    """Get the size of a PNG file

    Args:
        file_path (Path): The path to the PNG file

    Returns:
        Tuple[int, int]: The width and height of the PNG file
    """
    with open(file_path, "rb") as f:
        f.seek(16)
        data = f.read(8)
        width, height = struct.unpack(">II", data)
        return width, height
