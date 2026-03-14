import drawsvg as dw

from hive_engine.plotting.svg.constants import (
    PIECE_LABELS,
    PLAYER_COLORS,
    PLAYER_NAMES,
    PLAYER_TEXT_COLORS,
    load_svg_sprite,
)
from hive_engine.plotting.svg.geometry import (
    HexOrientation,
    axial_to_pixel,
    get_hex_points,
)
from hive_engine.state import Coordinate, GameState, PieceType, Player


def _draw_piece_hex(
    group: dw.Group,
    cx: float,
    cy: float,
    piece_type: PieceType,
    owner: Player,
    size: float,
    orientation: HexOrientation,
    use_sprites: bool,
    stroke_width: float | None = None,
) -> None:
    """Draw a single piece as a colored hexagon with a sprite or text label.

    Sprites are rendered using `dw.Image` with data-coordinate positioning so that
    they scale naturally with the board rather than staying at a fixed pixel size.

    Parameters
    ----------
    group : dw.Group
        The drawsvg group to append the piece elements to.
    cx : float
        The x-coordinate of the hex center.
    cy : float
        The y-coordinate of the hex center.
    piece_type : PieceType
        The type of piece to draw.
    owner : Player
        The player that owns the piece.
    size : float
        The radius of the surrounding grid hexagon.
    orientation : HexOrientation
        The hex orientation (pointy-top or flat-top).
    use_sprites : bool
        Whether to render the piece as a sprite image or a single-character text label.
    stroke_width : float or None
        Override for the hex border stroke width. Defaults to `size * 0.03` when
        `None`.
    """
    # Slightly smaller hex so the grid lines remain visible.
    inner_size = size * 0.88
    resolved_stroke_width = stroke_width if stroke_width is not None else size * 0.03
    points = get_hex_points(cx, cy, orientation=orientation, size=inner_size)
    group.append(
        dw.Lines(
            *points,
            close=True,
            fill=PLAYER_COLORS[owner],
            stroke="#555555",
            stroke_width=resolved_stroke_width,
        )
    )

    if use_sprites:
        # Place the sprite in data coordinates so it scales with the board.
        sprite_path = load_svg_sprite(piece_type)
        half = size * 0.7
        group.append(
            dw.Image(
                cx - half,
                cy - half,
                half * 2,
                half * 2,
                sprite_path,
            )
        )
    else:
        group.append(
            dw.Text(
                PIECE_LABELS.get(piece_type, "?"),
                font_size=size * 0.55,
                x=cx,
                y=cy,
                text_anchor="middle",
                dominant_baseline="central",
                fill=PLAYER_TEXT_COLORS[owner],
                font_weight="bold",
            )
        )


def _draw_stack_badge(
    group: dw.Group,
    cx: float,
    cy: float,
    stack_height: int,
    size: float,
) -> None:
    """Draw a small badge indicating how many pieces are stacked at a position.

    Parameters
    ----------
    group : dw.Group
        The drawsvg group to append the badge elements to.
    cx : float
        The x-coordinate of the hex center.
    cy : float
        The y-coordinate of the hex center.
    stack_height : int
        The number of pieces in the stack (badge is only drawn if > 1).
    size : float
        The radius of the surrounding grid hexagon.
    """
    if stack_height <= 1:
        return

    badge_x = cx + size * 0.4
    badge_y = cy - size * 0.45
    badge_radius = size * 0.18
    group.append(
        dw.Circle(
            badge_x,
            badge_y,
            badge_radius,
            fill="white",
            stroke="#CC4444",
            stroke_width=size * 0.02,
        )
    )
    group.append(
        dw.Text(
            str(stack_height),
            font_size=size * 0.22,
            x=badge_x,
            y=badge_y,
            text_anchor="middle",
            dominant_baseline="central",
            fill="#CC4444",
            font_weight="bold",
        )
    )


def draw_grid(
    group: dw.Group,
    grid_coords: list[Coordinate],
    orientation: HexOrientation,
    size: float,
) -> None:
    """Draw the background hex grid.

    Parameters
    ----------
    group : dw.Group
        The drawsvg group to append grid hexagons to.
    grid_coords : list[Coordinate]
        All axial coordinates in the grid.
    orientation : HexOrientation
        The hex orientation.
    size : float
        The radius of each hexagon.
    """
    for coord in grid_coords:
        cx, cy = axial_to_pixel(coord[0], coord[1], orientation=orientation, size=size)
        points = get_hex_points(cx, cy, orientation=orientation, size=size)
        group.append(
            dw.Lines(
                *points,
                close=True,
                fill="#EAEAEA",
                stroke="#BBBBBB",
                stroke_width=size * 0.016,
            )
        )


def draw_pieces(
    group: dw.Group,
    state: GameState,
    orientation: HexOrientation,
    size: float,
    use_sprites: bool,
) -> None:
    """Draw all pieces currently on the board.

    Only the top piece of each stack is rendered. Stacks taller than one piece receive a
    small red badge indicating the stack height.

    Parameters
    ----------
    group : dw.Group
        The drawsvg group to append piece elements to.
    state : GameState
        The current game state.
    orientation : HexOrientation
        The hex orientation.
    size : float
        The radius of each hexagon.
    use_sprites : bool
        If `True`, render pieces as SVG sprite images.
    """
    for coord in state.get_occupied_coords():
        cx, cy = axial_to_pixel(coord[0], coord[1], orientation=orientation, size=size)
        top_piece = state.get_top_piece(coord)

        _draw_piece_hex(
            group=group,
            cx=cx,
            cy=cy,
            piece_type=top_piece.type,
            owner=top_piece.owner,
            size=size,
            orientation=orientation,
            use_sprites=use_sprites,
        )

        _draw_stack_badge(
            group=group,
            cx=cx,
            cy=cy,
            stack_height=state.get_stack_height(coord),
            size=size,
        )


def draw_highlights(
    group: dw.Group,
    highlights: dict[str, list[Coordinate]],
    orientation: HexOrientation,
    size: float,
) -> None:
    """Draw colored highlight rings around specified coordinates.

    Parameters
    ----------
    group : dw.Group
        The drawsvg group to append highlight elements to.
    highlights : dict[str, list[Coordinate]]
        A mapping from color strings to lists of coordinates that should receive a
        colored ring.
    orientation : HexOrientation
        The hex orientation.
    size : float
        The radius of each hexagon.
    """
    for color, coords in highlights.items():
        for coord in coords:
            cx, cy = axial_to_pixel(
                coord[0], coord[1], orientation=orientation, size=size
            )
            ring_points = get_hex_points(cx, cy, orientation=orientation, size=size * 0.9)
            group.append(
                dw.Lines(
                    *ring_points,
                    close=True,
                    fill="none",
                    stroke=color,
                    stroke_width=size * 0.06,
                )
            )


def draw_hand_panel(
    group: dw.Group,
    state: GameState,
    orientation: HexOrientation,
    size: float,
    use_sprites: bool,
    panel_y: float,
    panel_width: float,
) -> float:
    """Draw the hand panel showing remaining pieces for each player.

    The panel is laid out as two side-by-side columns (White left, Black right). Each
    column has a header with the player name and a turn indicator arrow, followed by a
    horizontal row of piece icons with remaining counts displayed below each.

    Parameters
    ----------
    group : dw.Group
        The drawsvg group to append hand panel elements to.
    state : GameState
        The current game state, used to read hands and the active player.
    orientation : HexOrientation
        The hex orientation used for piece icons.
    size : float
        The radius used for piece icons in the hand panel.
    use_sprites : bool
        If `True`, render pieces as SVG sprite images.
    panel_y : float
        The top y-coordinate where the hand panel begins.
    panel_width : float
        The total width available for the hand panel.

    Returns
    -------
    float
        The total height consumed by the hand panel.
    """
    # Collect piece types present in either hand, sorted by enum value.
    all_types: list[PieceType] = sorted(
        set(state.hand[Player.WHITE].keys()) | set(state.hand[Player.BLACK].keys())
    )
    if not all_types:
        return 0.0

    # Layout constants.
    icon_spacing = size * 2.4
    header_font_size = size * 0.8
    count_font_size = size * 0.7
    header_gap = size * 0.8
    count_gap = size * 0.8
    icon_size = size * 0.9

    column_width = (len(all_types) - 1) * icon_spacing
    column_gap = icon_spacing * 1.5

    center_x = 0.0
    left_center = center_x - column_gap / 2 - column_width / 2
    right_center = center_x + column_gap / 2 + column_width / 2

    header_y = panel_y + header_gap
    icon_y = header_y + header_gap + icon_size
    count_y = icon_y + count_gap + icon_size

    column_centers = {Player.WHITE: left_center, Player.BLACK: right_center}

    for player in Player:
        col_cx = column_centers[player]
        is_active = player == state.current_player

        # Turn indicator arrow for the active player.
        if is_active:
            arrow_x = col_cx - column_width / 2 - icon_spacing * 0.7
            group.append(
                dw.Text(
                    "\u25b6",
                    font_size=header_font_size * 0.8,
                    x=arrow_x,
                    y=header_y,
                    text_anchor="middle",
                    dominant_baseline="central",
                    fill="#E8792B",
                )
            )

        # Player name header.
        font_weight = "bold" if is_active else "normal"
        group.append(
            dw.Text(
                PLAYER_NAMES[player],
                font_size=header_font_size,
                x=col_cx,
                y=header_y,
                text_anchor="middle",
                dominant_baseline="central",
                fill="#1A1A1A",
                font_weight=font_weight,
            )
        )

        # Piece icons arranged in a horizontal row.
        icon_x_start = col_cx - column_width / 2

        for type_idx, piece_type in enumerate(all_types):
            icon_x = icon_x_start + type_idx * icon_spacing
            count = state.hand[player].get(piece_type, 0)

            _draw_piece_hex(
                group=group,
                cx=icon_x,
                cy=icon_y,
                piece_type=piece_type,
                owner=player,
                size=icon_size,
                orientation=orientation,
                use_sprites=use_sprites,
                stroke_width=icon_size * 0.06,
            )

            # Semi-transparent overlay to dim exhausted pieces.
            if count == 0:
                dim_points = get_hex_points(
                    icon_x,
                    icon_y,
                    orientation=orientation,
                    size=icon_size * 0.88,
                )
                group.append(
                    dw.Lines(
                        *dim_points,
                        close=True,
                        fill="white",
                        fill_opacity=0.65,
                        stroke="none",
                    )
                )

            # Remaining count below the icon.
            count_color = "#999999" if count == 0 else "#1A1A1A"
            group.append(
                dw.Text(
                    f"x{count}",
                    font_size=count_font_size,
                    x=icon_x,
                    y=count_y,
                    text_anchor="middle",
                    dominant_baseline="central",
                    fill=count_color,
                    font_weight="bold",
                )
            )

    # Vertical divider between the two columns.
    divider_x = (left_center + right_center) / 2
    group.append(
        dw.Line(
            divider_x,
            header_y - header_gap * 0.3,
            divider_x,
            count_y + count_gap,
            stroke="#DDDDDD",
            stroke_width=size * 0.02,
        )
    )

    return count_y + count_gap - panel_y
