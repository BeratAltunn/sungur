# Aşama 2 geliştirme verisi (resmi değil)

Bu klasördeki dosyalar, organizatörün sunumda (slayt 26) paylaştığı **Saha Haritası**
sayfasına gömülü veriden yeniden üretildi. Resmi 2. aşama paketi Cumartesi dağıtılacak.
O gelene kadar pipeline'ı bu veriyle geliştirip test etmek için var.

| Dosya | İçerik |
|---|---|
| `image_meta.json` | 40 kare: `width_px`, `height_px`, `capture_time`, `corner_coordinates` |
| `zones.json` | Üs (Merkez Us) ve 8 bölge merkezi |
| `tracks.csv` | 226 track × 25 nokta (2 saat, 5 dk adım): `track_id,time,lat,lon` |
| `field_reports.json` | 137 rapor: `time`, `source` (official / third_party), `text` |
| `images/` | 40 görüntü (900×506 küçültülmüş sürüm) |

## Nasıl üretildi

Sayfa her şeyi üsse göre metre cinsinden (x = doğu, y = kuzey) tutuyor. Enlem/boylama şu
dönüşümle çevrildi:

```
lat = 39.92184 + y / 111320
lon = 32.85306 + x / (111320 · cos(39.92184°))
```

Kontrol: `img_000860` köşeleri ve `T0001` satırları sunumdaki (slayt 13–14) değerlerle
6 ondalık basamağa kadar aynı çıkıyor.

## Dikkat

- Görüntüler küçültülmüş sürümler. `width_px` / `height_px` bu sürüme göre yazıldı, bu yüzden
  piksel→koordinat dönüşümü tutarlı. Resmi paketteki boyutlar farklı olacak
  (ör. `img_000860` resmi hali 960×540).
- Resmi dosyaların alan adları ve formatı slayt 13–14'teki örneklere göre tahmin edildi.
  Resmi paket gelince loader'ları ona göre kontrol edin.
- Bu 40 görüntü Kaggle train/test setinde **yok**, yani hazır etiketleri yok.
