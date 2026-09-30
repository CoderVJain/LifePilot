# Every target is a one-liner delegating to uv, so the same work runs without make.
.PHONY: dev test seed eval lint

dev:
	uv run python -m simulator.app

test:
	uv run pytest

seed:
	uv run python -m eval.generate --seed-db

eval:
	uv run python -m eval.run $(if $(EXP),--exp $(EXP),)

lint:
	uv run ruff check .
