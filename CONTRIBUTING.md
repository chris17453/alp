# Contributing

This is an experiment; ideas are as welcome as patches.

- `uv sync --extra dev`, then `uv run pytest -q` and `uv run ruff check src tests examples`.
- Regenerate the example set with `sh examples/make_examples.sh` when rendering changes; commit the outputs.
- SIDs and the ALP/T form are the contract: a change that alters the SID of an existing composition is a version bump of the inventory, not a patch.
- The script is rendering only — it must never affect a hash.
- Design reasoning lives in `docs/script-design-notes.md`; if you change how a class is drawn, update the table in the README and the language reference.
