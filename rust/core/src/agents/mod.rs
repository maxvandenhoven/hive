//! The search of the agents: evaluation and iterative deepening tree search.
//!
//! The agents themselves are Python classes (`hive.agents`), which take their params,
//! build a [`Searcher`] and hand it the turn of each decision.

pub mod evaluation;
pub mod search;

pub use evaluation::{EvaluationWeights, Evaluator, PIECE_VALUES};
pub use search::{
    DepthReport, SEARCH_WIN_SCORE, SearchAlgorithm, SearchConfig, SearchObserver,
    Searcher,
};
