# Every target is a one-liner delegating to uv, so the same work runs without make.
.PHONY: dev serve test seed eval lint

# dev runs both processes once the simulator lands in phase 5. Until then, use `make serve`.
dev:
	uv run python -m simulator.app

serve:
	uv run uvicorn lifepilot.server:app --port 8931

test:
	uv run pytest

seed:
	uv run python -m eval.generate --seed-db

eval:
	uv run python -m eval.run $(if $(EXP),--exp $(EXP),)

lint:
	uv run ruff check .
