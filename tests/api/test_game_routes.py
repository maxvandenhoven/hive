import uuid
from typing import Any

import httpx2
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hive.api.db.models import GameRow, MoveRow, MoveSource, PhotoRow
from hive.api.storage import ObjectStore
from hive.engine.rules import Rules
from hive.engine.serialization import serialize_move, serialize_rules
from hive.engine.state import Move, PieceType

AGENT: dict[str, Any] = {
    "type": "agent",
    "spec": {"kind": "negamax", "params": {"depth": 2}},
    "budget_s": 2.5,
}
HUMAN = {"type": "human"}

pytestmark = pytest.mark.anyio


async def create_game(client: httpx2.AsyncClient, **fields: Any) -> dict[str, Any]:
    """Create a human vs negamax game with some fields set and return the response."""
    response = await client.post(
        "/api/games", json={"name": "Game", "white": HUMAN, "black": AGENT, **fields}
    )
    assert response.status_code == 201, response.text

    return response.json()


async def add_moves(
    session: AsyncSession, game_id: str, moves: list[Move | None]
) -> None:
    """Store moves for a game, as the move endpoints of a later work package will."""
    for ply, move in enumerate(moves):
        session.add(
            MoveRow(
                game_id=uuid.UUID(game_id),
                ply=ply,
                move=serialize_move(move),
                source=MoveSource.MANUAL,
            )
        )

    await session.commit()


async def count_rows(
    session: AsyncSession, model: type[MoveRow | PhotoRow], game_id: uuid.UUID
) -> int:
    """Count the moves or photos of a game."""
    query = select(func.count()).select_from(model).where(model.game_id == game_id)

    return await session.scalar(query) or 0


class TestCreateGame:
    async def test_creates_active_game(self, client: httpx2.AsyncClient) -> None:
        game = await create_game(client=client, rules={"max_turns": 40})

        assert game["name"] == "Game"
        assert game["status"] == "active"
        assert game["result"] is None
        assert game["white"] == HUMAN
        assert game["black"] == {**AGENT, "spec": {**AGENT["spec"], "label": None}}
        assert game["rules"] == serialize_rules(Rules(max_turns=40))
        assert game["setup"] == "initial"
        assert game["moves"] == []
        assert game["ply_count"] == 0

    async def test_rejects_human_vs_human(self, client: httpx2.AsyncClient) -> None:
        response = await client.post(
            "/api/games", json={"name": "Game", "white": HUMAN, "black": HUMAN}
        )

        assert response.status_code == 422
        assert "human vs human" in response.text

    async def test_rejects_invalid_agent_spec(self, client: httpx2.AsyncClient) -> None:
        response = await client.post(
            "/api/games",
            json={
                "name": "Game",
                "white": HUMAN,
                "black": {"type": "agent", "spec": {"kind": "x"}},
            },
        )

        assert response.status_code == 422
        assert "Unknown agent kind `x`" in response.text


class TestListGames:
    async def test_newest_first_with_pages(self, client: httpx2.AsyncClient) -> None:
        ids = [
            (await create_game(client=client, name=f"Game {i}"))["id"] for i in range(3)
        ]
        first = (await client.get("/api/games", params={"limit": 2})).json()
        second = (await client.get("/api/games", params={"limit": 2, "offset": 2})).json()

        assert [game["id"] for game in first["items"]] == ids[::-1][:2]
        assert [game["id"] for game in second["items"]] == ids[:1]
        assert (first["total"], first["limit"], first["offset"]) == (3, 2, 0)
        assert "moves" not in first["items"][0]

    async def test_filters_by_status(self, client: httpx2.AsyncClient) -> None:
        active = await create_game(client=client)
        finished = await create_game(client=client)
        await client.patch(f"/api/games/{finished['id']}", json={"status": "finished"})
        page = (await client.get("/api/games", params={"status": "active"})).json()

        assert [game["id"] for game in page["items"]] == [active["id"]]
        assert page["total"] == 1

    @pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
    async def test_rejects_bad_pages(
        self, client: httpx2.AsyncClient, params: dict[str, int]
    ) -> None:
        assert (await client.get("/api/games", params=params)).status_code == 422


class TestReadGame:
    async def test_includes_moves(
        self, client: httpx2.AsyncClient, session: AsyncSession
    ) -> None:
        game = await create_game(client=client)
        moves: list[Move | None] = [
            Move(piece_type=PieceType.QUEEN, source_coord=None, target_coord=(0, 0)),
            Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(1, 0)),
        ]
        await add_moves(session=session, game_id=game["id"], moves=moves)
        body = (await client.get(f"/api/games/{game['id']}")).json()

        assert body["ply_count"] == 2
        assert [move["ply"] for move in body["moves"]] == [0, 1]
        assert [move["move"] for move in body["moves"]] == [
            serialize_move(move) for move in moves
        ]
        assert body["moves"][0]["source"] == "manual"

    async def test_missing(self, client: httpx2.AsyncClient) -> None:
        game_id = uuid.uuid4()
        response = await client.get(f"/api/games/{game_id}")

        assert response.status_code == 404
        assert response.json() == {
            "code": "game_not_found",
            "detail": f"Game `{game_id}` not found.",
        }

    async def test_invalid_id(self, client: httpx2.AsyncClient) -> None:
        assert (await client.get("/api/games/not-a-uuid")).status_code == 422


class TestUpdateGame:
    async def test_renames_and_changes_status(self, client: httpx2.AsyncClient) -> None:
        game = await create_game(client=client)
        response = await client.patch(
            f"/api/games/{game['id']}", json={"name": "Renamed", "status": "abandoned"}
        )
        body = response.json()

        assert response.status_code == 200
        assert body["name"] == "Renamed"
        assert body["status"] == "abandoned"
        assert body["updated_at"] > game["updated_at"]

    async def test_rejects_invalid_status(self, client: httpx2.AsyncClient) -> None:
        game = await create_game(client=client)
        response = await client.patch(
            f"/api/games/{game['id']}", json={"status": "paused"}
        )

        assert response.status_code == 422

    async def test_missing(self, client: httpx2.AsyncClient) -> None:
        response = await client.patch(f"/api/games/{uuid.uuid4()}", json={"name": "x"})

        assert response.status_code == 404


class TestDeleteGame:
    async def test_deletes_moves_photos_and_objects(
        self, client: httpx2.AsyncClient, session: AsyncSession, store: ObjectStore
    ) -> None:
        game = await create_game(client=client)
        game_id = uuid.UUID(game["id"])
        await add_moves(session=session, game_id=game["id"], moves=[None])
        photo = PhotoRow(
            game_id=game_id,
            ply=0,
            object_key=f"photos/{game_id}/1.jpg",
            width=1,
            height=1,
        )
        session.add(photo)
        await session.commit()

        for key in (photo.object_key, "photos/other/1.jpg"):
            await store.put(key=key, data=b"jpeg", content_type="image/jpeg")

        response = await client.delete(f"/api/games/{game_id}")
        session.expunge_all()

        assert response.status_code == 204
        assert await session.get(GameRow, game_id) is None
        assert await count_rows(session=session, model=MoveRow, game_id=game_id) == 0
        assert await count_rows(session=session, model=PhotoRow, game_id=game_id) == 0
        assert await store.list_keys() == ["photos/other/1.jpg"]
        assert (await client.get(f"/api/games/{game_id}")).status_code == 404

    async def test_keeps_deletion_when_objects_fail(
        self,
        client: httpx2.AsyncClient,
        store: ObjectStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def fail(prefix: str) -> int:
            raise ConnectionError(prefix)

        monkeypatch.setattr(store, "delete_prefix", fail)
        game = await create_game(client=client)

        assert (await client.delete(f"/api/games/{game['id']}")).status_code == 204
        assert (await client.get(f"/api/games/{game['id']}")).status_code == 404

    async def test_missing(self, client: httpx2.AsyncClient) -> None:
        assert (await client.delete(f"/api/games/{uuid.uuid4()}")).status_code == 404


class TestExportGame:
    async def test_downloads_game_record(
        self, client: httpx2.AsyncClient, session: AsyncSession
    ) -> None:
        setup = {
            "board": [{"coord": [0, 0], "stack": [{"piece": "queen", "owner": "white"}]}],
            "current_player": "black",
            "current_ply": 1,
        }
        game = await create_game(client=client, setup=setup)
        move = Move(piece_type=PieceType.QUEEN, source_coord=None, target_coord=(1, 0))
        await add_moves(session=session, game_id=game["id"], moves=[move])
        response = await client.get(f"/api/games/{game['id']}/export")

        assert response.status_code == 200
        assert response.headers["content-disposition"] == (
            f'attachment; filename="game-{game["id"]}.json"'
        )
        assert response.json() == {
            "rules": serialize_rules(Rules()),
            "setup": setup,
            "moves": [serialize_move(move)],
        }

    async def test_missing(self, client: httpx2.AsyncClient) -> None:
        assert (await client.get(f"/api/games/{uuid.uuid4()}/export")).status_code == 404
