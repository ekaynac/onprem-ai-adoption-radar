# Radar · Kapsam sözleşmesi (SCOPE.md)
> v1 · Enes onayı: 2026-11-18 · PORTFOLIO v3 uyumu · Kanon okuma refi: `e23e2c09f161190beff8ea1f991b1f3e643a5428`.

## Kimlik
- **Bu repo:** model/makale/repo/haberleri gözetimsiz keşfeden, derleyip açıklanabilir sıralayan Pulse yayınıdır; çekirdeği korunarak başka alanlara genişleyebilir.
- **Bu repo değildir:** yönetişimli bilgi kataloğu, governance gateway veya altyapı teşhis cihazı değildir.
- **Neden ayrı bir proje:** periyodik bilgi üretimi/teslimatı Radar'ın; kabul/kullanım hakkı Kütüphane/kullanıcınındır. Alan/classifier/teslimat gelişebilir; bugünkü seçenekler değişmez değildir.

## Çekirdek (değişmezler)
- **C1** Model, paper, repo ve haber için gözetimsiz keşif ve teslimat.
- **C2** Olgu temelli triyaj, açıklanabilir sıralama ve görünür karar gerekçeleri; keşif parçası doğrulanmış araştırma sonucu değildir.
- **C3** Toplanan pencere-içi öğeler JSON görünümünde uncertain/hidden gerekçeleriyle korunur; sıralama içerik silme kapısı değildir.
- **C4** Kaynak arızası ve classifier fallback/degraded durumu görünürdür, sessiz başarı gibi sunulmaz.
- **C5** Pulse kendine yeter; tüketici sınırı sürümlü yayımlanmış JSONdur, iç depo veya başka projenin bilgi yönetişimi değildir.

## Kapsam içi (yetenekler)
- **K1** Kaynak keşfi/derleme/yapılandırması; bugünkü HF/GitHub/haber kaynakları kalıcı alan yasağı değildir.
- **K2** Kayıt kimliği/birleştirme/yayın penceresi ve orijinal/türev model ayrımı.
- **K3** Modelden bağımsız olgu triyajı, etiket önbelleği, gerekçeli sıralama; Jev sabit şart değildir.
- **K4** Site/RSS/JSON yayını, mevcut tüketiciler ve teslim yöntemlerinin geliştirilmesi.
- **K5** Pulse ürün Telegram yayını, araçsız kısa açıklamalar ve yayın/kaynak/triyaj/digest/worker sağlık denetimi.
- **K6** Repo CI/test/belge ve worker kaynak bakımı; yeni davranışa bakım atfı yapılamaz.
- **K7** Resmi `radar-*` arayüzüne tek tek Enes ön onayı olmadan, Kütüphane standartlarıyla Pulse girdisi sunma.

## Kapsam dışı
- **D1** Kalıcı katalog/kabul/hak/ajan belleği/RAG korpusu → Kütüphane; InfraMedic'in on-prem bilgi merkezi istisnası Radar'a sahiplik vermez.
- **D2** Ajan/LLM/araç kullanımının kimlik politikası, şifreleme ve çağrı denetimi → LLMDAP.
- **D3** Altyapı teşhisi/haritalama/ürün bilgi merkezi → InfraMedic; genel geliştirme döngüsü → nöbetçi-mcp. Radar yapısının InfraMedic'e girişi ayrı arayüz/sistem planı; sınır kendiliğinden kalkmaz.
- **D4** Silinen katalog/kapasite/teknik radar/API/MCP platformunu diriltme → SCOPE değişikliği gerekir.
- **D5** Resmi `radar-*` sözleşmesi dışı yazım → ayrı kapsam/arayüz kararı gerekir.
- **D6** Ajan kart/web/onay/host korkulukları → Spark; site → Site; yayınevi paneli → Polemik; çalışan homelab → homelab-dev; başka repo koduna müdahale yok.

## Sınırlar ve arayüzler
- **Sunduğu:** `data/pulse.v1.json`, site/RSS ve `radar-*` yazımı; dış sözleşme değişikliği B/Enes onayıdır.
- **Radar→Kütüphane:** yazım Radar'ın, kabul/kullanım hakkı Kütüphane/kullanıcının; girdi otomatik kabul/yayın değildir. Koleksiyon/alan/kimlik/sıklık [#234](https://github.com/ekaynac/kutuphane/issues/234) ile iki SCOPE'ta sabitlenir; yeni kabul mekanizması varsayılmaz.
- **Kullandığı:** HF/GitHub/RSS-HN, bugün Jev, Telegram Bot API, Claude CLI, Kütüphane yüzeyi; model seçimi Radar'da, sunumu spark-inference'ta, Radar için LLMDAP zorunlu değil.
- **Dokunabildiği/dokunmadığı:** repo kaynak/test/belgeleri; başka repo/korkuluk/canlı/sır/hosta dokunmaz. Homelab kaynak değişikliği `[istek: radar-dev]` issue'suyla homelab-dev'e gider; pin/çalışan kopya/zamanlayıcı onun, deploy SHA'ya özel Enes onayıyla kendi kapısından yapılır; Radar çalıştırmaz.
- **Merge = canlı yayın mı?** Evet; Enes'in `radar-a-pages-dahil` kararıyla A koşullarını sağlayan otomatik merge ve ardından mevcut workflowun Pages yayını aynı iznin kapsamındadır. Ayrı B/CI-deploy/arayüz değişikliği, homelab, diğer canlı işlemler ve release için genel kapılar sürer.

## Kanon
| Konu | Esas belge |
|---|---|
| Ürün/runtime/sözleşme | [README](README.md), [Pulse](docs/pulse.md) |
| Mevcut classifier | [Jev](docs/jev.md) |
| Kabul/retirement | [Kurtarma raporu — K1–K6/Faz 7](docs/reports/2026-09-29-radar-rescue-research-and-plan.md) |
| Geliştirme/güvenlik/worker | [CONTRIBUTING](CONTRIBUTING.md), [SECURITY](SECURITY.md), [runbook](deploy/homelab/README.md) |
Enes'in son kararı > PORTFOLIO v3 > SCOPE > repo kanonu; eski plan/profil/VISION önerileri yeni yetki değildir, vendor kilidi oluşturmaz.

## Değişiklik kaydı
- 2026-11-18 · v1 · Enes kapsam onayı; `radar-a-pages-dahil` ile A merge + mevcut Pages yayını dahil. Onaylı çekirdek ve PORTFOLIO v3 sınırları korundu.
