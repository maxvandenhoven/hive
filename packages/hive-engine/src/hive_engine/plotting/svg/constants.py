import importlib.resources

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

SVG_SPRITE_FILENAMES: dict[PieceType, str] = {
    PieceType.QUEEN: "queen.svg",
    PieceType.BEETLE: "beetle.svg",
    PieceType.GRASSHOPPER: "grasshopper.svg",
    PieceType.SPIDER: "spider.svg",
    PieceType.ANT: "ant.svg",
}


def load_svg_sprite(piece_type: PieceType) -> str:
    """Load an SVG sprite from the bundled assets and return its path.

    Parameters
    ----------
    piece_type : PieceType
        The type of piece whose sprite should be loaded.

    Returns
    -------
    str
        The filesystem path to the SVG sprite file.
    """
    sprite_folder = importlib.resources.files("hive_engine.assets.svg")
    return str(sprite_folder.joinpath(SVG_SPRITE_FILENAMES[piece_type]))
