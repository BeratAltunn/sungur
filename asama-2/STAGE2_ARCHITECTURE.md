# Aşama 2: Saha Raporu Destekli Risk Ajanı (Mimari Taslağı)

> Durum: taslak v0. Resmî veri paketi ve tespit modeli (Kaggle ekibinden) sonra gelecek. O zamana kadar her şey
> `Detector` arayüzü üzerinden bir yedek modelle geliştirilecek.

## 1. Görev özeti

Bir üssü koruyoruz. Etrafında 8 bölge var ve bu bölgeler drone'larla izleniyor. Ajana bir görüntü verildiğinde
**üs için risk var mı, ne kadar kritik, neden** sorularına kısa ve gerekçeli bir brief üretmesi gerekiyor.

Zorunlu 4 adım (bilgilendirme dokümanı + slayt 11):
1. Görseldeki araçları tespit et (Aşama 1'in modeli)
2. Piksel konumlarını harita bilgisiyle gerçek koordinatlara çevir
3. Koordinatları hareket verisiyle eşle, son 2 saatin hızını, yönünü ve rotasını çıkar
4. Bulguları saha raporlarıyla birlikte değerlendir ve risk analizi yap. Raporların bir kısmı **yanlış ya da ilgisiz**, bu yüzden kendi tespitimize güveniyoruz.

Değerlendirme kriterleri:

| Kriter | Ağırlık |
|---|---|
| Kaggle skoru (Aşama 1 tespit modeli) | %20 |
| Teknik kalite ve mimari | %15 |
| Problemin önemi ve çözümün sağladığı iş değeri | %20 |
| Çalışan ürün ortaya koyabilme | %20 |
| Ürün düşüncesi ve kullanıcı deneyimi | %20 |
| Sunum ve demo | %5 |

Demoda ajanın en az 1–2 görüntüde gerçekten çalıştığını göstermemiz gerekiyor.
LLM için takım başına 15 $ GLM API kredisi var; anahtarlar 2. aşamada dağıtılacak.

## 2. Veri: doğrulanmış gerçekler

(geliştirme verisi üzerinde ölçüldü; resmî paketle aynı senaryo, teslim sürümünde depodan kaldırıldı)

| Kaynak | Yapı | Not |
|---|---|---|
| `image_meta.json` | `{img_id: {width_px, height_px, capture_time "HH:MM", corner_coordinates{top_left, top_right, bottom_left, bottom_right: [lat, lon]}}}` | 40 kare, bölge başına 5. Üsten ~1,6 / 2,6 / 3,5 / 4,4 / 5,3 km halkalarda. Çekim saatleri 10:10–15:50, hepsi 5 dk ızgarasında. Kareler yerde ~110–370 m genişliğinde. |
| `zones.json` | `base{name, lat, lon}`, `zones[{name, center}]` | 8 bölge merkezi üsten tam 3200 m uzakta (K, KD, D, GD, G, GB, B, KB). Adlar ASCII (`Dogu Yolu`). |
| `tracks.csv` | `track_id,time,lat,lon` | 226 track, **her biri tam 25 nokta** (2 saat, 5 dk). **Her track'in son noktası bir karenin çekim saatine denk geliyor.** 206'sı o anda karenin içinde. 20'si karenin **7–26 m dışında**; bunlar eşleme için tuzak. |
| `field_reports.json` | `{time, source, text}` | 137 rapor (98 official, 39 third_party), 08:35–15:15. Yaklaşık 72'sinde metin içinde koordinat var (`39.9253N 32.8718E`). Görüntüyle bağlantı **verilmiyor**. |

**Doğrulanan formüller** (organizatör örneğindeki sayıları birebir üretiyor):
- Piksel → koordinat: `lon = TL.lon + (cx/W)·(TR.lon − TL.lon)`, `lat = TL.lat + (cy/H)·(BL.lat − TL.lat)`. Kutu **merkezi** kullanılıyor, kuşbakışı varsayılıyor. img_000860 kamyonu (756, 301) → 39.92531, 32.87183 veriyor.
- Mesafe: eşdikdörtgen yaklaşım, `111320 m/°` ve `cos(lat_üs)` ile. Organizatör verisi bununla üretilmiş. T0122 için: 13:15'te üsse 5,5 km, 14:10'da 1,6 km; 2 saatlik yol 10,5 km; son 10 dk hızı ~6,2 m/s.
- Organizatör örneğinde eşleme: T0122 <1 m, en yakın ikinci aday T0032 41 m. Yani track noktaları tespit merkezine çok yakın düşüyor ve dar bir kapı (gate) yeterli.

### Önemli bulgu: raporlar zamanla birlikte doğrulanmalı

Organizatör örneğinde 12:35 tarihli resmi rapor ("39.9253N 32.8718E çevresinde 1 ağır araç, hareketleri olağan")
**sadece konuma bakılarak** "tespitle uyumlu" sayılıyor. Oysa T0122 12:35'te o noktaya **5,6 km uzaktaydı** ve o
saatte o noktanın 200 m yakınında hiçbir track yoktu. Kamyon oraya ancak 14:05–14:10 arasında hızlı bir atakla geldi
(önce 40 + 20 + 45 dk duraklamalar, sonra 10 dakikada 5,3 km'den 1,6 km'ye). Bu durumda rapor, gelecek bir aracı
"olağan" diye gösteren **şüpheli bir rapor** gibi okunmalı.
→ **Tasarım kararı:** bir raporun iddiası, track'lerin *raporun kendi saatindeki* durumuyla karşılaştırılır.
Görüntünün çekim saatindeki durum bu karşılaştırma için kullanılmaz.

## 3. Tasarım ilkeleri

1. **Sayıları araçlar üretir, LLM yorumlar.** Konum, mesafe, hız ve eşleme deterministik Python koduyla hesaplanır. LLM hesap yapmaz. Brief'teki her sayı `EvidencePacket`'ten gelir ve bir grounding kontrolünden geçer.
2. **Kendi tespitimiz raporlardan önce gelir.** Rapor ancak bizim kanıtımızla karşılaştırıldıktan sonra kullanılır.
3. **Tak-çıkar model.** `Detector` arayüzü sayesinde Kaggle modeli geldiğinde tek satır config değişikliğiyle bağlanır.
4. **Sağlayıcıdan bağımsız LLM.** GLM'e OpenAI uyumlu istemciyle bağlanılır (`base_url` + `model` config'ten). Test için `MockLLM` kullanılır.
5. **Her adım izlenebilir.** Adım girdi/çıktıları `trace.jsonl`'e yazılır. UI bu izi adım adım gösterir; mentorlar ve jüri için "ajan ne yaptı" görünür olur.
6. **Bütçe bilinci (15 $).** Tespit sonuçları ve LLM yanıtları önbelleğe alınır. "Değerlendir" isteği görüntü başına 1 LLM çağrısı yapar. Araç çağıran döngü (tool-calling) sadece sohbette çalışır ve adım limiti vardır.
7. **Zarif bozulma.** LLM erişilemezse kural tabanlı skor ve şablon brief yine üretilir. Canlı demoda sistem çökmez.

## 4. Akış

```
image_id  (+ opsiyonel kullanıcı sorusu)
   │
   ▼
[1] Perception   Detector.detect(img) → [Detection(label, conf, bbox)]      conf ≥ τ_op
   │
   ▼
[2] Geo          bbox merkezi → (lat, lon) · üsse mesafe/yön · bölge
   │
   ▼
[3] Tracking     t = capture_time → track konumları → Hungarian eşleme (gate)
   │             eşleşen track → hız, yön, rota, duraklamalar, yaklaşma, ETA
   │             eşleşmeyen tespit / karede olup tespit edilmeyen track → belirsizlik
   ▼
[4] Reports      parse → iddialar (claims) → uzay+zaman ilgililiği → doğrula
   │             DOĞRULANDI / ÇELİŞİYOR / DOĞRULANAMAZ / İLGİSİZ
   ▼
[5] Risk         özellikler → açıklanabilir skor (0–100) → seviye
   │
   ▼
EvidencePacket  (şemalı JSON; brief'teki tüm sayılar buradan gelir)
   │
   ▼
[6] LLM Analyst  (GLM) → RiskBrief (şemalı JSON) → grounding kontrolü → Türkçe brief
   │
   ▼
UI (web) / CLI   +  trace.jsonl
```

## 5. Modüller

### 5.1 Data (`data/`)
- `pydantic` modelleri: `ImageMeta`, `Zone`, `Base`, `TrackPoint`, `Track`, `FieldReport`.
- `Repository`: dosyaları bir kez yükler ve indeksler:
  - `tracks_at(t) -> ndarray[N, 2]` (5 dk ızgarası, gerekirse doğrusal interpolasyon)
  - `track(track_id) -> Track`
  - `reports_between(t0, t1)`
- Zaman "HH:MM" olarak geliyor. Tek bir gün olduğu için içeride gece yarısından itibaren dakika olarak tutulur.

### 5.2 Perception (`perception/`)
```python
class Detector(Protocol):
    def detect(self, image_path: Path) -> list[Detection]: ...
# Detection: label ∈ {car, van, truck, bus}, conf, x, y, w, h (px, sol-üst köşe; Kaggle formatıyla aynı)
```
- `KaggleModelDetector`: ekibin modeli (ağırlık dosyası + kendi inference kodu).
- `CocoYoloDetector` (geçici): COCO ile önceden eğitilmiş YOLO. car/truck/bus eşleniyor, `van` yok. Model gelene kadar gerçekçi bir yedek.
- `OracleDetector` (sadece test): çekim anındaki track noktalarını piksele geri projekte eder, sınıfı bilinmez. Pipeline'ı model olmadan uçtan uca test etmeyi sağlar. **Demoda kullanılmaz.**
- `CachedDetector`: sonuçları `cache/detections/{img}.json`'a yazar. Demo canlı inference'a bağımlı kalmaz.
- **Eşik:** Kaggle'da düşük güvenli kutu göndermek zararsız. Ajanda ise yanlış pozitif "hayalet tehdit" üretir. Bu yüzden ayrı bir operasyonel eşik `τ_op` kullanılır (başlangıç 0,4, kalibre edilecek).

### 5.3 Geo (`geo/`)
- `GeoReferencer(meta)`: 4 köşeden **bilineer** interpolasyon yapar. Eksene hizalı kareler için organizatörün doğrusal formülüne indirgenir. Ters dönüşüm (lat/lon → px) OracleDetector ve çizim için kullanılır.
- `geodesy`: eşdikdörtgen `to_local_m(lat, lon) -> (x_east, y_north)`, `distance_m`, `bearing_deg` (pusula, 0 = K), 8'li yön adı (K, KD, ...).
- `zone_of(lat, lon)`: en yakın bölge merkezi. Üsse mesafe ve üsse göre yön de burada hesaplanır.

### 5.4 Tracking (`tracking/`)
- `TrackMatcher`: çekim anındaki track noktaları ile tespit merkezleri arasındaki maliyet matrisi `scipy.optimize.linear_sum_assignment` ile çözülür. Kapı ~10 m (kalibre edilecek). Her eşleme için `margin = 2. en yakın − en yakın` güven göstergesi olarak döner.
- Çıktılar: eşleşen çiftler, **track'siz tespit** (kayıtsız araç: kendi başına dikkat noktası), **tespitsiz track** (kare içinde olup model kaçırmış: belirsizlik olarak raporlanır).
- `Kinematics(track, base)`:
  - `d(t)` üsse mesafe serisi, `closing_speed` (son 10 dk, + değer yaklaşıyor demek), 2 saatteki mesafe değişimi
  - anlık/ortalama/maks hız, rota uzunluğu, pusula yönü, **hız vektörünün üsse doğrultuyla hizası** (cos)
  - duraklama segmentleri (hız < 0,5 m/s ve ≥ 2 adım): sayısı ve toplam süresi. "Dur-kalk yaklaşma" deseni.
  - ETA = `d_now / closing_speed` (yaklaşıyorsa)
  - geçtiği bölgeler

### 5.5 Reports (`reports/`)
- **Parser (önce deterministik):**
  - koordinat regex'i `(\d+\.\d+)N\s+(\d+\.\d+)E`
  - bölge adı eşleme (Türkçe karakter normalizasyonu ile)
  - araç tipi sözlüğü: kamyon→truck, otomobil→car, panelvan→van, otobüs→bus, "ağır araç"→{truck, bus}
  - sayı ("5 kamyonun"), renk (mavi/kırmızı/sarı)
  - iddia tipi: `COUNT`, `STATIONARY` ("uzun süredir hareketsiz", "bir saatten uzun süredir yerinden ayrılmadı", "park halinde"), `MOVING_TO_BASE`, `LEAVING`, `TRANSIT`, `FRIENDLY_ID` ("dost devriye", "bize bağlı unsur", "planlı ikmal aracı, kimlik teyidi"), `ZONE_NO_HEAVY` ("ağır araç hareketi yok"), `DENSITY`, `NOISE`
  - Regex'in kaçırdığı raporlar için LLM ile toplu çıkarım yapılır. Tek sefer çalışır ve önbelleğe alınır.
- **Gürültü sınıfı:** hava durumu, lojistik konvoyu duyurusu, planlı tatbikat, "dün gece doğrulanmamış ihbar", "ihbar incelendi, doğrulanamadı", telsiz kopukluğu, "sabah devriyesi olağandışı durum bildirmedi". Bunlar `İLGİSİZ` sayılır ama bağlam olarak saklanır; ör. "tatbikat nedeniyle dost unsurlar olacak" kimlik iddialarını kör kabul etmek için gerekçe değildir.
- **İlgililik:** rapor noktası karenin veya eşleşen track rotasının R m yakınında mı ve rapor saati [capture − 2 saat, capture] aralığında mı? Bölge düzeyindeki raporlarda bölge adı eşleşmesi aranır.
- **Doğrulama (uzay + zaman):** iddia, track'lerin **raporun saatindeki** durumuyla karşılaştırılır:
  - `STATIONARY`: o noktadaki track rapordan önceki 60 dk boyunca gerçekten hareketsiz miydi?
  - `COUNT`: o saatte R m içinde kaç track var? Uygunsa tespit sınıflarıyla karşılaştırılır.
  - `MOVING_TO_BASE` / `LEAVING`: `closing_speed` işareti ile karşılaştırılır.
  - `FRIENDLY_ID`: tip tutuyor mu (rapor "otomobil" diyor, biz kamyon görüyoruz → ÇELİŞİYOR), davranış tutuyor mu?
  - `ZONE_NO_HEAVY`: o bölgenin karelerinde truck/bus var mı?
- Kaynak güveni için sadece **ön-değer** kullanılır (official > third_party). Kanıt her zaman ön-değerin önüne geçer. **Kimlik iddiası içeren ama kanıtla çelişen rapor**, riski düşürmek yerine **artırır** (aldatma göstergesi).

### 5.6 Risk (`risk/`): Yetenek–Fırsat–Niyet
Açıklanabilir, kurala dayalı tehdit değerlendirmesi. Her faktör hangi kenara ne kadar katkı verdiğiyle birlikte döner ve UI'da "neden" olarak gösterilir. Eşikler ve puanlar `config.yaml → risk`'te.

| Kenar | Soru | Girdiler (0–100 alt puan → DÜŞÜK/ORTA/YÜKSEK bant) |
|---|---|---|
| Yetenek | ne? | sınıf (kamyon/otobüs 80, panelvan ve teyitsiz sınıf 50, otomobil 20); konvoy üyesi grup olarak en az 80 |
| Fırsat | nerede? | üsse mesafe: < 2 km YÜKSEK, 2–3,5 km ORTA, üstü DÜŞÜK |
| Niyet göstergeleri | ne yapıyor? | başlangıç 20 (bilinmiyor); yaklaşıyor +25, kanıtla çelişen kimlik iddiası +50, kare çevresinde çelişen kimlik +25, kayıtsız araç +25, uzaklaşıyor −25, teyitli dost −50 |

Seviye matrisi: üçü YÜKSEK → KRİTİK · iki YÜKSEK + ORTA → YÜKSEK · hiçbiri DÜŞÜK değil → ORTA · bir kenar DÜŞÜK → en fazla ORTA · iki+ DÜŞÜK → DÜŞÜK.
Taban kuralları: ETA < 10 dk + (teyitli ağır araç ya da niyet YÜKSEK) → KRİTİK; niyet + fırsat YÜKSEK, yetenek + fırsat YÜKSEK (aklayıcı kanıt yoksa) ya da < 2 km'de emin kayıtsız araç → en az YÜKSEK.
ETA bir kenar değil aciliyet eksenidir (taban + kuyruk sırası). Kare seviyesi = en yüksek araç seviyesi; sıralama skoru = üç alt puanın geometrik ortalaması. Duraklamalar skora girmez (bu veride neredeyse her araç bekle-ilerle yapıyor).

### 5.7 Agent (`agent/`)
- **LLM istemcisi:** OpenAI uyumlu SDK. `GLM_BASE_URL`, `GLM_API_KEY`, `GLM_MODEL` `.env`'den okunur. Token sayımı ve maliyet trace'e yazılır.
- **İki mod:**
  - `evaluate(image_id)`: sabit plan. [1]–[5] deterministik çalışır, ardından **tek LLM çağrısı** (analyst) yapılır. Ucuz, tekrarlanabilir, demoda güvenli.
  - `chat(question)`: araç çağıran döngü (en fazla ~6 adım). Kullanıcı "bu kamyon neden riskli?", "hangi raporlar yanlış?", "Doğu Yolu'nda gün boyu ne oldu?" gibi sorular sorabilir.
- **Araçlar (function calling):** `analyze_image`, `get_track(track_id)`, `tracks_near(lat, lon, time, radius_m)`, `find_reports(lat, lon, radius_m, t_from, t_to | zone)`, `get_zone(name)`, `list_frames(zone?)`.
- **Çıktı şeması (`RiskBrief`):**
  ```
  image_id, risk_level (DÜŞÜK|ORTA|YÜKSEK|KRİTİK), risk_score
  headline                                  # tek cümle
  key_findings[ {vehicle_ref, statement, evidence_refs[]} ]
  report_assessment[ {report_id, verdict, reason} ]
  recommended_action
  confidence, uncertainties[]
  ```
- **Grounding kontrolü:** metindeki her sayı `EvidencePacket`'te toleransla aranır. LLM seviyesi kural skorundan en fazla 1 kademe sapabilir ve sapınca gerekçe vermek zorundadır. Kontrol başarısız olursa bir kez yeniden sorulur, yine olmazsa şablon brief'e düşülür.
- Prompt'lar ayrı dosyalarda tutulur (`agent/prompts/*.md`) ve sürümlenir.

### 5.8 Arayüz (`interfaces/`)
- **Web (FastAPI + React; ilk taslakta Streamlit'ti, gerekçe PROJECT_DESIGN Ek A-9):**
  1. Görüntü seçimi → tespit kutuları görüntü üzerinde
  2. Harita (pydeck/folium): üs, 8 bölge, kare çokgeni, eşleşen track'lerin 2 saatlik izi, rapor pinleri (doğrulama rengine göre)
  3. Adım adım iz (organizatörün "Uçtan Uca Örnek"indeki gibi 1…N adım)
  4. Risk rozeti + brief + faktör katkıları + rapor tablosu (✓ / ✗ / ?)
  5. Sohbet kutusu
- **Triage paneli (iş değeri vurgusu):** 40 kare risk skoruna göre sıralanır. Operatör "önce nereye bakmalıyım?" sorusunun cevabını tek ekranda görür.
- **CLI:** `sentinel evaluate img_000860 [--json]`, `sentinel batch`. Yedek demo yolu ve test için.

### 5.9 Gözlemlenebilirlik ve test
- `trace.jsonl`: adım adı, girdi özeti, çıktı, süre, LLM token/maliyet.
- `pytest` birim testleri (dev verisindeki bilinen sayılarla):
  - geo: img_000860 (756, 301) → 39.92531, 32.87183
  - eşleme: T0122 < 1 m, 2. aday T0032 ~41 m
  - kinematik: T0122 13:15 → 5,5 km, 14:10 → 1,6 km, yol 10,5 km, son 10 dk ~6 m/s
  - rapor parser: 137 raporun hepsi bir iddia tipine düşmeli
  - kapı: karenin 7–26 m dışındaki 20 track, kenardaki tespitlere yanlış eşlenmemeli
- Entegrasyon: `OracleDetector` + `MockLLM` ile 40 kare hatasız çalışmalı.

## 6. Klasör yapısı

```
dizdar/
  pyproject.toml            # python 3.12, pydantic v2, numpy, pandas, scipy, openai, streamlit, pydeck, pytest, ruff
  .env.example              # GLM_BASE_URL, GLM_API_KEY, GLM_MODEL
  config.yaml               # veri yolları, eşikler, risk ağırlıkları, detector seçimi
  src/sentinel/
    domain/models.py        # tüm pydantic modeller (Detection, GeoDetection, Match, Kinematics, Claim, Evidence, RiskBrief)
    data/repository.py
    perception/{base,kaggle_model,coco_yolo,oracle,cache}.py
    geo/{georef,geodesy,zones}.py
    tracking/{matcher,kinematics}.py
    reports/{parser,relevance,verifier}.py
    risk/{features,scoring}.py
    agent/{llm,tools,analyst,chat,grounding}.py + prompts/
    pipeline.py             # evaluate_image(image_id) -> EvidencePacket
    observability/trace.py
    interfaces/{cli,app}.py
  tests/
  data/                     # resmî veri paketi buraya (git'e girmez)
```

## 7. Kaggle ekibiyle arayüz sözleşmesi

Ekipten istenecekler:
- Ağırlık dosyası + framework (ör. ultralytics YOLO `.pt`), sınıf sırası, eğitimdeki `imgsz`
- Minimal inference fonksiyonu. Çıktı **Kaggle submission formatının aynısı** olsun: `label conf x y w h` (px, sol-üst). Hem ekip hem ajan zaten bu formatı kullanıyor.
- Mac'te (MPS/CPU) görüntü başına süre. Demo için 40 karenin tespitleri önceden hesaplanıp önbelleğe alınacak, canlıda 1–2 görüntü gerçekten çalıştırılacak.
- Operasyonel eşik için öneri: sınıf başına precision–recall eğrisi varsa τ_op seçimine yardımcı olur.

## 8. Organizatöre sorulacaklar

- Resmi dosyalar slayt 13–14'teki formatta mı? Track'ler karedeki bütün araçlar için mi var?
- 40 görüntünün tam çözünürlükleri; `corner_coordinates` her zaman eksene hizalı mı?
- Hangi GLM modeli ve endpoint? Function calling / vision desteği ve hız limitleri?
- Beklenen bir risk ölçeği ya da çıktı formatı var mı? Çekim saatinden **sonraki** raporlar kullanılabilir mi?
