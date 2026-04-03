set shell := ["zsh", "-cu"]

up:
    docker compose up -d

build:
    docker compose build

logs:
    docker compose logs -f --tail=200

fmt:
    uv run ruff format .

lint:
    uv run ruff check --fix .

type:
    uv run ty check

test:
    uv run pytest -q -rA || { code=$?; [[ $code -eq 5 ]] && echo "No tests collected, skipping." || exit $code; }

check: fmt lint type test
