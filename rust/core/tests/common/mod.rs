//! Shared helpers of the integration tests: the perft suite of the Python tests.

#![allow(dead_code, reason = "each test crate uses a part of the helpers")]

use std::fs;
use std::path::PathBuf;

use hive_core::engine::{
    Coord, CoordMove, GameState, PieceType, Player, Rules, RulesConfig,
};
use serde_json::Value;

/// A position of the perft suite: the state after its moves and the expected counts.
pub struct SuitePosition {
    /// The name of the position.
    pub name: String,
    /// The state after the moves of the position.
    pub state: GameState,
    /// The expected count per depth, reference counts and engine counts together.
    pub counts: Vec<(u32, u64)>,
    /// The reference legal moves, if the suite has them.
    pub legal_moves: Option<Vec<Option<CoordMove>>>,
}

/// Read the perft suite of the Python tests.
pub fn load_suite() -> (Rules, Vec<SuitePosition>) {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../tests/data/perft/base.json");
    let suite: Value =
        serde_json::from_str(&fs::read_to_string(path).expect("the suite exists"))
            .expect("JSON");
    let json_rules = &suite["rules"];
    let mut config = RulesConfig::default();

    if let Some(player) = json_rules["starting_player"].as_str() {
        config.starting_player = parse_player(player);
    }

    config.queen_by_turn = json_rules["queen_by_turn"].as_i64();
    config.allow_queen_first_turn = json_rules["allow_queen_first_turn"]
        .as_bool()
        .unwrap_or(config.allow_queen_first_turn);
    config.move_before_queen =
        json_rules["move_before_queen"].as_bool().unwrap_or(config.move_before_queen);
    config.max_turns = json_rules["max_turns"].as_i64();
    let rules = Rules::new(config).expect("the suite rules are valid");

    let positions = suite["positions"]
        .as_array()
        .expect("positions")
        .iter()
        .map(|position| {
            let mut state = rules.create_initial_state();

            for mv in position["moves"].as_array().expect("moves") {
                rules
                    .apply_checked_move(&mut state, parse_move(mv))
                    .expect("a legal move");
            }

            let mut counts: Vec<(u32, u64)> = ["engine_counts", "counts"]
                .iter()
                .filter_map(|key| position[*key].as_object())
                .flat_map(|object| {
                    object.iter().map(|(depth, count)| {
                        (
                            depth.parse().expect("a depth"),
                            count.as_u64().expect("a count"),
                        )
                    })
                })
                .collect();
            counts.sort_unstable();
            counts.dedup_by_key(|(depth, _)| *depth);
            let legal_moves = position["legal_moves"]
                .as_array()
                .map(|moves| moves.iter().map(parse_move).collect());

            SuitePosition {
                name: position["name"].as_str().expect("a name").to_owned(),
                state,
                counts,
                legal_moves,
            }
        })
        .collect();

    (rules, positions)
}

/// Read a player from its JSON name.
pub fn parse_player(name: &str) -> Player {
    match name {
        "white" => Player::White,
        "black" => Player::Black,
        _ => panic!("unknown player `{name}`"),
    }
}

/// Read a move from its JSON form; `null` is a pass.
pub fn parse_move(value: &Value) -> Option<CoordMove> {
    if value.is_null() {
        return None;
    }

    let piece_type = PieceType::ALL
        .into_iter()
        .find(|piece_type| Some(piece_type.lower_name()) == value["piece"].as_str())
        .expect("a piece type");
    let coord = |coord: &Value| {
        let pair = coord.as_array().expect("a coordinate");
        let q = pair[0].as_i64().expect("q");
        let r = pair[1].as_i64().expect("r");
        Coord::new(i32::try_from(q).expect("q fits"), i32::try_from(r).expect("r fits"))
    };
    let source = (!value["from"].is_null()).then(|| coord(&value["from"]));

    Some(CoordMove { piece_type, source, target: coord(&value["to"]) })
}

/// Get the state of a named position of the suite.
pub fn suite_position(name: &str) -> (Rules, GameState) {
    let (rules, positions) = load_suite();
    let position = positions.into_iter().find(|position| position.name == name);
    (rules, position.expect("the position is in the suite").state)
}
