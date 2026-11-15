import random
import uuid
from collections import Counter
from typing import Any

import cv2
import httpx2
import numpy as np
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from hive.api.db.models import GameRow, MoveSource, PhotoRow
from hive.api.games import GameService
from hive.api.settings import ApiSettings
from hive.api.storage import ObjectStore
from hive.api.vision import BoardVision
from hive.engine.record import GameRecord
from hive.engine.rules import Rules
from hive.engine.state import GameBoard, Move, PieceType
from hive.vision.testing import SimulatedCamera, SimulatedDetector, simulate_observations
from hive.vision.types import TileObservation

pytestmark = pytest.mark.anyio

IMAGE_SIZE = (1024, 768)

CAMERA = SimulatedCamera(
    tilt_deg=25, azimuth_deg=30, roll_deg=2, distance=12, focal=900, image_size=IMAGE_SIZE
)
"""A phone camera over the middle of the table."""

HINT = {"spec": {"kind": "negamax", "params": {"depth": 1}}, "budget_s": 1.0}
HUMAN = {"type": "human"}
AGENT = {"type": "agent", "spec": {"kind": "negamax", "params": {"depth": 1}}}

FIRST_MOVES: list[Move | None] = [
    Move(piece_type=PieceType.QUEEN, source_coord=None, target_coord=(0, 0)),
    Move(piece_type=PieceType.ANT, source_coord=None, target_coord=(1, 0)),
    Move(piece_type=PieceType.SPIDER, source_coord=None, target_coord=(-1, 0)),
]
"""The first moves of the games of the tests: white queen, black ant, white spider."""


class QueuedReader:
    """A board reader that returns prepared detections, one list per photo.

    Attributes:
        name: The reader name.
        queue: The detections of the next photos, in order.
    """

    name = "fake"

    def __init__(self) -> None:
        """Create the reader with nothing queued."""
        self.queue: list[list[TileObservation]] = []

    def read(self, image: np.ndarray) -> list[TileObservation]:
        """Return the detections queued first."""
        assert image.shape[:2] == (IMAGE_SIZE[1], IMAGE_SIZE[0])

        return self.queue.pop(0)


@pytest.fixture(scope="function")
def reader() -> QueuedReader:
    """Build a reader with nothing queued."""
    return QueuedReader()


@pytest.fixture(scope="function")
def vision(reader: QueuedReader) -> BoardVision:
    """Give the test app the queued reader."""
    return BoardVision(reader=reader, model_version="fake/v0")


def jpeg(size: tuple[int, int] = IMAGE_SIZE) -> bytes:
    """Encode a grey image of a size as a JPEG."""
    pixels = np.full((size[1], size[0], 3), 128, dtype=np.uint8)
    encoded, buffer = cv2.imencode(".jpg", pixels)
    assert encoded

    return buffer.tobytes()


def observe(board: GameBoard, seed: int = 0) -> list[TileObservation]:
    """Detect the top faces of a board as the camera of the tests sees them."""
    return simulate_observations(
        board=board,
        camera=CAMERA,
        detector=SimulatedDetector(position_noise=0.02),
        rng=random.Random(seed),
    )


def board_after(moves: list[Move | None]) -> GameBoard:
    """Get the board after moves from the initial position."""
    return GameRecord(rules=Rules(), moves=moves).replay().board


async def create_game(client: httpx2.AsyncClient, **fields: Any) -> str:
    """Create a game at the table between two people, one with hints."""
    body = {
        "name": "Photos",
        "white": {**HUMAN, "hint": HINT},
        "black": HUMAN,
        "board_location": "table",
        **fields,
    }
    response = await client.post("/api/games", json=body)
    assert response.status_code == 201, response.text

    return response.json()["id"]


async def upload(
    client: httpx2.AsyncClient, game_id: str, expected_ply: int, data: bytes | None = None
) -> httpx2.Response:
    """Post a photo of a game."""
    return await client.post(
        f"/api/games/{game_id}/photos",
        files={"image": ("photo.jpg", data or jpeg(), "image/jpeg")},
        data={"expected_ply": str(expected_ply)},
    )


async def play(
    client: httpx2.AsyncClient,
    game_id: str,
    move: Move | None,
    expected_ply: int,
    photo_id: str | None = None,
) -> httpx2.Response:
    """Play a move, read from a photo if a photo is given."""
    body: dict[str, Any] = {
        "move": None if move is None else move.to_json(),
        "expected_ply": expected_ply,
        "allow_agent_side": True,
    }

    if photo_id is not None:
        body |= {"source": "photo", "photo_id": photo_id}

    return await client.post(f"/api/games/{game_id}/moves", json=body)


def best_moves(photo: dict[str, Any]) -> list[Move | None]:
    """Get the moves of the best candidate of a read photo."""
    candidates = photo["match"]["resolution"]["candidates"]

    return [
        None if move is None else Move.from_json(move) for move in candidates[0]["moves"]
    ]


class TestStorePhotos:
    @pytest.fixture(scope="function")
    def vision(self) -> BoardVision:
        """Store photos without a reader."""
        return BoardVision(reader=None)

    async def test_stores_photo_without_reading_it(
        self, client: httpx2.AsyncClient, store: ObjectStore
    ) -> None:
        game_id = await create_game(client=client)
        response = await upload(client=client, game_id=game_id, expected_ply=0)
        photo = response.json()
        image = await client.get(f"/api/photos/{photo['id']}/image")
        pixels = cv2.imdecode(np.frombuffer(image.content, np.uint8), cv2.IMREAD_COLOR)
        listed = store.client.list_objects_v2(Bucket=store.bucket)

        assert response.status_code == 201, response.text
        assert (photo["game_id"], photo["ply"]) == (game_id, 0)
        assert (photo["width"], photo["height"]) == IMAGE_SIZE
        assert (photo["reader"], photo["match"], photo["confirmed"]) == (
            None,
            None,
            False,
        )
        assert image.status_code == 200
        assert image.headers["content-type"] == "image/jpeg"
        assert "immutable" in image.headers["cache-control"]
        assert pixels is not None
        assert pixels.shape == (IMAGE_SIZE[1], IMAGE_SIZE[0], 3)
        assert [item["Key"] for item in listed["Contents"]] == [
            f"photos/{game_id}/{photo['id']}.jpg"
        ]

    async def test_scales_large_photos_down(
        self, client: httpx2.AsyncClient, settings: ApiSettings
    ) -> None:
        settings.photo_max_side = 1000
        game_id = await create_game(client=client)
        response = await upload(
            client=client, game_id=game_id, expected_ply=0, data=jpeg((2000, 1500))
        )

        assert (response.json()["width"], response.json()["height"]) == (1000, 750)

    async def test_deleting_the_game_deletes_its_photos(
        self, client: httpx2.AsyncClient, store: ObjectStore
    ) -> None:
        game_id = await create_game(client=client)
        await upload(client=client, game_id=game_id, expected_ply=0)
        response = await client.delete(f"/api/games/{game_id}")
        listed = store.client.list_objects_v2(Bucket=store.bucket)

        assert response.status_code == 204
        assert "Contents" not in listed

    async def test_unknown_photo_image(self, client: httpx2.AsyncClient) -> None:
        response = await client.get(f"/api/photos/{uuid.uuid4()}/image")

        assert response.status_code == 404
        assert response.json()["code"] == "photo_not_found"

    async def test_rejects_screen_games(self, client: httpx2.AsyncClient) -> None:
        game_id = await create_game(
            client=client, white=HUMAN, black=AGENT, board_location="screen"
        )
        response = await upload(client=client, game_id=game_id, expected_ply=0)

        assert response.status_code == 409
        assert response.json()["code"] == "not_at_table"

    async def test_rejects_a_stale_ply(self, client: httpx2.AsyncClient) -> None:
        game_id = await create_game(client=client)
        response = await upload(client=client, game_id=game_id, expected_ply=1)

        assert response.status_code == 409
        assert response.json()["code"] == "ply_conflict"

    async def test_rejects_ended_games(self, client: httpx2.AsyncClient) -> None:
        game_id = await create_game(client=client)
        await client.patch(f"/api/games/{game_id}", json={"status": "abandoned"})
        response = await upload(client=client, game_id=game_id, expected_ply=0)

        assert response.status_code == 409
        assert response.json()["code"] == "game_not_active"

    async def test_rejects_files_that_are_not_images(
        self, client: httpx2.AsyncClient
    ) -> None:
        game_id = await create_game(client=client)
        response = await upload(
            client=client, game_id=game_id, expected_ply=0, data=b"not an image"
        )

        assert response.status_code == 422
        assert response.json()["code"] == "photo_not_readable"

    async def test_rejects_large_files(
        self, client: httpx2.AsyncClient, settings: ApiSettings
    ) -> None:
        settings.photo_max_bytes = 100
        game_id = await create_game(client=client)
        response = await upload(client=client, game_id=game_id, expected_ply=0)

        assert response.status_code == 413
        assert response.json()["code"] == "photo_too_large"

    async def test_board_estimates_need_a_reader(
        self, client: httpx2.AsyncClient
    ) -> None:
        response = await client.post(
            "/api/board-estimates", files={"image": ("photo.jpg", jpeg(), "image/jpeg")}
        )

        assert response.status_code == 503
        assert response.json()["code"] == "vision_unavailable"


class TestReadMoves:
    async def test_proposes_the_move_and_commits_it_with_the_photo(
        self, client: httpx2.AsyncClient, reader: QueuedReader, session: AsyncSession
    ) -> None:
        game_id = await create_game(client=client)
        reader.queue.append(observe(board_after(FIRST_MOVES[:1])))
        photo = (await upload(client=client, game_id=game_id, expected_ply=0)).json()
        response = await play(
            client=client,
            game_id=game_id,
            move=best_moves(photo)[0],
            expected_ply=0,
            photo_id=photo["id"],
        )
        game = (await client.get(f"/api/games/{game_id}")).json()
        row = await session.get(PhotoRow, uuid.UUID(photo["id"]))

        assert (photo["reader"], photo["model_version"]) == ("fake", "fake/v0")
        assert photo["match"]["purpose"] == "move"
        assert photo["match"]["resolution"]["status"] == "resolved"
        assert photo["match"]["previous_photo_id"] is None
        assert photo["match"]["photo_ids"] == [photo["id"]]
        assert photo["match"]["tile_count"] == 1
        assert best_moves(photo) == FIRST_MOVES[:1]
        assert response.status_code == 201, response.text
        assert game["moves"][0]["source"] == "photo"
        assert game["moves"][0]["photo_id"] == photo["id"]
        assert row is not None
        await session.refresh(row)
        assert row.confirmed
        assert row.detections is not None
        assert len(row.detections) == 1

    async def test_uses_the_previous_photo(
        self, client: httpx2.AsyncClient, reader: QueuedReader
    ) -> None:
        game_id = await create_game(client=client)
        reader.queue.append(observe(board_after(FIRST_MOVES[:1])))
        first = (await upload(client=client, game_id=game_id, expected_ply=0)).json()
        await play(
            client=client,
            game_id=game_id,
            move=FIRST_MOVES[0],
            expected_ply=0,
            photo_id=first["id"],
        )
        reader.queue.append(observe(board_after(FIRST_MOVES[:2]), seed=1))
        second = (await upload(client=client, game_id=game_id, expected_ply=1)).json()

        assert second["ply"] == 1
        assert second["match"]["resolution"]["status"] == "resolved"
        assert second["match"]["previous_photo_id"] == first["id"]
        assert [move and move.piece_type for move in best_moves(second)] == [
            PieceType.ANT
        ]

    async def test_combines_an_unclear_photo_with_the_next(
        self, client: httpx2.AsyncClient, reader: QueuedReader
    ) -> None:
        game_id = await create_game(client=client)

        for ply, move in enumerate(FIRST_MOVES[:2]):
            await play(client=client, game_id=game_id, move=move, expected_ply=ply)

        # The first photo is taken before the move was made, so it fits several moves.
        reader.queue.append(observe(board_after(FIRST_MOVES[:2])))
        unclear = (await upload(client=client, game_id=game_id, expected_ply=2)).json()
        reader.queue.append(observe(board_after(FIRST_MOVES), seed=1))
        clear = (await upload(client=client, game_id=game_id, expected_ply=2)).json()

        assert unclear["match"]["resolution"]["status"] == "ambiguous"
        assert unclear["match"]["resolution"]["reason"]
        assert clear["match"]["photo_ids"] == [unclear["id"], clear["id"]]
        assert clear["match"]["resolution"]["status"] == "resolved"
        assert best_moves(clear) == FIRST_MOVES[2:]

    async def test_photos_from_before_a_move_are_not_combined(
        self, client: httpx2.AsyncClient, reader: QueuedReader
    ) -> None:
        game_id = await create_game(client=client)
        reader.queue.append(observe({}))
        await upload(client=client, game_id=game_id, expected_ply=0)
        await play(client=client, game_id=game_id, move=FIRST_MOVES[0], expected_ply=0)
        await client.delete(f"/api/games/{game_id}/moves/last")
        reader.queue.append(observe(board_after(FIRST_MOVES[:1])))
        photo = (await upload(client=client, game_id=game_id, expected_ply=0)).json()

        assert photo["match"]["photo_ids"] == [photo["id"]]

    async def test_photo_without_tiles_fails(
        self, client: httpx2.AsyncClient, reader: QueuedReader
    ) -> None:
        game_id = await create_game(client=client)
        reader.queue.append([])
        photo = (await upload(client=client, game_id=game_id, expected_ply=0)).json()

        assert photo["match"]["resolution"]["status"] == "failed"
        assert "No tiles" in photo["match"]["resolution"]["reason"]
        assert photo["match"]["tile_count"] == 0

    async def test_counts_photos_by_outcome(
        self, client: httpx2.AsyncClient, reader: QueuedReader
    ) -> None:
        game_id = await create_game(client=client)
        reader.queue += [[], observe(board_after(FIRST_MOVES[:1]))]
        await upload(client=client, game_id=game_id, expected_ply=0)
        await upload(client=client, game_id=game_id, expected_ply=0)
        metrics = (await client.get("/metrics")).text

        assert 'hive_photo_match_total{outcome="failed"} 1.0' in metrics
        assert 'hive_photo_match_total{outcome="resolved"} 1.0' in metrics
        assert 'hive_photo_read_seconds_count{reader="fake"} 2.0' in metrics


class TestVerifyAgentMoves:
    async def start(
        self, client: httpx2.AsyncClient, session: AsyncSession, store: ObjectStore
    ) -> str:
        """Create a game against an agent at the table with the agent move pending."""
        game_id = await create_game(client=client, white=HUMAN, black=AGENT)
        await play(client=client, game_id=game_id, move=FIRST_MOVES[0], expected_ply=0)
        games = GameService(session=session, store=store)
        game = await games.get_game(uuid.UUID(game_id), lock=True)
        await games.append_move(
            game=game,
            state=game.replay(),
            move=FIRST_MOVES[1],
            source=MoveSource.AGENT,
            pending=True,
        )

        return game_id

    async def test_matching_photo_confirms_the_agent_move(
        self,
        client: httpx2.AsyncClient,
        reader: QueuedReader,
        session: AsyncSession,
        store: ObjectStore,
    ) -> None:
        game_id = await self.start(client=client, session=session, store=store)
        reader.queue.append(observe(board_after(FIRST_MOVES[:2])))
        photo = (await upload(client=client, game_id=game_id, expected_ply=2)).json()
        response = await client.post(
            f"/api/games/{game_id}/moves/last/confirm",
            json={"expected_ply": 2, "photo_id": photo["id"]},
        )
        game = (await client.get(f"/api/games/{game_id}")).json()

        assert photo["ply"] == 1
        assert photo["match"]["purpose"] == "verification"
        assert photo["match"]["verification"]["status"] == "matched"
        assert response.status_code == 200, response.text
        assert response.json()["pending_move"] is False
        assert game["moves"][1]["photo_id"] == photo["id"]
        assert game["moves"][1]["source"] == "agent"

    async def test_photo_of_another_move_does_not_match(
        self,
        client: httpx2.AsyncClient,
        reader: QueuedReader,
        session: AsyncSession,
        store: ObjectStore,
    ) -> None:
        game_id = await self.start(client=client, session=session, store=store)
        other = Move(piece_type=PieceType.BEETLE, source_coord=None, target_coord=(1, 0))
        reader.queue.append(observe(board_after([FIRST_MOVES[0], other])))
        photo = (await upload(client=client, game_id=game_id, expected_ply=2)).json()
        verification = photo["match"]["verification"]

        assert verification["status"] == "mismatched"
        assert "beetle" in verification["reason"]
        assert verification["probability"] < 0.05

    async def test_confirm_rejects_photos_of_other_games(
        self,
        client: httpx2.AsyncClient,
        reader: QueuedReader,
        session: AsyncSession,
        store: ObjectStore,
    ) -> None:
        game_id = await self.start(client=client, session=session, store=store)
        other_id = await create_game(client=client)
        reader.queue.append(observe({}))
        photo = (await upload(client=client, game_id=other_id, expected_ply=0)).json()
        response = await client.post(
            f"/api/games/{game_id}/moves/last/confirm",
            json={"expected_ply": 2, "photo_id": photo["id"]},
        )
        row = await session.get(GameRow, uuid.UUID(game_id))

        assert response.status_code == 422
        assert response.json()["code"] == "photo_not_found"
        assert row is not None


class TestEstimateBoard:
    async def test_reads_a_board_from_one_photo(
        self, client: httpx2.AsyncClient, reader: QueuedReader
    ) -> None:
        board = board_after(FIRST_MOVES)
        reader.queue.append(observe(board))
        response = await client.post(
            "/api/board-estimates", files={"image": ("photo.jpg", jpeg(), "image/jpeg")}
        )
        estimate = response.json()
        pieces = Counter(
            (tile["piece"]["piece"], tile["piece"]["owner"]) for tile in estimate["tiles"]
        )

        assert response.status_code == 200, response.text
        assert estimate["status"] == "confident"
        assert estimate["players"] == ["white", "black"]
        assert pieces == Counter(
            (stack[-1].type.name.lower(), stack[-1].owner.name.lower())
            for stack in board.values()
        )
        assert len(estimate["board"]) == len(board)

    async def test_estimated_board_starts_a_game(
        self, client: httpx2.AsyncClient, reader: QueuedReader
    ) -> None:
        reader.queue.append(observe(board_after(FIRST_MOVES)))
        estimate = (
            await client.post(
                "/api/board-estimates",
                files={"image": ("photo.jpg", jpeg(), "image/jpeg")},
            )
        ).json()
        game_id = await create_game(
            client=client, setup={"board": estimate["board"], "current_player": "black"}
        )
        position = (await client.get(f"/api/games/{game_id}/state")).json()

        assert position["current_player"] == "black"
        assert len(position["board"]) == 3


class TestReadiness:
    @pytest.fixture(scope="function")
    def vision(self) -> BoardVision:
        """Leave the app without the reader model it was configured with."""
        return BoardVision(reader=None, configured=True, error="The model is missing.")

    async def test_fails_without_the_configured_model(
        self, client: httpx2.AsyncClient
    ) -> None:
        response = await client.get("/readyz")

        assert response.status_code == 503
        assert response.json()["checks"]["vision"] == "failed"

    async def test_board_estimates_say_why(self, client: httpx2.AsyncClient) -> None:
        response = await client.post(
            "/api/board-estimates", files={"image": ("photo.jpg", jpeg(), "image/jpeg")}
        )

        assert response.status_code == 503
        assert response.json()["detail"] == "The model is missing."
