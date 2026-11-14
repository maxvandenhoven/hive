"""The params models that agent kinds declare.

Each agent class names its params model in `Agent.Params`. The model validates the
`params` of an `AgentSpec`, and its fields, with their constraints, defaults and
descriptions, are the params schema the API serves for the parameter forms.
"""

from pydantic import BaseModel, ConfigDict, Field


class AgentParams(BaseModel):
    """Base class of the params models, and the params of kinds that take none.

    The models are frozen and reject unknown params. Each field states its description
    with `Field(description=...)`, which the params schema shows next to the field.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


class SearchParams(AgentParams):
    """The params of the search agents: the depth limit, evaluation weights and options.

    Each evaluation weight scales one term of the evaluation, scored from the perspective
    of the evaluated player, and a weight of zero skips its term. The remaining fields
    configure the tree search of the Rust core (`Searcher`), which validates them again.
    """

    depth: int | None = Field(
        default=None,
        ge=1,
        description="The maximum search depth in plies, or `None` to search until "
        "stopped.",
    )
    queen_safety: float = Field(
        default=1.0,
        description="The weight of the occupied neighbours of the opponent's queen minus "
        "those of the player's own queen.",
    )
    mobility: float = Field(
        default=0.0,
        description="The weight of the player's legal moves minus the opponent's. This "
        "term generates moves at every leaf, which makes it slow.",
    )
    positioning: float = Field(
        default=0.0,
        description="The weight of the player's pieces next to the opponent's queen "
        "minus the opponent's pieces next to the player's queen.",
    )
    material_on_board: float = Field(
        default=0.0,
        description="The weight of the value of the player's pieces on the board minus "
        "the opponent's.",
    )
    material_in_hand: float = Field(
        default=0.0,
        description="The weight of the value of the player's pieces in hand minus the "
        "opponent's.",
    )
    queen_danger: float = Field(
        default=0.0,
        allow_inf_nan=False,
        description="Nonlinear queen crowding: squared occupied-neighbour counts.",
    )
    queen_escape: float = Field(
        default=0.0,
        allow_inf_nan=False,
        description="Legal queen escapes, excluding covered or pinned queens.",
    )
    pinned_material: float = Field(
        default=0.0,
        allow_inf_nan=False,
        description="Opponent minus own covered or articulation-pinned material.",
    )
    free_ants: float = Field(
        default=0.0,
        allow_inf_nan=False,
        description="Own minus opponent uncovered, unpinned ants after queen placement.",
    )
    beetle_control: float = Field(
        default=0.0,
        allow_inf_nan=False,
        description="Elevated beetle balance, doubled over an enemy queen.",
    )
    tempo: float = Field(
        default=0.0, allow_inf_nan=False, description="A bonus for the player to move."
    )
    mobile_queen: float = Field(
        default=0.0,
        allow_inf_nan=False,
        description="Own minus opponent queens that can take a first step.",
    )
    mobile_beetle: float = Field(
        default=0.0,
        allow_inf_nan=False,
        description="Own minus opponent beetles that can move.",
    )
    mobile_grasshopper: float = Field(
        default=0.0,
        allow_inf_nan=False,
        description="Own minus opponent grasshoppers that can move.",
    )
    mobile_spider: float = Field(
        default=0.0,
        allow_inf_nan=False,
        description="Own minus opponent spiders that can take a first step.",
    )
    mobile_ant: float = Field(
        default=0.0,
        allow_inf_nan=False,
        description="Own minus opponent ants that can take a first step.",
    )
    placement_cells: float = Field(
        default=0.0,
        allow_inf_nan=False,
        description="Own minus opponent free cells to place a piece on.",
    )
    queen_locked_neighbors: float = Field(
        default=0.0,
        allow_inf_nan=False,
        description="Queen neighbours its owner cannot move away.",
    )
    alpha_beta: bool = Field(
        default=True,
        description="Whether to prune the search with alpha-beta, searching the best "
        "line of the previous depth first. It finds the same scores in far fewer nodes, "
        "but may choose another of several equally scored moves.",
    )
    table_megabytes: int = Field(
        default=32,
        ge=0,
        description="The size of the transposition table in MB, zero for none. `negamax` "
        "with alpha-beta uses it, and orders moves by killer moves and a history table "
        "too; it is kept between decisions of a match.",
    )
    aspiration_window: float = Field(
        default=0.0,
        ge=0,
        allow_inf_nan=False,
        description="Initial score half-window, zero to disable aspiration.",
    )
    threads: int = Field(
        default=1,
        ge=1,
        le=256,
        description="Total negamax search threads sharing one table, at least one.",
    )
    principal_variation_search: bool = Field(
        default=False, description="Scout later moves before a full-window search."
    )
    table_deeper_hits: bool = Field(
        default=False, description="Reuse table entries searched deeper than needed."
    )
    late_move_reductions: int = Field(
        default=0,
        ge=0,
        le=255,
        description="Moves searched at full depth before later ones are scouted a ply "
        "shallower, zero for none. Needs principal variation search.",
    )
    null_move_reduction: int = Field(
        default=0,
        ge=0,
        le=8,
        description="Extra depth reduction of a null move at scout nodes, zero for none.",
    )
    queen_attack_ordering: bool = Field(
        default=False, description="Order moves next to the enemy queen after killers."
    )
    queen_threat_extension: bool = Field(
        default=False, description="Search a ply deeper once a queen has five neighbours."
    )
    repetition_draws: bool = Field(
        default=False, description="Score a repeat of an earlier position as a draw."
    )
    forced_move_extension: bool = Field(
        default=False, description="Search a forced move without using up depth."
    )
