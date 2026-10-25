"""Check that Python comments follow the project comment style.

A comment starts with a capital letter and, when it has 5 or more words, ends with a
period. Consecutive full-line comments at the same indentation form one block that is
checked as a single comment, and an empty `#` line starts a new block. Pragmas such as
`# noqa` and `# type: ignore` are skipped.

Usage: `python scripts/tooling/check_comments.py PATH [PATH ...]`, where each path is a
Python file or a directory that is searched recursively.
"""

import io
import re
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path

MIN_WORDS_FOR_PERIOD = 5
PRAGMA_PATTERN = re.compile(r"^(noqa\b|type:|pragma:|fmt:|ruff:|ty:|isort:)")


@dataclass(frozen=True, slots=True)
class CommentViolation:
    """A comment style violation at a line in a file.

    Attributes:
        path: The file containing the violation.
        line: The 1-based line number of the violation.
        message: A description of the violation.
    """

    path: Path
    line: int
    message: str

    def __str__(self) -> str:
        """Format the violation as `path:line: message`."""
        return f"{self.path}:{self.line}: {self.message}"


@dataclass(frozen=True, slots=True)
class CommentToken:
    """A single comment token.

    Attributes:
        line: The 1-based line number of the comment.
        column: The 0-based column of the `#` character.
        text: The comment text without the leading `#` characters and whitespace.
        inline: Whether the comment trails code on the same line.
    """

    line: int
    column: int
    text: str
    inline: bool

    @classmethod
    def from_token(cls, token: tokenize.TokenInfo) -> "CommentToken":
        """Create a comment from a `COMMENT` token."""
        line, column = token.start
        return cls(
            line=line,
            column=column,
            text=token.string.lstrip("#").strip(),
            inline=token.line[:column].strip() != "",
        )

    @property
    def is_exempt(self) -> bool:
        """Whether the comment is a pragma or shebang that is not checked."""
        return bool(PRAGMA_PATTERN.match(self.text)) or (
            self.line == 1 and self.text.startswith("!")
        )

    def continues(self, previous: "CommentToken") -> bool:
        """Whether the comment continues the block that ends with `previous`."""
        return (
            not self.inline
            and not previous.inline
            and self.column == previous.column
            and self.line == previous.line + 1
        )


@dataclass(frozen=True, slots=True)
class CommentBlock:
    """Consecutive comments that are checked as one comment.

    Attributes:
        comments: The comments in the block, in source order.
    """

    comments: tuple[CommentToken, ...]

    @classmethod
    def from_source(cls, source: str) -> list["CommentBlock"]:
        """Group the comments in `source` into blocks.

        Args:
            source: Python source code.

        Returns:
            The comment blocks in source order, without exempt comments.

        Raises:
            tokenize.TokenError: If the source cannot be tokenized.
            SyntaxError: If the source contains invalid indentation.
        """
        blocks: list[list[CommentToken]] = []
        previous: CommentToken | None = None
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)

        for token in tokens:
            if token.type != tokenize.COMMENT:
                continue

            comment = CommentToken.from_token(token)

            if comment.is_exempt or not comment.text:
                previous = None
                continue

            if previous is not None and comment.continues(previous):
                blocks[-1].append(comment)
            else:
                blocks.append([comment])

            previous = comment

        return [cls(tuple(block)) for block in blocks]

    @property
    def text(self) -> str:
        """The text of all comments in the block, joined by spaces."""
        return " ".join(comment.text for comment in self.comments)

    def violations(self, path: Path) -> list[CommentViolation]:
        """Check the block against the comment style rules.

        Args:
            path: The file containing the block, used in the reported violations.

        Returns:
            The violations found in the block, if any.
        """
        words = self.text.split()
        violations = []

        if words[0][0].islower() and "://" not in words[0]:
            violations.append(
                CommentViolation(
                    path=path,
                    line=self.comments[0].line,
                    message="comment should start with a capital letter",
                )
            )

        if (
            len(words) >= MIN_WORDS_FOR_PERIOD
            and not self.text.endswith(".")
            and "://" not in words[-1]
        ):
            violations.append(
                CommentViolation(
                    path=path,
                    line=self.comments[-1].line,
                    message=f"comment of {MIN_WORDS_FOR_PERIOD} or more words should end "
                    "with a period",
                )
            )

        return violations


def check_file(path: Path) -> list[CommentViolation]:
    """Check all comments in a Python file.

    Args:
        path: The Python file to check.

    Returns:
        The violations found in the file, or a single violation if it cannot be tokenized.
    """
    try:
        blocks = CommentBlock.from_source(path.read_text())
    except (tokenize.TokenError, SyntaxError) as error:
        return [
            CommentViolation(path=path, line=1, message=f"could not tokenize: {error}")
        ]

    return [violation for block in blocks for violation in block.violations(path)]


def main(argv: list[str] | None = None) -> int:
    """Check the comments in the given files and directories.

    Args:
        argv: Paths to check. Defaults to the command line arguments.

    Returns:
        1 if any violations were found, otherwise 0.
    """
    paths = [Path(arg) for arg in (sys.argv[1:] if argv is None else argv)]
    files = sorted(
        file
        for path in paths
        for file in (path.rglob("*.py") if path.is_dir() else [path])
        if file.suffix == ".py"
    )
    violations = [violation for file in files for violation in check_file(file)]

    for violation in violations:
        sys.stdout.write(f"{violation}\n")

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
