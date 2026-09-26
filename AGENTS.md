# AGENTS.md — NÖBETÇİ (ROKETSAN Level Up AI Hackathon, Aşama 2)

Bu dosya, bu depoda çalışan LLM agent'ları (Claude Code, Codex, Cursor, Copilot …) ve onları kullanan ekip üyeleri içindir. Amaç: projeyi sıfırdan ayağa kaldırmak, LLM'i (Evren) bağlamak ve mimariyi bozmadan geliştirme yapmak.

> **Agent'a not:** Bu dosyadaki "Kesin kurallar" bölümü projenin tasarım sözleşmesidir; kullanıcı açıkça istemedikçe ihlal etme. Kullanıcı adına şart/sözleşme kabul etme, API anahtarı üretme ya da anahtarı bir dosyaya yazıp commit etme; bunları kullanıcıya yaptır.

---

## 1. Proje tek paragrafta

NÖBETÇİ, bir askerî üssü çevreleyen 8 bölgeden gelen drone karelerini risk sırasına dizen bir ajandır. Her kare için 6 adım çalışır: **(1) araç tespiti (YOLO) → (2) pikselden koordinata → (3) araçları 2 saatlik hareket izleriyle eşleme + kinematik (hız, yaklaşma, duraklama, ETA) → (4) saha raporlarını raporun *kendi saatindeki* duruma göre doğrulama → (5) açıklanabilir kural tabanlı risk skoru + taban kuralları → (6) LLM'in her sayısı kanıtla kontrol edilen (grounding) Türkçe brief yazması.** 1–5 deterministik Python'dur; LLM hesap yapmaz, yalnızca yazar. Ayrıca araç çağıran bir sohbet paneli ve operatör için bir web arayüzü (triage kuyruğu + kare detayı + zaman kaydırıcısı) vardır.

**Değerlendirme kriterleri:** Kaggle skoru (Aşama 1 tespit modeli) %20 · teknik kalite ve mimari %15 · problemin önemi ve çözümün sağladığı iş değeri %20 · çalışan ürün ortaya koyabilme %20 · ürün düşüncesi ve kullanıcı deneyimi %20 · sunum ve demo %5. Resmî veri paketi, Kaggle ekibinin modeli ve hackathon GLM anahtarı sonra gelecek; sistem şu an dev verisi, geçici YOLO modeli ve Evren üzerindeki glm-5.3 ile çalışıyor.

Ürün/tasarım gerekçeleri: `ROKETSAN HACKATHON/PROJECT_DESIGN.md` · modül ayrıntıları: `ROKETSAN HACKATHON/STAGE2_ARCHITECTURE.md` · kullanım: `ROKETSAN HACKATHON/stage2/README.md`.

## 2. Depo haritası

> Klasör adında **boşluk** var: `ROKETSAN HACKATHON`. Kabuk komutlarında yolu her zaman tırnak içine al.

```
sungur/                                   ← git kökü
  AGENTS.md  CLAUDE.md  .gitignore
  ROKETSAN HACKATHON/
    PROJECT_DESIGN.md  STAGE2_ARCHITECTURE.md
    stage2_dev_data/                      ← dev verisi (40 kare, 226 track, 137 rapor) — depoda
    dataset/                              ← Kaggle verisi (1,8 GB) — GIT'E GİRMEZ, gerekmez
    stage2/                               ← UYGULAMA (tüm komutlar buradan çalışır)
      config.yaml                         ← tüm eşikler, ağırlıklar, model seçimi
      .env.example → .env                 ← LLM anahtarı (git'e girmez)
      Makefile  Dockerfile  docker-compose.yml  pyproject.toml
      src/sentinel/
        domain/models.py                  ← tüm pydantic modeller (sözleşme)
        data/                             ← dosya okuma + Repository (zaman ızgarası, uzay-zaman sorguları)
        perception/                       ← Detector arayüzü: ultralytics | callable (Kaggle) | oracle (test) | cache
        geo/  tracking/  reports/  risk/  ← adım 2–5
        agent/                            ← LLM istemcisi, analyst, grounding, şablon brief, sohbet, araçlar, prompts/*.md
        pipeline.py                       ← evaluate(image_id) -> EvidencePacket (adım 1–5)
        service.py                        ← SentinelService: UI/CLI/API'nin TEK giriş noktası
        interfaces/{api.py, cli.py}       ← FastAPI REST + CLI
      web/                                ← React + Vite + TypeScript + MapLibre arayüzü
        src/pages  src/components  src/lib
      tests/{unit,contract,security,integration}/
      scripts/                            ← validate_data, precompute, compare_detectors, calibrate, stopwatch
      calibration/                        ← kör etiketler (labels/*.jsonl) + kronometre (stopwatch.csv) — depoda
      DEMO.md                             ← canlı demo akışı ve B planları
      cache/{detections,llm}/             ← demo önbelleği — depoda (internetsiz/LLM'siz demo için)
      runs/                               ← trace.jsonl, decisions.jsonl — git'e girmez
      models/                             ← YOLO ağırlıkları — git'e girmez, `make weights` indirir
```

## 3. Ayağa kaldırma

Tüm komutlar `ROKETSAN HACKATHON/stage2` içinden çalışır:

```bash
cd "ROKETSAN HACKATHON/stage2"
```

### Yol A — Docker (önerilen; ekip ve yedek laptop)

Gereken: Docker Desktop (Compose v2.24+).

```bash
cp .env.example .env            # anahtarı 4. bölümdeki gibi doldur; boş kalırsa sistem şablon brief ile çalışır
docker compose up --build -d    # ilk derleme birkaç dakika (~2,6 GB imaj)
```

Arayüz: http://127.0.0.1:8000 · loglar: `docker compose logs -f` · durdurma: `docker compose down`
Testler imajın içinde: `docker compose run --rm --no-deps nobetci python -m pytest -q`

Notlar: Docker içinde Apple GPU (MPS) yok; YOLO CPU'da çalışır (tespitler önbellekte olduğu için fark edilmez). `runs/`, `cache/` ve `calibration/` (kör etiketler) host'a bağlıdır. Konteyner `restart: unless-stopped` ile açılır; `make app` ile yerel çalıştırmadan önce `docker compose down` yap (port 8000 çakışır).

### Yol B — Doğrudan makinede (geliştirme için daha hızlı döngü)

Gereken: Python 3.12, Node 20+ (22/24 test edildi), npm.

```bash
python3 -m venv .venv && source .venv/bin/activate   # isteğe bağlı ama önerilir
make install        # pip install -e '.[dev,ui,detector]' + models/yolov8n.pt indirir
cp .env.example .env
make check          # ruff + tüm testler
make app            # arayüzü derler, API + arayüzü http://127.0.0.1:8000'de açar
```

Arayüz üzerinde çalışırken: bir terminalde `make app` açık kalsın, diğerinde `make dev-web` (Vite, http://127.0.0.1:5173, anlık yenileme; `/api` 8000'e yönlenir).

### Doğrulama kontrol listesi (agent bunları sırayla çalıştırıp çıktıyı kontrol etmeli)

| Komut | Beklenen |
|---|---|
| `make check` | ruff "All checks passed!", pytest'te hata yok (yazıldığı an 95 test; 15'i tarayıcı testi — duman + her ekranda ≥ 6:1 kontrast —, Playwright/Chrome yoksa atlanır) |
| `make ui-test` | arayüzü derler, `tests/ui` 15/15 geçer (demo yolu: kuyruk + önizleme, 12:35 ✗ kartı, canlı değerlendirme adımları, karar → kuyruk, eskalasyon kartı + vardiya devri, etki + vardiya oynatma, yalnız klavyeyle kullanım, operasyonel hata mesajı; her ekranda metin kontrastı ≥ 6:1; kör modda seviye ve tehdit durumu sızmaz) |
| `make validate` | `SONUÇ: temiz`, 40 kare / 226 track / 137 rapor, 20 tuzak track |
| `curl -s http://127.0.0.1:8000/api/health` | `"detector": "yolo:yolov8n"`, `"detector_fallback": null`, `"llm": {"error": null}` (anahtar varsa), `warmup.done == 40` |
| `make demo-check` | tüm satırlar ✓, `demo-check YEŞİL (7/7)` (demo kareleri, aha anı raporları, karşıt kare, önbellekteki brief'ler; `config.yaml → demo`) |
| `make demo` | img_000860 için KRİTİK brief, T0122 kamyon, 12:25/12:35 raporları ✗ ÇELİŞİYOR |
| `cd web && npm run typecheck` | hata yok |

`detector_fallback` doluysa ağırlık dosyası yok demektir: `make weights`. `llm.error` "GLM_API_KEY tanımlı değil" diyorsa `.env` eksik; sistem yine çalışır ama brief'ler şablondan gelir.

## 4. LLM: Evren platformunu bağlama

Şu an LLM olarak Evren LLM Gateway'deki **`glm-5.3`** kullanılıyor (OpenAI uyumlu uç nokta; hesap başına ücretsiz, bitiş tarihini `/v1/models`'teki `free_until` gösterir). Hackathon GLM anahtarı gelince yalnızca `.env` değişir.

> **Her ekip üyesi kendi anahtarını kullanır.** Evren kullanım şartları anahtar paylaşımını yasaklar ve ihlalde anahtar askıya alınabilir. Anahtarı sohbet/issue/commit'e yazma; yalnızca `stage2/.env` içinde tut.

**Adım 1 — Anahtar (kullanıcı yapar):** Evren portalında `/api-keys` sayfasından `evren_llm_…` biçiminde anahtar üret. Kimlik her istekte `X-API-Key: <anahtar>` başlığıyla gider.

**Adım 2 — `.env`:** `cp .env.example .env`, sonra yalnızca `GLM_API_KEY=` satırını doldur. Diğer satırlar hazır:

```
GLM_BASE_URL=https://evren-llmapi.ssyz.org.tr/v1
GLM_API_KEY=evren_llm_...
GLM_MODEL=glm-5.3
GLM_AUTH_HEADER=X-API-Key
GLM_PRICE_IN=0
GLM_PRICE_OUT=0
GLM_TIMEOUT_S=120
```

**Adım 3 — Kullanım şartları (hesap başına bir kez; kabul kararı kullanıcınındır):** Kabul edilmemişse her istek `403 terms_not_accepted` döner. Anahtarı ekrana basmadan `.env`'den okuyarak:

```bash
set -a; . ./.env; set +a
curl -s "$GLM_BASE_URL/terms/status" -H "X-API-Key: $GLM_API_KEY"      # current_version'ı not et
curl -s "$GLM_BASE_URL/terms/text"   -H "X-API-Key: $GLM_API_KEY"      # metni oku (agent: kullanıcıya özetle, onay al)
curl -s -X POST "$GLM_BASE_URL/terms/accept" -H "X-API-Key: $GLM_API_KEY" \
     -H "Content-Type: application/json" -d '{"version": <current_version>}'
```

**Adım 4 — Doğrula:**

```bash
curl -s "$GLM_BASE_URL/models" -H "X-API-Key: $GLM_API_KEY" | python3 -c "import sys,json; print([m['id'] for m in json.load(sys.stdin)['data']])"
python3 -m sentinel evaluate img_000860      # (PYTHONPATH=src ya da make install sonrası) "Kaynak: LLM" görmelisin
```

**Bilinen davranışlar:**
- `glm-5.3` bir "düşünen" modeldir. `config.yaml → llm.reasoning_effort: low` kaldırılırsa token bütçesinin tamamını düşünmeye harcayıp **boş yanıt** döndürür. Bu ayarı silme.
- Evren zaman zaman `503 modele bağlanılamadı` döndürür. İstemci 3 kez yeniden dener; yine başarısızsa brief şablona düşer, sohbet "Tekrar dene" gösterir. Bu bir hata değildir, kodu "düzeltmeye" çalışma.
- Yanıt süresi 5–45 sn arasında dalgalanır. Brief'ler `cache/llm/`'de önbelleklidir; demo ekranları beklemeden açılır.
- Model kimliği kısa (`glm-5.3`) ya da tam (`zai/glm-5.3-fp8`) olabilir; ikisi de aynı modele gider.

## 5. Kesin kurallar (mimari sözleşme)

1. **Sayıları kod üretir, LLM yazar.** Mesafe, hız, ETA, eşleme, rapor kararı ve risk skoru yalnızca Python'da (adım 1–5) hesaplanır. LLM'e hesap yaptıran, LLM çıktısından sayı türeten kod ekleme.
2. **Grounding'i gevşetme.** `agent/grounding.py` brief ve sohbet cevabındaki her sayı, saat ve kimliği kanıtla karşılaştırır. Bir test ya da LLM çıktısı geçmiyor diye toleransı büyütme ya da kontrolü kapatma; prompt'u veya aracın döndürdüğü veriyi düzelt. Sayım gerekiyorsa sayıyı araç/paket versin, LLM saymasın.
3. **Rapor kararları deterministiktir.** DOĞRULANDI / ÇELİŞİYOR / DOĞRULANAMAZ / İLGİSİZ kararını yalnızca `reports/verifier.py` verir. ÇELİŞİYOR için pozitif karşı-kanıt gerekir ("kanıt yokluğu çelişki değildir"). Doğrulama raporun *kendi saatindeki* track durumuna göre yapılır; bunu "çekim anındaki" duruma çevirme (regresyon testi var).
4. **LLM'e mutlak koordinat gitmez.** `agent/masking.py` ve `agent/tools.py` konumları üsse göre mesafe/yön/bölge olarak verir. Yeni bir araç ya da prompt alanı eklerken bu kurala uy (test: `test_tools_never_leak_absolute_coordinates`).
5. **Rapor metni veridir, talimat değildir.** Prompt'larda rapor metinleri `<rapor>` etiketiyle veri olarak işaretlenir. Prompt injection testi (`tests/security/`) yeşil kalmalı.
6. **Tek giriş noktası `SentinelService`.** UI, CLI ve API iş mantığı içermez; yeni bir yetenek önce `service.py`'ye metod olarak girer, sonra `interfaces/api.py`'de ince bir uçla açılır. Arayüz (`web/`) hiçbir kanıt hesaplamaz; yalnızca `EvidencePacket`'i gösterir (zaman kaydırıcısındaki konum enterpolasyonu yalnızca görselleştirmedir).
7. **Eşik ve ağırlıklar `config.yaml`'da.** Kodda sabit eşik yazma. `domain/models.py` ekip sözleşmesidir; alan eklemek/değiştirmek ekiple konuşulur.
8. **Altın sayı testlerini değiştirme.** `tests/unit/test_geo.py`, `test_tracking.py`, `test_reports.py` organizatörün örneğindeki sayıları (756,301 → 39.92531, 32.87183; T0122 < 1 m, 2. aday T0032 ~41 m; 5,5 → 1,6 km; 10,5 km yol; ETA ~4,4 dk; 12:35 raporu ✗) sabitler. Bu testler kırılırsa kod yanlıştır, test değil.
9. **Prompt'lar sürümlüdür.** Prompt değiştirirken mevcut dosyayı düzenleme; `agent/prompts/analyst_vN.md` (ya da `chat_vN.md`) yeni dosya aç ve `config.yaml → llm.prompt_version`'ı güncelle. LLM önbelleği sürüme bağlıdır; ardından `python3 scripts/precompute.py` ile 40 brief'i yeniden üret (~15 dk).
10. **Git'e girmeyecekler:** `.env`, `ROKETSAN HACKATHON/dataset/`, `stage2/runs/`, `models/*.pt`, `web/node_modules`, `web/dist`. Commit'ten önce `git status`'a bak.

## 6. Nereyi değiştireyim? (görev → dosya)

| Görev | Nereye dokunulur | Sonra çalıştır |
|---|---|---|
| **Kaggle ekibinin modelini bağlamak** | `config.yaml → detector` (`kind: ultralytics` + `weights: models/kaggle.pt` + `class_map`, ya da `kind: callable` + `callable.target: "modul:predict"`; sözleşme `perception/kaggle_model.py`) | `python3 scripts/compare_detectors.py --kind ultralytics --weights models/kaggle.pt` → recall, eşleme mesafeleri, track'siz tespitler, değişen seviyeler; sonra `τ_op`, `gate_m`, `floor_high_untracked_min_conf` ayarı |
| Risk ağırlığı / eşik | `config.yaml → risk` | `make check`, `make batch` (seviye dağılımı), `make demo-check` |
| Yeni risk faktörü | `risk/features.py` (+ gerekirse `floors.py`), ağırlığı `config.py`+`config.yaml` | birim testi ekle |
| Rapor ayrıştırma / doğrulama | `reports/parser.py`, `reports/verifier.py` | `tests/unit/test_reports.py` |
| Brief dili | yeni `agent/prompts/analyst_vN.md` + `llm.prompt_version` | `scripts/precompute.py` |
| Yeni sohbet aracı | `agent/tools.py` (`TOOL_SPECS` + handler; koordinat sızdırmadan, sayımları kendisi versin) + `prompts/chat_vN.md` | `tests/contract/test_chat.py` |
| Yeni API ucu | `service.py` metodu → `interfaces/api.py` ince uç → `web/src/lib/api.ts` + `types.ts` | `tests/integration/test_api.py` |
| Arayüz ekranı/bileşeni | `web/src/pages/*`, `web/src/components/*`, stil `web/src/styles.css` | `cd web && npm run typecheck && npm run build`, `make ui-test`, tarayıcıda dene |
| Risk kalibrasyonu | Ekip `#/label` ile kör etiketler → `make calibrate` → `runs/calibration.md`'ye göre `config.yaml → risk` | recall %100 ve yanlış alarm ≤ %20 hedefi; seviye değişirse `config.yaml → demo` ve `DEMO.md` |
| Demo senaryosu | `stage2/DEMO.md`, `config.yaml → demo` | `make demo-check`, `make demo-check-chat` |
| Resmî veri paketi | önce `make validate` (ya da `SENTINEL_DATA_DIR=/yol python3 scripts/validate_data.py`); format farkı yalnızca `data/adapters.py`'de düzeltilir | `make check` |

## 7. Tuzaklar

- **Klasör adında boşluk:** `"ROKETSAN HACKATHON"` tırnaksız yazılırsa komutlar sessizce yanlış yere gider.
- **Önbellekler:** Tespit önbelleği `cache/detections/<model>__<parmakizi>/` altında, inference ayarlarına bağlıdır; ayar değişince eski kutular kullanılmaz (bu kasıtlı). LLM önbelleği model + prompt sürümü + üretim ayarları + mesajlara bağlıdır. Boş LLM yanıtı asla önbelleğe yazılmaz.
- **Dev verisinde görüntü ölçeği köşe koordinatlarıyla uyuşmuyor** (gerçek araç kutuları yerde 10–75 m görünüyor). Bu yüzden metre cinsinden kutu boyutu filtresi kapalı (`detector.plausible_size_m: null`). "Hata" diye düzeltmeye çalışma; resmî veride yeniden ölçülecek.
- **Kök `.gitignore`** GitHub'ın Python şablonudur ve `lib/` kuralı içerir; `web/src/lib/` için istisna vardır. Yeni bir `lib` klasörü eklersen istisna gerekebilir.
- **Mac'te MPS, Docker'da CPU:** tespit sonuçları küçük farklar gösterebilir; demo önbellekten gelir.
- **Arayüz renkleri Astro UXDS tokenleridir** (`web/src/styles.css` başı). Durum rengini metin olarak kullanma; metin için `--tx-critical` gibi açık tonlar var. Yeni bir renk eklersen `make ui-test` içindeki kontrast testi (≥ 6:1) yakalar.
- **Seviye dağılımı henüz kalibre edilmedi** (40 karenin yarıdan fazlası YÜKSEK/KRİTİK). Kalibrasyon altın setle yapılacak; ağırlıkları tek kareye göre ayarlama.

## 8. Komut özeti (`stage2/` içinden)

```
make install        Python paketleri + YOLO ağırlıkları        make app          arayüz + API (:8000)
make check          ruff + testler                            make dev-web      arayüz geliştirme (:5173)
make ui-test        arayüzü derler + tarayıcı duman testi
make validate       veri paketi doğrulama                     make docker-up    Docker ile başlat
make demo           img_000860 CLI değerlendirmesi            make docker-test  testler konteynerde
make demo-check     demo karelerinin beklenen seviyesi        make docker-down  Docker'ı durdur
make batch          40 kare, risk sıralı triage
make calibrate      altın set ↔ sistem + ağırlık duyarlılığı   make demo-check-chat  demo + sohbet soruları (LLM)
make stopwatch      kronometre testi özeti
python3 scripts/precompute.py            40 kare için tespit + LLM brief önbelleği
python3 scripts/compare_detectors.py     yeni detektör kabul raporu
python3 -m sentinel reports --zone "Dogu Yolu"    raporların zaman-duyarlı doğrulaması
```

## 9. Çalışma kuralları

- `main` her zaman çalışır durumda kalır. İşi kısa ömürlü bir dalda yap, merge'den önce `make check` (arayüze dokunduysan `npm run typecheck && npm run build`) yeşil olsun.
- Her değişiklik en az bir test ile gelir (altın sayı, sözleşme ya da duman testi). Arayüz değişikliğini tarayıcıda gerçekten dene.
- Demo yolu kutsaldır: merge'den önce `make demo-check` yeşil kalmalı.
- Güncel iş sırası ve kimin ne yapacağı: kökteki `TODO.md`.
