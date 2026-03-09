import importlib.resources

import numpy as np
from PIL import Image

from hive_engine.state import PieceType, Player

PIECE_LABELS: dict[PieceType, str] = {
    PieceType.QUEEN: "Q",
    PieceType.BEETLE: "B",
    PieceType.GRASSHOPPER: "G",
    PieceType.SPIDER: "S",
    PieceType.ANT: "A",
}

PLAYER_COLORS: dict[Player, str] = {
    Player.WHITE: "#F5F0E1",
    Player.BLACK: "#2C2C2C",
}

PLAYER_TEXT_COLORS: dict[Player, str] = {
    Player.WHITE: "#1A1A1A",
    Player.BLACK: "#F0F0F0",
}

PLAYER_NAMES: dict[Player, str] = {
    Player.WHITE: "White",
    Player.BLACK: "Black",
}

SPRITE_FILENAMES: dict[PieceType, str] = {
    PieceType.QUEEN: "queen.png",
    PieceType.BEETLE: "beetle.png",
    PieceType.GRASSHOPPER: "grasshopper.png",
    PieceType.SPIDER: "spider.png",
    PieceType.ANT: "ant.png",
}


def load_sprite(piece_type: PieceType, resolution: int = 256) -> np.ndarray:
    """Load and resize a piece sprite from the bundled assets.

    Parameters
    ----------
    piece_type : PieceType
        The type of piece whose sprite should be loaded.
    resolution : int
        The pixel size to which the sprite is resized.

    Returns
    -------
    np.ndarray
        An RGBA image array of shape `(resolution, resolution, 4)`.
    """
    sprite_folder = importlib.resources.files("hive_engine.assets")
    sprite_path = sprite_folder.joinpath(SPRITE_FILENAMES[piece_type])

    image = Image.open(str(sprite_path)).convert("RGBA")
    image = image.resize((resolution, resolution), Image.Resampling.LANCZOS)

    return np.array(image)
