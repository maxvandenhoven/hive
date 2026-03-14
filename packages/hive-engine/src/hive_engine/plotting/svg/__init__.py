import math

import drawsvg as dw

from hive_engine.plotting.svg.drawing import (
    draw_grid,
    draw_hand_panel,
    draw_highlights,
    draw_pieces,
)
from hive_engine.plotting.svg.geometry import (
    HexOrientation,
    axial_to_pixel,
    get_distance,
    get_grid_coords,
)
from hive_engine.state import Coordinate, GameState, Player

HEX_SIZE = 50.0


def _hand_panel_natural_size(
    state: GameState,
) -> tuple[float, float]:
    """Compute the hand panel's natural width and height in HEX_SIZE units.

    Returns `(width, height)` in the same coordinate space used by `draw_hand_panel`
    (centered at x = 0).
    """
    all_types = sorted(
        set(state.hand[Player.WHITE].keys()) | set(state.hand[Player.BLACK].keys())
    )
    num_types = max(len(all_types), 1)
    spacing = HEX_SIZE * 2.4
    column_width = (num_types - 1) * spacing
    column_gap = spacing * 1.5
    width = 2 * column_width + column_gap + 2 * spacing
    height = HEX_SIZE * 5.5
    return width, height


def draw_board(
    state: GameState,
    orientation: HexOrientation = HexOrientation.POINTY_TOP,
    highlights: dict[str, list[Coordinate]] | None = None,
    use_sprites: bool = True,
    show_hands: bool = True,
    title: str | None = None,
    canvas_width: float = 800,
    min_radius: int = 3,
) -> dw.Drawing:
    """Draw the Hive game board as an SVG using drawsvg.

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
        Whether to load SVG piece sprites from the bundled assets or fall back to
        character labels, by default `True`.
    show_hands : bool
        Whether to draw a hand panel below the board showing each player's remaining
        pieces and whose turn it is, by default `True`.
    title : str or None
        An optional title displayed above the board, by default `None`.
    canvas_width : float
        The width of the SVG canvas in pixels, by default 800.
    min_radius : int
        The minimum radius of the hex grid in hexes, by default 3.

    Returns
    -------
    dw.Drawing
        The drawsvg `Drawing` containing the rendered board.
    """
    if highlights is None:
        highlights = {}

    # Determine the grid extent based on the furthest occupied coordinate. Always show
    # at least min_radius to give some breathing room around the starting pieces.
    max_distance = max(get_distance((0, 0), coord) for coord in state.board)
    grid_radius = max(min_radius, max_distance + 1)
    grid_coords = get_grid_coords(grid_radius)

    # Pixel positions of every grid hex center.
    all_xy = [
        axial_to_pixel(coord[0], coord[1], orientation=orientation, size=HEX_SIZE)
        for coord in grid_coords
    ]
    all_x = [pixel[0] for pixel in all_xy]
    all_y = [pixel[1] for pixel in all_xy]

    # Compute the visual bounding box from hex centers plus the actual hex extent. For
    # pointy-top the horizontal extent is the inradius (sqrt(3)/2 * size) and the
    # vertical extent is the circumradius (size); vice-versa for flat-top.
    if orientation is HexOrientation.POINTY_TOP:
        horizontal_extent = math.sqrt(3) / 2 * HEX_SIZE
        vertical_extent = HEX_SIZE
    else:
        horizontal_extent = HEX_SIZE
        vertical_extent = math.sqrt(3) / 2 * HEX_SIZE

    grid_left = min(all_x) - horizontal_extent
    grid_right = max(all_x) + horizontal_extent
    grid_top = min(all_y) - vertical_extent
    grid_bottom = max(all_y) + vertical_extent

    grid_width = grid_right - grid_left
    grid_height = grid_bottom - grid_top
    grid_cx = (grid_left + grid_right) / 2
    grid_cy = (grid_top + grid_bottom) / 2

    # Uniform padding (fraction of the larger dimension) so the gap between the
    # outermost hexes and the canvas edge looks the same on every side.
    padding = max(grid_width, grid_height) * 0.04
    padded_width = grid_width + 2 * padding
    padded_height = grid_height + 2 * padding

    # Scale so the padded board fills canvas_width exactly.
    board_scale = canvas_width / padded_width
    board_pixel_height = padded_height * board_scale

    title_height = 40.0 if title else 0.0

    # Compute hand panel sizing with its own independent scale.
    hand_pixel_height = 0.0
    hand_scale = board_scale
    hand_natural_width = 0.0
    if show_hands:
        hand_natural_width, hand_natural_height = _hand_panel_natural_size(state)
        hand_scale = canvas_width / hand_natural_width
        hand_pixel_height = hand_natural_height * hand_scale

    # Create the canvas with enough room for the title, board, and hand panel.
    separator_gap = canvas_width * 0.015 if show_hands else 0.0
    canvas_height = title_height + board_pixel_height + separator_gap + hand_pixel_height

    drawing = dw.Drawing(canvas_width, canvas_height)
    drawing.append(dw.Rectangle(0, 0, canvas_width, canvas_height, fill="white"))

    if title:
        drawing.append(
            dw.Text(
                title,
                font_size=18,
                x=canvas_width / 2,
                y=title_height / 2,
                text_anchor="middle",
                dominant_baseline="central",
                fill="#1A1A1A",
                font_weight="bold",
            )
        )

    # Translate the center of the visual bounding box to the center of the allocated
    # board region, then scale uniformly.
    board_group = dw.Group(
        transform=(
            f"translate({canvas_width / 2}, "
            f"{title_height + board_pixel_height / 2}) "
            f"scale({board_scale}) "
            f"translate({-grid_cx}, {-grid_cy})"
        ),
    )

    # Draw the layers of the board from back to front.
    draw_grid(
        group=board_group,
        grid_coords=grid_coords,
        orientation=orientation,
        size=HEX_SIZE,
    )
    draw_pieces(
        group=board_group,
        state=state,
        orientation=orientation,
        size=HEX_SIZE,
        use_sprites=use_sprites,
    )
    draw_highlights(
        group=board_group,
        highlights=highlights,
        orientation=orientation,
        size=HEX_SIZE,
    )
    drawing.append(board_group)

    # Draw the hand panel if requested.
    if show_hands:
        separator_y = title_height + board_pixel_height + separator_gap / 2
        drawing.append(
            dw.Line(
                canvas_width * 0.06,
                separator_y,
                canvas_width * 0.94,
                separator_y,
                stroke="#DDDDDD",
                stroke_width=max(1.0, canvas_width * 0.002),
            )
        )

        hand_group = dw.Group(
            transform=(
                f"translate({canvas_width / 2}, "
                f"{title_height + board_pixel_height + separator_gap}) "
                f"scale({hand_scale})"
            ),
        )
        draw_hand_panel(
            group=hand_group,
            state=state,
            orientation=orientation,
            size=HEX_SIZE,
            use_sprites=use_sprites,
            panel_y=0,
            panel_width=hand_natural_width,
        )
        drawing.append(hand_group)

    return drawing
