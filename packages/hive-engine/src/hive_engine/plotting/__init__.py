import matplotlib.gridspec as gridspec
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from hive_engine.plotting.drawing import (
    draw_grid,
    draw_hand_panel,
    draw_highlights,
    draw_pieces,
    fit_axes_to_grid,
)
from hive_engine.plotting.geometry import (
    HexOrientation,
    get_distance,
    get_grid_coords,
)
from hive_engine.state import Coordinate, GameState

HEX_SIZE = 1.0


def draw_board(
    state: GameState,
    orientation: HexOrientation = HexOrientation.POINTY_TOP,
    highlights: dict[str, list[Coordinate]] | None = None,
    use_sprites: bool = True,
    sprite_resolution: int = 256,
    show_hands: bool = True,
    title: str | None = None,
    figsize: tuple[float, float] = (12, 12),
    dpi: int = 300,
) -> Figure:
    """Draw the Hive game board with an optional hand panel.

    Parameters
    ----------
    state : GameState
        The game state to visualize. The board layout, player hands, and current player
        are all read from this object.
    orientation : HexOrientation
        Whether hexagons are pointy-top or flat-top, by default pointy-top.
    highlights : dict[str, list[Coordinate]] or None
        Color string to list of coordinates that should receive a colored highlight ring,
        by default `None`, which disables highlighting.
    use_sprites : bool
        Whether to load piece sprites from the bundled assets or fall back to character
        sprites, by default True.
    sprite_resolution : int
        Pixel size for sprite rendering, by default 256.
    show_hands : bool
        Whether to draw a hand panel below the board showing each player's remaining
        pieces and whose turn it is, by default True.
    title : str or None
        An optional title displayed above the board, by default None.
    figsize : tuple[float, float]
        The overall figure size in inches, by default (12, 12).
    dpi : int
        The figure resolution in dots per inch, by default 300.

    Returns
    -------
    Figure
        The matplotlib figure containing the rendered board.
    """
    if highlights is None:
        highlights = {}

    # Determine the grid extent based on the furthest occupied coordinate. Always show
    # at least a radius of 3 to give some breathing room around the starting pieces.
    max_distance = max(get_distance((0, 0), c) for c in state.board)
    grid_radius = max(3, max_distance + 1)
    grid_coords = get_grid_coords(grid_radius)

    # Create the figure with an optional lower subplot for the hand panel.
    if show_hands:
        fig = plt.figure(figsize=figsize, dpi=dpi)
        gs = gridspec.GridSpec(2, 1, height_ratios=[5, 1], hspace=0.05)
        ax_board: Axes = fig.add_subplot(gs[0])
        ax_hand: Axes = fig.add_subplot(gs[1])
    else:
        fig, ax_board = plt.subplots(1, 1, figsize=figsize, dpi=dpi)
        ax_hand = None

    ax_board.set_aspect("equal")
    ax_board.axis("off")
    if title:
        ax_board.set_title(title, fontsize=14, fontweight="bold", pad=12)

    # Draw the layers of the board from back to front.
    draw_grid(
        ax=ax_board,
        grid_coords=grid_coords,
        orientation=orientation,
        size=HEX_SIZE,
    )
    draw_pieces(
        ax=ax_board,
        state=state,
        orientation=orientation,
        size=HEX_SIZE,
        use_sprites=use_sprites,
        sprite_resolution=sprite_resolution,
    )
    draw_highlights(
        ax=ax_board,
        highlights=highlights,
        orientation=orientation,
        size=HEX_SIZE,
    )
    fit_axes_to_grid(
        ax=ax_board,
        grid_coords=grid_coords,
        orientation=orientation,
        size=HEX_SIZE,
    )

    # Draw the hand panel if requested.
    if show_hands and ax_hand is not None:
        draw_hand_panel(
            ax=ax_hand,
            state=state,
            orientation=orientation,
            use_sprites=use_sprites,
            sprite_resolution=sprite_resolution,
        )

    if show_hands:
        fig.subplots_adjust(hspace=0.02)
    else:
        fig.tight_layout()

    return fig
