import matplotlib.pyplot as plt
from matplotlib.axes import Axes

from hive_engine.plotting.constants import (
    PIECE_LABELS,
    PLAYER_COLORS,
    PLAYER_NAMES,
    PLAYER_TEXT_COLORS,
    load_sprite,
)
from hive_engine.plotting.geometry import HexOrientation, axial_to_pixel, get_hex_verts
from hive_engine.state import Coordinate, GameState, PieceType, Player


def _draw_piece_hex(
    ax: Axes,
    cx: float,
    cy: float,
    piece_type: PieceType,
    owner: Player,
    size: float,
    orientation: HexOrientation,
    use_sprites: bool,
    sprite_resolution: int,
) -> None:
    """Draw a single piece as a colored hexagon with a sprite or text label.

    Sprites are rendered using `ax.imshow` with a data-coordinate `extent` so that they
    scale naturally with the board rather than staying at a fixed pixel size.

    Parameters
    ----------
    ax : Axes
        The matplotlib axes to draw on.
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
    sprite_resolution : int
        The pixel size for sprite rendering. Only used when `use_sprites` is `True`.
    """
    # Slightly smaller hex so the grid lines remain visible.
    hex_verts = get_hex_verts(cx, cy, orientation=orientation, size=size * 0.88)
    poly = plt.Polygon(
        hex_verts,
        closed=True,
        facecolor=PLAYER_COLORS[owner],
        edgecolor="#555555",
        linewidth=1.5,
        zorder=2,
    )
    ax.add_patch(poly)

    if use_sprites:
        # Place the sprite in data coordinates so it scales with the board.
        sprite = load_sprite(piece_type=piece_type, resolution=sprite_resolution)
        half = size * 0.7
        ax.imshow(
            sprite,
            extent=(cx - half, cx + half, cy - half, cy + half),
            interpolation="antialiased",
            zorder=3,
        )
    else:
        ax.text(
            cx,
            cy,
            PIECE_LABELS.get(piece_type, "?"),
            ha="center",
            va="center",
            fontsize=13,
            fontweight="bold",
            color=PLAYER_TEXT_COLORS[owner],
            zorder=3,
        )


def _draw_stack_badge(
    ax: Axes,
    cx: float,
    cy: float,
    stack_height: int,
    size: float,
) -> None:
    """Draw a small badge indicating how many pieces are stacked at a position.

    Parameters
    ----------
    ax : Axes
        The matplotlib axes to draw on.
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

    ax.text(
        cx + size * 0.4,
        cy + size * 0.45,
        str(stack_height),
        ha="center",
        va="center",
        fontsize=8,
        fontweight="bold",
        color="#CC4444",
        bbox=dict(
            boxstyle="round,pad=0.15",
            facecolor="white",
            edgecolor="#CC4444",
            linewidth=0.8,
        ),
        zorder=4,
    )


def draw_grid(
    ax: Axes, grid_coords: list[Coordinate], orientation: HexOrientation, size: float
) -> None:
    """Draw the background hex grid.

    Parameters
    ----------
    ax : Axes
        The matplotlib axes to draw on.
    grid_coords : list[Coordinate]
        All axial coordinates in the grid.
    orientation : HexOrientation
        The hex orientation.
    size : float
        The radius of each hexagon.
    """
    for coord in grid_coords:
        cx, cy = axial_to_pixel(coord[0], coord[1], orientation=orientation, size=size)
        hex_verts = get_hex_verts(cx, cy, orientation=orientation, size=size)
        poly = plt.Polygon(
            hex_verts,
            closed=True,
            facecolor="#EAEAEA",
            edgecolor="#BBBBBB",
            linewidth=0.8,
            zorder=0,
        )
        ax.add_patch(poly)


def draw_pieces(
    ax: Axes,
    state: GameState,
    orientation: HexOrientation,
    size: float,
    use_sprites: bool,
    sprite_resolution: int,
) -> None:
    """Draw all pieces currently on the board.

    Only the top piece of each stack is rendered. Stacks taller than one piece receive a
    small red badge indicating the stack height.

    Parameters
    ----------
    ax : Axes
        The matplotlib axes to draw on.
    state : GameState
        The current game state.
    orientation : HexOrientation
        The hex orientation.
    size : float
        The radius of each hexagon.
    use_sprites : bool
        If `True`, render pieces as sprite images.
    sprite_resolution : int
        The pixel size for sprite rendering.
    """
    for coord in state.get_occupied_coords():
        cx, cy = axial_to_pixel(coord[0], coord[1], orientation=orientation, size=size)
        top_piece = state.get_top_piece(coord)

        _draw_piece_hex(
            ax,
            cx,
            cy,
            piece_type=top_piece.type,
            owner=top_piece.owner,
            orientation=orientation,
            size=size,
            use_sprites=use_sprites,
            sprite_resolution=sprite_resolution,
        )

        _draw_stack_badge(
            ax=ax, cx=cx, cy=cy, stack_height=state.get_stack_height(coord), size=size
        )


def draw_highlights(
    ax: Axes,
    highlights: dict[str, list[Coordinate]],
    orientation: HexOrientation,
    size: float,
) -> None:
    """Draw colored highlight rings around specified coordinates.

    Parameters
    ----------
    ax : Axes
        The matplotlib axes to draw on.
    highlights : dict[str, list[Coordinate]]
        A mapping from color strings to lists of coordinates that should
        receive a colored ring.
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
            ring_verts = get_hex_verts(cx, cy, orientation=orientation, size=size * 0.9)
            ring_poly = plt.Polygon(
                ring_verts,
                closed=True,
                facecolor="none",
                edgecolor=color,
                linewidth=3.0,
                zorder=5,
            )
            ax.add_patch(ring_poly)


def fit_axes_to_grid(
    ax: Axes,
    grid_coords: list[Coordinate],
    orientation: HexOrientation,
    size: float,
) -> None:
    """Set the axes limits to tightly frame the hex grid with a small margin.

    Parameters
    ----------
    ax : Axes
        The matplotlib axes to adjust.
    grid_coords : list[Coordinate]
        All axial coordinates in the grid.
    orientation : HexOrientation
        The hex orientation.
    size : float
        The radius of each hexagon.
    """
    all_x, all_y = zip(
        *[
            axial_to_pixel(coord[0], coord[1], orientation=orientation, size=size)
            for coord in grid_coords
        ],
        strict=True,
    )
    margin = size * 1.5
    ax.set_xlim(min(all_x) - margin, max(all_x) + margin)
    ax.set_ylim(min(all_y) - margin, max(all_y) + margin)


def draw_hand_panel(
    ax: Axes,
    state: GameState,
    orientation: HexOrientation,
    use_sprites: bool,
    sprite_resolution: int,
) -> None:
    """Draw the hand panel showing remaining pieces for each player.

    The panel is laid out as two side-by-side columns (White left, Black
    right). Each column has a header with the player name and a turn
    indicator arrow, followed by a horizontal row of piece icons with
    remaining counts displayed below each.

    Parameters
    ----------
    ax : Axes
        The matplotlib axes to draw on.
    state : GameState
        The current game state, used to read hands and the active player.
    orientation : HexOrientation
        The hex orientation used for piece icons.
    use_sprites : bool
        If `True`, render pieces as sprite images.
    sprite_resolution : int
        The pixel size for sprite rendering.
    """
    ax.set_aspect("equal")
    ax.axis("off")

    # Collect piece types present in either hand, sorted by enum value.
    all_types: list[PieceType] = sorted(
        set(state.hand[Player.WHITE].keys()) | set(state.hand[Player.BLACK].keys())
    )
    if not all_types:
        return

    # Layout constants.
    size = 0.35
    icon_spacing = 1.0
    column_gap = 1.8
    count_offset_y = -0.55
    header_offset_y = 0.7
    icon_y = 0.0

    column_width = (len(all_types) - 1) * icon_spacing
    total_width = column_width * 2 + column_gap
    left_center = -total_width / 4 - column_gap / 4
    right_center = total_width / 4 + column_gap / 4

    column_centers = {Player.WHITE: left_center, Player.BLACK: right_center}

    for player in Player:
        col_cx = column_centers[player]
        is_active = player == state.current_player
        header_y = icon_y + header_offset_y

        # Turn indicator arrow for the active player.
        if is_active:
            ax.plot(
                col_cx - column_width / 2 - 0.55,
                header_y,
                marker=">",
                markersize=10,
                color="#E8792B",
                zorder=3,
                clip_on=False,
            )

        # Player name header.
        ax.text(
            col_cx,
            header_y,
            PLAYER_NAMES[player],
            ha="center",
            va="center",
            fontsize=11,
            fontweight="bold" if is_active else "normal",
            color="#1A1A1A",
            zorder=3,
        )

        # Thin underline below the header.
        underline_y = header_y - 0.25
        ax.plot(
            [col_cx - column_width / 2 - 0.3, col_cx + column_width / 2 + 0.3],
            [underline_y, underline_y],
            color="#CCCCCC",
            linewidth=1.0,
            zorder=1,
            clip_on=False,
        )

        # Piece icons arranged in a horizontal row.
        icon_x_start = col_cx - column_width / 2

        for type_idx, piece_type in enumerate(all_types):
            icon_x = icon_x_start + type_idx * icon_spacing
            count = state.hand[player].get(piece_type, 0)

            _draw_piece_hex(
                ax=ax,
                cx=icon_x,
                cy=icon_y,
                piece_type=piece_type,
                owner=player,
                size=size,
                orientation=orientation,
                use_sprites=use_sprites,
                sprite_resolution=sprite_resolution,
            )

            # Semi-transparent overlay to dim exhausted pieces.
            if count == 0:
                dim_verts = get_hex_verts(
                    icon_x, icon_y, orientation=orientation, size=size * 0.88
                )
                dim_poly = plt.Polygon(
                    dim_verts,
                    closed=True,
                    facecolor="white",
                    alpha=0.65,
                    edgecolor="none",
                    zorder=3.5,
                )
                ax.add_patch(dim_poly)

            # Remaining count below the icon.
            ax.text(
                icon_x,
                icon_y + count_offset_y,
                f"x{count}",
                ha="center",
                va="center",
                fontsize=9,
                fontweight="bold",
                color="#999999" if count == 0 else "#1A1A1A",
                zorder=4,
            )

    # Vertical divider between the two columns.
    div_x = (left_center + right_center) / 2
    ax.plot(
        [div_x, div_x],
        [icon_y + header_offset_y + 0.3, icon_y + count_offset_y - 0.3],
        color="#DDDDDD",
        linewidth=1.0,
        zorder=1,
        clip_on=False,
    )

    # Fit view to the panel contents.
    margin_x, margin_y = 1.5, 0.6
    ax.set_xlim(
        left_center - column_width / 2 - margin_x,
        right_center + column_width / 2 + margin_x,
    )
    ax.set_ylim(
        icon_y + count_offset_y - margin_y,
        icon_y + header_offset_y + margin_y,
    )
