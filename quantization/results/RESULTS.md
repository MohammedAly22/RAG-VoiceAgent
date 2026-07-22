# Quantization & Backend Comparison — Restaurant Assistant

Local model: `Qwen/Qwen2.5-3B-Instruct` · GPU: NVIDIA GeForce RTX 4060 Ti · prompts: real grounded restaurant Q&A (retrieve_kb → answer).

## Performance

| Backend | Peak VRAM | Avg TTFT | Throughput | Where it runs |
|---------|-----------|----------|------------|---------------|
| Local bf16 | 6.53 GB | 0.921 s | 10.9 tok/s | local GPU |
| Local 4-bit NF4 | 2.45 GB | 0.727 s | 4.8 tok/s | local GPU |
| Gemini gemini-2.5-flash | 0 (cloud) | 0.575 s | — (streamed) | Google API |

**4-bit NF4 uses ~62% less VRAM** (6.53→2.45 GB) — the difference between fitting the LLM *alongside* ASR+TTS on one 16 GB card or not.

## Answers (identical grounded prompts)

### مواعيد عمل المطعم إيه؟
- **local bf16**: العمل: المطعم بيفتح يومياً من الساعة ٧:٠٠ صباحاً حتى ٨:٣٠ مساءً. مصدر: [1]
- **local 4-bit**: الحمدالله، النهاردة المطعم بيفتح من الساعة ٧:٠٠ صباحاً حتى ٨:٣٠ مساءً، وبيوقف استقبال الطلبات قبل ميعاد القفل بنص ساعة. معلومات من مصدر [1].
- **Gemini**: المطعم بيفتح يومياً من الساعة 7:00 الصبح لحد 8:30 بالليل. (المصدر: معلومات_المطعم.md)

### أسعار المشويات كام؟
- **local bf16**: مشويات كام، مشويات كام! كباب ضاني (٢٥٠ جرام) ٢٩٥ جنيه، كفتة مشوية (٢٥٠ جرام) ٢٦٥ جنيه، ريش ضاني مشوية (٤ قطع) ٣٢٠ جنيه، طبق مشويات مشكل لفردين ٥٩٠ جنيه. من مصادر معلومات المنيو.md
- **local 4-bit**: مشويات كام، مشويات كام! كباب ضاني (٢٥٠ جرام) ٢٩٥ جنيه، كفتة مشوية (٢٥٠ جرام) ٢٦٥ جنيه، ريش ضاني مشوية (٤ قطع) ٣٢٠ جنيه، طبق مشويات مشكل لفردين ٥٩٠ جنيه. من مصادر موثوقة.
- **Gemini**: أسعار المشويات كالتالي: - كباب ضاني (250 جرام): 295 جنيه. - كفتة مشوية (250 جرام): 265 جنيه. - ريش ضاني مشوية (4 قطع): 320 جنيه. - طبق مشويات مشكل لفردين: 590 جنيه. (المصدر: المنيو.md)

### بكام الكشري؟
- **local bf16**: بكام الكشري الكبير بـ ٤٥ جنيه يا فندم، من مصادر المنيو.
- **local 4-bit**: لكشري أبو السيد بـ ٨٥ جنيه، من مصادر المنيو.
- **Gemini**: الكشري بـ 85 جنيه يا فندم. (المنيو.md)

### فين عنوان المطعم؟
- **local bf16**: فين المطعم ده؟ المطعم ده في ١٥٧ شارع ٢٦ يوليو، الزمالك، القاهرة. من المصدر [٢].
- **local 4-bit**: فين المطعم ده يا فندم؟ المطعم في ١٥٧ شارع ٢٦ يوليو، الزمالك، القاهرة، من معلومات المطعم.
- **Gemini**: المطعم في 157 شارع 26 يوليو بالزمالك، القاهرة، وفيه خدمة صف سيارات (Valet) قدامه. (المصدر: التوصيل_والاسئلة.md)

### عندكم أصناف نباتية؟
- **local bf16**: أيوه، عندنا أصناف نباتية كتير زي الطعمية والطحينة وبابا غنوج والملوخية الخضرة والكشري والمحشي والسلطات وكل الحلويات الشرقية. من المنيو.
- **local 4-bit**: أيوه، عندنا أصناف نباتية كتير زي الطعمية والطحينة وبابا غنوج والملوخية الخضرة والكشري والمحشي والسلطات وكل الحلويات الشرقية. من المنيو.
- **Gemini**: أيوه يا فندم، عندنا أصناف نباتية كتير زي الطعمية والطحينة وبابا غنوج والملوخية الخضرة والكشري والمحشي والسلطات وكل الحلويات الشرقية. (المصدر: التوصيل_والاسئلة.md، دليل_مطعم_أبو_السيد.pdf ص3، المنيو.md)

### إزاي أحجز ترابيزة؟
- **local bf16**: أيوه، إحجز ترابيزة من خلال رقم الهاتف ٠٢٢٧٣٥٩٦٤٠ أو واتساب ٠١٠٢٠١٦١٦٩٩.
- **local 4-bit**: لازم تقول ليه كمية وأي عدد تانية لو عندك، واتصل على رقم الحجز اللي بتقدمه المطعم، وده هيبشر في المنيو. مثلاً: "أنا بحب أ Reserve ترابيزة، وحدة وحدة، واتصل على ٠١٠٢٠١٦١٦٩٩". المصدر: ٥
- **Gemini**: الحجز متاح للمجموعات من 6 أفراد أو أكتر، وممكن تحجز عن طريق الاتصال على 01020161699 أو واتساب على نفس الرقم. (المصدر: دليل_مطعم_أبو_السيد.pdf ص4)

## When to use which

| Situation | Recommended backend |
|-----------|---------------------|
| Best answer quality / lowest latency, online | **Gemini** (default) |
| Offline / on-prem / data-privacy, GPU free | **Local bf16** |
| Local + must share the 16 GB GPU with ASR+TTS | **Local 4-bit NF4** |
| Cost-sensitive high volume, own hardware | **Local 4-bit via vLLM** (Section 4) |

**Takeaway.** Gemini wins on quality and TTFT with zero VRAM and is the product default. The local Qwen2.5-3B path exists for offline/on-prem use; 4-bit NF4 makes it *co-resident* with the voice models at a small quality cost, while bf16 keeps maximum local quality when VRAM is free.
