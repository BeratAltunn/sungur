# AGENTS.md — DİZDAR (ROKETSAN Level Up AI Hackathon, Aşama 2)

Bu dosya, bu depoda çalışan LLM agent'ları (Claude Code, Codex, Cursor, Copilot …) ve onları kullanan ekip üyeleri içindir. Amaç: projeyi sıfırdan ayağa kaldırmak, LLM'i (Evren) bağlamak ve mimariyi bozmadan geliştirme yapmak.

> **Agent'a not:** Bu dosyadaki "Kesin kurallar" bölümü projenin tasarım sözleşmesidir; kullanıcı açıkça istemedikçe ihlal etme. Kullanıcı adına şart/sözleşme kabul etme, API anahtarı üretme ya da anahtarı bir dosyaya yazıp commit etme; bunları kullanıcıya yaptır.

---

## 1. Proje tek paragrafta

DİZDAR (kod adı NÖBETÇİ; Python paketi `sentinel`, prompt'lar ve CLI bu adı kullanır), bir askerî üssü çevreleyen 8 bölgeden gelen drone karelerini risk sırasına dizen bir ajandır. Her kare için 6 adım çalışır: **(1) araç tespiti (Kaggle ekibinin D-FINE-M modeli) → (2) pikselden koordinata → (3) araçları 2 saatlik hareket izleriyle eşleme + kinematik (hız, yaklaşma, duraklama, ETA) → (4) saha raporlarını raporun *kendi saatindeki* duruma göre doğrulama → (5) Yetenek–Fırsat–Niyet (C-O-I) tehdit değerlendirmesi: her araç için üç kenar bandı → seviye matrisi + taban kuralları (ETA ayrı aciliyet ekseni) → (6) LLM'in her sayısı kanıtla kontrol edilen (grounding) Türkçe brief yazması.** 1–5 deterministik Python'dur; LLM hesap yapmaz, yalnızca yazar. Ayrıca araç çağıran bir sohbet paneli ve operatör için bir web arayüzü (triage kuyruğu + kare detayı + zaman kaydırıcısı) vardır.

**Değerlendirme kriterleri:** Kaggle skoru (Aşama 1 tespit modeli) %20 · teknik kalite ve mimari %15 · problemin önemi ve çözümün sağladığı iş değeri %20 · çalışan ürün ortaya koyabilme %20 · ürün düşüncesi ve kullanıcı deneyimi %20 · sunum ve demo %5. Sistem resmî Aşama 2 veri paketi, Kaggle ekibinin D-FINE-M modeli ve hackathon ağ geçidindeki `glm-5.3-flash` ile çalışır. Dev verisi, yolov8n ve Evren yedek olarak durur.

Aşama 2 belgesi (jüri için): `asama-2/README.md` · ürün/tasarım gerekçeleri: `asama-2/PROJECT_DESIGN.md` · modül ayrıntıları: `asama-2/STAGE2_ARCHITECTURE.md` · demo: `asama-2/stage2/DEMO.md`.

## 2. Depo haritası

```
sungur/                                   ← git kökü
  README.md                               ← depo özeti (Aşama 1 + Aşama 2)
  AGENTS.md  CLAUDE.md  .gitignore
  asama-2/                                ← AŞAMA 2 (bu belge). Aşama 1 ayrıca asama-1/ olarak eklenecek
    README.md                             ← Aşama 2 belgesi (jüri için: problem, mimari, risk modeli, kurulum, demo)
    PROJECT_DESIGN.md  STAGE2_ARCHITECTURE.md
    data/                                 ← RESMÎ Aşama 2 paketi (40 kare, 226 track, 137 rapor) — GIT'E GİRMEZ, ekip ayrıca paylaşır
    stage2_dev_data/                      ← dev verisi (aynı senaryo, küçültülmüş görüntüler) — depoda, yedek
    dataset/                              ← Kaggle verisi (1,8 GB) — GIT'E GİRMEZ, gerekmez
    gorev_tanimi.pdf                      ← resmî görev tanımı (GLM kullanım rehberi dahil) — GIT'E GİRMEZ
    stage2/                               ← UYGULAMA (tüm komutlar buradan çalışır)
      config.yaml                         ← tüm eşikler, ağırlıklar, model seçimi
      .env.example → .env                 ← LLM anahtarı (git'e girmez)
      Makefile  Dockerfile  docker-compose.yml  pyproject.toml
      src/sentinel/
        domain/models.py                  ← tüm pydantic modeller (sözleşme)
        data/                             ← dosya okuma + Repository (zaman ızgarası, uzay-zaman sorguları)
        perception/                       ← Detector arayüzü: dfine (Kaggle) | ultralytics (yedek) | callable | oracle (test) | cache
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
      models/                             ← dfine_m_kaggle.pth (Ekip-1 modelinin EMA ağırlıkları, 79 MB, ekipten) + yolov8n.pt (`make weights`) — git'e girmez
```

## 3. Ayağa kaldırma

Tüm komutlar `asama-2/stage2` içinden çalışır:

```bash
cd asama-2/stage2
```

### Yol A — Docker (önerilen; ekip ve yedek laptop)

Gereken: Docker Desktop (Compose v2.24+).

```bash
cp .env.example .env            # anahtarı 4. bölümdeki gibi doldur; boş kalırsa sistem şablon brief ile çalışır
docker compose up --build -d    # ilk derleme birkaç dakika (~2,6 GB imaj)
```

Arayüz: http://127.0.0.1:8000 · loglar: `docker compose logs -f` · durdurma: `docker compose down`
Testler imajın içinde: `docker compose run --rm --no-deps nobetci python -m pytest -q`

Notlar: Resmî veri (`../data`) ve D-FINE ağırlıkları (`models/dfine_m_kaggle.pth`) imaja girmez, volume ile salt okunur bağlanır; `.env` de `.dockerignore` sayesinde imaja girmez. Veri host'ta yoksa `docker-compose.yml`'deki iki `data` satırını yorumla (dev verisiyle açılır). Docker içinde Apple GPU (MPS) yok; D-FINE CPU'da çalışır (tespitler önbellekte olduğu için fark edilmez). `runs/`, `cache/` ve `calibration/` (kör etiketler) host'a bağlıdır. Konteyner `restart: unless-stopped` ile açılır; `make app` ile yerel çalıştırmadan önce `docker compose down` yap (port 8000 çakışır).

### Yol B — Doğrudan makinede (geliştirme için daha hızlı döngü)

Gereken: Python 3.12, Node 20+ (22/24 test edildi), npm.

```bash
python3 -m venv .venv && source .venv/bin/activate   # isteğe bağlı ama önerilir
make install        # pip install -e '.[dev,ui,detector]' (torch + transformers) + models/yolov8n.pt indirir
cp .env.example .env
# Ekipten al (git'e girmez): resmî paket → "asama-2/data/", Kaggle modeli → models/dfine_m_kaggle.pth
# Resmî paket yoksa: export SENTINEL_DATA_DIR=../stage2_dev_data
make check          # ruff + tüm testler
make app            # arayüzü derler, API + arayüzü http://127.0.0.1:8000'de açar
```

Arayüz üzerinde çalışırken: bir terminalde `make app` açık kalsın, diğerinde `make dev-web` (Vite, http://127.0.0.1:5173, anlık yenileme; `/api` 8000'e yönlenir).

### Doğrulama kontrol listesi (agent bunları sırayla çalıştırıp çıktıyı kontrol etmeli)

| Komut | Beklenen |
|---|---|
| `make check` | ruff "All checks passed!", pytest'te hata yok (yazıldığı an 155 test; 29'u tarayıcı testi — duman + her ekranda ≥ 6:1 kontrast —, Playwright/Chrome yoksa atlanır) |
| `make ui-test` | arayüzü derler, `tests/ui` 29/29 geçer (arazi karoları yoksa 1'i atlanır) (demo yolu: kuyruk + önizleme, 12:35 ✗ kartı, canlı değerlendirme adımları, karar → kuyruk, eskalasyon kartı + vardiya devri, etki + vardiya oynatma, yalnız klavyeyle kullanım, operasyonel hata mesajı; her ekranda metin kontrastı ≥ 6:1; kör modda seviye ve tehdit durumu sızmaz) |
| `make validate` | `SONUÇ: temiz`, 40 kare / 226 track / 137 rapor, 20 tuzak track |
| `curl -s http://127.0.0.1:8000/api/health` | `"detector": "dfine:dfine_m_kaggle"`, `"detector_fallback": null`, `"llm": {"error": null}` (anahtar varsa), `warmup.done == 40` |
| `make demo-check` | tüm satırlar ✓, `demo-check YEŞİL (7/7)` (img_000860 KRİTİK + R119/R125 ✗, karşıt kare img_001733 DÜŞÜK ve çelişen rapor yok, önbellekteki brief'ler; `config.yaml → demo`) |
| `make demo` | img_000860 için KRİTİK brief, T0122 olası kamyon (sınıf teyitsiz), 12:25/12:35 raporları ✗ ÇELİŞİYOR |
| `cd web && npm run typecheck` | hata yok |

`detector_fallback` doluysa ağırlık dosyası ya da `transformers` yok demektir: `models/dfine_m_kaggle.pth`'yi ekipten al, `make install`. Tespitler o sırada önbellekten gelir. `llm.error` "GLM_API_KEY tanımlı değil" diyorsa `.env` eksik; sistem yine çalışır ama brief'ler şablondan gelir.

## 4. LLM: hackathon GLM ağ geçidi

LLM olarak organizatörün ağ geçidindeki **`glm-5.3-flash`** kullanılır (LiteLLM, OpenAI uyumlu, standart `Authorization: Bearer`). Adres, model ve limitler `asama-2/gorev_tanimi.pdf` s. 3–10'da.

> **Anahtar takıma özeldir ve bütçe sıfırlanmaz: toplam 15 USD.** Anahtarı sohbet/issue/commit'e yazma; yalnızca `stage2/.env` içinde tut (git'e ve Docker imajına girmez). Depo özel olsa da anahtar hiçbir dosyaya yazılmaz.

**Adım 1 — `.env` (kullanıcı yapar):** `cp .env.example .env`, sonra yalnızca `GLM_API_KEY=` satırını takımın anahtarıyla doldur. `GLM_AUTH_HEADER` satırı **olmamalı** (Bearer kullanılır).

**Adım 2 — Doğrula (anahtarı ekrana basmadan):**

```bash
set -a; . ./.env; set +a
curl -s "${GLM_BASE_URL%/v1}/key/info" -H "Authorization: Bearer $GLM_API_KEY" | python3 -c "import sys,json; d=json.load(sys.stdin); d=d.get('info',d); print('harcanan', d.get('spend'), '/', d.get('max_budget'), 'USD')"
python3 -m sentinel evaluate img_000860      # (PYTHONPATH=src ya da make install sonrası) "Kaynak: LLM" görmelisin
```

**Limitler ve bütçe:** takım başına 60 istek/dk, 500 000 token/dk, **aynı anda en fazla 4 istek**. `scripts/precompute.py` sıralı çalışır. Toplu işlerden (ön hesaplama, `demo-check-chat`) önce ve sonra `/key/info`'daki `spend`'e bak. Bütçe bekçisi (`config.yaml → llm.budget_stop_usd`) fiyat bilinmediği için config'teki temkinli varsayılan fiyatlarla sayar; `.env`'e `GLM_PRICE_*=0` yazma.

**Bilinen davranışlar:**
- `glm-5.3-flash` her zaman düşünür (`message.reasoning_content`). `max_tokens` düşünmeyi de kapsar: cömert tut. `config.yaml → llm.reasoning_effort: low` kalmalı; `thinking` parametresi gönderilmez.
- Boş `content` + `finish_reason: length` → `max_tokens` yetersiz. 429 → istemci geri çekilip yeniden dener. 400 "Budget has been exceeded" → organizatöre yaz. 400 "key not allowed to access model" → model adı yanlış (tam olarak `glm-5.3-flash`).
- `analyst_v3` ile 40 karede brief'lerin ~38'i LLM'den gelir; kalan 1–2 kare, LLM bir DOĞRULANAMAZ raporu "çelişiyor" diye yazdığı için grounding'e takılıp şablona düşer. Bu beklenen davranış; grounding'i gevşetme. Şablon manşeti de aynı kalıptadır.
- Yanıt süresi dalgalanır. Brief'ler `cache/llm/`'de önbelleklidir (anahtar: model + prompt sürümü + ayarlar + mesajlar); demo ekranları beklemeden açılır.
- Model görüntü okuyabilir, ama tasarım gereği LLM'e görüntü gönderilmez (PROJECT_DESIGN §2.4 Won't; grounding ilkesi).

**Yedek — Evren (`glm-5.3`, ücretsiz, kişisel anahtar):** `.env.example`'daki yorumlu blok. Kimlik `X-API-Key` başlığıyla (`GLM_AUTH_HEADER=X-API-Key`). Kullanım şartları hesap başına bir kez kabul edilir (`$GLM_BASE_URL/terms/status|text|accept`; kabul kararı kullanıcınındır). Evren anahtarı paylaşılamaz; zaman zaman `503 modele bağlanılamadı` döner (istemci 3 kez dener, sonra şablon brief).

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
10. **Git'e girmeyecekler:** `.env`, `asama-2/dataset/`, organizatör PDF/PPTX'leri, `stage2/runs/`, `models/*.pt`, `asama-2/data/` (resmî paket), `*.pth`, `web/node_modules`, `web/dist`, `web/public/terrain/` (`make terrain` indirir). Commit'ten önce `git status`'a bak.

## 6. Nereyi değiştireyim? (görev → dosya)

| Görev | Nereye dokunulur | Sonra çalıştır |
|---|---|---|
| **Kaggle ekibinin modeli (D-FINE-M)** | `config.yaml → detector.dfine` (`weights`, `input_size` [800, 1408], `class_names` indeks sırası [car, truck, van, bus]); yükleyici `perception/dfine.py` (orijinal D-FINE anahtarları → transformers, strict). Yeni bir kontrol noktası gelirse aynı yol; ultralytics `.pt` için `kind: ultralytics` | `python3 scripts/compare_detectors.py --kind dfine` → recall, eşleme mesafeleri, track'siz tespitler, değişen seviyeler; `tests/unit/test_dfine.py`; sonra `τ_op`, `gate_m`, `floor_high_untracked_min_conf` ayarı (kalibrasyonla) |
| Risk kenarları / bantlar / tabanlar | `config.yaml → risk` (yetenek sınıf puanları, niyet göstergesi puanları, bant eşikleri, mesafe bantları); matris `risk/scoring.py`, tabanlar `risk/floors.py` | `make check`, `make batch` (seviye dağılımı), `make demo-check` |
| Yeni risk faktörü | `risk/features.py` (hangi kenara yazıldığını `dimension` ile belirt; yaklaşma yalnızca niyette, ETA kenar değil), puanı `config.py`+`config.yaml` | birim testi ekle |
| Rapor ayrıştırma / doğrulama | `reports/parser.py`, `reports/verifier.py` | `tests/unit/test_reports.py` |
| Brief dili | yeni `agent/prompts/analyst_vN.md` + `llm.prompt_version` | `scripts/precompute.py` |
| Yeni sohbet aracı | `agent/tools.py` (`TOOL_SPECS` + handler; koordinat sızdırmadan, sayımları kendisi versin) + `prompts/chat_vN.md` | `tests/contract/test_chat.py` |
| Yeni API ucu | `service.py` metodu → `interfaces/api.py` ince uç → `web/src/lib/api.ts` + `types.ts` | `tests/integration/test_api.py` |
| Arayüz ekranı/bileşeni | `web/src/pages/*`, `web/src/components/*`, stil `web/src/styles.css` | `cd web && npm run typecheck && npm run build`, `make ui-test`, tarayıcıda dene |
| Demo senaryosu | `stage2/DEMO.md`, `config.yaml → demo` | `make demo-check`, `make demo-check-chat` |
| Resmî veri paketi | önce `make validate` (ya da `SENTINEL_DATA_DIR=/yol python3 scripts/validate_data.py`); format farkı yalnızca `data/adapters.py`'de düzeltilir | `make check` |

## 7. Tuzaklar

- **Önbellekler:** Tespit önbelleği `cache/detections/<model>__<parmakizi>/` altında; parmak izi inference ayarlarını ve veri paketinin kimliğini (`image_meta.json` özeti) içerir. Ayar ya da veri paketi değişince eski kutular kullanılmaz (bu kasıtlı: dev ve resmî pakette kare kimlikleri aynı, pikseller farklı). LLM önbelleği model + prompt sürümü + üretim ayarları + mesajlara bağlıdır. Boş LLM yanıtı asla önbelleğe yazılmaz.
- **Görüntü ölçeği köşe koordinatlarıyla uyuşmuyor** (resmî veride de yeniden ölçüldü: track'le eşleşen gerçek araç kutuları yerde medyan 10 m, en fazla 60 m). Bu yüzden metre cinsinden kutu boyutu filtresi kapalı (`detector.plausible_size_m: null`). "Hata" diye düzeltmeye çalışma.
- **Rapor kimlikleri dosya sırasıdır:** `field_reports.json`'da kimlik yok; `R{sıra:03d}` resmî dosyadaki 0 tabanlı sıradır (dev dosyası saate göre sıralıydı, resmî dosya değil). Demo raporları: 12:25 → R119, 12:35 → R125.
- **D-FINE ve transformers:** `DFineConfig(eval_size=…)` verme; transformers 4.55'te kodlayıcının konum gömmesini atlayıp çöker. Ön işleme Ekip-1'in eğitimiyle birebir: RGB, `cv2.resize(INTER_LINEAR)` ile 1408×800'e düz gerdirme, letterbox yok, yalnızca /255 (ImageNet normalizasyonuyla recall %89'dan %57'ye düşer; PIL resize küçültürken antialias uyguladığı için kullanılmaz). Sınıf sırası [car, truck, van, bus], yarışma sayfasındaki sıradan farklı. Ekip-1'in 2×2 parçalı çıkarımı mAP'ye +0,01 katıyor ama 5 kat yavaş; recall zaten %100 olduğu için kullanılmıyor. D-FINE NMS'sizdir; iç içe gerçek araçlar olduğu için (img_002256 V8/V9) sezgisel NMS eklenmedi, birkaç yinelenen kutu kalır.
- **Kök `.gitignore`** GitHub'ın Python şablonudur ve `lib/` kuralı içerir; `web/src/lib/` için istisna vardır. Yeni bir `lib` klasörü eklersen istisna gerekebilir.
- **Mac'te MPS, Docker'da CPU:** tespit sonuçları küçük farklar gösterebilir; demo önbellekten gelir.
- **Arayüz renkleri Astro UXDS tokenleridir** (`web/src/styles.css` başı). Durum rengini metin olarak kullanma; metin için `--tx-critical` gibi açık tonlar var. Yeni bir renk eklersen `make ui-test` içindeki kontrast testi (≥ 6:1) yakalar.
- **Risk modeli Yetenek–Fırsat–Niyet (C-O-I):** seviye bantlardan matrisle verilir, skor yalnızca sıralar. Altın set / kalibrasyon yapılmıyor (ekip kararı); eşikleri tek kareye göre değil dağılıma ve demo karelerine bakarak ayarla (D-FINE ile şu an DÜŞÜK 16 · ORTA 14 · YÜKSEK 6 · KRİTİK 4). Dur-kalk skora girmez: bu veride neredeyse her araç bekle-ilerle yapıyor. Güveni τ_op altındaki kutunun sınıfı 'bilinmiyor' sayılır; sınıf bilgisi yalnızca bu ve önceki karelerden gelir.

## 8. Komut özeti (`stage2/` içinden)

```
make install        Python paketleri + yolov8n (yedek)        make app          arayüz + API (:8000)
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
make terrain                             ana harita 3B arazi karoları (DEM + doku) → web/public/terrain; yalnızca görsel
python3 -m sentinel reports --zone "Dogu Yolu"    raporların zaman-duyarlı doğrulaması
```

## 9. Çalışma kuralları

- `main` her zaman çalışır durumda kalır. İşi kısa ömürlü bir dalda yap, merge'den önce `make check` (arayüze dokunduysan `npm run typecheck && npm run build`) yeşil olsun.
- Her değişiklik en az bir test ile gelir (altın sayı, sözleşme ya da duman testi). Arayüz değişikliğini tarayıcıda gerçekten dene.
- Demo yolu kutsaldır: merge'den önce `make demo-check` yeşil kalmalı.
