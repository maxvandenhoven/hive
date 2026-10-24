# hive

A Python engine for the board game Hive, with search agents and (planned) a web app that
tracks physical games at the table, with manual or camera-based move entry. See
[`docs/plans/README.md`](docs/plans/README.md) for the project plan.

## Development

Requires [`uv`](https://docs.astral.sh/uv/) and Python 3.13.

```
make sync           # install all dependencies, extras and dev tools
make check          # format, lint and type check
make test           # run the tests with coverage
make install-hooks  # install pre-commit hooks
uv run hive --version
```
