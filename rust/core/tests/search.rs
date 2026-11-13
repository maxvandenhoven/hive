//! The search of the agents visits the same nodes and finds the same results as the
//! Python agents it replaces, on the positions of the engine benchmark.

mod common;

use common::{parse_move, suite_position};
use hive_core::agents::{
    DepthReport, EvaluationWeights, SEARCH_WIN_SCORE, SearchAlgorithm, SearchConfig,
    SearchObserver, Searcher,
};
use hive_core::engine::{
    Coord, CoordMove, GameState, Piece, PieceType, Player, Rules, RulesConfig,
};

/// An observer that never stops and keeps every report.
#[derive(Default)]
struct Recorder {
    /// The reports received, one per completed depth.
    reports: Vec<DepthReport>,
    /// The number of stop checks.
    checks: u64,
}

impl SearchObserver for Recorder {
    fn should_stop(&mut self) -> bool {
        self.checks += 1;
        false
    }

    fn report(&mut self, report: &DepthReport) {
        self.reports.push(report.clone());
    }
}

/// Run one decision and return the observer.
fn decide(
    rules: Rules,
    state: &mut hive_core::engine::GameState,
    algorithm: SearchAlgorithm,
    depth: u32,
    weights: EvaluationWeights,
    alpha_beta: bool,
) -> (Searcher, Recorder) {
    let config = SearchConfig {
        algorithm,
        depth: Some(depth),
        weights,
        stop_check_interval: 32,
        alpha_beta,
        table_megabytes: 16,
        aspiration_window: 0.0,
        threads: 1,
        principal_variation_search: false,
        table_deeper_hits: false,
        late_move_reductions: 0,
        null_move_reduction: 0,
        queen_attack_ordering: false,
        queen_threat_extension: false,
        repetition_draws: false,
        forced_move_extension: false,
    };
    let mut searcher = Searcher::new(rules, config);
    let mut recorder = Recorder::default();
    let before = state.clone();
    searcher.think(state, &mut recorder);
    assert_eq!(*state, before, "the search restores the state");
    (searcher, recorder)
}

#[test]
fn negamax_visits_the_nodes_of_the_python_agent() {
    let (rules, mut state) = suite_position("long_hive");
    let (searcher, recorder) = decide(
        rules,
        &mut state,
        SearchAlgorithm::Negamax,
        3,
        EvaluationWeights::default(),
        false,
    );

    assert_eq!(searcher.nodes(), 153_360);
    assert_eq!(
        recorder.reports.iter().map(|report| report.depth).collect::<Vec<_>>(),
        [1, 2, 3]
    );
    assert!(recorder.reports.last().is_some_and(|report| report.is_final));
}

#[test]
fn minimax_agrees_with_negamax() {
    let (rules, state) = suite_position("long_hive");
    let weights = EvaluationWeights {
        positioning: 1.0,
        material_on_board: 1.0,
        ..Default::default()
    };
    let (_, negamax) =
        decide(rules, &mut state.clone(), SearchAlgorithm::Negamax, 3, weights, false);
    let (_, minimax) =
        decide(rules, &mut state.clone(), SearchAlgorithm::Minimax, 3, weights, false);

    assert_eq!(
        negamax.reports,
        minimax
            .reports
            .iter()
            .map(|report| DepthReport {
                elapsed_seconds: negamax.reports[(report.depth - 1) as usize]
                    .elapsed_seconds,
                ..report.clone()
            })
            .collect::<Vec<_>>()
    );
}

#[test]
fn mobility_visits_the_nodes_of_the_python_agent() {
    let (rules, mut state) = suite_position("ant_moves");
    let weights = EvaluationWeights { mobility: 1.0, ..Default::default() };
    let (searcher, _) =
        decide(rules, &mut state, SearchAlgorithm::Negamax, 2, weights, false);
    assert_eq!(searcher.nodes(), 946);
}

#[test]
fn a_forced_win_is_final_at_depth_one() {
    // The black queen at (0, 0) has five occupied neighbours, and the white ant at (2, 0)
    // can slide around the white grasshopper to the last free neighbour (0, 1).
    let white = |piece_type| Piece::new(Player::White, piece_type);
    let black = |piece_type| Piece::new(Player::Black, piece_type);
    let stacks = [
        ((0, 0), black(PieceType::Queen)),
        ((1, 0), white(PieceType::Grasshopper)),
        ((1, -1), white(PieceType::Queen)),
        ((0, -1), white(PieceType::Beetle)),
        ((-1, 0), black(PieceType::Grasshopper)),
        ((-1, 1), black(PieceType::Spider)),
        ((-2, 1), black(PieceType::Ant)),
        ((2, 0), white(PieceType::Ant)),
    ]
    .map(|((q, r), piece)| (Coord::new(q, r), vec![piece]));
    let rules = Rules::default();
    let mut state =
        rules.from_board(&stacks, Player::White, None).expect("a valid board");
    let config = SearchConfig {
        algorithm: SearchAlgorithm::Negamax,
        depth: None,
        weights: EvaluationWeights::default(),
        stop_check_interval: 32,
        alpha_beta: true,
        table_megabytes: 16,
        aspiration_window: 0.0,
        threads: 1,
        principal_variation_search: false,
        table_deeper_hits: false,
        late_move_reductions: 0,
        null_move_reduction: 0,
        queen_attack_ordering: false,
        queen_threat_extension: false,
        repetition_draws: false,
        forced_move_extension: false,
    };
    let mut recorder = Recorder::default();
    Searcher::new(rules, config).think(&mut state, &mut recorder);

    let report = recorder.reports.last().expect("one depth");
    let winning_move = CoordMove {
        piece_type: PieceType::Ant,
        source: Some(Coord::new(2, 0)),
        target: Coord::new(0, 1),
    };
    assert_eq!((report.depth, report.score), (1, SEARCH_WIN_SCORE - 1.0));
    assert_eq!(report.principal_variation, [Some(winning_move)]);
    assert!(report.is_final);
}

#[test]
fn alpha_beta_finds_the_scores_of_the_full_search_with_fewer_nodes() {
    let weights = EvaluationWeights {
        positioning: 0.5,
        material_on_board: 0.1,
        ..Default::default()
    };

    for (name, depth) in
        [("long_hive", 3), ("ant_moves", 3), ("tournament_opening", 4), ("long_hive", 4)]
    {
        let (rules, state) = suite_position(name);

        for algorithm in [SearchAlgorithm::Negamax, SearchAlgorithm::Minimax] {
            let (full, full_reports) =
                decide(rules, &mut state.clone(), algorithm, depth, weights, false);
            let (pruned, pruned_reports) =
                decide(rules, &mut state.clone(), algorithm, depth, weights, true);
            let scores = |reports: &Recorder| {
                reports.reports.iter().map(|report| report.score).collect::<Vec<_>>()
            };

            assert_eq!(
                scores(&pruned_reports),
                scores(&full_reports),
                "{name} depth {depth}"
            );
            assert!(
                pruned.nodes() < full.nodes(),
                "{name}: {} < {}",
                pruned.nodes(),
                full.nodes()
            );
        }
    }
}

#[test]
fn negamax_orders_its_moves_better_than_minimax() {
    // Both prune with alpha-beta to the same scores; negamax also uses the transposition
    // table, killer moves and the history, so it visits fewer nodes.
    let (rules, state) = suite_position("long_hive");
    let weights = EvaluationWeights::default();
    let (negamax, negamax_reports) =
        decide(rules, &mut state.clone(), SearchAlgorithm::Negamax, 4, weights, true);
    let (minimax, minimax_reports) =
        decide(rules, &mut state.clone(), SearchAlgorithm::Minimax, 4, weights, true);
    let scores = |recorder: &Recorder| {
        recorder.reports.iter().map(|report| report.score).collect::<Vec<_>>()
    };

    assert_eq!(scores(&negamax_reports), scores(&minimax_reports));
    assert!(negamax.nodes() < minimax.nodes());
}

#[test]
fn aspiration_and_helpers_preserve_scores_and_state_with_a_warm_table() {
    for name in ["long_hive", "ant_moves", "tournament_opening"] {
        let (rules, state) = suite_position(name);
        let weights = EvaluationWeights {
            positioning: 0.5,
            material_on_board: 0.1,
            queen_danger: 0.1,
            queen_escape: 0.1,
            pinned_material: 0.025,
            free_ants: 0.25,
            beetle_control: 0.5,
            tempo: 0.05,
            mobile_queen: 0.2,
            mobile_beetle: 0.1,
            mobile_grasshopper: 0.1,
            mobile_spider: 0.1,
            mobile_ant: 0.3,
            placement_cells: 0.02,
            ..Default::default()
        };
        let (_, reference) = decide(
            rules,
            &mut state.clone(),
            SearchAlgorithm::Negamax,
            3,
            weights,
            false,
        );
        let expected: Vec<_> = reference.reports.iter().map(|r| r.score).collect();

        for threads in [1, 2, 4] {
            let config = SearchConfig {
                algorithm: SearchAlgorithm::Negamax,
                depth: Some(3),
                weights,
                stop_check_interval: 32,
                alpha_beta: true,
                table_megabytes: 1,
                aspiration_window: 0.01,
                threads,
                principal_variation_search: true,
                table_deeper_hits: false,
                late_move_reductions: 0,
                null_move_reduction: 0,
                queen_attack_ordering: false,
                queen_threat_extension: false,
                repetition_draws: false,
                forced_move_extension: false,
            };
            let mut searcher = Searcher::new(rules, config);

            for _ in 0..2 {
                let mut position = state.clone();
                let mut recorder = Recorder::default();
                searcher.think(&mut position, &mut recorder);
                assert_eq!(position, state);
                let scores: Vec<_> = recorder.reports.iter().map(|r| r.score).collect();
                assert_eq!(scores, expected, "{name}, {threads} threads");

                for report in &recorder.reports {
                    let mut replay = state.clone();
                    for mv in &report.principal_variation {
                        let mut legal = Vec::new();
                        rules.legal_moves(&mut replay, &mut legal);
                        assert!(mv.map_or(legal.is_empty(), |mv| {
                            legal.iter().any(|&packed| replay.decode(packed) == mv)
                        }));
                        replay.apply_coord_move(*mv).expect("legal variation");
                    }
                }
            }
        }
    }
}

/// Stops during a depth, including while helpers are still searching.
struct StopObserver {
    /// Remaining checks until cancellation.
    remaining: u32,
    /// Completed reports.
    reports: Vec<DepthReport>,
}

impl SearchObserver for StopObserver {
    fn should_stop(&mut self) -> bool {
        self.remaining = self.remaining.saturating_sub(1);
        self.remaining == 0
    }
    fn report(&mut self, report: &DepthReport) {
        self.reports.push(report.clone());
    }
}

#[test]
fn cancellation_joins_helpers_and_restores_the_position() {
    let (rules, mut state) = suite_position("long_hive");
    let before = state.clone();
    let config = SearchConfig {
        algorithm: SearchAlgorithm::Negamax,
        depth: None,
        weights: EvaluationWeights::default(),
        stop_check_interval: 1,
        alpha_beta: true,
        table_megabytes: 1,
        aspiration_window: 0.01,
        threads: 4,
        principal_variation_search: true,
        table_deeper_hits: false,
        late_move_reductions: 0,
        null_move_reduction: 0,
        queen_attack_ordering: false,
        queen_threat_extension: false,
        repetition_draws: false,
        forced_move_extension: false,
    };
    let mut searcher = Searcher::new(rules, config);
    let mut observer = StopObserver { remaining: 200, reports: Vec::new() };
    searcher.think(&mut state, &mut observer);
    assert_eq!(state, before);
    assert!(observer.reports.iter().all(|report| !report.is_final));
    searcher.clear();
}

/// A failing client must not leave scoped helpers running indefinitely.
struct PanickingObserver;

impl SearchObserver for PanickingObserver {
    fn should_stop(&mut self) -> bool {
        panic!("client observer failed");
    }

    fn report(&mut self, _report: &DepthReport) {}
}

#[test]
#[should_panic(expected = "client observer failed")]
fn observer_panic_cancels_helpers_before_joining() {
    let (rules, mut state) = suite_position("long_hive");
    let config = SearchConfig {
        algorithm: SearchAlgorithm::Negamax,
        depth: None,
        weights: EvaluationWeights::default(),
        stop_check_interval: 32,
        alpha_beta: true,
        table_megabytes: 1,
        aspiration_window: 0.5,
        threads: 2,
        principal_variation_search: true,
        table_deeper_hits: false,
        late_move_reductions: 0,
        null_move_reduction: 0,
        queen_attack_ordering: false,
        queen_threat_extension: false,
        repetition_draws: false,
        forced_move_extension: false,
    };
    Searcher::new(rules, config).think(&mut state, &mut PanickingObserver);
}

#[test]
fn search_refinements_restore_the_state_and_visit_fewer_nodes() {
    for name in ["long_hive", "ant_moves", "tournament_opening"] {
        let (rules, state) = suite_position(name);
        let weights = EvaluationWeights {
            queen_danger: 0.1,
            mobile_ant: 0.3,
            placement_cells: 0.02,
            ..Default::default()
        };
        let plain = SearchConfig {
            principal_variation_search: true,
            ..SearchConfig::new(SearchAlgorithm::Negamax, Some(5), weights)
        };
        let refined = SearchConfig {
            table_deeper_hits: true,
            late_move_reductions: 3,
            null_move_reduction: 2,
            queen_attack_ordering: true,
            queen_threat_extension: true,
            repetition_draws: true,
            ..plain
        };
        let mut nodes = Vec::new();

        for (config, threads) in [(plain, 1), (refined, 1), (refined, 2)] {
            let mut searcher = Searcher::new(rules, SearchConfig { threads, ..config });
            let mut position = state.clone();
            let mut recorder = Recorder::default();
            searcher.think(&mut position, &mut recorder);
            assert_eq!(position, state, "{name}");
            let last = recorder.reports.last().expect("a completed depth");
            let mut replay = state.clone();

            for mv in &last.principal_variation {
                replay.apply_coord_move(*mv).expect("legal variation");
            }

            nodes.push(searcher.nodes());
        }

        assert!(nodes[1] < nodes[0], "{name}: {nodes:?}");
    }
}

#[test]
fn repetition_draws_change_the_search_and_restore_the_state() {
    let (rules, state) = suite_position("long_hive");
    let weights = EvaluationWeights { mobile_ant: 0.3, ..Default::default() };
    let plain = SearchConfig {
        principal_variation_search: true,
        ..SearchConfig::new(SearchAlgorithm::Negamax, Some(6), weights)
    };
    let mut nodes = Vec::new();

    for repetition_draws in [false, true] {
        let config = SearchConfig { repetition_draws, ..plain };
        let mut searcher = Searcher::new(rules, config);
        let mut position = state.clone();
        searcher.think(&mut position, &mut Recorder::default());
        assert_eq!(position, state);
        nodes.push(searcher.nodes());
    }

    assert_ne!(nodes[0], nodes[1], "repeated positions end the line early");
}

#[test]
fn repetition_draws_remember_the_decisions_of_the_game() {
    let (rules, start) = suite_position("long_hive");
    let reverse = |mv: CoordMove| CoordMove {
        source: Some(mv.target),
        target: mv.source.expect("a movement"),
        ..mv
    };
    let mut pair = None;
    let mut state = start.clone();

    'search: for first in rules.movement_coord_moves(&mut state.clone()) {
        let mut after_first = state.clone();
        after_first.apply_coord_move(Some(first)).expect("legal move");

        for second in rules.movement_coord_moves(&mut after_first.clone()) {
            let mut back = after_first.clone();
            back.apply_coord_move(Some(second)).expect("legal move");
            let mut returns = false;

            if rules.movement_coord_moves(&mut back).contains(&reverse(first)) {
                back.apply_coord_move(Some(reverse(first))).expect("legal move");
                returns =
                    rules.movement_coord_moves(&mut back).contains(&reverse(second));
                back.apply_coord_move(Some(reverse(second))).expect("legal move");
            }

            if returns && back.hash() == start.hash() {
                pair = Some((first, second));
                break 'search;
            }
        }
    }

    let (first, second) = pair.expect("two reversible moves");
    state.apply_coord_move(Some(first)).expect("legal move");
    state.apply_coord_move(Some(second)).expect("legal move");
    let config = SearchConfig {
        repetition_draws: true,
        alpha_beta: false,
        table_megabytes: 0,
        ..SearchConfig::new(
            SearchAlgorithm::Negamax,
            Some(3),
            EvaluationWeights::default(),
        )
    };
    let mut fresh = Searcher::new(rules, config);
    fresh.think(&mut state.clone(), &mut Recorder::default());
    let mut playing = Searcher::new(rules, config);
    playing.think(&mut start.clone(), &mut Recorder::default());
    playing.think(&mut state.clone(), &mut Recorder::default());

    assert!(playing.nodes() < fresh.nodes(), "the start position recurs as a draw");
}

/// Get the last position of a capped game in which Black is frozen and only passes.
fn frozen_opponent() -> (Rules, GameState) {
    let path = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../tests/data/search/frozen_opponent.json");
    let game: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(path).expect("the game exists"))
            .expect("JSON");
    let rules = Rules::new(RulesConfig::default()).expect("the default rules are valid");
    let mut state = rules.create_initial_state();

    for mv in game["moves"].as_array().expect("moves") {
        rules.apply_checked_move(&mut state, parse_move(mv)).expect("a legal move");
    }

    (rules, state)
}

#[test]
fn forced_move_extension_searches_the_moves_against_a_frozen_opponent_deeper() {
    let (rules, state) = frozen_opponent();
    let config = SearchConfig {
        principal_variation_search: true,
        ..SearchConfig::new(
            SearchAlgorithm::Negamax,
            Some(4),
            EvaluationWeights::default(),
        )
    };
    let mut nodes = Vec::new();

    for forced_move_extension in [false, true] {
        let mut searcher =
            Searcher::new(rules, SearchConfig { forced_move_extension, ..config });
        let mut position = state.clone();
        searcher.think(&mut position, &mut Recorder::default());
        assert_eq!(position, state);
        nodes.push(searcher.nodes());
    }

    assert!(nodes[1] > nodes[0], "{nodes:?}");
}
