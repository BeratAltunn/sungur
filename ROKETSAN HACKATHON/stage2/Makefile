PY ?= python3
export PYTHONPATH := src

.PHONY: install check lint test validate precompute batch demo demo-check web app dev-web docker-up docker-test docker-down

install:
	$(PY) -m pip install -e '.[dev]'

lint:
	$(PY) -m ruff check src tests scripts
	$(PY) -m ruff format --check src tests scripts

test:
	$(PY) -m pytest

check: lint test

validate:
	$(PY) scripts/validate_data.py

precompute:
	$(PY) scripts/precompute.py

batch:
	$(PY) -m sentinel batch

demo:
	$(PY) -m sentinel evaluate img_000860

demo-check:
	$(PY) -m sentinel demo-check

web:
	cd web && npm install --no-audit --no-fund && npm run build

# Arayüz + API tek süreçte: http://127.0.0.1:8000
app: web
	$(PY) -m uvicorn sentinel.interfaces.api:app --app-dir src --host 127.0.0.1 --port 8000

# Docker: imajı derleyip arayüzü http://127.0.0.1:8000'de açar (LLM anahtarı .env'den okunur)
docker-up:
	docker compose up --build -d
	@echo "Arayüz: http://127.0.0.1:8000  ·  loglar: docker compose logs -f"

# Testleri imajın içinde çalıştırır (ortamın tekrarlanabilir olduğunu kanıtlar)
docker-test:
	docker compose run --rm --no-deps nobetci python -m pytest -q

docker-down:
	docker compose down

# Arayüz geliştirme: API'yi `make app` ile açık tutun, bu komut :5173'te anlık yenilemeli arayüzü açar
dev-web:
	cd web && npm run dev
