# NÖBETÇİ: Saha Raporu Destekli Üs Risk Ajanı (Aşama 2)

Drone karesini alır, **tespit → koordinat → track eşleme ve kinematik → zaman-duyarlı rapor doğrulama → açıklanabilir risk** adımlarını deterministik olarak çalıştırır ve ardından GLM ile tek çağrıda, her sayısı kanıta bağlı (grounding kontrollü) bir brief yazar. LLM'e erişilemezse şablon brief'e düşer, sistem çalışmaya devam eder.

Tasarım: [PROJECT_DESIGN.md](../PROJECT_DESIGN.md) · Modül ayrıntıları: [STAGE2_ARCHITECTURE.md](../STAGE2_ARCHITECTURE.md)

## 5 dakikada kurulum

**Docker ile (önerilen, ekip ve yedek laptop için):**

```bash
cd "ROKETSAN HACKATHON/stage2"
cp .env.example .env                   # LLM anahtarını yazın; boş bırakılırsa şablon brief çalışır
docker compose up --build              # ilk derleme birkaç dakika; sonra http://127.0.0.1:8000
docker compose run --rm nobetci python -m pytest -q    # testler imajın içinde
```

İmaj arayüzü derler, CPU'ya özel torch ve geçici YOLO ağırlıklarını kurar. `runs/` (iz, kararlar) ve `cache/` (tespit + LLM önbelleği) host'a bağlıdır; önbellek depoda olduğu için demo internetsiz ve LLM'siz de açılır. Docker içinde Apple GPU yoktur, "canlı yeniden değerlendir" CPU'da birkaç saniye sürer; canlı demoyu doğrudan makinede (`make app`) çalıştırmak daha hızlıdır.
Resmî veri paketi gelince `docker-compose.yml`'deki `volumes`/`SENTINEL_DATA_DIR` satırlarını açın; imajı yeniden derlemek gerekmez.

**Doğrudan makinede:**

```bash
cd stage2
make install                           # Python paketleri + geçici YOLO ağırlıkları
cp .env.example .env                   # LLM anahtarını yazın; boşken şablon brief çalışır
make check                             # ruff + testler
make demo                              # img_000860 değerlendirmesi (CLI)
make batch                             # 40 kare, risk sıralı triage
make app                               # arayüz + API → http://127.0.0.1:8000
```

| Komut | Ne yapar |
|---|---|
| `python -m sentinel evaluate IMG [--json] [--no-llm] [--live]` | Tek kare: brief, faktörler, kinematik, rapor kararları |
| `python -m sentinel batch` | Nöbet devri özeti + triage kuyruğu |
| `python -m sentinel reports [--zone "Dogu Yolu"]` | Tüm raporların zaman-duyarlı doğrulaması |
| `make validate` | Veri paketini doğrular (resmi paket gelince **ilk iş** bunu çalıştırın) |
| `make precompute` | 40 karenin tespit + brief önbelleği |
| `make demo-check` | Demo karelerinin beklenen seviyede olduğunu kontrol eder |
| `make ui-test` | Arayüzü derler, tarayıcı duman testi (Playwright + sistem Chrome'u) |

Her çalıştırma `runs/trace.jsonl`'e adım adım iz yazar (`run_id` ile). Operatör kararları `runs/decisions.jsonl`'e, kare açılışları `runs/views.jsonl`'e ek-kayıt olarak gider; ikisinden **açılış → karar süresi** (kare başına işlem süresi) ölçülür ve nöbet devri kartında gösterilir.

Arayüz ekranları: `#/` triage · `#/frame/<id>` kare detayı · `#/handover` vardiya devri (kurala dayalı, yazdırılabilir) · `#/brief/<id>` eskalasyon kartı (amir için, yazdırılabilir) · `#/impact` etki (vardiya simülasyonu: karar, araç varmadan önce mi?) · `#/?replay=1` kuyrukta vardiya oynatma · `#/label` kör etiketleme.

Vardiya simülasyonu (`src/sentinel/impact.py`) bir operatör zamanı modelidir, kanıt değildir: kare başına süreler `config.yaml → impact` varsayımlarından başlar, kronometre testi (`calibration/stopwatch.csv`) ve üründeki açılış → karar ölçümü yeterli olunca onlarla değişir.

## Mimari (kısaca)

```
src/sentinel/
  domain/models.py        tüm pydantic modeller (ekip sözleşmesi)
  data/                   adapters (dosya formatı) + Repository (zaman ızgarası, uzay-zaman sorguları)
  perception/             Detector arayüzü: oracle (test) · ultralytics (yedek / Kaggle .pt) · callable (Kaggle predict) · cache
  geo/                    eşdikdörtgen geodesy · bilineer georef · bölge (sektör) indeksi
  tracking/               Hungarian + kapı eşleme · kinematik (yaklaşma, hiza, duraklama, ETA)
  reports/                parser (regex) · relevance · verifier (rapor saatindeki duruma göre)
  risk/                   faktörler · skor · taban kuralları
  agent/                  masking · analyst (1 çağrı + 1 düzeltme) · grounding · şablon · llm (GLM/Mock/cache) · bütçe
  pipeline.py             evaluate(image_id) -> EvidencePacket (adım 1–5, LLM'siz)
  service.py              SentinelService: UI ve CLI'ın tek giriş noktası
  interfaces/cli.py
```

Katman kuralı: `domain` hiçbir şeye bağlı değil; UI/CLI yalnızca `SentinelService`'i çağırır.

## Arayüz (FastAPI + React)

`make app` arayüzü derler (`web/dist`) ve FastAPI ile tek süreçte sunar: http://127.0.0.1:8000. İnternet gerekmez; altlık harita isteğe bağlıdır (haritadaki "Altlık" düğmesi).

- **Triage:** nöbet devri kartı, risk sıralı kuyruk (bölge/seviye filtresi, "bakılmamışlar"), bölge haritası. <kbd>J</kbd>/<kbd>K</kbd> gez, <kbd>Enter</kbd> aç.
- **Kare detayı:** brief (seviye → manşet → önerilen eylem → kanıt çipli bulgular → grounding rozeti), kutulu görüntü, 2 saatlik izlerle harita ve **zaman kaydırıcısı**, sekmeler: *Neden?* (faktör katkıları, taban kuralı), *Raporlar* (satıra tıkla → harita ve kaydırıcı rapor saatine gider), *Araçlar*, *Ajan izi*. Kararlar: Onayla (<kbd>A</kbd>), Seviyeyi değiştir (gerekçe zorunlu), Amire ilet (<kbd>E</kbd>, brief panoya kopyalanır), Geri al. <kbd>Space</kbd> oynat, <kbd>Esc</kbd> kuyruğa dön.
- **Canlı yeniden değerlendir:** tespit önbelleğini atlayıp 6 adımı yeniden çalıştırır (demodaki canlı çalıştırma).

Arayüz hiçbir kanıt hesaplamaz; sayıların hepsi `EvidencePacket`'ten gelir. Kod: `web/src/pages` (ekranlar), `web/src/components` (parçalar), `web/src/lib` (API tipleri ve biçimlendirme). Geliştirirken `make app` açıkken `make dev-web` (:5173, anlık yenileme).

REST uçları `src/sentinel/interfaces/api.py`'de; her biri `SentinelService`'in bir metodunu çağırır. Açılışta 40 kare ağ çağrısı yapılmadan (LLM önbelleğinden) ısıtılır; önbellekte olmayan bir brief kare açılınca üretilir, deterministik kanıt ise beklemeden gelir.

## Sohbet

Her ekranda sağ alttaki **Sohbet** düğmesi (<kbd>/</kbd>) yan paneli açar. Açık bir kare varsa soru o karenin bağlamında sorulur ("bu kamyon neden riskli?"). Cevaptaki `img_…`, `V…`, `T…`, `R…` kimlikleri tıklanabilir: kareyi açar ya da haritada aracı/raporu gösterir.

- LLM soruyu cevaplamak için **salt-okur araçlar** çağırır (`src/sentinel/agent/tools.py`): `list_frames`, `analyze_image`, `get_track`, `find_reports`, `zone_summary`. Araçlar mutlak koordinat döndürmez; konumlar üsse mesafe, yön ve bölge olarak gelir.
- En fazla 6 LLM adımı. Cevaptaki her sayı, saat ve kimlik o turdaki araç çıktılarıyla karşılaştırılır; tutmazsa bir düzeltme turu, yine tutmazsa cevap **"doğrulanamayan değerler"** uyarısıyla gösterilir (sessizce geçmez).
- Sayımları araçlar verir (`toplam`, `kaynaklara_gore` …); LLM saymaz.
- Prompt: `src/sentinel/agent/prompts/chat_v1.md`. Her tur `runs/trace.jsonl`'e araç çağrılarıyla birlikte yazılır.
- Yanıt süresi büyük ölçüde LLM uç noktasına bağlı: Evren/glm-5.3 ile ölçülen 5–45 sn.

## Kalibrasyon, kör etiketleme, kronometre, demo

- **Kör etiketleme (altın set):** http://127.0.0.1:8000/#/label — etiketleyici adını girer; kareler çekim saatine göre gelir, sistemin seviyesi/skoru/brief'i ve araç renkleri gizlidir. Klavye: <kbd>1</kbd>–<kbd>4</kbd> seviye (DÜŞÜK→KRİTİK), <kbd>Enter</kbd> kaydet ve sonraki, <kbd>J</kbd>/<kbd>K</kbd> gez. Etiketler `calibration/labels/<ad>.jsonl`'e yazılır (git'e girer).
- **Kalibrasyon raporu:** `make calibrate` → `runs/calibration.md`: etiketleyici uyumu (ağırlıklı Cohen's κ), sistem ↔ altın set karışıklık matrisi, YÜKSEK/KRİTİK recall (hedef %100), yanlış alarm oranı (hedef ≤ %20) ve her ağırlık ±%20 değişince kaç karenin seviyesinin değiştiği.
- **Kronometre testi:** `python3 scripts/stopwatch.py manual <kare> --who <ad>` (yalnızca ham dosyalar) ve `… system <başka kare> …` (arayüzle); özet `make stopwatch`. Sonuçlar `calibration/stopwatch.csv`.
- **Demo:** akış ve B planları `DEMO.md`. Demo kareleri ve beklentiler `config.yaml → demo`; `make demo-check` (LLM çağırmaz) ve `make demo-check-chat` (sohbet soruları da).

## Kaggle modelini bağlamak (Ekip-1)

İki yol, ikisi de tek config değişikliği (`config.yaml → detector`):

1. **Ultralytics `.pt`**: `kind: ultralytics`, `ultralytics.weights: models/kaggle.pt`, `class_map` ile sınıf adlarını `car/van/truck/bus`'a eşleyin. `pip install -e '.[detector]'`.
2. **Kendi inference kodu**: `kind: callable`, `callable.target: "paket.modul:predict"`. Sözleşme:
   ```python
   def predict(image_path: Path) -> list[tuple[str, float, float, float, float, float]]:
       """[(label, conf, x, y, w, h), ...]  px, sol-üst köşe (Kaggle submission formatı)"""
   ```

Tespitler `cache/detections/<detektör>/` altında önbelleğe alınır. `τ_op` (`detector.tau_op`) altındaki kutular silinmez, "düşük güven" katmanına düşer ve bir track ile eşleşirse terfi eder.

## LLM'i bağlamak

`.env` içindeki `GLM_BASE_URL`, `GLM_API_KEY`, `GLM_MODEL` ile herhangi bir OpenAI uyumlu uç nokta kullanılır (`config.yaml → llm.provider: openai_compat`). Anahtar yoksa ya da uç nokta düşerse şablon brief'e düşülür.

- **Şu an:** Evren platformu, `glm-5.3` (ücretsiz, 1 Kasım'a kadar). Kimlik `X-API-Key` başlığıyla (`GLM_AUTH_HEADER`). Örnek: `.env.example`.
- **GLM hackathon anahtarı gelince:** `.env`'deki adres/anahtar/model satırlarını değiştirin, `GLM_AUTH_HEADER`'ı silin.
- `glm-5.3` bir "düşünen" model: `llm.reasoning_effort: low` olmadan tüm token bütçesini düşünmeye harcayıp boş yanıt döndürüyor.
- Yanıtlar `cache/llm/`'e yazılır (anahtar: model + prompt sürümü + üretim ayarları + mesajlar); boş yanıt önbelleğe yazılmaz. Bütçe bekçisi 12 $'da durdurur (`runs/budget.json`).
- Prompt: `src/sentinel/agent/prompts/analyst_v2.md`; değiştirirken yeni sürüm dosyası açın.

## Geçici detektör ve "model geldi" kontrolü

Varsayılan detektör COCO ile önceden eğitilmiş **yolov8n** (`models/yolov8n.pt`, Ultralytics resmî sürümü). Ekibin modeli geldiğinde önce karşılaştırma raporunu alın:

```bash
python3 scripts/compare_detectors.py --kind ultralytics --weights models/kaggle.pt
```

Rapor 40 karede track'leri referans alarak şunları verir: yaklaşık recall, track ile doğrulanan tespit oranı, eşleme mesafesi dağılımı (kapı ayarı için), track'siz tespitler ve değişen risk seviyeleri (`runs/compare_*.json`).

yolov8n ölçümü (dev verisi): recall ≈ %82, tespitlerin %87'si track ile doğrulanıyor, eşleme mesafesi medyan 0,4 m. Düşük güvenli kutuların track ile terfisi gerçek araçların bir kısmını kurtarıyor.

Veri notu: dev karelerinde **görüntü ölçeği köşe koordinatlarıyla uyuşmuyor** (eşleşen gerçek araç kutularının yerdeki boyu medyan 10 m, en fazla 75 m). Bu yüzden metre cinsinden boyut filtresi (`detector.plausible_size_m`) kapalı; resmi veride yeniden ölçün.

Model yüklenemezse (paket/ağırlık eksik) sistem aynı ayarlarla üretilmiş tespit önbelleğinden devam eder ve bunu belirsizlik olarak yazar. Önbellek, inference ayarlarının parmak izine bağlıdır; eşik veya NMS değişince eski kutular kullanılmaz.

## Durum

- ✅ Altın sayılar testte: (756, 301) → 39.92531, 32.87183 · T0122 < 1 m, 2. aday T0032 ~41 m · 13:15'te 5,5 km → 14:10'da 1,6 km · yol 10,5 km · 6,2 m/s · ETA ~4,4 dk
- ✅ 20 tuzak track hiçbir karede eşlenmiyor (yalnızca karenin içindeki track'ler aday)
- ✅ Zaman-duyarlı rapor doğrulama; 12:25/12:35 raporları ✗ ÇELİŞİYOR (regresyon testi)
- ✅ Gerçek detektör (yolov8n) + gerçek LLM (glm-5.3) ile uçtan uca; img_000860 → KRİTİK, grounding geçiyor
- ✅ Grounding, prompt injection, LLM kesintisi, model yüklenememe ve çözünürlük farkı testleri
- ✅ Arayüz: triage + kare detayı + zaman kaydırıcısı + karar kaydı (FastAPI + React, internetsiz çalışır)
- ✅ Sohbet: araç çağıran döngü (≤ 6 adım), kare bağlamı, tıklanabilir kanıt çipleri, cevap grounding'i
- ⏳ Risk kalibrasyonu (altın set), ekibin modeli
