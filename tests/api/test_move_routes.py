import uuid
from typing import Any

import anyio
import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from hive.api.db.models import GameRow, MoveRow, PhotoRow
from hive.api.games import GameService
from hive.engine.codec import json_adapter
from hive.engine.record import GameRecord
from hive.engine.rules import Rules
from hive.engine.state import GameBoard, Player

AGENT: dict[str, Any] = {
    "type": "agent",
    "spec": {"kind": "negamax", "params": {"depth": 2}},
}
HUMAN = {"type": "human"}

WHITE_WIN: list[dict[str, Any]] = [
    {"piece": "spider", "from": None, "to": [0, 0]},
    {"piece": "queen", "from": None, "to": [-1, 0]},
    {"piece": "grasshopper", "from": None, "to": [1, -1]},
    {"piece": "grasshopper", "from": None, "to": [-1, -1]},
    {"piece": "queen", "from": None, "to": [1, -2]},
    {"piece": "grasshopper", "from": None, "to": [-2, 0]},
    {"piece": "queen", "from": [1, -2], "to": [0, -1]},
    {"piece": "spider", "from": None, "to": [-2, 1]},
    {"piece": "grasshopper", "from": [1, -1], "to": [-1, 1]},
]
"""A game in which white surrounds the black queen with its ninth move."""

PASS_SETUP: dict[str, Any] = {
    "board": [
        {
            "coord": [-1, 0],
            "stack": [
                {"piece": "ant", "owner": "white"},
                {"piece": "beetle", "owner": "black"},
            ],
        },
        {"coord": [0, 0], "stack": [{"piece": "queen", "owner": "white"}]},
        {"coord": [1, 0], "stack": [{"piece": "queen", "owner": "black"}]},
    ],
    "current_player": "white",
    "current_ply": None,
}
"""A position in which white has no legal move and must pass."""

pytestmark = pytest.mark.anyio


async def create_game(client: httpx2.AsyncClient, **fields: Any) -> str:
    """Create a human vs negamax game with some fields set and return its ID."""
    response = await client.post(
        "/api/games", json={"name": "Game", "white": HUMAN, "black": AGENT, **fields}
    )
    assert response.status_code == 201, response.text

    return response.json()["id"]


async def play(
    client: httpx2.AsyncClient,
    game_id: str,
    move: object,
    expected_ply: int,
    **fields: Any,
) -> httpx2.Response:
    """Post a move that may be entered for either side."""
    body = {"move": move, "expected_ply": expected_ply, "allow_agent_side": True}

    return await client.post(f"/api/games/{game_id}/moves", json={**body, **fields})


async def play_all(
    client: httpx2.AsyncClient, game_id: str, moves: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Play moves in order, checking that each is accepted, and return the positions."""
    positions = []

    for ply, move in enumerate(moves):
        response = await play(client=client, game_id=game_id, move=move, expected_ply=ply)
        assert response.status_code == 201, response.text
        positions.append(response.json())

    return positions


def board_json(board: GameBoard) -> object:
    """Get the JSON form of a board."""
    return json_adapter(GameBoard).dump_python(board, mode="json")


def error_code(response: httpx2.Response) -> str:
    """Get the error code of an error response."""
    return response.json()["code"]


class TestPlayGame:
    async def test_plays_to_a_win(self, client: httpx2.AsyncClient) -> None:
        game_id = await create_game(client=client)
        positions = await play_all(client=client, game_id=game_id, moves=WHITE_WIN)
        game = (await client.get(f"/api/games/{game_id}")).json()
        final = positions[-1]

        assert [position["ply"] for position in positions] == list(range(1, 10))
        assert [position["result"] for position in positions[:-1]] == [None] * 8
        assert final["result"] == "white"
        assert final["last_move"]["move"] == WHITE_WIN[-1]
        assert final["movable_pieces"] == []
        assert final["placeable_coords"] == []
        assert final["must_pass"] is False
        assert (game["status"], game["result"], game["ply_count"]) == (
            "finished",
            "white",
            9,
        )
        assert [move["move"] for move in game["moves"]] == WHITE_WIN
        assert {move["source"] for move in game["moves"]} == {"manual"}

    async def test_plays_to_a_draw(self, client: httpx2.AsyncClient) -> None:
        rules = Rules(max_turns=2)
        game_id = await create_game(client=client, rules=rules.to_json())
        record = GameRecord(rules=rules)
        position = (await client.get(f"/api/games/{game_id}/state")).json()

        while position["result"] is None:
            move = rules.legal_moves(record.replay())[0]
            response = await play(
                client=client,
                game_id=game_id,
                move=None if move is None else move.to_json(),
                expected_ply=len(record.moves),
            )
            assert response.status_code == 201, response.text
            record.moves.append(move)
            position = response.json()

        game = (await client.get(f"/api/games/{game_id}")).json()

        assert position["result"] == "draw"
        assert (game["status"], game["result"]) == ("finished", "draw")

    async def test_replays_every_ply(self, client: httpx2.AsyncClient) -> None:
        game_id = await create_game(client=client)
        await play_all(client=client, game_id=game_id, moves=WHITE_WIN)
        record = GameRecord.from_json({"rules": Rules().to_json(), "moves": WHITE_WIN})

        for ply, state in enumerate(record.states()):
            response = await client.get(
                f"/api/games/{game_id}/state", params={"ply": ply}
            )
            position = response.json()
            last_move = position["last_move"]

            assert response.status_code == 200
            assert position["ply"] == ply
            assert position["ply_count"] == 9
            assert position["board"] == board_json(state.board)
            assert position["current_player"] == state.current_player.name.lower()
            assert position["hands"]["white"] == {
                piece_type.name.lower(): count
                for piece_type, count in state.hand[Player.WHITE].items()
            }
            assert (last_move and last_move["move"]) == (
                WHITE_WIN[ply - 1] if ply else None
            )
            assert position["result"] == ("white" if ply == 9 else None)

    async def test_rejects_moves_after_the_end(self, client: httpx2.AsyncClient) -> None:
        game_id = await create_game(client=client)
        await play_all(client=client, game_id=game_id, moves=WHITE_WIN)
        move = {"piece": "ant", "from": None, "to": [-3, 1]}
        response = await play(client=client, game_id=game_id, move=move, expected_ply=9)

        assert response.status_code == 409
        assert error_code(response) == "game_not_active"


class TestReadState:
    async def test_initial_position(self, client: httpx2.AsyncClient) -> None:
        game_id = await create_game(client=client)
        position = (await client.get(f"/api/games/{game_id}/state")).json()

        assert position == {
            "ply": 0,
            "ply_count": 0,
            "board": [],
            "hands": {
                player: {"queen": 1, "beetle": 2, "grasshopper": 3, "spider": 2, "ant": 3}
                for player in ("white", "black")
            },
            "current_player": "white",
            "result": None,
            "last_move": None,
            "movable_pieces": [],
            "placeable_coords": [[0, 0]],
            "placeable_piece_types": ["queen", "beetle", "grasshopper", "spider", "ant"],
            "must_pass": False,
            "pending_move": False,
        }

    async def test_lists_movable_pieces(self, client: httpx2.AsyncClient) -> None:
        game_id = await create_game(client=client)
        await play_all(client=client, game_id=game_id, moves=WHITE_WIN[:6])
        position = (await client.get(f"/api/games/{game_id}/state")).json()

        # The white spider and grasshopper hold the hive together.
        assert position["movable_pieces"] == [{"coord": [1, -2], "piece": "queen"}]
        assert position["placeable_piece_types"] == [
            "beetle",
            "grasshopper",
            "spider",
            "ant",
        ]
        assert [2, -3] in position["placeable_coords"]

    async def test_rejects_ply_past_the_end(self, client: httpx2.AsyncClient) -> None:
        game_id = await create_game(client=client)
        response = await client.get(f"/api/games/{game_id}/state", params={"ply": 1})

        assert response.status_code == 422
        assert response.json() == {
            "code": "ply_out_of_range",
            "detail": "Ply `1` is past the last move; the game has 0.",
        }

    async def test_rejects_negative_ply(self, client: httpx2.AsyncClient) -> None:
        game_id = await create_game(client=client)
        response = await client.get(f"/api/games/{game_id}/state", params={"ply": -1})

        assert response.status_code == 422

    async def test_missing(self, client: httpx2.AsyncClient) -> None:
        response = await client.get(f"/api/games/{uuid.uuid4()}/state")

        assert response.status_code == 404
        assert error_code(response) == "game_not_found"


class TestReadTargets:
    async def test_lists_targets(self, client: httpx2.AsyncClient) -> None:
        game_id = await create_game(client=client)
        await play_all(client=client, game_id=game_id, moves=WHITE_WIN[:6])
        state = GameRecord.from_json(
            {"rules": Rules().to_json(), "moves": WHITE_WIN[:6]}
        ).replay()
        response = await client.get(
            f"/api/games/{game_id}/targets", params={"q": 1, "r": -2}
        )
        expected = sorted(Rules().target_coords(state=state, coord=(1, -2)))

        assert response.status_code == 200
        assert response.json() == {
            "coord": [1, -2],
            "piece": "queen",
            "targets": [list(coord) for coord in expected],
        }
        assert [0, -1] in response.json()["targets"]

    async def test_empty_coordinate(self, client: httpx2.AsyncClient) -> None:
        game_id = await create_game(client=client)
        response = await client.get(
            f"/api/games/{game_id}/targets", params={"q": 0, "r": 0}
        )

        assert response.status_code == 404
        assert error_code(response) == "coordinate_empty"

    @pytest.mark.parametrize(
        ("coord", "reason"),
        [
            ((-1, 0), "the piece belongs to `BLACK`"),
            ((0, 0), "moving the piece would split the hive"),
        ],
    )
    async def test_piece_not_movable(
        self, client: httpx2.AsyncClient, coord: tuple[int, int], reason: str
    ) -> None:
        game_id = await create_game(client=client)
        await play_all(client=client, game_id=game_id, moves=WHITE_WIN[:6])
        response = await client.get(
            f"/api/games/{game_id}/targets", params={"q": coord[0], "r": coord[1]}
        )

        assert response.status_code == 422
        assert response.json() == {
            "code": "piece_not_movable",
            "detail": f"The piece at `{coord}` cannot move: {reason}.",
        }

    async def test_finished_game(self, client: httpx2.AsyncClient) -> None:
        game_id = await create_game(client=client)
        await play_all(client=client, game_id=game_id, moves=WHITE_WIN)
        response = await client.get(
            f"/api/games/{game_id}/targets", params={"q": 0, "r": 0}
        )

        assert response.status_code == 422
        assert "the game is over" in response.json()["detail"]

    async def test_requires_coordinates(self, client: httpx2.AsyncClient) -> None:
        game_id = await create_game(client=client)
        response = await client.get(f"/api/games/{game_id}/targets", params={"q": 0})

        assert response.status_code == 422


class TestPlayMove:
    async def test_rejects_stale_ply(self, client: httpx2.AsyncClient) -> None:
        game_id = await create_game(client=client)
        first = await play(
            client=client, game_id=game_id, move=WHITE_WIN[0], expected_ply=0
        )
        second = await play(
            client=client, game_id=game_id, move=WHITE_WIN[1], expected_ply=0
        )
        game = (await client.get(f"/api/games/{game_id}")).json()

        assert first.status_code == 201
        assert second.status_code == 409
        assert second.json() == {
            "code": "ply_conflict",
            "detail": "Expected the game at ply `0`, but it is at ply `1`.",
        }
        assert game["ply_count"] == 1

    async def test_rejects_illegal_move(self, client: httpx2.AsyncClient) -> None:
        game_id = await create_game(client=client)
        move = {"piece": "ant", "from": None, "to": [1, 0]}
        response = await play(client=client, game_id=game_id, move=move, expected_ply=0)
        game = (await client.get(f"/api/games/{game_id}")).json()

        assert response.status_code == 422
        assert response.json() == {
            "code": "move_not_legal",
            "detail": "Move `place ant at (1, 0)` is not legal for player `WHITE` at ply "
            "`0`: the first piece must be placed at `(0, 0)`.",
        }
        assert game["ply_count"] == 0

    async def test_rejects_pass_with_legal_moves(
        self, client: httpx2.AsyncClient
    ) -> None:
        game_id = await create_game(client=client)
        response = await play(client=client, game_id=game_id, move=None, expected_ply=0)

        assert response.status_code == 422
        assert "passing is only allowed" in response.json()["detail"]

    async def test_plays_forced_pass(self, client: httpx2.AsyncClient) -> None:
        game_id = await create_game(client=client, setup=PASS_SETUP)
        before = (await client.get(f"/api/games/{game_id}/state")).json()
        response = await play(client=client, game_id=game_id, move=None, expected_ply=0)
        after = response.json()

        assert before["must_pass"] is True
        assert before["movable_pieces"] == []
        assert before["placeable_coords"] == []
        assert response.status_code == 201
        assert after["current_player"] == "black"
        assert after["last_move"]["move"] is None
        assert after["board"] == before["board"]

    @pytest.mark.parametrize(
        "body",
        [
            {"move": None},
            {"expected_ply": 0},
            {"move": None, "expected_ply": -1},
            {"move": None, "expected_ply": 0, "source": "agent"},
            {"move": None, "expected_ply": 0, "source": "photo"},
            {"move": None, "expected_ply": 0, "photo_id": str(uuid.uuid4())},
            {"move": {"piece": "ant", "to": [0, 0]}, "expected_ply": 0},
        ],
    )
    async def test_rejects_invalid_body(
        self, client: httpx2.AsyncClient, body: dict[str, Any]
    ) -> None:
        game_id = await create_game(client=client)
        response = await client.post(f"/api/games/{game_id}/moves", json=body)

        assert response.status_code == 422
        assert isinstance(response.json()["detail"], list)

    async def test_rejects_agent_side(self, client: httpx2.AsyncClient) -> None:
        game_id = await create_game(client=client)
        url = f"/api/games/{game_id}/moves"
        white = await client.post(url, json={"move": WHITE_WIN[0], "expected_ply": 0})
        black = await client.post(url, json={"move": WHITE_WIN[1], "expected_ply": 1})
        allowed = await play(
            client=client, game_id=game_id, move=WHITE_WIN[1], expected_ply=1
        )

        assert white.status_code == 201
        assert black.status_code == 409
        assert error_code(black) == "agent_turn"
        assert "`black`" in black.json()["detail"]
        assert allowed.status_code == 201

    async def test_rejects_abandoned_game(self, client: httpx2.AsyncClient) -> None:
        game_id = await create_game(client=client)
        await client.patch(f"/api/games/{game_id}", json={"status": "abandoned"})
        response = await play(
            client=client, game_id=game_id, move=WHITE_WIN[0], expected_ply=0
        )

        assert response.status_code == 409
        assert response.json()["detail"] == (
            f"Game `{game_id}` is abandoned; no more moves can be played."
        )

    async def test_missing(self, client: httpx2.AsyncClient) -> None:
        response = await play(
            client=client, game_id=str(uuid.uuid4()), move=WHITE_WIN[0], expected_ply=0
        )

        assert response.status_code == 404

    async def test_confirms_photo(
        self, client: httpx2.AsyncClient, session: AsyncSession
    ) -> None:
        game_id = await create_game(client=client)
        photo = PhotoRow(
            game_id=uuid.UUID(game_id), ply=0, object_key="photo.jpg", width=1, height=1
        )
        session.add(photo)
        await session.commit()
        response = await play(
            client=client,
            game_id=game_id,
            move=WHITE_WIN[0],
            expected_ply=0,
            source="photo",
            photo_id=str(photo.id),
        )
        await session.refresh(photo)

        assert response.status_code == 201
        assert response.json()["last_move"]["source"] == "photo"
        assert response.json()["last_move"]["photo_id"] == str(photo.id)
        assert photo.confirmed is True

        await client.delete(f"/api/games/{game_id}/moves/last")
        await session.refresh(photo)

        assert photo.confirmed is False

    async def test_rejects_photo_of_other_game(
        self, client: httpx2.AsyncClient, session: AsyncSession
    ) -> None:
        game_id = await create_game(client=client)
        other_id = await create_game(client=client)
        photo = PhotoRow(
            game_id=uuid.UUID(other_id), ply=0, object_key="photo.jpg", width=1, height=1
        )
        session.add(photo)
        await session.commit()
        response = await play(
            client=client,
            game_id=game_id,
            move=WHITE_WIN[0],
            expected_ply=0,
            source="photo",
            photo_id=str(photo.id),
        )

        assert response.status_code == 422
        assert error_code(response) == "photo_not_found"


class TestUndoMove:
    async def test_undoes_last_move(self, client: httpx2.AsyncClient) -> None:
        game_id = await create_game(client=client)
        positions = await play_all(client=client, game_id=game_id, moves=WHITE_WIN[:2])
        response = await client.delete(f"/api/games/{game_id}/moves/last")
        game = (await client.get(f"/api/games/{game_id}")).json()

        assert response.status_code == 200
        assert response.json() == positions[0]
        assert game["ply_count"] == 1
        assert game["updated_at"] > game["created_at"]

    async def test_reopens_finished_game(self, client: httpx2.AsyncClient) -> None:
        game_id = await create_game(client=client)
        await play_all(client=client, game_id=game_id, moves=WHITE_WIN)
        undone = await client.delete(
            f"/api/games/{game_id}/moves/last", params={"expected_ply": 9}
        )
        reopened = (await client.get(f"/api/games/{game_id}")).json()
        replayed = await play(
            client=client, game_id=game_id, move=WHITE_WIN[-1], expected_ply=8
        )

        assert undone.json()["result"] is None
        assert (reopened["status"], reopened["result"]) == ("active", None)
        assert replayed.json()["result"] == "white"

    async def test_rejects_stale_ply(self, client: httpx2.AsyncClient) -> None:
        game_id = await create_game(client=client)
        await play_all(client=client, game_id=game_id, moves=WHITE_WIN[:2])
        response = await client.delete(
            f"/api/games/{game_id}/moves/last", params={"expected_ply": 1}
        )

        assert response.status_code == 409
        assert error_code(response) == "ply_conflict"

    async def test_rejects_game_without_moves(self, client: httpx2.AsyncClient) -> None:
        game_id = await create_game(client=client)
        response = await client.delete(f"/api/games/{game_id}/moves/last")

        assert response.status_code == 409
        assert error_code(response) == "no_move_to_undo"

    async def test_missing(self, client: httpx2.AsyncClient) -> None:
        response = await client.delete(f"/api/games/{uuid.uuid4()}/moves/last")

        assert response.status_code == 404


async def test_plays_from_editor_setup(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    setup = {
        "board": [{"coord": [0, 0], "stack": [{"piece": "queen", "owner": "white"}]}],
        "current_player": "black",
        "current_ply": 1,
    }
    game_id = await create_game(client=client, setup=setup)
    start = (await client.get(f"/api/games/{game_id}/state")).json()
    move = {"piece": "queen", "from": None, "to": [1, 0]}
    played = await play(client=client, game_id=game_id, move=move, expected_ply=0)
    replayed = (await client.get(f"/api/games/{game_id}/state", params={"ply": 0})).json()
    undone = (await client.delete(f"/api/games/{game_id}/moves/last")).json()
    stored = await session.get(MoveRow, (uuid.UUID(game_id), 0))

    assert start["board"] == setup["board"]
    assert start["current_player"] == "black"
    assert start["hands"]["white"]["queen"] == 0
    assert start["placeable_coords"] == [
        [-1, 0],
        [-1, 1],
        [0, -1],
        [0, 1],
        [1, -1],
        [1, 0],
    ]
    assert played.status_code == 201
    assert played.json()["ply"] == 1
    assert played.json()["board"] == [
        *setup["board"],
        {"coord": [1, 0], "stack": [{"piece": "queen", "owner": "black"}]},
    ]
    assert played.json()["movable_pieces"] == [{"coord": [0, 0], "piece": "queen"}]
    assert replayed == {**start, "ply_count": 1}
    assert undone == start
    assert stored is None


async def test_concurrent_moves_conflict(
    committing_client: httpx2.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    game_id = await create_game(client=committing_client)
    responses: list[httpx2.Response] = []
    get_game = GameService.get_game
    loaded_games: list[GameRow] = []
    both_loaded = anyio.Event()

    async def get_game_together(
        self: GameService, game_id: uuid.UUID, *, lock: bool = False
    ) -> GameRow:
        """Load a game, then wait until the other request loaded it too or a second.

        Without the lock both requests would read the game before either writes. With
        it, the second request can only load the game once the first has committed.
        """
        game = await get_game(self, game_id, lock=lock)
        loaded_games.append(game)

        if len(loaded_games) == 2:
            both_loaded.set()

        with anyio.move_on_after(1):
            await both_loaded.wait()

        return game

    async def play_first_move(move: dict[str, Any]) -> None:
        """Play a first move and keep the response."""
        responses.append(
            await play(
                client=committing_client, game_id=game_id, move=move, expected_ply=0
            )
        )

    monkeypatch.setattr(GameService, "get_game", get_game_together)

    try:
        async with anyio.create_task_group() as task_group:
            for move in (WHITE_WIN[0], {"piece": "ant", "from": None, "to": [0, 0]}):
                task_group.start_soon(play_first_move, move)

        game = (await committing_client.get(f"/api/games/{game_id}")).json()

        assert sorted(response.status_code for response in responses) == [201, 409]
        assert game["ply_count"] == 1
    finally:
        await committing_client.delete(f"/api/games/{game_id}")
