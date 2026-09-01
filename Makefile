.PHONY: setup test lint examples chart clean
setup:      ; uv sync --extra dev
test:       ; uv run pytest -q
lint:       ; uv run ruff check src tests examples
examples:   ; sh examples/make_examples.sh
chart:      ; uv run alp chart --png chart.png && uv run alp key --png key.png
clean:      ; rm -rf .pytest_cache .ruff_cache dist build *.egg-info
