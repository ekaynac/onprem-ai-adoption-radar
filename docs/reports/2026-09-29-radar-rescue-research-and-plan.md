# Radar Kurtarma — Araştırma Raporu ve Geliştirme Planı

- Tarih: 2026-09-29
- Hazırlayan: Claude (mentör rolünde), Enes Kaynakcı için
- Durum: Plan onaylandı (2026-09-30), Faz 0 başladı

---

## 0. Tek cümlelik teşhis

Radar **çalışıyor** ama **yanlış şeyi üretiyor**. Veri her 2 saatte bir, gözetimsiz ve taze
şekilde toplanıyor. Fakat bu veri sahibin ihtiyacına ("bugün hangi yeni model, paper ve repo
çıktı, hangisi önemli?") dönüştürülmüyor. Onun yerine halka (ring), çağrı defteri (calls ledger),
kapasite planlama ve lineage gibi katmanlardan geçiyor. Bu katmanlar da gürültü üretiyor.

---

## 1. Kullanıcı ihtiyacı (kabul kriteri)

> "AI çalışan bir developer olarak güncel modellerden, paper'lardan ve GitHub repolarından
> haberdar olmak istiyorum. Sistem tamamen unattended çalışmalı."

Bu cümleyi ölçülebilir kabul kriterlerine çeviriyorum. Plan boyunca test ve kontrollerin
hedefi bunlar:

| # | Kriter | Ölçüm |
|---|--------|-------|
| K1 | Büyük bir lab model yayınladığında (Qwen, DeepSeek, Llama, Gemma, Mistral, GLM, gpt-oss…) ≤ 24 saat içinde radarın ön yüzünde görünür | Kaçırılan sürüm sayısı (geriye dönük test) |
| K2 | Günün önemli paper'ları kendi şeritlerinde (lane) listelenir; teknik gibi insan onayı beklemez | Günlük paper şeridi dolu mu |
| K3 | Kayda değer yeni repolar listelenir; mülakat soruları, "awesome" listeleri ve spam ayıklanır | Hassasiyet (precision) örnek seti |
| K4 | Hiçbir adım sahibin Mac'ine veya elle onaya bağlı değildir | launchd / `proposed-*.yaml` bağımlılığı = 0 |
| K5 | Sistem bozulduğunda sessiz kalmaz, sahibe haber verir | Tazelik alarmı + kırmızı iş akışı sayısı |
| K6 | Sonuç sahibin eline gelir (site + RSS + haftalık bülten veya anlık bildirim) | Teslimat kanalı aktif |

---

## 2. Repo araştırması — bulgular (kanıtlı)

### 2.1 Neler çalışıyor

- `publish.yml` her 2 saatte bir çalışıyor, son 100 çalıştırmanın 96'sı başarılı. Her çalıştırma
  16–34 dk sürüyor.
- Veri taze: `model-candidate-observations`, `trending-observations`, `news-observations` ve
  diğerleri 2026-09-29 10:47Z'de güncellenmiş.
- Haftalık catalog-autopilot, source-autopilot ve digest iş akışları yeşil.
- Kod tabanı disiplinli: 1.667 test, ruff/mypy kapıları var.

### 2.2 Neden "istenildiği gibi çalışmıyor" — kök nedenler

**KN-1. Çıktı ihtiyaca göre şekillenmemiş.** W40 brief'inde 11 kalem var. Bunların 8'i
"new-repos/ignore", 2'si ring move, 1'i benchmark move. Yeni model, paper veya haber bölümü yok.
Örnekler:
- Haftanın bir numaralı "on-prem aday" reposu `ai-engineering-interview-questions-company-wise`.
- Apple Silicon için yerel inference motoru `incoai/splash`, "velocity < 200/day" gerekçesiyle
  **ignore** almış.

**KN-2. Veri toplanıyor ama süzülmüyor.** 2026-09-15'ten beri **10.302 yeni HF model reposu**
gözlenmiş. Bunların büyük kısmı türev: quant, GGUF, abliterated, merge. Brief'e ise yalnızca
**1 model** (bir NVFP4 quant'ı) ulaşmış. Orijinal lab sürümünü türevden ayıran bir sınıflandırıcı
yok.

**KN-3. Paper'lar insan onayına takılı; eski model onay kuyruğu terk edilmiş.** Paper'lar
yalnızca "teknik adayı" olarak giriyor, keyword kapısından geçip insan onayına takılıyor
(`discovery/arxiv_technique_candidates.py:7`). `proposed-technique-seeds.yaml` 2026-07-05'ten beri
güncellenmemiş. **Düz bir "yeni paper'lar" akışı yok.** Model tarafında eski
`proposed-model-seeds.yaml` (son güncelleme 2026-06-23) terk edilmiş durumda. Ancak
catalog-autopilot haftada 5 modeli otomatik terfi ettiriyor.

> **Düzeltme (2026-09-30):** Raporun ilk sürümünde DeepSeek-V4-Flash ve Qwen3.6'nın onay
> kuyruğunda takılı kaldığını yazmıştım. Bu **yanlıştı**. İkisi de catalog-autopilot ile
> kataloğa girmiş (Qwen3.6: 2026-06-29, DeepSeek-V4-Flash: 2026-07-13) ve W29/W32/W33 bültenlerinde
> görünmüşler. Model tarafındaki asıl sorun KN-2: haftada 5 terfi hakkı var ve binlerce türev
> repoyu orijinalden ayıracak bir triyaj yok.

**KN-4. Halka salınımı (ring flapping) gürültü üretiyor.** Son 7 günde teknik halkalarında
**75 değişiklik** var. `disaggregated-prefill-decode`, `domain-randomization`, `mixture-of-experts`
ve `yarn-context-extension` her biri **16 kez** pilot↔adopt arasında gidip gelmiş. Digest de bu
gürültüyü "ring changes this week" diye basıyor.

> **Kök neden (Faz 0'da bulundu ve düzeltildi):** sorun eşik değil, veri kaynağıydı. Semantic
> Scholar rate-limit'e takıldığında atıf sayısı OpenAlex'ten alınıyor ve iki kaynak aynı paper
> için çok farklı sayılar veriyor (MoE için 4.899'a karşı 362). Düzeltme: OpenAlex yedeğine
> düşüldüğünde son bilinen S2 değeri kullanılıyor. Model ve proje halkalarında salınım yok.

**KN-5. Haber kapsamı çok dar.** `config/news-sources.yaml` içinde yalnızca vLLM, HF ve Ollama
blogları ile HN'de "vllm/ollama/llama.cpp" aramaları var. Veri dağılımı: 1.331 hn-vllm, 878
hf-blog. Frontier lab blogları (OpenAI, Anthropic, Google DeepMind, Meta, Qwen, Mistral,
DeepSeek, NVIDIA) yok. r/LocalLLaMA kapalı.

**KN-6. "Unattended" gerçekte Mac'e bağlı.**
- Haber sınıflandırması, sahibin Mac'indeki launchd ajanıyla çalışıyor:
  `com.megabilisim.onpremradar.news-classify` → `claude` CLI.
- CI'da `ANTHROPIC_API_KEY` secret'ı yok, bu yüzden `publish.yml` içindeki sınıflandırma adımı
  sessizce atlanıyor.
- Mac uyursa ya da `claude` oturumu düşerse Newsroom ham akışa döner.
- İkinci ajan `ai.openclaw.radar-scan`, `git pull` yapmayan bir checkout'ta çalışıyor. Yerel MCP
  verisi bu yüzden bayatlıyor. Bugün yerel `main` 569 commit gerideydi.

**KN-7. Kırmızı iş akışları haftalardır fark edilmiyor.**
- `ci.yml`: main 2026-08-28'den beri kırmızı (`tests/test_cross_device_sanity.py:60` —
  "gpt-oss-120b must carry provenance").
- `spec-verify.yml`: 2026-08-24'ten beri her hafta kırmızı. HF_TOKEN geçilmiyor, bu yüzden gated
  repolar 401 dönüyor. Ayrıca gerçek bir drift var: gpt-oss-120b parametre sayısı.
- `backtest.yml`: 2026-08-31'den beri her hafta kırmızı (`ConfigError: Configuration file not found`).

Kimse haberdar olmadı. K5'in ihlali tam olarak bu.

**KN-8. Kapsam kayması (scope creep).**
- Yaklaşık **38.9k satır** Python var. En büyük modül `intelligence/` (10.187 satır). Ana iş olan
  `collectors/` ise yalnızca **456 satır**.
- Kapasite planlayıcı, TCO, donanım kataloğu, platform matrisi, lineage, workspaces, advisor,
  calls ledger, backtest, kalibrasyon, review kuyruğu, PNG kartlar ve 24 frontend route var.
- Her biri tek başına makul. Ama hepsi ana ihtiyacın önüne geçmiş ve bakım yükü oluşturmuş.
- Ayrıca iki paralel ingest hattı var: legacy `radar scan` + `radar.db` ve `intelligence` +
  release tarball.

**KN-9. Jev lansmanı radarın kendi verisinde vardı ama öne çıkmadı.** `jev-chat/jev-chat-jarvis`
günde 957 yıldızla "Elsewhere in AI" bölümüne düştü. Haberde ve model şeridinde yeri yok. Bu
durum sorunun özeti: sinyal toplanıyor, anlamlandırılmıyor.

---

## 3. Jev araştırması

### 3.1 Ne olduğu

| Alan | Bilgi | Güven |
|------|-------|-------|
| Üretici | TypeSafe AI (San Francisco, 2024). CEO Diogo Almeida, eski OpenAI araştırmacısı | Doğrulandı (Wikipedia, TechCrunch) |
| Çıkış | 2026-09-15, sınırlı erken erişim. 40M$ seed yatırımı (DCVC) | Doğrulandı |
| Tür | **"System One model"**: serbest metin üretmez, önceden tanımlı çıktılar arasından **tipli karar** verir ve kalibre edilmiş olasılık döner | Doğrulandı (docs) |
| Soru tipleri | `choice` (tek seçim, ≤255 seçenek), `score` (2–10 seviyeli rubrik), `noul` (0–1 doğruluk olasılığı). Tek çağrıda birden çok soru | Doğrulandı (docs.typesafe.ai/api.md) |
| Gecikme | 70–500 ms (üretici). The Register 10k çağrıda 150–620 ms ölçmüş | Kısmen bağımsız |
| Fiyat | **Milyar input token başına 42$ (= 0,042$/M), output ücretsiz** | Doğrulandı (3 kaynak) |
| Lisans / dağıtım | Kapalı. Yalnızca API (HTTP, Python SDK `typesafe-ai`, JS SDK, DigitalOcean Serverless). **Self-host, GGUF veya Ollama yok** | Doğrulandı |
| Bilinmeyenler | Context uzunluğu, parametre sayısı, rate limit değerleri, bağımsız benchmark | **Doğrulanamadı** |

API şekli (bizim kullanacağımız):

```http
POST https://api.typesafe.ai/v1/systemone
Authorization: Bearer $TYPESAFE_API_KEY
{"model": "jev-latest",
 "state": "<öğe metni veya JSON>",
 "questions": {
   "is_original_release": {"type": "noul", "instructions": "...", "criteria": {"true": "...", "false": "..."}},
   "lane": {"type": "choice", "instructions": "...", "criteria": {"model": "...", "paper": "...", "repo": "...", "news": "..."}},
   "importance": {"type": "score", "instructions": "...", "criteria": ["gürültü", "niş", "kayda değer", "önemli", "kaçırılmamalı"]}
 }}
→ answers.<key>.{choice|score|noul, probabilities, confidence}, usage.input_tokens
```

HF'de "open-jev" adıyla dolaşan topluluk modelleri var (DeBERTa ve Qwen3 tabanlı, 0.6B–27B).
Bunlar TypeSafe'in resmi ağırlıkları **değil** ve kaliteleri doğrulanmadı.

### 3.2 Jev bu radara neden uygun?

Radarın eksik parçası tam olarak **sınıflandırma ve önem skorlama**. Özet yazmak eksik değil.
Jev de tam bunu yapıyor: ucuz, hızlı ve olasılıklı. Olasılık bilgisi sayesinde "emin değilim"
kovası kurulabiliyor. Maliyet tahmini:

- Günde yaklaşık 700 yeni HF model reposu gözleniyor. Deterministik ön filtre (GGUF, AWQ ve
  benzeri ekler, bilinen türev kalıpları) bunu yaklaşık 100'e indirir.
- Buna yaklaşık 130 paper, 50 repo ve 50 haber eklenince günde ~330 öğe eder.
- Öğe başına ~400 token ile günde ~130k token → **günde yaklaşık 0,006$, ayda 0,2$'dan az.**
- Karşılaştırma: Claude CLI ile Mac'te çalışan mevcut sınıflandırma abonelik kotası yiyor ve
  Mac'e bağlı.

### 3.3 Jev kullanım yüzeyleri (öncelik sırasıyla)

| # | Yüzey | Soru(lar) | Çözdüğü kök neden |
|---|-------|-----------|-------------------|
| J1 | **Model triyajı** | `noul` is_original_release (lab/orijinal mi, quant/finetune/merge mi) · `choice` modality · `score` importance | KN-2, KN-3 |
| J2 | **Haber sınıflandırma** (Claude CLI'ın yerine) | `choice` event_type (mevcut 10 sınıf) · `noul` relevant · `score` operational_impact | KN-6 |
| J3 | **Paper önem skoru** | `score` importance-for-practitioner · `choice` topic (inference, training, agents, RAG, eval, multimodal…) · `noul` has_code/weights | KN-3 (paper şeridi) |
| J4 | **Repo kalite kapısı** | `noul` is_listicle_or_course_or_spam · `choice` repo_kind (tool, framework, model-release, demo, list) | KN-1 (mülakat reposu sorunu) |
| J5 | **Bildirim kapısı** | `noul` worth_interrupting (anlık bildirime değer mi). Düşük güvenli öğeler bülten "emin değil" kovasına gider | K6 |
| J6 | **Mega ilgisi** (opsiyonel) | `noul` relevant_to_enterprise_onprem: Mega'nın müşteri tarafı için işaret | Ürün değeri |

Jev'in **yapmayacakları**: özet yazmak (metin üretmiyor), halka salınımını düzeltmek (bu
deterministik bir hata, histerezis ile çözülür), veri toplamak.

### 3.4 Jev riskleri ve karşı önlemler

| Risk | Önlem |
|------|-------|
| 2 haftalık ürün, sınırlı erken erişim. API anahtarı alınamayabilir | `Classifier` protokolü: `jev`, `claude-api`, `rules` motorları arasında config ile seçim. Kurallar motoru her zaman yedek |
| Kalite doğrulanmamış, bağımsız benchmark yok | **Değerlendirme kapısı:** mevcut `data/news-classified.jsonl` içinde Claude Opus'un etiketlediği **2.487 öğe** gümüş etiket (silver label) olarak var. Jev'in uyumu CI'da ölçülür. Ayrıca sahibin etiketleyeceği 150 öğelik altın set (gold set) kullanılır |
| Vendor kilidi, fiyat değişimi | Soru tanımları sağlayıcıdan bağımsız YAML'da tutulur. Aynı sorular Claude'a JSON şema olarak da sorulabilir |
| Servis kesintisi (429/529) | Üstel geri çekilme (exponential backoff). Başarısızlıkta `rules` motoruna düşülür ve sitede **görünür** "degraded" rozeti gösterilir. Asla sessiz kalınmaz |
| Veri gizliliği | Gönderilen tek şey kamuya açık metin (HF kartı, arXiv özeti, repo açıklaması). Kurumsal veri gönderilmez |

---

## 4. Hedef mimari — "Radar Pulse"

```
 kaynaklar (mevcut collector'lar + genişletilmiş haber)
   HF yeni modeller · HF daily papers · arXiv · GitHub trending/releases · lab blogları · HN
        │
        ▼
 normalize → data/pulse/items.jsonl (tek şema: id, lane, title, url, source, published_at, signals)
        │
        ▼
 ön filtre (deterministik, ucuz): türev ad kalıpları, dedup, yaş penceresi
        │
        ▼
 triyaj (Classifier protokolü: jev | claude-api | rules) → labels.jsonl (olasılık + güven + motor)
        │
        ▼
 sıralama (önem × tazelik × lane kotası) → günlük/haftalık Pulse
        │
        ├── site ön sayfası: "Bugün / Bu hafta" 4 şerit (Modeller · Paper'lar · Repolar · Haberler)
        ├── RSS/JSON her şerit için
        ├── haftalık bülten (e-posta veya Telegram/Slack)
        └── anlık bildirim: yalnızca J5 kapısından geçenler
 sağlık: tazelik alarmı (dead-man switch) + haftalık öz-rapor issue'su
```

İlkeler:

1. **İnsan kapısı yok.** Belirsiz öğeler "emin değil" kovasında görünür, kuyrukta beklemez.
2. **Sessiz hata yok.** Her yedek motor kullanımı ve her bayat kaynak sitede ve bildirimde görünür.
3. **Mevcut toplayıcılar yeniden kullanılır.** Yeniden yazmıyoruz, çıktıyı yeniden
   şekillendiriyoruz.
4. **Eski yüzeyler silinmeden önce dondurulur.** Kapasite, lineage ve benzerleri önce
   publish'ten çıkarılır, silme kararı 4 hafta sonra verilir.

---

## 5. Geliştirme planı (fazlar, testler, kontroller)

Her faz ayrı bir branch'te geliştirilir (`feature/pulse/<faz>` veya `fix/...`) ve PR ile main'e
girer. Her fazın "bitti" tanımı: kapılar yeşil **ve** publish iş akışı main'de yeşil. Önceki
dersimiz, PR check'lerinin yetmediği ve publish'in main'de doğrulanması gerektiğiydi.

### Faz 0 — Stabilizasyon (1–2 gün) · `fix/stabilize`

- [x] CI kırmızısı. 08-28'deki gpt-oss provenance hatası veride kendiliğinden düzelmişti. Güncel
      kırmızının sebebi `test_docs_contract`: README'de sabit "77 curated sources" yazıyor,
      source-autopilot ise her hafta `[skip ci]` ile kaynak ekliyor. README'den sabit sayı kaldırıldı;
      test artık sabit sayı olmamasını kontrol ediyor.
- [x] `spec-verify.yml`'e `HF_TOKEN` geçildi. gpt-oss-120b `params_total` 120.4B'den 116.8B'ye
      düzeltildi (kartın "117B" değeriyle uyumlu). Yerel sonuç: "53 seeds verified, no drift".
- [x] `backtest.yml` donduruldu: schedule kaldırıldı, manuel tetikleme bırakıldı (§6.1 karar 5).
- [x] **Halka salınımı:** kök neden atıf kaynağının değişmesiydi (bkz. KN-4). Histerezis yerine
      kaynak düzeltmesi yapıldı.
      - Testler: S2/OpenAlex dönüşümlü çalıştırmalarda skor ve halka sabit kalmalı; iki ardışık
        kesintide de S2 değeri korunmalı; S2 geçmişi yoksa OpenAlex kullanılmalı.
- [ ] Kontrol: 7 günlük teknik halka değişikliği 75'ten 10'un altına iner (canlı ölçüm).

### Faz 1 — Tek öğe modeli ve kaynak genişletme (3–4 gün) · `feature/pulse/ingest`

- [x] `PulseItem` şeması (`src/radar/pulse/items.py`) ve `data/pulse/items.jsonl` deposu. Birleştirme
      saf bir fonksiyon, yazma atomik, pencere 14 gün (`config/pulse.yaml`). Repo ve haber
      şeritleri mevcut gözlem günlüklerinden okunuyor (`adapters.py`), yeni ağ kodu yok.
- [x] **Paper şeridi:** HF daily papers doğrudan paper öğesi olur (upvote ve kod linki sinyaliyle).
      Keyword kapısı ve insan onayı yok. Ham arXiv sweep'i bilerek eklenmedi: günde yüzlerce
      filtresiz başlık, triyaj (Faz 2) gelmeden gürültüden başka bir şey üretmez.
- [x] **Model şeridi:** 30 lab org'unun en yeni yüklemeleri doğrudan HF API'den çekiliyor
      (`sources.py`). Aday taramasına bağlı değil, çünkü o tarama seed'e giren modeli bırakıyor.
      Kimi-K3'ün gözlemleri 2026-07-31'de bu yüzden kesilmişti.
- [x] **Haber genişletme:** 10 doğrulanmış kaynak eklendi: OpenAI, DeepMind, Google AI, Mistral,
      NVIDIA Dev, MSR, GitHub AI, Simon Willison, Latent Space ve HN LLM >100 puan. Anthropic ve
      Meta'nın RSS'i yok (404); Qwen blogu 2025-09'da durmuş. Bunlar gerekçesiyle config'e yazıldı.
- [x] **Deterministik köken triyajı** (`lineage.py`): HF `base_model` etiketi (quantized, finetune,
      adapter, merge) + org + ad işaretleri → original, variant, derivative veya unknown. Yalnızca
      `unknown` classifier'a (Jev) gider. Canlı ilk koşuda ortaya çıkan hata düzeltildi: bir lab'ın
      başka bir tabandan eğittiği model (apple/LensVLM-9B → Qwen3.5-9B) yeni bir sürümdür.
- [x] **K1 kabul testi** (`tests/test_pulse_k1_acceptance.py`): 2026-08/09'dan 16 lab sürümü
      (Qwen3.8, GLM-5.3, DeepSeek-V4.1-Flash, Kimi-K3, MiniCPM5, Nemotron-3.5…) gerçek HF
      etiketleriyle %100 "original" çıkıyor. 9 quant/repack'in hiçbiri "original" değil.
- [x] `radar pulse collect` publish hattına eklendi (her 2 saat). Tüm kaynaklar düşerse run'da
      görünür uyarı çıkar, site yayını engellenmez. `data/pulse/items.jsonl` bot tarafından persist
      edilir.

**Faz 1 canlı ölçüm (2026-09-30):** son 14 günde 20 model (15 original), 100 paper, 44 repo ve
571 haber. Haber şeridinin yarısından fazlası gürültü (hn-vllm 388; OpenAI'ın müşteri hikâyeleri).
"Introducing GPT-6.1 Sol" gibi kaçırılmaması gereken bir öğe, "Airbnb widens access…" gibi
kalabalığın arasında kalıyor. **Bu, Faz 2'nin (Jev triyajı) tam olarak çözeceği problem.**

### Faz 2 — Classifier katmanı ve Jev (3–4 gün) · `feature/pulse/classifier`

- [x] Sağlayıcıdan bağımsız soru setleri: `config/pulse-questions.yaml` (şerit başına; versiyonlu,
      etiketler versiyona göre önbelleklenir). İlke: **olgu sor, zevk sorma.** İlk canlı denemede Jev
      olay türünü net ayırdı (GPT-6.1 Sol → model-release, 1.00). Öznel "kaçırılmamalı mı?" sorusu ise
      bir frontier lansmanıyla Airbnb müşteri hikâyesine aynı puanı verdi (0.33'e karşı 0.34).
- [x] Motorlar: `jev` (`src/radar/pulse/jev.py`; Bearer auth; 429/529 backoff — 529 ortak retry
      setine eklendi; anahtar hiçbir hata mesajına sızmaz) ve `rules` (her zaman var, güveni 0.3).
      `claude-api` motoru **düştü**: kararın gereği API anahtarı yok. Claude, homelab'daki abonelik
      üzerinden yalnızca özetler için kullanılacak (Faz 6).
- [x] Önbellek: `data/pulse/labels.jsonl`, (öğe, içerik hash'i, soru versiyonu) anahtarıyla.
      Kurallarla etiketlenmiş öğeler Jev erişilebilir olunca yükseltilir. Sonradan gelen bir kural
      etiketi, aynı içerikteki bir Jev etiketini asla ezmez. Canlı doğrulama: ikinci çalıştırma
      yalnızca 52 öğeyi yükseltti, üçüncüsü 0 çağrı yaptı.
- [x] Bütçe ve dayanıklılık: çalıştırma başına 300k token tavanı (~0,013$). 5 ardışık hatada devre
      kesici açılır. Her iki durum da raporda ve run log'unda görünür.
- [x] Deterministik sıralama (`rank.py`): olay türü ağırlığı × güven × kaynak otoritesi; model için
      köken + like/indirme; paper için upvote + konu + "kod/ağırlık yayınlıyor"; repo için tür +
      yıldız/gün. Her öğe gerekçesini taşır. Güveni düşük olan "emin değil" kovasına düşer;
      müşteri hikâyeleri, listeler ve repack'ler gizlenir.
- [x] Publish hattında: `radar pulse triage`, `TYPESAFE_API_KEY` secret'ı ile her 2 saatte bir
      çalışır. Hata olursa run'da uyarı çıkar ve öğeler etiketsiz kalır ("emin değil").
- [ ] **Kapı: sahibin altın seti.** `eval/pulse-gold-2026-09-30.md`: şerit bazında tabakalı 120 öğe
      (Jev'den bağımsız örneklem) ve donmuş snapshot. Sahip işaretler; `radar pulse eval` Jev ile
      kural motorunun TOP kovasını precision/recall/F1 olarak karşılaştırır.

**Gümüş karşılaştırma (Claude opus'un 266 tabakalı newsroom etiketi, 2026-09-30, maliyet
0,0073$).** Ön kayıtlı kapı "F1 ≥ 0.85 ve uyum ≥ %80" idi; Jev **az farkla geçemedi**:

| Ölçüm | Jev ve Claude karşılaştırması |
|---|---|
| "On-prem operatör için ilgili mi?" F1 (eşik 0.4) | 0.83 (P 0.82 / R 0.84) |
| Uyum | %79,3 |
| Olay türü uyumu / macro-F1 | %63,9 / 0.66. En büyük karışıklık: Claude "other" dediğine Jev "community" diyor (24 öğe); ikisi de ürün için önemsiz kovalar |
| Güven ≥ 0.9 | %48 kapsam, %79,5 uyum. Güven puanı anlamlı |

**Karar:** Claude'un etiketleri eski ürün sorusunu (on-prem operatör ilgisi) yanıtlıyor, Pulse'un
sorusunu ("AI developer bunu görmeli mi?") değil. Bu yüzden gümüş sonuç Jev'i reddetmek için de
kabul etmek için de yetmez. **Nihai kapı sahibin altın seti.** O gelene kadar Jev, sonuçları
görünür rozetle etiketlenmiş olarak çalışır. Kural motoru her an geri dönüş olarak hazır.

**Canlı sıralama örneği (haber, 2026-09-30):** ilk sıralarda GPT-6 Sol/Luna ve GPT-6.1 Sol
(openai), Gemini 3.8 Live (deepmind), Claude Sonnet/Opus 5.5 (simonwillison), MiMo-V2.6-Pro
(latent-space) ve Jev lansmanı var. Bilinen hata: "How we will do better for Australia" →
`security (0.93)`. Altın set bu tür hataların oranını ölçecek.

### Faz 3 — Pulse yüzeyi ve teslimat (3 gün) · `feature/pulse/surface`

- [ ] Sitenin ön sayfası "Bugün / Bu hafta" olur. 4 şerit, her birinde en çok 10 öğe, önem
      sırasıyla. Her öğede kaynak linki, HF/arXiv/GitHub linki, motor ve güven rozeti bulunur.
- [ ] "Emin değil" kovası. Degraded rozetleri.
- [ ] Şerit başına RSS/JSON (`pulse-models.xml` ve diğerleri).
- [ ] Haftalık bülten: mevcut digest iş akışı Pulse'tan beslenir. Halka değişiklikleri
      bültenden çıkar, istenirse ekte kalır.
- [ ] Teslimat kanalı (karar → §6): e-posta, Telegram veya Slack webhook. Mevcut
      `notify/webhook.py` yeniden kullanılır.
- [ ] Testler: Playwright ile ön sayfanın 4 şeridi dolu mu; boş şeritte açıklayıcı mesaj var mı.
      Bülten snapshot testi.

### Faz 4 — Gerçek unattended operasyon (1–2 gün) · `feature/pulse/ops`

- [ ] Sınıflandırma tamamen GitHub Actions'ta çalışır. **launchd ajanları emekliye ayrılır**
      (kaldırma adımları dokümante edilir; kaldırma işini sahip yapar ya da onaylar).
- [ ] **Dead-man switch:** herhangi bir şerit 24 saattir boşsa, herhangi bir iş akışı 2 kez üst
      üste kırmızıysa ya da herhangi bir kaynak 3 gündür bayatsa → sahibe bildirim gider ve bir
      GitHub issue açılır.
- [ ] Haftalık öz-rapor: toplanan öğeler, motor dağılımı, maliyet, kırmızı iş akışları,
      bayat kaynaklar.
- [ ] Yerel MCP için `radar-scan` checkout'u `git pull` ile başlar; ya da MCP canlı siteden okur.

### Faz 5 — Sadeleştirme (2–3 gün) · `refactor/pulse-slim`

- [ ] Publish'ten dondurulan adımlar: kapasite/TCO, lineage backfill, calls ledger, backtest,
      review kuyruğu, workspaces, hardware (karar → §6).
- [ ] Hedef: publish süresi 16–34 dk'dan 10 dk'nın altına iner. Tek ingest hattı kalır: legacy
      `radar scan` veya `intelligence`'tan biri.
- [ ] 4 hafta dondurulup kimse aramazsa silme PR'ı açılır (vulture raporu eşliğinde).

### Faz 6 — (Opsiyonel) Kısa özetler (1 gün)

- [ ] Günün ilk 10 öğesi için 1–2 cümlelik Türkçe/İngilizce özet: Claude Haiku 4.5
      (`ANTHROPIC_API_KEY`). Günlük bütçe tavanı ~0,05$ civarında olur.
- [ ] Anahtar yoksa kaynak özeti (HF kartı veya arXiv abstract'ının ilk cümlesi) kullanılır.

**Toplam tahmin:** yaklaşık 2–3 hafta, parça parça. Her faz tek başına değer üretir. Faz 0 ile
Faz 1'in sonunda bile "yeni modeller ve paper'lar görünüyor" hedefine ulaşılır.

### Genel kalite kapıları (her PR)

- `pytest`, `ruff`, `mypy` yeşil. Yeni kodda test kapsamı ≥ %80.
- Ağ çağrıları testte mock'lanır. Canlı "smoke" testi yalnızca `workflow_dispatch` ile çalışır.
- Merge sonrası: main'deki publish çalıştırması yeşil olmalı ve canlı sitede ilgili şerit dolu
  olmalı. Kontrol Playwright ile ya da elle yapılır.

---

## 6. Sahibin vermesi gereken kararlar

1. **Jev erişimi:** TypeSafe erken erişimine başvuru yapılacak mı / `TYPESAFE_API_KEY` alınabilir
   mi? (Alınamazsa plan `claude-api` + `rules` ile aynen ilerler, Jev sonradan takılır.)
2. **ANTHROPIC_API_KEY** CI secret'ı olarak eklensin mi? (Mac bağımlılığını bitirmenin
   Jev'siz yolu; aylık maliyet birkaç dolar.)
3. **Teslimat kanalı:** e-posta mı, Telegram mı, Slack mı, yalnızca RSS mi?
4. **Sadeleştirme:** kapasite planlayıcı, hardware kataloğu, lineage, calls ledger ve workspaces
   dondurulsun mu? (Önerim: evet. Mega'nın danışmanlık kullanımına özel olarak lazım olan varsa
   onu işaretle.)
5. **Mega görünürlüğü:** footer'da "Built by Enes Kaynakcı · Software Engineer at Mega Bilgisayar
   Tic. Ltd. Şti." yazıyor. Bu şekilde kalsın mı?

---

### 6.1 Verilen kararlar (2026-09-30)

| # | Karar | Plana etkisi |
|---|-------|--------------|
| 1 | Jev API anahtarı **alındı** | Faz 2'de `jev` motoru birincil aday. Anahtar yalnızca secret/env olarak tutulur (`TYPESAFE_API_KEY`), repoya veya sohbete yazılmaz |
| 2 | `ANTHROPIC_API_KEY` **yok**, Claude **abonelikten** kullanılacak | `claude-api` motoru düşer. Onun yerine `claude-cli` motoru, **homelab sunucusunda** sürekli açık bir abonelik oturumuyla çalışır |
| 3 | Radar **evdeki homelab'da** serve edilecek | Faz 4 yeniden tanımlandı: homelab birincil çalıştırıcı olur (zamanlayıcı, Jev, `claude` CLI, Telegram, site ve RSS). GitHub, kod + CI + yedek Pages olarak kalır |
| 4 | Özetler **Telegram**'dan gelecek, **RSS** de sunulacak | Faz 3 teslimat kanalı Telegram Bot API olur (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`). Şerit başına RSS kalır |
| 5 | Kapasite, hardware, lineage, calls ledger ve workspaces **dondurulacak** | Faz 5 onaylı |
| 6 | Footer ifadesi **kalıyor** | Değişiklik yok |

**Homelab mimarisi (Faz 4, güncellenmiş):**

```
homelab (sürekli açık)
 ├─ zamanlayıcı (systemd timer veya docker compose + cron)
 │    ├─ her 2 saatte: git pull → ingest → ön filtre → Jev triyaj → labels
 │    ├─ günde 1–2 kez: claude -p (abonelik) → ilk N öğe için Türkçe özet
 │    └─ Telegram: günlük özet + anlık "kaçırılmamalı" bildirimi (J5)
 ├─ statik site + RSS servisi (caddy/nginx; dışarıya Cloudflare Tunnel veya Tailscale)
 └─ sağlık: heartbeat → GitHub Actions'taki bekçi, homelab 6 saat susarsa
             Telegram'a ve bir GitHub issue'suna alarm düşer (dead-man switch)
GitHub
 ├─ CI (testler, kapılar)
 └─ publish.yml yedek olarak kalır (homelab kapalıyken site bayatlamasın)
```

Kural motoru homelab'da da yedektir. Jev kesilirse ya da `claude` oturumu düşerse sistem
susmaz: görünür bir "degraded" rozeti gösterir ve Telegram'a uyarı düşer.

**Homelab ayrıntıları (2026-09-30, `~/Github/homelab` okunarak):** tek node'lu Proxmox VE 9.2,
32 GB RAM, GTX 1070. Kurallar: her servis ayrı bir unprivileged LXC'de, `vmbr1` üzerinde; router'da
port yönlendirme yok; herkese açık trafik yalnızca Cloudflare Tunnel + Access üzerinden, yönetim
Tailscale üzerinden.

Bu kurallara uyan öneri:

- **`ct-radar` (CTID 105, 10.10.0.6).** Debian 13, unprivileged, GPU yok (Jev bir API; `claude` CLI
  GPU istemiyor). `onboot 1`, `unattended-upgrades` açık, nightly PBS yedeği otomatik.
- **Dışarıya hiçbir yüzey açılmıyor.** ct-radar yalnızca dışarıya bağlanan bir işçi: pipeline'ı
  çalıştırır, sonucu GitHub'a push eder. Site ve RSS GitHub Pages'ten sunulur. Bu yüzden yeni bir
  tunnel hostname'i veya Access uygulaması gerekmiyor. Kural: "şüphedeysen Tailscale / hiçbir şey açma".
- **Secret'lar** `/etc/radar/env` dosyasında (izin 600) durur: `TYPESAFE_API_KEY`, `GITHUB_TOKEN`
  (yalnızca bu repoya yazabilen fine-grained deploy anahtarı), `HF_TOKEN`, Telegram bot token'ları.
  Repoya asla girmez.
- **`claude` aboneliği:** ct-radar içinde Enes, Tailscale SSH ile bir kez `claude` login yapar.
  Oturum düşerse Çakır alarm verir ve özetler kaynak metne düşer (görünür rozetle).

**Telegram (openclaw bot'larından seçim):**

- **Pulse özetleri → Memati (`@memati_claw_bot`).** Memati zaten "Radar Brifingcisi". Ancak
  bugünkü brifingi (HEARTBEAT Adım B), Mac'teki dev checkout'u MCP ile okuyor. O checkout
  2026-09-29'da 569 commit gerideydi ve üstelik branch değiştikçe değişiyor. Pulse, mesajı
  deterministik olarak Bot API `sendMessage` ile Memati'nin bot'undan gönderir. Openclaw gateway'in
  polling'iyle çakışmaz. Pulse canlıya çıkınca Memati'nin Adım B'si emekliye ayrılır (Enes'in
  onayıyla), böylece çift brifing olmaz. Memati sohbet ve soru-cevap için kalır.
- **Alarmlar → Çakır (`@cakir_claw_bot`).** Çakır zaten "radar tarama/brifing tazeliği" nöbetçisi.
  Dead-man switch ve degraded uyarıları onun kanalından gider.

## 7. Mentörlük notu — neden bu sefer farklı olmalı

Önceki turlar (restoration, v3 Desk, capacity) hep **yeni katman ekleyerek** ilerledi.
Toplanan veri hiçbir zaman "sahip bunu okuyunca ne öğrenir?" sorusuna karşı test edilmedi. Bu
planın farkı, **kabul kriterlerinin (K1–K6) ürün davranışı olması**: "DeepSeek-V4 çıktığında 24
saatte ön sayfada mıydı?" gibi. Kod metrikleri bu kriterlerin yerine geçmiyor. Her fazın sonunda
canlı siteye birlikte bakıp bu kriterleri işaretleyeceğiz.
