# Canlı demo akışı (4 dk 30 sn + 30 sn tampon)

Tasarım: `PROJECT_DESIGN.md` §4.6. Bu dosya o senaryonun **şu anki arayüzdeki tıklamalarını** ve B planlarını içerir.
Demo kareleri ve beklentileri `config.yaml → demo` altında; `make demo-check` bunları korur.

## Demodan önce (30 dk önce)

```bash
cd asama-2/stage2
make demo-check                                   # 7/7 YEŞİL olmalı (LLM çağırmaz)
make demo-check-chat                              # sohbet soruları da (demo akışındaki V7 sorusu dahil); ~1 dk, önbelleğe alır
make app                                          # ya da Docker: docker compose up -d
```

- `curl -s http://127.0.0.1:8000/api/health` → `"detector": "dfine:dfine_m_kaggle"`, `"llm": {"error": null, "enabled": true}`, `warmup.done == 40`. Üst çubukta DİZDAR logosu ve **Tehdit durumu: KRİTİK · 4 karar bekliyor** görünmeli (hiç karar verilmemiş).
- Tarayıcı penceresi ≥ 1280×800, yakınlaştırma %100. Ana harita günün araçlarını gösterir (renk = o anki tehdit seviyesi). Sohbet kapalı başlasın (sağ kenardaki sohbet ikonu). İpucu kartı daha önce kapatılmış olsun.
- Sohbette eski konuşma varsa **Temizle**: önbellek soruyla birlikte konuşma geçmişine de bağlıdır; geçmiş varsa cevap önbellekten gelmez (5–45 sn).
- `cmd+shift+R` ile sayfayı sert yenile (eski önbellekli arayüz kalmasın).
- **Demo sırasında `scripts/precompute.py` çalıştırma**; brief'ler önbellekte.

## Akış

| Süre | Ekran | Ne yapıyorsun | Ne söylüyorsun |
|---|---|---|---|
| 0:00–0:30 | Başlık slaytı | — | "Nöbetteki operatöre 2,5 dakikada bir yeni bilgi geliyor. Raporların bir kısmı yanlış, bir kısmı kasıtlı. Her kareyi elle incelemek, gelen bilgiye yetişmiyor." |
| 0:30–1:00 | **Ana ekran** (tam ekran harita) | Üst çubukta **Tehdit durumu** (en yüksek kararsız seviye ve bekleyen karar sayısı). Solda **Aktif uyarılar** şeridi risk sırasıyla; en üstteki img_000860 seçili, kartı haritada karenin yanında açık (ETA, hareket, sınıflar, anormal araçlar). Haritada günün araçları 3B arazi üzerinde; alttaki zaman çubuğuyla **Oynat** araçları hareket ettirir. **Kareyi aç** (ya da `Enter`) | "40 kare ve 137 rapor işlendi. Operatör artık geliş sırasıyla değil, risk sırasıyla bakıyor. En acil kare img_000860; kareyi açmadan haritadaki kartında ETA'sını, çelişen raporlarını ve hangi araçların anormal olduğunu görüyorum." |
| 1:00–2:00 | **Kare detayı** (`Kareyi aç →`) | Üstte **Canlı yeniden değerlendir** → sayfa **Ajan izi** sekmesine kayar, 6 adım tek tek dolar (her satırda gerçek süre ve okunur özet: "6 araç hareket kaydıyla eşleşti … V6→T0122", "✗2 · çelişen R119, R125"). Adımlar izlenebilsin diye en az 250 ms arayla gösterilir; toplam gerçek süre bildirimde yazar (ısınmış modelle ~0,1 sn, ilk çalıştırmada model yüklemesiyle ~2–3 sn) | "Tespit, koordinat, T0122 ile 1 metrenin altında eşleşme, kinematik, rapor doğrulama, risk. Organizatörün 4 adımı canlı." Haritada **Oynat**: 2 saatlik iz, duraklamalar, son 10 dakikadaki atak. |
| 2:00–2:50 | **Aha anı** (haritada araçlardan üsse kesikli **tahmini varış** vektörleri; sol üstte "4 araç üsse yaklaşıyor · en kısa ETA ~4,5 dk") | Kaydırıcıdaki **12:35 ✗** işaretine tıkla (ya da Raporlar sekmesinde R125). Kaydırıcının altında rapor kartı açılır: rapor metni + "12:35'te noktanın 200 m içinde kayıtlı araç yok … T0122 5,6 km" | "Resmî rapor 'olağan' diyor. Sadece konuma baksaydık uyumlu çıkardı. Ama 12:35'te bu noktada kimse yok; bu karedeki araçlar kilometrelerce uzakta." Sonra **12:25 ✗** (R119): "Bu da 'üsse gelen otomobil bize bağlı' diyor; ama o saatte orada araç yok, şimdi üsse yaklaşan araçlar o saatte kilometrelerce uzaktaydı. Çelişen kimlik iddiası riski düşürmüyor: aldatma göstergesi, niyet kenarını YÜKSEK yapıyor." Tehdit profilini göster: **yetenek YÜKSEK** (konvoy), **fırsat YÜKSEK** (üsse 1,6 km), **niyet göstergeleri YÜKSEK** (yaklaşıyor + çelişen kimlik) → üçgen tam, ETA < 10 dk: KRİTİK. |
| 2:50–3:20 | **Brief** | Manşet, önerilen eylem, "✓ … sayı kanıtla doğrulandı" rozeti; brief'teki bir çipe (V6) tıkla → haritada araç | "LLM hesap yapmıyor, sadece yazıyor. Brief'teki her sayı kanıtla karşılaştırılıyor." |
| 3:20–3:50 | **Karşıt kare** | `Esc` → adres çubuğunda `#/frame/img_001733` aç (img_001733, Kuzeybatı Yolu, 15:05, DÜŞÜK). Raporlar sekmesinde **13:40 ✗** | "Bu kare de üsse 2,7 km, beş araç var: otomobil ve panelvan, yetenek düşük; hiçbiri yaklaşmıyor, ikisi uzaklaşıyor, niyet göstergesi yok. Üçgenin iki kenarı eksik: DÜŞÜK." Raporlar sekmesinde **13:40 ?** (R042): "Rapor burada *yüklü bir kamyon* diyor. O noktada park halinde bir araç var ama kamyon olduğunu teyit edemiyoruz. Sistem raporu ne büyütüyor ne onaylıyor: DOĞRULANAMAZ. Kanıt yoksa çelişki de yok, doğrulama da." (Seviye değişirse `config.yaml → demo`'yu güncelle.) |
| 3:50–4:10 | **Sohbet** (sağ kenardaki ikon ya da `/`) | img_000860 açıkken brief'in altındaki **Anormal araçlar** şeridinde **V7 kamyon · T0122** çipinde **Sor**'a bas (ya da çipi sohbete sürükle): bağlamda "V7 kamyon · T0122", sorular V7'ye göre değişir. **Alt+1** → "R119 raporundaki kimlik iddiası V7 (T0122) için neden kanıtla çelişiyor?" (`demo-check-chat` ile önbellekte). Yazarken **T01** → otomatik tamamlama T0122'yi önerir (sunucuya istek gitmez). | "Operatör soru yazmak zorunda değil: sistem duruma göre soruyu kendisi öneriyor, anormal aracı sohbete taşımak yetiyor. Ajan kayıtları sorguluyor, her sayı doğrulanıyor; sorgular burada görünüyor." |
| 4:10–4:30 | **Etki** (adres çubuğunda `#/impact`) | Üstteki üç kutuyu göster | "Kritik karelerde elle karar, araçlar üsse vardıktan sonra geliyor: 4'te 0. DİZDAR ile 4'te 4 karar varıştan önce." Kare başına süreler varsayımdır (elle 6 dk, sistemle 1 dk; `config.yaml → impact`); net süre iddiası yapma, sıralamanın etkisini anlat. Sonra brief başına maliyet, on-prem. |

## İsteğe bağlı: vardiya oynatma (30 sn; sohbet adımının yerine)

Etki ekranında (`#/impact`) **▶ Vardiyayı oynat** → saat kaydırıcısını **14:05**'e çek, hızı **1 dk/sn** yap, **▶ Oynat**. 14:10'da img_000860 **YENİ** rozetiyle kuyruğun tepesine düşer; uyarı şeridinde "araçlar ~14:14'te üste · DİZDAR: karar 14:11 ✓ varıştan önce · Elle: inceleniyor…" ve 14:18'de "Elle: karar 14:18 ✗ varıştan sonra" görünür. Söylenecek: "Aynı operatör, aynı gün. Elle çalışırken kamyon kapıya karar verilmeden varıyor." Bitince **✕ Kapat** (açık kalırsa kuyruk simüle saatteki kareleri gösterir).

## 1 dakikalık tanıtım videosu

Hazırlık: yukarıdaki "Demodan önce" adımları; tarayıcı 1440×900, ipucu kartı kapalı, sohbet kapalı ve boş.

| Süre | Ekranda | Söylenen |
|---|---|---|
| 0:00–0:10 | Ana harita. `Esc` ile açık kartı kapat, zaman çubuğunu **13:55**'e çek, **Oynat**; araçlar üsse ilerler, ~14:10'da **Durdur**. | "DİZDAR, üssün çevresindeki 40 drone karesini, 226 hareket izini ve 137 saha raporunu tek haritada birleştiriyor." |
| 0:10–0:18 | **Aktif uyarılar**'da en üstteki **img_000860** → kart (ETA ~4,5 dk, 4 araç yaklaşıyor, ✗2 rapor) → **Kareyi aç**. | "Operatör kareleri geliş sırasıyla değil risk sırasıyla görüyor." |
| 0:18–0:27 | Brief'te **V1 tehdit profili** (yetenek, fırsat, niyet göstergeleri YÜKSEK) → **Canlı yeniden değerlendir** → *Ajan izi*'nde 6 adım, "tamamlandı · ~2,3 sn". | "Tespitten riske her adım deterministik ve izlenebilir; risk yetenek, fırsat ve niyet göstergeleriyle değerlendiriliyor." |
| 0:27–0:40 | Harita kaydırıcısında **12:35 ✗** (R125): araçlar o saatte kilometrelerce uzakta; rapor kartı "noktada kayıtlı araç yok … T0122 5,6 km". | "Resmî rapor 'olağan' diyor; ama raporun saatinde o noktada kimse yok. Sistem raporu kanıtla çürütüyor." |
| 0:40–0:52 | Sol altta **Anormal araçlar → V7 kamyon · T0122 → Sor**; ilk hazır soru; cevap önbellekten anında ("2 kayıt sorgusu"). | "Anormal aracı sohbete taşımak yetiyor; cevaptaki her sayı kayıtlarla doğrulanıyor." |
| 0:52–1:00 | Sohbeti kapat → **Amire ilet** → "Amire iletildi · Eskalasyon kartı". | "Karar insanda; DİZDAR neyin, neden acil olduğunu saniyeler içinde gösteriyor." |

Kayıttan sonra `runs/decisions.jsonl` ve `runs/views.jsonl`'i yeniden adlandır (aşağıda "Demodan sonra").

## B planları

| Sorun | Belirti | Yapılacak |
|---|---|---|
| Evren/GLM yanıt vermiyor | Canlı değerlendirmede brief "Kural tabanlı şablon", sohbette "LLM'e şu an ulaşılamıyor" | Sorun değil: brief önbellekten/şablondan gelir, kanıt ve seviye aynıdır. "Sistem LLM olmadan da çalışıyor" diye anlat. Sohbette **Tekrar dene**; yine olmazsa sohbeti atla. |
| Sohbet yavaş (> 30 sn) | "Kayıtları sorguluyor… N sn" | Önceden `make demo-check-chat` ile sorulan sorular önbellekten anında gelir; **yalnızca o soruları** sor (V7 bağlamdayken Alt+1 dahil; sohbette eski konuşma varsa önce **Temizle**). Olmazsa bağlamı boşaltıp **"Bu karedeki kamyon neden riskli?"** yaz (o da önbellekte). |
| LLM'i bilerek kapatmak | — | `curl -s -X POST http://127.0.0.1:8000/api/llm -H 'Content-Type: application/json' -d '{"enabled": false}'`: hiçbir istek gitmez, brief'ler önbellekten ya da şablondan gelir, sohbet "kapalı" der (geri açmak: `true`). Soru önerileri ve otomatik tamamlama LLM'siz çalışır. |
| İnternet yok | Altlık harita gelmiyor | Altlık zaten kapalı; her şey yerel. LLM yoksa yukarıdaki satır. |
| Canlı değerlendirme hata verdi | Kırmızı hata kutusu | Sayfayı yenile; önbellekteki değerlendirme açılır. Canlı çalıştırma şartını CLI ile göster: `make demo`. |
| Laptop çöktü | — | Yedek laptopta `docker compose up -d` (repo + `.env` hazır). Son çare: yedek ekran kaydı. |

## Demodan sonra

Demo sırasında verilen kararlar `runs/decisions.jsonl`'e, kare açılışları `runs/views.jsonl`'e yazılır; bir sonraki prova için temiz başlamak istersen ikisini de yeniden adlandır (silme, denetim kaydıdır). img_000860'a karar verilmişse uyarı şeridinden düşer ve haritada gri görünür; demoya kararsız başlamak için bu adım gerekir.
