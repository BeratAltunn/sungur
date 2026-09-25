# NÖBETÇİ: web arayüzü + API tek imajda.
# Derleme bağlamı "ROKETSAN HACKATHON/" klasörüdür (stage2 + stage2_dev_data gerekir):
#   docker compose -f stage2/docker-compose.yml up --build
# Not: Docker içinde Apple GPU (MPS) yoktur; YOLO CPU'da çalışır. Tespitler önbellekte olduğu için
# demo akışı etkilenmez, yalnızca "canlı yeniden değerlendir" birkaç saniye sürer.

# ---------------------------------------------------------------- 1) arayüz derlemesi
FROM node:22-slim AS web
WORKDIR /web
COPY stage2/web/package.json stage2/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY stage2/web/ ./
RUN npm run build

# ---------------------------------------------------------------- 2) Python çalışma ortamı
FROM python:3.12-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/stage2/src \
    YOLO_CONFIG_DIR=/tmp/ultralytics \
    SENTINEL_DATA_DIR=/app/stage2_dev_data

# OpenCV (ultralytics bağımlılığı) için gereken sistem kütüphaneleri
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app/stage2

# Bağımlılıklar kod değişikliklerinden ayrı katmanda: CPU'ya özel torch (CUDA'lı sürümden ~2 GB küçük)
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision
COPY stage2/pyproject.toml ./
RUN python - <<'EOF' > /tmp/requirements.txt
import tomllib
p = tomllib.load(open("pyproject.toml", "rb"))["project"]
deps = p["dependencies"] + [d for extra in ("ui", "detector", "dev") for d in p["optional-dependencies"][extra]]
print("\n".join(deps))
EOF
RUN pip install -r /tmp/requirements.txt

# Geçici tespit modeli: Ultralytics'in resmî COCO ağırlıkları (depoda tutulmuyor)
RUN mkdir -p models \
 && python -c "from ultralytics import YOLO; YOLO('models/yolov8n.pt')" \
 && test -f models/yolov8n.pt

# Uygulama kodu, veri, önbellek ve derlenmiş arayüz
COPY stage2_dev_data /app/stage2_dev_data
COPY stage2/ ./
COPY --from=web /web/dist ./web/dist

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"

CMD ["python", "-m", "uvicorn", "sentinel.interfaces.api:app", "--host", "0.0.0.0", "--port", "8000"]
