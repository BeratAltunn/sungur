# Yapılacaklar

Resmî veri paketi, Kaggle ekibinin tespit modeli ve hackathon GLM anahtarı **sonra gelecek**. Sıra önemli: kalibrasyon **son** adım, çünkü model, veri ve LLM değişince seviyeler de değişir.
Komutlar `ROKETSAN HACKATHON/stage2` içinden çalışır; kurulum için kökteki `AGENTS.md`.

## Değerlendirme kriterleri

| Kriter | Ağırlık |
|---|---|
| Kaggle skoru (Aşama 1 tespit modeli) | %20 |
| Teknik kalite ve mimari | %15 |
| Problemin önemi ve çözümün sağladığı iş değeri | %20 |
| Çalışan ürün ortaya koyabilme | %20 |
| Ürün düşüncesi ve kullanıcı deneyimi | %20 |
| Sunum ve demo | %5 |

## ✅ Tamamlananlar

- Deterministik çekirdek (tespit → koordinat → eşleme/kinematik → zaman-duyarlı rapor doğrulama → risk), LLM brief + grounding, sohbet
- Web arayüzü: triage, kare detayı, zaman kaydırıcısı, karar kaydı, sohbet paneli
- Docker ortamı, `AGENTS.md`
- Kalibrasyon altyapısı: `make calibrate` (etiketleyici uyumu, karışıklık matrisi, recall / yanlış alarm, ±%20 duyarlılık)
- Kör etiketleme modu: `http://127.0.0.1:8000/#/label`
- Demo senaryosu: `stage2/DEMO.md`, `config.yaml → demo` (ana kare img_000860 KRİTİK, karşıt kare img_001733 DÜŞÜK), `make demo-check`, `make demo-check-chat`
- Kronometre aracı: `scripts/stopwatch.py`
- Arayüz duman testi: `make ui-test` (Playwright + sistem Chrome'u; demo yolu ve kör modda seviye sızmaması)
- Arayüz/UX turu: aha rapor kartı, ETA'lı sıkı kuyruk, kuyrukta kararlar + "Sonraki bekleyen" (N), canlı değerlendirmede adım adım ilerleme, sohbette iptal/takip soruları, kare arama
- Amir (P2) için: yazdırılabilir eskalasyon kartı (`#/brief/<id>`) ve kurala dayalı vardiya devri (`#/handover`)
- North Star ölçümü: açılış → karar süresi (medyan) ve seviye düşürme oranı nöbet devri kartında
- Etki görünümü (`#/impact`) ve kuyrukta vardiya oynatma: elle FIFO ↔ NÖBETÇİ risk sırası, karar araçların tahmini varışından önce mi? Kronometre testi yapılınca "varsayım" etiketi kalkar.
- Erişilebilirlik turu: tüm ekranlarda metin kontrastı ≥ 4,5:1 (otomatik tarama), gövde 16 px / en küçük 12 px, klavyeyle tam kullanım (İçeriğe geç, kuyrukta roving focus, sekmelerde ←/→), `prefers-reduced-motion`, bütçe rozeti, şablon brief için "LLM ile tekrar dene"
- Profesyonel UI (dal `ui-redesign`): Astro UXDS renk/yazı tokenleri, görsel sessizlik, global durum çubuğu (gizlilik bandı, saat, tehdit durumu, alt sistemler), taktik ekran düzeni (uyarılar · harita · önizleme), haritada tahmini varış vektörleri ve 2525'ten esinlenen semboller, operasyonel hata mesajları, ≥ 6:1 kontrast testi

## 1. Şimdi — veri ve model gelmeden yapılabilecekler

| # | İş | Kim | Nasıl | Çıktı |
|---|---|---|---|---|
| 1 | **Kronometre testi** | Ekip-3 (+ bir kişi daha) | 3 kare elle (`python3 scripts/stopwatch.py manual <kare> --who <ad>`), **başka** 3 kare sistemle (`… system …`). Aynı kareyi iki yöntemle ölçmeyin. Etiketlemeden **önce** yapın, yoksa kareleri tanırsınız. | `calibration/stopwatch.csv` → `make stopwatch` sunuma |
| 2 | **Etiketleme deneme turu** (8 kare) | Ekip-1 ve Ekip-3, birbirinden bağımsız | `#/label` ekranında aynı 8 kareyi etiketleyin. Amaç aracı ve seviye tanımlarını sınamak, iki kişinin nerede ayrıştığını erken görmek. | Ayrıştığınız kareler → seviye tanımlarını netleştirin |
| 3 | **Demo provası** | Sunumu yapacak kişi | `stage2/DEMO.md`'yi baştan sona bir kez oynayın, süre tutun | takıldığınız yerler → ekibe |
| 4 | **Tasarım ve UX iyileştirmeleri** | Teknik lider + Ekip-2 | `PROJECT_DESIGN.md` §2 ile mevcut arayüz arasındaki farklar; `make demo-check` yeşil kalmalı | — |

Önerilen kare ayrımı (kronometre ↔ demo çakışmasın): elle `img_005672, img_003189, img_004416` · sistemle `img_001230, img_000531, img_008562`.

## 2. Veri, model ve anahtar gelince (bu sırayla)

| # | İş | Kim | Nasıl |
|---|---|---|---|
| 5 | Resmî veri paketi | Teknik lider | `make validate`; format farkı yalnızca `data/adapters.py`. Kare kimlikleri dev verisiyle aynı mı, bakın (aynıysa deneme etiketleri geçerli kalır). Sonra `make check`, `make demo-check`. |
| 6 | Kaggle ekibinin modeli | Ekip-1 | `python3 scripts/compare_detectors.py --kind ultralytics --weights models/kaggle.pt` → τ_op, eşleme kapısı, `floor_high_untracked_min_conf` ayarı; `config.yaml → detector` |
| 7 | Hackathon GLM anahtarı | Teknik lider | `.env`'de 3 satır; `python3 scripts/precompute.py` ile brief'leri yeniden üret; `make demo-check-chat` |
| 8 | **Tam etiketleme** (40 kare) | Ekip-1 ve Ekip-3, bağımsız | Final model ve veriyle `#/label`; bitene kadar birbirinizin etiketine bakmayın ve konuşmayın. Kare başına ~1–2 dk. Bitince `calibration/labels/<ad>.jsonl` → commit + push. |
| 9 | **Kalibrasyon** | Teknik lider + Ekip-3 | `make calibrate` → `config.yaml → risk` ağırlıkları. Hedef: YÜKSEK/KRİTİK recall %100, yanlış alarm ≤ %20. Duyarlılık tablosu sunuma. Seviyeler değişirse `config.yaml → demo` ve `DEMO.md` güncellenir. |

B planı: model entegrasyonu uzarsa tam etiketlemeyi mevcut yedek modelle yapıp kalibrasyonu o etiketlerle tamamlayın; kalibrasyonun özellik dondurmadan önce bitmesi şart.

## 3. Özellik dondurmaya kadar, zaman kalırsa

- Organizatöre sor: "görüntü verildiğinde" şartı jürinin **yeni** bir görüntü vermesi mi? Öyleyse görüntü yükleme akışı (görüntü + köşe koordinatları + çekim saati) gerekir.
- Vardiya devri için LLM'li anlatı (tasarımda "Could"); kurala dayalı sürüm `#/handover`'da hazır.
- Demodan önce: yedek ekran kaydı, yedek laptopta `docker compose up -d`.
