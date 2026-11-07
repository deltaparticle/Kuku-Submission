# Research notes (collected Nov 2026, before building)

Three research tracks were run so the design follows what top players actually do. Everything here has a source URL.
Items marked **[unverified]** came from a vendor page or a secondary source and were not independently confirmed.
Paywalled pages (Variety, Deadline, Business Standard, eMarketer) were read only through search snippets.

## 1. How microdrama apps make and run promos

- **Ads are mostly cut from the show itself.** AppGrowing says ReelShort's ad pool is its content library; over 80% of creatives are vertical
  video reusing clips from popular dramas, and its #1 creative was a 4+ minute clip from episode 1 of *The Double Life of My Billionaire Husband*.
  https://appgrowing.net/blog/en/reelshort · https://www.growthtrait.com/en/blog/short-drama-ads
- **Three recurring structures** (Insightrackr, May 2025): extended single clip, fast montage (often mixed with app screen recordings),
  and a long clip interrupted by an app pop-up. https://blog.insightrackr.com/en/docs/May25TopShortDrama
- **Length varies a lot; there is no published 20–60 s standard.** AppGrowing says an ad must reach conflict, climax and cliffhanger within
  15 s. India's Balaji makes 90–120 s teasers that stop at a tense point (afaqs, Jan 2026).
  https://appgrowing.net/blog/en/ai-for-short-drama-app-ua-creative-insights-to-cross-market-localization/ ·
  https://www.afaqs.com/news/mktg/tiny-episodes-big-hooks-how-micro-dramas-are-advertised-in-india-10971497
- **Hooks.** ReelShort's formula is "Conflict + Reversal" in the first 3 s (its top ad opens on a humiliation). In an AI Vidia study of 39
  long-running English Meta ads, openings were: conflict mid-scene 36%, narrator recap 26%, sensual/taboo bait 23%, object close-up 10%,
  flash-forward to the reveal 3%. https://ai-vidia.com/ai-drama-ads · SocialPeta via https://mobidictum.com/?p=209705
- **Cliffhanger/CTA.** Ads end on a cliffhanger that leads into the download button; 49% of the 39 Meta ads end on a search bar prompting
  the viewer to search the title. Reviews complain when ads do not name the drama (about 12–15% of 1-star reviews for some apps), which supports
  keeping a traceable title/episode in each clip. https://unstar.app/blog/is-pinedrama-legit-worth-it-short-drama-app-reviews-2026
- **Volume (why automation matters).** ReelShort UA director: "We launch thousands of creative variations every day"
  (https://liftoff.ai/?p=35846). Short drama had the highest creative density of any app category in H1 2026, ~1,887 creatives per advertiser app
  (https://xmp.mobvista.com/en-blog/docs/short-drama-ua-creative-iteration-race). AI-drama creatives fatigue in ~3–5 days
  (https://appgrowing.net/blog/en/creative-lifecycle-management-when-to-make-when-to-retire/). A "1.34M creatives" figure for ReelShort is **[unverified]**.
- **Genres in US ads:** werewolf/alpha, revenge, billionaire/CEO, hidden heir, contract marriage, true-vs-fake heiress, second chances;
  25–44-year-old women are the main audience. https://oakgen.ai/blog/what-is-a-micro-drama
- **Hook/hold benchmarks (general video ads, not drama-specific):** hook rate = 3-second plays / impressions (~25–30% typical, 30%+ strong);
  hold rate = ThruPlays / 3-second plays. No published short-drama-specific benchmark was found.
  https://admanage.ai/blog/what-is-a-good-hook-rate-for-facebook-ads · https://insights.vaizle.com/hook-rate-hold-rate/
- **No public source describes the scoring rubric editors use before posting.** Teams pick winners by live testing; that is the gap this tool fills.

### Kuku specifically
- FY26: revenue ₹1,484 cr, marketing ₹1,105 cr = 77.7% of total expenses. https://inc42.com/buzz/ipo-bound-kuku-technologies-turns-profitable-in-fy26-revenue-surges-6x-to-₹1484-cr/
- Output 200–250 shows/month, targeting 1,000/month; AI already used to find hook points and cliffhangers.
  https://www.hollywoodreporterindia.com/features/insight/indias-microdrama-boom-how-data-desire-and-aritifical-intelligence-are-reshaping-entertainment
- A 1,000-person AI production unit in Mumbai; cost target under $100 per minute. https://entrackr.com/news/kuku-to-build-1000-member-ai-team-ahead-of-rs-3500-cr-ipo-12507869
- Meta Advantage+ results for Kuku TV: 1.6x ROAS, 29% lower cost per subscription. https://www.medianews4u.com/kuku-tv-sees-1-6x-higher-roas-29-lower-cost-per-subscription-with-metas-advantage-report/
- No public interview about Kuku's or ReelShort's editors' promo workflow was found.

## 2. How existing AI clipping tools pick and score moments

- **ByteDance/USTC "HIVE" (arXiv 2507.02790)**: the closest published match (built on short-drama ads). Pipeline: speech recognition corrected by subtitles,
  face clustering for characters, scene-level segments so cuts never break dialogue, a **plot memory across episodes**, LLM scoring by genre and audience,
  and **choosing the opening and the ending as a pair** (opening must hook and stand alone, ending must leave suspense).
  Results on their DramaAD set: hook 0.71 / suspense 0.73 vs a plain end-to-end LLM at 0.64 / 0.47 and human editors at 0.87 / 0.91; removing the opening/ending
  step sharply hurt both. https://arxiv.org/html/2507.02790v2
- **OpusClip:** score 0–99 from Hook, Flow, Value, Trend (weights unpublished); has a `/score` API for any start/end window. Reviews: cuts mid-thought, weak outside
  talking-head video. https://help.opus.pro/docs/article/virality-score · https://www.opus.pro/blog/viral-moment-detection-api
- **Vizard v2 (Jul 2026):** fewer, complete clips (setup → insight → payoff) and "virality reasons" instead of one number. https://vizard.ai/blog/meet-vizard-model-v2-full-context-clips-that-the-algorithm-actually-rewards
- **Chinese short-drama ad-cut tooling:** ad spend is 70–90% of a drama's cost; typical pipeline = LLM writes ad script from selling points → AI tags footage → matches clips →
  montage → **mandatory human review**. Volcengine's short-drama highlight API has an `opening_hook_param` (move a strong moment to the front) and can return a storyboard only;
  Alibaba IMS takes a natural-language highlight brief, clip count and duration caps. https://m.huxiu.com/article/3283853.html · https://www.woshipm.com/ai/6102794.html
- **Open source:** ClipsAI (WhisperX + TextTiling), FunClip (LLM reads SRT, returns timestamps), AutoClip, AI-Youtube-Shorts-Generator (Whisper + GPT picks).
  https://github.com/ClipsAI/clipsai · https://github.com/modelscope/FunClip
- **Common failure modes and fixes:** mid-sentence cuts (snap to utterance/scene boundaries), missing context (require setup→payoff / a standalone test),
  invented timestamps on long inputs (chunk and verify; Gemini users report drift, https://discuss.ai.google.dev/t/improve-timestamp-accuracy-on-video-understanding/95356),
  repetitive picks (per-source caps, de-duplication), opaque single score (split into parts with reasons), no feedback (human review queue).

## 3. Academic ideas that carry over to a text pipeline

- **Trailer generation** (Papalampidi et al., arXiv 2111.08774): picking "important lines" (TextRank) did *worse than random*; intensity alone favours loud but plot-irrelevant shots,
  so score intensity **and** plot relevance. https://arxiv.org/abs/2111.08774
- **TeaserGen** (ICLR 2025, arXiv 2410.05586): write the hook narration first, clips ≥3 s, penalise repeats. https://arxiv.org/html/2410.05586v2
- **"Find the Cliffhanger" (arXiv 2401.16076)**: trailer-worthiness in soap operas. No dedicated LLM paper on cliffhanger detection was found; the rubric here is our own.
- **Suspense:** uncertainty reduction predicts suspense (ACL 2020); LLMs detect suspense but not its degree (arXiv 2508.15794), so use **relative ranking**, not absolute 1–10 scores.
  https://aclanthology.org/2020.acl-main.161/ · https://arxiv.org/abs/2508.15794
- **LLM-judge biases:** position, verbosity, self-preference (arXiv 2306.05685); pairwise ranking prompts are robust to order (arXiv 2306.17563);
  models underuse the middle of long contexts (arXiv 2307.03172). Hence: shuffled listwise ranking × 3 with Borda count, per-episode calls, different model for judging where possible.

## 4. Free-tier and tooling facts (Nov 2026)

- **Observed on this project's Gemini key (verified by calls):** `gemini-3.6-flash` and `gemini-3-flash-preview` allow only **~20 requests/day** each (error quota id
  `GenerateRequestsPerDayPerProjectPerModel-FreeTier`); lite models (`gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`) have more headroom but often return 503 "high demand";
  `gemini-3.8-flash`/`3.7-flash` were overloaded; `gemini-2.5-flash` returns 404 for new keys. Google no longer publishes free-tier quotas; check the AI Studio rate-limit page.
- Gemini exposes an OpenAI-compatible endpoint (`https://generativelanguage.googleapis.com/v1beta/openai/`); Groq, OpenRouter, Cerebras and Mistral do too, so one `openai`-SDK client covers all.
  Free-tier data may be used by Google to improve products. https://aistudio.google.com/docs/openai
- **GitHub Models was retired (30 Jul 2026)**, per its docs: don't use it.
- **LiteLLM** was reported compromised on PyPI twice in 2026 (credential stealer targeting AI API keys): https://futuresearch.ai/blog/litellm-pypi-supply-chain-attack/ and
  https://cloudsmith.com/blog/litellm-1-107-0-compromised-on-pypi.md. The second is a single source **[unverified]**. The project uses the plain `openai` SDK instead.
- **Hosting:** Streamlit Community Cloud is free (apps sleep after 12 h idle; secrets via the Advanced settings box). Hugging Face Spaces now needs a paid plan for Gradio/Docker apps.
  https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management · https://huggingface.co/docs/hub/spaces-overview
- **Ideas for checking quality without ground truth:** rule checks as unit tests, a small hand-labelled gold set with temporal IoU ≥ 0.5, cross-model judge agreement (Kendall τ),
  blind pairwise A/B with swapped order. After launch: hook rate, hold rate, CTR, CPI, episode-1→N continuation.

## 5. Meta Ad Library check (8 Nov 2026, done with the built-in browser)

**Method.** Meta Ad Library, country = United States, active ads, media = video, keyword search for `reelshort` and
`dramabox` (this matches ads linking to the apps' domains, including affiliate pages), sorted by **total impressions**
(Meta's own ordering, the best free "this ad performed" signal; it only covers ads active now). Scraped the visible
fields of the top results: start date, video length, number of ads sharing one creative, ad copy. Video frames could
not be read reliably (the library only shows a small poster image), so opening shots were NOT analysed.

| | ReelShort-linked | DramaBox-linked |
|---|---|---|
| Ads sampled (top by impressions) | 135 | 30 |
| Video length > 10 min | 104 (77%) | 28 (93%) |
| 3-10 min | 8 | 2 |
| 61-180 s | 12 | 0 |
| <= 60 s | 10 (7%) | 0 |
| Ads sharing one creative (max) | 70 | 4 |
| Language | mostly Spanish (US Hispanic targeting); 9 unique English creatives | 10 unique English creatives |

**Premises in the English ad copy** (keyword-coded, unique creatives): hidden identity / secret heir / disguised
powerful man is the most common theme for both apps (ReelShort 18 of 20 English ads incl. duplicates; DramaBox 7 of
10 unique), followed by betrayal/abandonment, a child or pregnancy secret, "years later he/she returns", humiliation
then reversal. Examples (paraphrased): a disguised godfather heir proposed to by the CEO he saved; a blind heir cast
out by his stepfamily who returns years later in command; a sea god marrying into a family disguised as a fisherman.

**What this means for PromoFinder**
1. On Meta, the apps' highest-impression paid creatives are mostly **long compilations (10-30 min)**, not 20-60 s
   clips. The brief's 20-60 s promos match TikTok/Reels/Shorts placements and the **opening of a long ad**: the first
   20-60 s of a compilation must hook the same way. A promo pick can therefore double as the cold open of a long cut.
2. **Hidden identity is the dominant selling premise**, which supports treating this show's title twist ("He was a
   Duke") as promotable rather than a spoiler (the spoiler majority vote now also leaves eps 41-42 unflagged).
3. Limits: active ads only, keyword matching includes affiliates, small English sample, no view of the actual opening
   seconds, impressions are not clicks or installs.
