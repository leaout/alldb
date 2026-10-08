.PHONY: up down logs test test-docker

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f alldb

test:
	cd backend && python -m pytest -q

test-docker:
	docker build --target runtime -t alldb:test .
	docker run --rm --entrypoint python alldb:test -c "from app.main import app; print(app.title, app.version)"

