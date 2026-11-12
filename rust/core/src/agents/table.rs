//! The transposition table: search results of positions, reused when a position recurs.

use crate::agents::search::SEARCH_WIN_SCORE;
use crate::engine::Move;

/// What a stored score says about the true score of its position.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Default)]
pub enum TableBound {
    /// The score is exact.
    #[default]
    Exact,
    /// The true score is at least the stored score (the search failed high).
    Lower,
    /// The true score is at most the stored score (the search failed low).
    Upper,
}

/// One stored search result.
#[derive(Clone, Copy, Debug, Default)]
pub struct TableEntry {
    /// The key of the position: its Zobrist hash and ply key.
    pub key: u64,
    /// The score, with win and loss scores counted from the position (see
    /// [`to_table_score`]).
    pub score: f64,
    /// The bits of the best move found, zero if none.
    pub best: u32,
    /// The remaining depth the position was searched to.
    pub depth: u8,
    /// What the score says about the true score.
    pub bound: TableBound,
    /// Whether the search below the position stopped at the depth limit somewhere.
    pub cutoff: bool,
}

impl TableEntry {
    /// Get the best move found, if any.
    pub fn best_move(&self) -> Option<Move> {
        Move::from_stored_bits(self.best)
    }
}

/// A fixed-size table of search results, one per slot, indexed by the low bits of the
/// key. A new result replaces the old one of its slot unless the old one is of the same
/// position and searched deeper.
#[derive(Clone, Debug)]
pub struct TranspositionTable {
    /// The slots; empty slots have key zero and depth zero.
    entries: Vec<TableEntry>,
    /// The mask that maps a key to its slot.
    mask: u64,
}

impl TranspositionTable {
    /// Create a table of at most `megabytes` MB (a power of two number of slots), or an
    /// empty table that stores nothing when `megabytes` is zero.
    pub fn new(megabytes: usize) -> Self {
        let slots = megabytes * 1024 * 1024 / size_of::<TableEntry>();
        let slots = if slots == 0 { 0 } else { 1 << slots.ilog2() };
        TranspositionTable {
            entries: vec![TableEntry::default(); slots],
            mask: (slots as u64).saturating_sub(1),
        }
    }

    /// Forget every stored result.
    pub fn clear(&mut self) {
        self.entries.fill(TableEntry::default());
    }

    /// Get the stored result of a position, if its slot holds it.
    #[inline]
    pub fn probe(&self, key: u64) -> Option<TableEntry> {
        let index = usize::try_from(key & self.mask).ok()?;
        self.entries.get(index).copied().filter(|entry| entry.key == key && key != 0)
    }

    /// Store a search result, unless the slot holds a deeper result of the same position.
    #[inline]
    pub fn store(&mut self, entry: TableEntry) {
        let Ok(index) = usize::try_from(entry.key & self.mask) else { return };
        let Some(slot) = self.entries.get_mut(index) else { return };

        if slot.key != entry.key || entry.depth >= slot.depth {
            *slot = entry;
        }
    }
}

/// The scores above this are wins (and below its negation losses), whose distance to the
/// end of the game is in the score.
const WIN_THRESHOLD: f64 = SEARCH_WIN_SCORE - 10_000.0;

/// Convert a score counted from the root to one counted from the position at `ply`, so a
/// win stored in one search means the same in another.
pub fn to_table_score(score: f64, ply: u32) -> f64 {
    if score > WIN_THRESHOLD {
        score + f64::from(ply)
    } else if score < -WIN_THRESHOLD {
        score - f64::from(ply)
    } else {
        score
    }
}

/// Undo [`to_table_score`] for a position at `ply`.
pub fn from_table_score(score: f64, ply: u32) -> f64 {
    if score > WIN_THRESHOLD {
        score - f64::from(ply)
    } else if score < -WIN_THRESHOLD {
        score + f64::from(ply)
    } else {
        score
    }
}
