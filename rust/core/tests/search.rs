//! The search of the agents visits the same nodes and finds the same results as the
//! Python agents it replaces, on the positions of the engine benchmark.

mod common;

use common::suite_position;
use hive_core::agents::{
    DepthReport, EvaluationWeights, SEARCH_WIN_SCORE, SearchAlgorithm, SearchConfig,
    SearchObserver, Searcher,
};
use hive_core::engine::{Coord, CoordMove, Piece, PieceType, Player, Rules};

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
    };
    Searcher::new(rules, config).think(&mut state, &mut PanickingObserver);
}
