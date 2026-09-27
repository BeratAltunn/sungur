PY ?= python3
export PYTHONPATH := src

.PHONY: install weights terrain calibrate stopwatch demo-check-chat check lint test ui-test validate precompute batch demo demo-check web app dev-web docker-up docker-test docker-down

install:
	$(PY) -m pip install -e '.[dev,ui,detector]'
	$(MAKE) weights

# Geçici tespit modeli: Ultralytics'in resmî COCO ağırlıkları (git'e girmez, ~6 MB)
weights:
	mkdir -p models && $(PY) -c "from ultralytics import YOLO; YOLO('models/yolov8n.pt')"

# Ana haritanın 3B arazisi: DEM + uydu dokusu karoları → web/public/terrain (~4 MB, internetsiz demo için)
terrain:
	$(PY) scripts/build_terrain.py

lint:
	$(PY) -m ruff check src tests scripts
	$(PY) -m ruff format --check src tests scripts

test:
	$(PY) -m pytest

check: lint test

# Arayüz duman testi: derlenmiş arayüz + gerçek API, sistem Chrome'uyla (tarayıcı indirmez).
# Playwright/Chrome yoksa testler atlanır; `make check` da bunları çalıştırır ama arayüzü derlemez.
ui-test: web
	$(PY) -m pytest tests/ui

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

# Demo yolu + sohbet soruları (LLM çağırır, ~1 dk; soruları önbelleğe alır)
demo-check-chat:
	$(PY) -m sentinel demo-check --chat

# Kalibrasyon raporu: altın set ↔ sistem + ağırlık duyarlılığı → runs/calibration.md
calibrate:
	$(PY) scripts/calibrate.py

# Kronometre testi özeti (ölçüm: python3 scripts/stopwatch.py manual|system <kare> --who <ad>)
stopwatch:
	$(PY) scripts/stopwatch.py summary

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
