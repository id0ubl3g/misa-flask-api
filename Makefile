.PHONY: install run deploy stop restart logs backup

install:
	@test -d .venv || python3 -m venv .venv
	@. .venv/bin/activate && pip install -q -r requirements.txt

run:
	docker compose up -d --build --wait

deploy:
	docker compose --profile prod up -d --build --wait

stop:
	docker compose --profile prod down

restart:
	docker compose up -d --build --wait misa-api misa-worker

logs:
	docker compose logs -f misa-api misa-worker

backup:
	@mkdir -p backups
	docker exec misa-mongo sh -c 'mongodump --quiet --archive --gzip -u "$$MONGO_INITDB_ROOT_USERNAME" -p "$$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin' > backups/mongo-$$(date +%Y%m%d-%H%M%S).archive.gz
	@ls -lh backups | tail -1
