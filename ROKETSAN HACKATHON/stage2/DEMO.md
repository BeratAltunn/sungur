# Canlı demo akışı (4 dk 30 sn + 30 sn tampon)

Tasarım: `PROJECT_DESIGN.md` §4.6. Bu dosya o senaryonun **şu anki arayüzdeki tıklamalarını** ve B planlarını içerir.
Demo kareleri ve beklentileri `config.yaml → demo` altında; `make demo-check` bunları korur.

## Demodan önce (30 dk önce)

```bash
cd "ROKETSAN HACKATHON/stage2"
make demo-check                                   # 7/7 YEŞİL olmalı (LLM çağırmaz)
PYTHONPATH=src python3 -m sentinel demo-check --chat   # sohbet soruları da; ~1 dk, soruları önbelleğe alır
make app                                          # ya da Docker: docker compose up -d
```

- Tarayıcıda http://127.0.0.1:8000 → üst bar: **"LLM çevrimiçi · glm-5.3"** ve **"Model: Yedek yolov8n"** (Kaggle modeli bağlandıysa onun adı).
- Tarayıcı penceresi ≥ 1280×800, yakınlaştırma %100. Sohbet paneli kapalı başlasın. İpucu kartı daha önce kapatılmış olsun.
- Sohbette eski konuşma varsa **Temizle**: önbellek soruyla birlikte konuşma geçmişine de bağlıdır; geçmiş varsa cevap önbellekten gelmez (5–45 sn).
- `cmd+shift+R` ile sayfayı sert yenile (eski önbellekli arayüz kalmasın).
- **Demo sırasında `scripts/precompute.py` çalıştırma**; brief'ler önbellekte.

## Akış

| Süre | Ekran | Ne yapıyorsun | Ne söylüyorsun |
|---|---|---|---|
| 0:00–0:30 | Başlık slaytı | — | "Nöbetteki operatöre 2,5 dakikada bir yeni bilgi geliyor. Raporların bir kısmı yanlış, bir kısmı kasıtlı. Bir karenin elle analizi ~X dk sürüyor." (X = kronometre testi, `calibration/stopwatch.csv`) |
| 0:30–1:00 | **Triage** | Nöbet devri kartını göster, kuyruğun en üstünü işaret et | "40 kare ve 137 rapor işlendi. Operatör artık geliş sırasıyla değil, risk sırasıyla bakıyor. En acil kare img_000860." |
| 1:00–2:00 | **Kare detayı** (`Kareyi aç →`) | Üstte **↻ Canlı yeniden değerlendir** → sayfa **Ajan izi** sekmesine kayar, 6 adım tek tek dolar (her satırda gerçek süre ve okunur özet: "6 araç hareket kaydıyla eşleşti … V6→T0122", "✗2 · çelişen R069, R075"). Adımlar izlenebilsin diye en az 250 ms arayla gösterilir; toplam gerçek süre bildirimde yazar (ısınmış modelle ~0,1 sn, ilk çalıştırmada model yüklemesiyle ~2–3 sn) | "Tespit, koordinat, T0122 ile 1 metrenin altında eşleşme, kinematik, rapor doğrulama, risk. Organizatörün 4 adımı canlı." Haritada **▶ Oynat**: 2 saatlik iz, duraklamalar, son 10 dakikadaki atak. |
| 2:00–2:50 | **Aha anı** | Kaydırıcıdaki **12:35 ✗** işaretine tıkla (ya da Raporlar sekmesinde R075). Kaydırıcının altında rapor kartı açılır: rapor metni + "12:35'te noktanın 200 m içinde kayıtlı araç yok … T0122 5,6 km" | "Resmî rapor 'olağan' diyor. Sadece konuma baksaydık uyumlu çıkardı. Ama 12:35'te bu noktada kimse yok; bu karedeki araçlar kilometrelerce uzakta." Sonra **12:25 ✗** (R069): "Bu da 'bize bağlı otomobil' diyor; biz kamyon görüyoruz ve o saatte orada araç yok. Çelişen kimlik iddiası riski düşürmüyor, artırıyor." |
| 2:50–3:20 | **Brief** | Manşet, önerilen eylem, "✓ … sayı kanıtla doğrulandı" rozeti; brief'teki bir çipe (V6) tıkla → haritada araç | "LLM hesap yapmıyor, sadece yazıyor. Brief'teki her sayı kanıtla karşılaştırılıyor." |
| 3:20–3:50 | **Karşıt kare** | `Esc` → kuyrukta **img_006388** (Kuzeybatı Yolu, ORTA) | "Bu da üsse 1,7 km, neredeyse aynı mesafe. Ama hiçbir araç yaklaşmıyor ve rapor doğrulanmış: ORTA. Yakınlık tek başına alarm sebebi değil." (Kalibrasyondan sonra seviye değişirse `config.yaml → demo`'yu güncelle.) |
| 3:50–4:10 | **Sohbet** (`/`) | img_000860 açıkken yaz: **"Bu karedeki kamyon neden riskli?"** (önbellekte; 4 araç 100 puanda eşit olduğu için "en riskli araç" sorusu otomobil V2'yi gösterebilir) | "Önceden tanımlanmamış sorular da sorulabiliyor; ajan kayıtları sorgulayıp cevaplıyor, sorgular burada görünüyor." |
| 4:10–4:30 | **Etki** (`#/impact`: nöbet devri kartında **Etki →**) | Üstteki üç kutuyu göster | "Kritik karelerde elle karar, araçlar üsse vardıktan sonra geliyor: 5'te 0. NÖBETÇİ ile 5'te 5 karar varıştan önce. Kare başına süreler kronometre ve üründeki açılış→karar ölçümünden geliyor." (Kutudaki "varsayım" etiketi ölçüm yoksa görünür; sunumdan önce kronometre testini yapın.) Sonra brief başına maliyet, on-prem. |

## İsteğe bağlı: vardiya oynatma (30 sn; sohbet adımının yerine)

Kuyrukta **▶ Vardiyayı oynat** → saat kaydırıcısını **14:05**'e çek, hızı **1 dk/sn** yap, **▶ Oynat**. 14:10'da img_000860 **YENİ** rozetiyle kuyruğun tepesine düşer; uyarı şeridinde "araçlar ~14:14'te üste · NÖBETÇİ: karar 14:11 ✓ varıştan önce · Elle: inceleniyor…" ve 14:18'de "Elle: karar 14:18 ✗ varıştan sonra" görünür. Söylenecek: "Aynı operatör, aynı gün. Elle çalışırken kamyon kapıya karar verilmeden varıyor." Bitince **✕ Kapat** (açık kalırsa kuyruk simüle saatteki kareleri gösterir).

## B planları

| Sorun | Belirti | Yapılacak |
|---|---|---|
| Evren/GLM yanıt vermiyor | Canlı değerlendirmede brief "Kural tabanlı şablon", sohbette "LLM'e şu an ulaşılamıyor" | Sorun değil: brief önbellekten/şablondan gelir, kanıt ve seviye aynıdır. "Sistem LLM olmadan da çalışıyor" diye anlat. Sohbette **Tekrar dene**; yine olmazsa sohbeti atla. |
| Sohbet yavaş (> 30 sn) | "Kayıtları sorguluyor… N sn" | Önceden `demo-check --chat` ile sorulan sorular önbellekten anında gelir; **yalnızca o soruları** sor. |
| İnternet yok | Altlık harita gelmiyor | Altlık zaten kapalı; her şey yerel. LLM yoksa yukarıdaki satır. |
| Canlı değerlendirme hata verdi | Kırmızı hata kutusu | Sayfayı yenile; önbellekteki değerlendirme açılır. Canlı çalıştırma şartını CLI ile göster: `make demo`. |
| Laptop çöktü | — | Yedek laptopta `docker compose up -d` (repo + `.env` hazır). Son çare: yedek ekran kaydı. |

## Demodan sonra

Demo sırasında verilen kararlar `runs/decisions.jsonl`'e, kare açılışları `runs/views.jsonl`'e yazılır; bir sonraki prova için temiz başlamak istersen ikisini de yeniden adlandır (silme, denetim kaydıdır). Nöbet devri kartındaki "En acil" satırı karar verilmişse "onaylandı" rozetiyle görünür; demoya kararsız başlamak için bu adım gerekir.
