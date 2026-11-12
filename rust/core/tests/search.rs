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
) -> (Searcher, Recorder) {
    let config =
        SearchConfig { algorithm, depth: Some(depth), weights, stop_check_interval: 32 };
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
        decide(rules, &mut state.clone(), SearchAlgorithm::Negamax, 3, weights);
    let (_, minimax) =
        decide(rules, &mut state.clone(), SearchAlgorithm::Minimax, 3, weights);

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
    let (searcher, _) = decide(rules, &mut state, SearchAlgorithm::Negamax, 2, weights);
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
