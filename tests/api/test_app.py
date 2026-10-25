from hive.api.app import create_app
from hive.api.settings import ApiSettings


def test_operation_ids_are_handler_names(settings: ApiSettings) -> None:
    operation_ids = [
        operation["operationId"]
        for path in create_app(settings=settings).openapi()["paths"].values()
        for operation in path.values()
    ]

    assert sorted(operation_ids) == [
        "create_game",
        "delete_game",
        "export_game",
        "list_agent_kinds",
        "list_games",
        "read_game",
        "read_liveness",
        "read_readiness",
        "update_game",
    ]


def test_resources_are_under_api(settings: ApiSettings) -> None:
    paths = set(create_app(settings=settings).openapi()["paths"])

    assert {"/healthz", "/readyz", "/api/agents", "/api/games"} <= paths
    assert all(path.startswith("/api/") for path in paths - {"/healthz", "/readyz"})


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
