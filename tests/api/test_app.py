from hive.api.app import create_app
from hive.api.settings import ApiSettings


def test_operation_ids_are_handler_names(settings: ApiSettings) -> None:
    operation_ids = [
        operation["operationId"]
        for path in create_app(settings=settings).openapi()["paths"].values()
        for operation in path.values()
    ]

    assert sorted(operation_ids) == [
        "confirm_move",
        "create_game",
        "delete_game",
        "export_game",
        "list_agent_kinds",
        "list_agent_presets",
        "list_games",
        "play_move",
        "read_game",
        "read_game_state",
        "read_liveness",
        "read_metrics",
        "read_piece_targets",
        "read_readiness",
        "think",
        "undo_move",
        "update_game",
    ]


def test_resources_are_under_api(settings: ApiSettings) -> None:
    paths = set(create_app(settings=settings).openapi()["paths"])

    probes = {"/healthz", "/readyz", "/metrics"}

    assert {*probes, "/api/agents", "/api/games"} <= paths
    assert all(path.startswith("/api/") for path in paths - probes)


def test_error_responses_are_documented(settings: ApiSettings) -> None:
    schema = create_app(settings=settings).openapi()
    read_game = schema["paths"]["/api/games/{game_id}"]["get"]
    readiness = schema["paths"]["/readyz"]["get"]

    assert read_game["responses"]["404"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }
    assert "503" in readiness["responses"]


def test_engine_values_are_typed_in_the_schema(settings: ApiSettings) -> None:
    schemas = create_app(settings=settings).openapi()["components"]["schemas"]
    move = schemas["Move"]

    assert move["required"] == ["piece", "from", "to"]
    assert {"Rules", "BoardSetup", "AgentSpec", "AgentRegistration"} <= set(schemas)
    assert sorted(schemas["AgentRegistration"]["properties"]) == [
        "description",
        "kind",
        "params_schema",
    ]


def test_error_responses_keep_validation_errors(settings: ApiSettings) -> None:
    schema = create_app(settings=settings).openapi()
    play_move = schema["paths"]["/api/games/{game_id}/moves"]["post"]
    unprocessable = play_move["responses"]["422"]["content"]["application/json"]

    assert unprocessable["schema"] == {
        "anyOf": [
            {"$ref": "#/components/schemas/ErrorResponse"},
            {"$ref": "#/components/schemas/HTTPValidationError"},
        ]
    }
    assert {"ErrorResponse", "HTTPValidationError"} <= set(
        schema["components"]["schemas"]
    )
    assert set(play_move["responses"]) == {"201", "404", "409", "422"}


def test_think_events_are_typed_in_the_schema(settings: ApiSettings) -> None:
    schema = create_app(settings=settings).openapi()
    think = schema["paths"]["/api/games/{game_id}/think"]["post"]
    stream = think["responses"]["200"]["content"]["text/event-stream"]
    data = stream["itemSchema"]["properties"]["data"]

    assert data["contentMediaType"] == "application/json"
    assert data["contentSchema"] == {"$ref": "#/components/schemas/ThinkEvent"}
    assert sorted(
        schema["components"]["schemas"]["ThinkEvent"]["discriminator"]["mapping"]
    ) == ["candidate", "decision", "error", "info"]
    assert think["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ThinkRequest"
    }
    assert set(think["responses"]) == {"200", "404", "409", "422", "503"}


def test_metrics_response_is_text(settings: ApiSettings) -> None:
    schema = create_app(settings=settings).openapi()
    responses = schema["paths"]["/metrics"]["get"]["responses"]

    assert list(responses["200"]["content"]) == [
        "text/plain; version=1.0.0; charset=utf-8"
    ]
