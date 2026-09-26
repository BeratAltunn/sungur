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

İmaj arayüzü derler, CPU'ya özel torch, transformers ve yedek yolov8n ağırlıklarını kurar. Resmî veri paketi (`../data`) ve D-FINE ağırlıkları (`models/dfine_m_kaggle.pth`) imaja girmez, salt okunur volume ile bağlanır; `.env` de imaja girmez (`.dockerignore`). `runs/` (iz, kararlar) ve `cache/` (tespit + LLM önbelleği) host'a bağlıdır; önbellek depoda olduğu için demo internetsiz ve LLM'siz de açılır. Docker içinde Apple GPU yoktur, "canlı yeniden değerlendir" CPU'da birkaç saniye sürer; canlı demoyu doğrudan makinede (`make app`) çalıştırmak daha hızlıdır.
Resmî paket host'ta yoksa `docker-compose.yml`'deki iki `data` satırını yorumlayın; sistem dev verisiyle açılır.

**Doğrudan makinede:**

```bash
cd stage2
make install                           # Python paketleri (torch + transformers) + yedek yolov8n
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

Arayüz ekranları: `#/` triage (ortak harekât resmi: uyarılar · harita · seçili kare önizlemesi) · `#/frame/<id>` kare detayı · `#/handover` vardiya devri (kurala dayalı, yazdırılabilir) · `#/brief/<id>` eskalasyon kartı (amir için, yazdırılabilir) · `#/impact` etki (vardiya simülasyonu: karar, araç varmadan önce mi?) · `#/?replay=1` kuyrukta vardiya oynatma · `#/label` kör etiketleme.

Vardiya simülasyonu (`src/sentinel/impact.py`) bir operatör zamanı modelidir, kanıt değildir: kare başına süreler `config.yaml → impact` varsayımlarından başlar, kronometre testi (`calibration/stopwatch.csv`) ve üründeki açılış → karar ölçümü yeterli olunca onlarla değişir.

## Mimari (kısaca)

```
src/sentinel/
  domain/models.py        tüm pydantic modeller (ekip sözleşmesi)
  data/                   adapters (dosya formatı) + Repository (zaman ızgarası, uzay-zaman sorguları)
  perception/             Detector arayüzü: dfine (Kaggle ekibinin D-FINE-M) · ultralytics (yedek) · callable · oracle (test) · cache
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

- **Taktik ekran (triage):** üstte durum çubuğu (gizlilik bandı, saat, tesis tehdit durumu, alt sistemler) ve nöbet devri şeridi; solda risk sıralı uyarılar (arama, bölge/seviye/durum filtreleri), ortada bölge haritası (yalnızca kararsız KRİTİK kareler dolu renkte), sağda seçili karenin önizlemesi. Tek tıklama seçer; <kbd>J</kbd>/<kbd>K</kbd> gez, <kbd>Enter</kbd> ya da çift tıklama aç.
- **Kare detayı:** brief (seviye → manşet → önerilen eylem → kanıt çipli bulgular → grounding rozeti), kutulu görüntü, 2 saatlik izlerle harita (araçlardan üsse tahmini varış vektörleri; üs dost dikdörtgen, araçlar kimliği belirsiz dört yaprak sembolü) ve **zaman kaydırıcısı**, sekmeler: *Neden?* (faktör katkıları, taban kuralı), *Raporlar* (satıra tıkla → harita ve kaydırıcı rapor saatine gider), *Araçlar*, *Ajan izi*. Kararlar: Onayla (<kbd>A</kbd>), Seviyeyi değiştir (gerekçe zorunlu), Amire ilet (<kbd>E</kbd>, brief panoya kopyalanır), Geri al. <kbd>Space</kbd> oynat, <kbd>Esc</kbd> kuyruğa dön.
- **Canlı yeniden değerlendir:** tespit önbelleğini atlayıp 6 adımı yeniden çalıştırır (demodaki canlı çalıştırma).

Görsel dil Astro UXDS koyu temasından (renk ve durum tokenleri, Roboto / Roboto Mono; `web/src/styles.css` başı). Durum renkleri dolgu ve sembolde kullanılır, metinler ≥ 6:1 kontrastlıdır (`tests/ui/test_contrast.py`).

Arayüz hiçbir kanıt hesaplamaz; sayıların hepsi `EvidencePacket`'ten gelir. Kod: `web/src/pages` (ekranlar), `web/src/components` (parçalar), `web/src/lib` (API tipleri ve biçimlendirme). Geliştirirken `make app` açıkken `make dev-web` (:5173, anlık yenileme).

REST uçları `src/sentinel/interfaces/api.py`'de; her biri `SentinelService`'in bir metodunu çağırır. Açılışta 40 kare ağ çağrısı yapılmadan (LLM önbelleğinden) ısıtılır; önbellekte olmayan bir brief kare açılınca üretilir, deterministik kanıt ise beklemeden gelir.

## Sohbet

Her ekranda sağ alttaki **Sohbet** düğmesi (<kbd>/</kbd>) yan paneli açar. Açık bir kare varsa soru o karenin bağlamında sorulur ("bu kamyon neden riskli?"). Cevaptaki `img_…`, `V…`, `T…`, `R…` kimlikleri tıklanabilir: kareyi açar ya da haritada aracı/raporu gösterir.

- LLM soruyu cevaplamak için **salt-okur araçlar** çağırır (`src/sentinel/agent/tools.py`): `list_frames`, `analyze_image`, `get_track`, `find_reports`, `zone_summary`. Araçlar mutlak koordinat döndürmez; konumlar üsse mesafe, yön ve bölge olarak gelir.
- En fazla 6 LLM adımı. Cevaptaki her sayı, saat ve kimlik o turdaki araç çıktılarıyla karşılaştırılır; tutmazsa bir düzeltme turu, yine tutmazsa cevap **"doğrulanamayan değerler"** uyarısıyla gösterilir (sessizce geçmez).
- Sayımları araçlar verir (`toplam`, `kaynaklara_gore` …); LLM saymaz.
- Prompt: `src/sentinel/agent/prompts/chat_v1.md`. Her tur `runs/trace.jsonl`'e araç çağrılarıyla birlikte yazılır.
- Yanıt süresi büyük ölçüde LLM uç noktasına bağlı (Evren/glm-5.3 ile 5–45 sn ölçülmüştü); demo soruları önbelleğe alınır.

## Kalibrasyon, kör etiketleme, kronometre, demo

- **Kör etiketleme (altın set):** http://127.0.0.1:8000/#/label — etiketleyici adını girer; kareler çekim saatine göre gelir, sistemin seviyesi/skoru/brief'i ve araç renkleri gizlidir. Klavye: <kbd>1</kbd>–<kbd>4</kbd> seviye (DÜŞÜK→KRİTİK), <kbd>Enter</kbd> kaydet ve sonraki, <kbd>J</kbd>/<kbd>K</kbd> gez. Etiketler `calibration/labels/<ad>.jsonl`'e yazılır (git'e girer).
- **Kalibrasyon raporu:** `make calibrate` → `runs/calibration.md`: etiketleyici uyumu (ağırlıklı Cohen's κ), sistem ↔ altın set karışıklık matrisi, YÜKSEK/KRİTİK recall (hedef %100), yanlış alarm oranı (hedef ≤ %20) ve her ağırlık ±%20 değişince kaç karenin seviyesinin değiştiği.
- **Kronometre testi:** `python3 scripts/stopwatch.py manual <kare> --who <ad>` (yalnızca ham dosyalar) ve `… system <başka kare> …` (arayüzle); özet `make stopwatch`. Sonuçlar `calibration/stopwatch.csv`.
- **Demo:** akış ve B planları `DEMO.md`. Demo kareleri ve beklentiler `config.yaml → demo`; `make demo-check` (LLM çağırmaz) ve `make demo-check-chat` (sohbet soruları da).

## Kaggle modeli (Ekip-1): D-FINE-M

Ekibin kontrol noktası (`model_epoch_11_iter_6431_ap50_712.pth`, AP50 0,712) `models/dfine_m_kaggle.pth` olarak durur (git'e girmez; yalnızca çıkarım için gereken EMA ağırlıkları, 79 MB — orijinal 314 MB dosya optimizer durumunu da taşır, tespitler bit düzeyinde aynıdır) ve `kind: dfine` ile çalışır (`perception/dfine.py`):

- Orijinal D-FINE/DEIM anahtarları transformers'ın `DFineForObjectDetection` düzenine çevrilir; yükleme **strict**, eşlenmeyen tek anahtar bile hata verir. EMA ağırlıkları kullanılır.
- Ön işleme eğitimle birebir (Ekip-1): RGB, `cv2.resize` ile 1408×800'e düz gerdirme (letterbox yok), yalnızca /255 (mean/std yok). Sınıf indeks sırası `[car, truck, van, bus]`: yarışma sayfasındaki sıradan farklı; Kaggle train karışıklık matrisiyle çıkarıldı, Ekip-1 teyit etti. Kaggle train'den 60 görüntüde recall %89 (IoU 0,5, güven ≥ 0,4).
- Cihaz MPS → CUDA → CPU. Mac M1'de ~0,3 sn/kare.

Başka bir model gelirse: ultralytics `.pt` için `kind: ultralytics` + `class_map`; kendi inference kodu için `kind: callable`, `callable.target: "paket.modul:predict"`. Sözleşme (D-FINE modülü de `sentinel.perception.dfine:predict` olarak sunar):
   ```python
   def predict(image_path: Path) -> list[tuple[str, float, float, float, float, float]]:
       """[(label, conf, x, y, w, h), ...]  px, sol-üst köşe (Kaggle submission formatı)"""
   ```

Tespitler `cache/detections/<detektör>/` altında önbelleğe alınır. `τ_op` (`detector.tau_op`) altındaki kutular silinmez, "düşük güven" katmanına düşer ve bir track ile eşleşirse terfi eder.

## LLM'i bağlamak

`.env` içindeki `GLM_BASE_URL`, `GLM_API_KEY`, `GLM_MODEL` ile herhangi bir OpenAI uyumlu uç nokta kullanılır (`config.yaml → llm.provider: openai_compat`). Anahtar yoksa ya da uç nokta düşerse şablon brief'e düşülür.

- **Şu an:** hackathon ağ geçidi, `glm-5.3-flash` (standart `Authorization: Bearer`; takım başına 15 USD, sıfırlanmaz; aynı anda en fazla 4 istek). Örnek: `.env.example`, ayrıntı: kökteki `AGENTS.md` §4.
- **Yedek:** Evren, `glm-5.3` (kişisel anahtar, `X-API-Key` başlığı → `GLM_AUTH_HEADER`); `.env.example`'da yorum satırında.
- Model her zaman düşünür: `llm.reasoning_effort: low` olmadan token bütçesinin tamamını düşünmeye harcayıp boş yanıt döndürebilir.
- Yanıtlar `cache/llm/`'e yazılır (anahtar: model + prompt sürümü + üretim ayarları + mesajlar); boş yanıt önbelleğe yazılmaz. Bütçe bekçisi 12 $'da durdurur (`runs/budget.json`).
- Prompt: `src/sentinel/agent/prompts/analyst_v3.md` (manşet ≤ 80 karakter, manşette araç kimliği yok, en kısa ETA'lı araç önde; bu araç pakette `risk.en_kisa_eta` olarak kodla seçilir). Değiştirirken yeni sürüm dosyası açın.

## Detektör kabul raporu

Yeni bir model ya da ayar için önce karşılaştırma raporunu alın:

```bash
python3 scripts/compare_detectors.py --kind dfine                      # Kaggle ekibinin modeli
python3 scripts/compare_detectors.py --kind ultralytics --weights models/yolov8n.pt   # yedek
```

Rapor 40 karede track'leri referans alarak şunları verir: yaklaşık recall, track ile doğrulanan tespit oranı, eşleme mesafesi dağılımı (kapı ayarı için), track'siz tespitler ve değişen risk seviyeleri (`runs/compare_*.json`).

D-FINE-M (resmî veri): recall **%100** (karedeki 206 track'in 206'sı), eşleme mesafesi medyan 0,17 m (p90 0,74 m), tespitlerin %72'si track ile doğrulanıyor. Track'siz 80 tespitin çoğu gerçek ama kayıtsız araç; birkaçı yinelenen kutu (D-FINE NMS'sizdir, iç içe gerçek araçlar olduğu için sezgisel NMS eklenmedi). Karşılaştırma: yolov8n (dev verisi) recall ≈ %82, medyan 0,4 m.

Veri notu: **görüntü ölçeği köşe koordinatlarıyla uyuşmuyor** (resmî veride de: eşleşen gerçek araç kutularının yerdeki boyu medyan 10 m, en fazla 60 m). Bu yüzden metre cinsinden boyut filtresi (`detector.plausible_size_m`) kapalı.

Model yüklenemezse (paket/ağırlık eksik) sistem aynı ayarlarla üretilmiş tespit önbelleğinden devam eder ve bunu belirsizlik olarak yazar. Önbellek, inference ayarlarının ve veri paketinin (`image_meta.json`) parmak izine bağlıdır; eşik, sınıf sırası ya da veri paketi değişince eski kutular kullanılmaz.

## Durum

- ✅ Altın sayılar testte: (756, 301) → 39.92531, 32.87183 · T0122 < 1 m, 2. aday T0032 ~41 m · 13:15'te 5,5 km → 14:10'da 1,6 km · yol 10,5 km · 6,2 m/s · ETA ~4,4 dk
- ✅ 20 tuzak track hiçbir karede eşlenmiyor (yalnızca karenin içindeki track'ler aday)
- ✅ Zaman-duyarlı rapor doğrulama; 12:25/12:35 raporları ✗ ÇELİŞİYOR (regresyon testi)
- ✅ Kaggle ekibinin D-FINE-M modeli + resmî veri ile uçtan uca; img_000860 → KRİTİK, R119/R125 (12:25/12:35) ✗, grounding geçiyor
- ✅ Grounding, prompt injection, LLM kesintisi, model yüklenememe ve çözünürlük farkı testleri
- ✅ Arayüz: triage + kare detayı + zaman kaydırıcısı + karar kaydı (FastAPI + React, internetsiz çalışır)
- ✅ Sohbet: araç çağıran döngü (≤ 6 adım), kare bağlamı, tıklanabilir kanıt çipleri, cevap grounding'i
- ⏳ Risk kalibrasyonu (altın set), ekibin modeli
