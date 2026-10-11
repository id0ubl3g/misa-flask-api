.PHONY: install run stop restart logs

install:
	@test -d .venv || python3 -m venv .venv
	@. .venv/bin/activate && pip install -q -r requirements.txt

run:
	docker compose up -d --build --wait

stop:
	docker compose down

restart:
	docker compose up -d --build --wait misa-api misa-worker

logs:
	docker compose logs -f misa-api misa-worker
