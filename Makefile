# Every target is a one-liner delegating to uv, so the same work runs without make.
.PHONY: dev serve seed-demo test seed eval lint

# Two processes. Run `make serve` in one terminal and `make dev` in another.
# The demo uses a local SQLite file: Neon is ~1.9s per tool call from India, local is ~35ms.
dev:
	uv run uvicorn simulator.app:app --port 8000

serve:
	DATABASE_URL=sqlite+pysqlite:///demo.db uv run uvicorn lifepilot.server:app --port 8931

seed-demo:
	DATABASE_URL=sqlite+pysqlite:///demo.db uv run python -m eval.generate --seed-db

test:
	uv run pytest

seed:
	uv run python -m eval.generate --seed-db

eval:
	uv run python -m eval.run $(if $(EXP),--exp $(EXP),)

lint:
	uv run ruff check .
