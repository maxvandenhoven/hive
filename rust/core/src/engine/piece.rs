//! Players, piece types and pieces.

use std::fmt;

/// One of the two players of a game.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Player {
    /// The player with the white pieces, who starts by default.
    White,
    /// The player with the black pieces.
    Black,
}

impl Player {
    /// Both players, in the order of their values in the Python package.
    pub const ALL: [Player; 2] = [Player::White, Player::Black];

    /// Get the other player.
    pub const fn opponent(self) -> Self {
        match self {
            Player::White => Player::Black,
            Player::Black => Player::White,
        }
    }

    /// Get the value of the player in the Python `Player` enum, 0 or 1.
    pub const fn index(self) -> usize {
        match self {
            Player::White => 0,
            Player::Black => 1,
        }
    }

    /// Get the player with a value of the Python `Player` enum.
    pub const fn from_index(index: usize) -> Option<Self> {
        match index {
            0 => Some(Player::White),
            1 => Some(Player::Black),
            _ => None,
        }
    }

    /// Get the name of the Python enum member, for example `WHITE`, used in messages.
    pub const fn name(self) -> &'static str {
        match self {
            Player::White => "WHITE",
            Player::Black => "BLACK",
        }
    }
}

/// The type of a piece, which decides how it moves.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum PieceType {
    /// The queen bee: slides one space, and losing it surrounded loses the game.
    Queen,
    /// The beetle: moves one space and may climb onto the hive.
    Beetle,
    /// The grasshopper: jumps in a straight line over at least one piece.
    Grasshopper,
    /// The spider: slides exactly three spaces.
    Spider,
    /// The soldier ant: slides any number of spaces.
    Ant,
}

impl PieceType {
    /// The number of piece types of the base game.
    pub const COUNT: usize = 5;

    /// Every piece type, in the order of their values in the Python package.
    pub const ALL: [PieceType; PieceType::COUNT] = [
        PieceType::Queen,
        PieceType::Beetle,
        PieceType::Grasshopper,
        PieceType::Spider,
        PieceType::Ant,
    ];

    /// Get the value of the type in the Python `PieceType` enum, from 0 to 4.
    pub const fn index(self) -> usize {
        match self {
            PieceType::Queen => 0,
            PieceType::Beetle => 1,
            PieceType::Grasshopper => 2,
            PieceType::Spider => 3,
            PieceType::Ant => 4,
        }
    }

    /// Get the piece type with a value of the Python `PieceType` enum.
    pub const fn from_index(index: usize) -> Option<Self> {
        if index < PieceType::COUNT { Some(PieceType::ALL[index]) } else { None }
    }

    /// Get the name of the Python enum member, for example `ANT`, used in messages.
    pub const fn name(self) -> &'static str {
        match self {
            PieceType::Queen => "QUEEN",
            PieceType::Beetle => "BEETLE",
            PieceType::Grasshopper => "GRASSHOPPER",
            PieceType::Spider => "SPIDER",
            PieceType::Ant => "ANT",
        }
    }

    /// Get the lower case name, for example `ant`, which is also its JSON form.
    pub const fn lower_name(self) -> &'static str {
        match self {
            PieceType::Queen => "queen",
            PieceType::Beetle => "beetle",
            PieceType::Grasshopper => "grasshopper",
            PieceType::Spider => "spider",
            PieceType::Ant => "ant",
        }
    }
}

/// A piece: its owner and type packed into one byte.
#[derive(Clone, Copy, PartialEq, Eq, Hash, Default)]
pub struct Piece(u8);

impl Piece {
    /// The number of distinct pieces, the bound of [`Piece::code`].
    pub const CODE_COUNT: usize = 16;

    /// Create a piece of a type owned by a player.
    pub const fn new(owner: Player, piece_type: PieceType) -> Self {
        Piece(((owner as u8) << 3) | piece_type as u8)
    }

    /// Get the player who owns the piece.
    #[inline]
    pub const fn owner(self) -> Player {
        if self.0 >> 3 == 0 { Player::White } else { Player::Black }
    }

    /// Get the type of the piece.
    #[inline]
    pub const fn piece_type(self) -> PieceType {
        PieceType::ALL[(self.0 & 7) as usize]
    }

    /// Get a number below [`Piece::CODE_COUNT`] that identifies the piece.
    #[inline]
    pub const fn code(self) -> usize {
        self.0 as usize
    }
}

impl fmt::Debug for Piece {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{:?} {:?}", self.owner(), self.piece_type())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pieces_pack_owner_and_type() {
        for owner in Player::ALL {
            for piece_type in PieceType::ALL {
                let piece = Piece::new(owner, piece_type);
                assert_eq!((piece.owner(), piece.piece_type()), (owner, piece_type));
                assert!(piece.code() < Piece::CODE_COUNT);
            }
        }
    }

    #[test]
    fn indices_round_trip() {
        for piece_type in PieceType::ALL {
            assert_eq!(PieceType::from_index(piece_type.index()), Some(piece_type));
        }

        for player in Player::ALL {
            assert_eq!(Player::from_index(player.index()), Some(player));
            assert_eq!(player.opponent().opponent(), player);
        }
    }
}
