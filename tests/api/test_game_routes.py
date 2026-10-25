import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from hive.api.db.models import GameRow, MoveRow, MoveSource, PhotoRow
from hive.api.storage import InMemoryObjectStore
from hive.engine.rules import Rules
from hive.engine.serialization import serialize_move, serialize_rules
from hive.engine.state import Move, PieceType

AGENT: dict[str, Any] = {
    "type": "agent",
    "spec": {"kind": "negamax", "params": {"depth": 2}},
    "budget_s": 2.5,
}
HUMAN = {"type": "human"}


def create_game(client: TestClient, **fields: Any) -> dict[str, Any]:
    """Create a human vs negamax game with some fields set and return the response."""
    response = client.post(
        "/api/games", json={"name": "Game", "white": HUMAN, "black": AGENT, **fields}
    )
    assert response.status_code == 201, response.text

    return response.json()


def add_moves(session: Session, game_id: str, moves: list[Move | None]) -> None:
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

    session.commit()


class TestCreateGame:
    def test_creates_active_game(self, client: TestClient) -> None:
        game = create_game(client=client, rules={"max_turns": 40})

        assert game["name"] == "Game"
        assert game["status"] == "active"
        assert game["result"] is None
        assert game["white"] == HUMAN
        assert game["black"] == {**AGENT, "spec": {**AGENT["spec"], "label": None}}
        assert game["rules"] == serialize_rules(Rules(max_turns=40))
        assert game["setup"] == "initial"
        assert game["moves"] == []
        assert game["ply_count"] == 0

    def test_rejects_human_vs_human(self, client: TestClient) -> None:
        response = client.post(
            "/api/games", json={"name": "Game", "white": HUMAN, "black": HUMAN}
        )

        assert response.status_code == 422
        assert "human vs human" in response.text

    def test_rejects_invalid_agent_spec(self, client: TestClient) -> None:
        response = client.post(
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
    def test_newest_first_with_pages(self, client: TestClient) -> None:
        ids = [create_game(client=client, name=f"Game {i}")["id"] for i in range(3)]
        first = client.get("/api/games", params={"limit": 2}).json()
        second = client.get("/api/games", params={"limit": 2, "offset": 2}).json()

        assert [game["id"] for game in first["items"]] == ids[::-1][:2]
        assert [game["id"] for game in second["items"]] == ids[:1]
        assert (first["total"], first["limit"], first["offset"]) == (3, 2, 0)
        assert "moves" not in first["items"][0]

    def test_filters_by_status(self, client: TestClient) -> None:
        active = create_game(client=client)
        finished = create_game(client=client)
        client.patch(f"/api/games/{finished['id']}", json={"status": "finished"})
        page = client.get("/api/games", params={"status": "active"}).json()

        assert [game["id"] for game in page["items"]] == [active["id"]]
        assert page["total"] == 1

    @pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
    def test_rejects_bad_pages(self, client: TestClient, params: dict[str, int]) -> None:
        assert client.get("/api/games", params=params).status_code == 422


class TestReadGame:
    def test_includes_moves(self, client: TestClient, session: Session) -> None:
        game = create_game(client=client)
        moves: list[Move | None] = [
            Move(piece_type=PieceType.QUEEN, source_coord=None, target_coord=(0, 0)),
            Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(1, 0)),
        ]
        add_moves(session=session, game_id=game["id"], moves=moves)
        body = client.get(f"/api/games/{game['id']}").json()

        assert body["ply_count"] == 2
        assert [move["ply"] for move in body["moves"]] == [0, 1]
        assert [move["move"] for move in body["moves"]] == [
            serialize_move(move) for move in moves
        ]
        assert body["moves"][0]["source"] == "manual"

    def test_missing(self, client: TestClient) -> None:
        response = client.get(f"/api/games/{uuid.uuid4()}")

        assert response.status_code == 404

    def test_invalid_id(self, client: TestClient) -> None:
        assert client.get("/api/games/not-a-uuid").status_code == 422


class TestUpdateGame:
    def test_renames_and_changes_status(self, client: TestClient) -> None:
        game = create_game(client=client)
        response = client.patch(
            f"/api/games/{game['id']}", json={"name": "Renamed", "status": "abandoned"}
        )
        body = response.json()

        assert response.status_code == 200
        assert body["name"] == "Renamed"
        assert body["status"] == "abandoned"
        assert body["updated_at"] > game["updated_at"]

    def test_rejects_invalid_status(self, client: TestClient) -> None:
        game = create_game(client=client)
        response = client.patch(f"/api/games/{game['id']}", json={"status": "paused"})

        assert response.status_code == 422

    def test_missing(self, client: TestClient) -> None:
        response = client.patch(f"/api/games/{uuid.uuid4()}", json={"name": "x"})

        assert response.status_code == 404


class TestDeleteGame:
    def test_deletes_moves_photos_and_objects(
        self, client: TestClient, session: Session, store: InMemoryObjectStore
    ) -> None:
        game = create_game(client=client)
        game_id = uuid.UUID(game["id"])
        add_moves(session=session, game_id=game["id"], moves=[None])
        photo = PhotoRow(
            game_id=game_id,
            ply=0,
            object_key=f"photos/{game_id}/1.jpg",
            width=1,
            height=1,
        )
        session.add(photo)
        session.commit()

        for key in (photo.object_key, "photos/other/1.jpg"):
            store.put(key=key, data=b"jpeg", content_type="image/jpeg")

        response = client.delete(f"/api/games/{game_id}")
        session.expunge_all()

        assert response.status_code == 204
        assert session.get(GameRow, game_id) is None
        assert session.query(MoveRow).filter_by(game_id=game_id).count() == 0
        assert session.query(PhotoRow).filter_by(game_id=game_id).count() == 0
        assert list(store.objects) == ["photos/other/1.jpg"]
        assert client.get(f"/api/games/{game_id}").status_code == 404

    def test_keeps_deletion_when_objects_fail(
        self,
        client: TestClient,
        store: InMemoryObjectStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def fail(prefix: str) -> int:
            raise ConnectionError(prefix)

        monkeypatch.setattr(store, "delete_prefix", fail)
        game = create_game(client=client)

        assert client.delete(f"/api/games/{game['id']}").status_code == 204
        assert client.get(f"/api/games/{game['id']}").status_code == 404

    def test_missing(self, client: TestClient) -> None:
        assert client.delete(f"/api/games/{uuid.uuid4()}").status_code == 404


class TestExportGame:
    def test_downloads_game_record(self, client: TestClient, session: Session) -> None:
        setup = {
            "board": [{"coord": [0, 0], "stack": [{"piece": "queen", "owner": "white"}]}],
            "current_player": "black",
            "current_ply": 1,
        }
        game = create_game(client=client, setup=setup)
        move = Move(piece_type=PieceType.QUEEN, source_coord=None, target_coord=(1, 0))
        add_moves(session=session, game_id=game["id"], moves=[move])
        response = client.get(f"/api/games/{game['id']}/export")

        assert response.status_code == 200
        assert response.headers["content-disposition"] == (
            f'attachment; filename="game-{game["id"]}.json"'
        )
        assert response.json() == {
            "rules": serialize_rules(Rules()),
            "setup": setup,
            "moves": [serialize_move(move)],
        }

    def test_missing(self, client: TestClient) -> None:
        assert client.get(f"/api/games/{uuid.uuid4()}/export").status_code == 404
