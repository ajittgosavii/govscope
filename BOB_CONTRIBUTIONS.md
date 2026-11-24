# IBM Bob Contributions — 2026-11-24

> **Commit:** `70ffa6e` — *"Procurement Health Check - built with IBM Bob"*  
> **Other tools:** Claude (Anthropic) was used alongside Bob for planning, data-quality investigation and some UI styling — see [§ Code not written by Bob](#code-not-written-by-bob).  
> All 163 tests pass in < 2 s. No network access required.

---

## Plan

### Design the application architecture

**Prompt intent:** Define a Streamlit procurement-audit tool that scores how concentrated a Canadian federal department's contract spending is, pulling live data from the Government of Canada Open Data API with a local fallback.

**Files created / changed:**  
- [`README.md`](README.md) — full architecture decision record: module responsibilities, data-flow Mermaid diagram, secrets reference, deploy guide.

**Outcome:**  
- Established a strict separation of concerns: pure-function modules (`concentration.py`, `analytics.py`) own all scoring logic; `data_client.py` owns all I/O; `app.py` is UI-only.  
- Documented the deduplication strategy (keep the highest `reporting_period` row per `procurement_id`).  
- Chosen technology stack recorded: Streamlit 1.58, pandas, Altair, Plotly (gauge/donut), `ibm-watsonx-ai` SDK, pytest.

---

## Build

### 1 — Pure scoring engine (`concentration.py`)

**Prompt intent:** Implement HHI concentration scoring as a testable, I/O-free module.

**Files created:**  
- [`concentration.py`](concentration.py)

**Outcome:**  
- [`_parse_value()`](concentration.py:17) — tolerant currency-string parser (strips `$`, commas; negative → 0).  
- [`normalize_vendor()`](concentration.py:37) — uppercases and strips trailing punctuation to merge duplicate vendor spellings.  
- [`vendor_shares()`](concentration.py:51) — builds a vendor → % of total value map.  
- [`hhi()`](concentration.py:72) — Herfindahl–Hirschman Index (0–10 000).  
- [`band()`](concentration.py:80) — classifies HHI into Low / Moderate / High using DOJ thresholds.  
- [`top_vendor()`](concentration.py:99) — returns name and share of the dominant vendor.  
- [`noncompetitive_share()`](concentration.py:110) — fraction of spend using TN (sole-source) solicitation.  
- [`flags()`](concentration.py:128) — emits human-readable risk strings when thresholds are exceeded.

---

### 2 — Advanced analytics engine (`analytics.py`)

**Prompt intent:** Add richer analytics beyond simple HHI: amendment red-flags, split-purchase detection, monthly trends, health scoring, multi-department comparison.

**Files created:**  
- [`analytics.py`](analytics.py)

**Outcome:**  
- [`value_vs_count_share()`](analytics.py:76) — divergence between vendor spend share and contract-count share.  
- [`largest_contract_share()`](analytics.py:120) — single-contract dominance indicator.  
- [`competition_breakdown()`](analytics.py:147) — solicitation-type breakdown, tendering-reason breakdown, single-bid competitive count.  
- [`split_purchase_clusters()`](analytics.py:219) — detects clusters of same-vendor contracts near a sole-source threshold within a 30-day window.  
- [`amendment_flags()`](analytics.py:299) — flags contracts where an amendment exceeded $100 k **and** 50 % of original value.  
- [`monthly_trend()`](analytics.py:327) — per-month spend, contract count, HHI, and non-competitive %.  
- [`province_from_postal()`](analytics.py:366) — maps Canadian postal prefix to province/territory.  
- [`health_score()`](analytics.py:390) — composite 0–100 score (concentration 40 pts, competition 30 pts, diversity 15 pts, red flags 15 pts).  
- [`health_band()`](analytics.py:423) — Healthy / Watch / At risk labels.  
- [`dedupe_amendments()`](analytics.py:441) — removes duplicate amendment rows, keeping the most recent per `procurement_id`.  
- [`compare_departments()`](analytics.py:516) — batch-scores every department and returns a sorted `DeptRow` list.

---

### 3 — Data client (`data_client.py`)

**Prompt intent:** Isolate all network and filesystem I/O in one module so the rest of the app is fully testable offline.

**Files created:**  
- [`data_client.py`](data_client.py)

**Outcome:**  
- [`fetch_contracts()`](data_client.py:57) — paginates the Open Government Portal API, deduplicates, returns `(records, is_cached, raw_count)`.  
- [`_paginate()`](data_client.py:202) — handles multi-page CKAN `datastore_search` responses up to `max_rows`.  
- [`_fallback()`](data_client.py:245) — loads the bundled `sample_data/ssc-spc_latest1000.json` when the API is unreachable.  
- [`load_code_labels()`](data_client.py:115) — reads `sample_data/code_labels.json` for human-readable field labels.  
- [`fetch_many()`](data_client.py:156) — multi-department aggregate fetch.  
- [`register_allowed_orgs()`](data_client.py:47) — input-validation guard: rejects unknown `owner_org` slugs with a `ValueError`.

---

### 4 — Authentication module (`auth.py`)

**Prompt intent:** Add a login gate that prevents unauthenticated access and resists brute-force attempts.

**Files created:**  
- [`auth.py`](auth.py)

**Outcome:**  
- [`require_login()`](auth.py:141) — gates all app content; calls `st.stop()` if the session is not authenticated.  
- [`_check_credentials()`](auth.py:43) — uses `hmac.compare_digest` to prevent timing-attack credential leakage.  
- Lockout: 5 failed attempts trigger a 30-second lockout.  
- [`render_signout_button()`](auth.py:157) — clears all session state including cached AI briefs on sign-out.

---

### 5 — Branding and CSS (`branding.py`)

**Prompt intent:** Give the app a polished enterprise look with a custom animated logo and IBM Carbon-inspired styling, with no external image dependencies.

**Files created:**  
- [`branding.py`](branding.py)

**Outcome:**  
- [`logo_html()`](branding.py:31) — inline SVG animated logo (ascending bar-chart + ECG heartbeat line); animation respects `prefers-reduced-motion`.  
- [`apply_styles()`](branding.py:391) — injects Carbon-inspired CSS: metric cards, IBM Blue buttons, responsive layout.  
- [`render_header()`](branding.py:396) — navy header bar with logo, app title, and "Built with IBM Bob · IBM watsonx.ai" pill badge.  
- [`render_login_page()`](branding.py:421) — two-column enterprise login layout (navy feature panel + white form card) built entirely from Streamlit-native columns + injected CSS.  
- [`render_legal_footer()`](branding.py:413) — Open Government Licence attribution footer.

> Bob built the original theme, header, animated logo and login page. The final login-page layout, the heartbeat logo and the header "Built with IBM Bob" pill were restyled afterwards with Claude.

---

### 6 — AI audit brief (`ai_brief.py`)

**Prompt intent:** Generate a plain-English audit brief from the computed analytics facts, using IBM watsonx.ai when configured and falling back to a deterministic rule-based brief otherwise.

**Files created:**  
- [`ai_brief.py`](ai_brief.py)

**Outcome:**  
- [`generate_brief()`](ai_brief.py:246) — returns `(brief_markdown, is_ai, label)`; calls watsonx.ai chat API or falls back automatically.  
- [`_call_watsonx()`](ai_brief.py:101) — uses `ibm_watsonx_ai.foundation_models.ModelInference` with `meta-llama/llama-3-3-70b-instruct` (Toronto endpoint); `max_new_tokens=600`, `temperature=0.2`.  
- [`_rule_based_brief()`](ai_brief.py:136) — deterministic fallback: assembles a four-section structured brief from the facts dict with no LLM dependency.  
- [`brief_to_html()`](ai_brief.py:284) — exports the brief as a standalone HTML document for download.  
- Watsonx error messages are truncated to 120 characters before display to avoid leaking API credentials that the IBM SDK sometimes embeds in exception text.

---

### 7 — Streamlit UI (`app.py`)

**Prompt intent:** Wire all modules into a multi-tab Streamlit dashboard with no business logic in the UI layer.

**Files created:**  
- [`app.py`](app.py)

**Outcome:**  
Eight tabs implemented: **Overview** (health score gauge, 6 KPI cards, key findings), **Concentration** (HHI gauge, top-vendor bar chart, value-vs-count scatter), **Competition** (solicitation donut, tendering-reason bars, single-bid table), **Red flags** (split-purchase clusters, large amendments, CSV export), **Trends** (dual-axis monthly spend/count + HHI overlay), **Vendors & regions** (vendor search, cross-department bar, province bar), **AI audit brief** (watsonx.ai or rule-based, with Markdown + HTML download), **Compare departments** (batch health-score table with sortable chart).

---

### 8 — Configuration and data files

**Prompt intent:** Provide a working project skeleton with secrets management and bundled sample data.

**Files created:**  
- [`.streamlit/config.toml`](.streamlit/config.toml) — enterprise Carbon theme.  
- [`.streamlit/secrets.toml.example`](.streamlit/secrets.toml.example) — safe template; real `secrets.toml` is git-ignored.  
- [`requirements.txt`](requirements.txt) — pinned dependency manifest.  
- [`.gitignore`](.gitignore) — excludes `secrets.toml`, `.venv`, `__pycache__`, etc.  
- [`sample_data/ssc-spc_latest1000.json`](sample_data/ssc-spc_latest1000.json) — 1 000 real SSC contract rows as offline fallback.  
- [`sample_data/code_labels.json`](sample_data/code_labels.json) — official Government of Canada solicitation / tendering / commodity code labels.

---

## Debug

### Bug fixes identified and resolved during the build session

**Bob code review** (full report in `Bob_Proj.docx`): 14 findings — 3 High, 5 Medium, 6 Low. Bob fixed all 8 High and Medium findings and added 16 regression tests.

| ID | Finding (from Bob's review) | File | Fix applied by Bob |
|----|-----------------------------|------|--------------------|
| H-1 | `DEPARTMENTS[active_dept]` unguarded — `KeyError` if a slug is not in the dict | [`app.py`](app.py) | Lookups switched to `DEPARTMENTS.get(...)` |
| H-2 | `__import__('datetime')` inside an f-string for the download date | [`app.py`](app.py) | Proper `import datetime`; `datetime.date.today()` |
| H-3 | Dead `if recs` guard after an unconditional `continue` in `compare_departments` | [`analytics.py`](analytics.py) | Misleading dead guard removed |
| M-1 | Raw watsonx SDK exception text shown in the UI — could expose tokens or URLs | [`ai_brief.py`](ai_brief.py) | Message truncated to 120 characters |
| M-2 | `owner_org` not validated against known departments before calling the API | [`data_client.py`](data_client.py) | `register_allowed_orgs()` + `ValueError` guard |
| M-3 | `st.stop()` inside the Compare tab would abort any tab added after it | [`app.py`](app.py) | Replaced with `if`/`else` structure |
| M-4 | Sign-out left previous user's data in `session_state` | [`auth.py`](auth.py) | Data keys and `ai_brief_*` keys cleared on sign-out |
| M-5 | Unused `import math` | [`branding.py`](branding.py) | Removed |

Low findings L-1 to L-7 (redundant passes, a null `total` edge case, a hard-coded department count, etc.) were reported but not changed.

**Earlier fixes during the build** (issue diagnosed with Claude, fix implemented by Bob):

| Issue | Fix by Bob |
|-------|-----------|
| App crashed on API rows where `number_of_bids` is null (`'NoneType' object has no attribute 'strip'`) | None-safe field helper used throughout; regression test added |
| The dataset adds a new row for every contract amendment, so one contract was counted many times (e.g. one vendor's share at Shared Services Canada shown as 62% instead of ~17%) | `dedupe_amendments()` keeps the latest row per `procurement_id`; UI shows raw vs unique counts; tests added |

---

## Test

### Test suite (`tests/`)

**Prompt intent:** Achieve high coverage of all pure-function modules with no network access; include regression tests for each bug fixed above.

**Files created:**  
- [`tests/test_concentration.py`](tests/test_concentration.py) — 84 tests  
- [`tests/test_analytics.py`](tests/test_analytics.py) — 79 tests  

**Total: 163 tests — all pass in 1.07 s.**

| Test class | Module under test | What is covered |
|---|---|---|
| `TestParseValue` | `concentration._parse_value` | Currency strings, negatives, `None`, non-string types |
| `TestNormalizeVendor` | `concentration.normalize_vendor` | Case, whitespace, trailing punctuation, non-string inputs |
| `TestVendorShares` | `concentration.vendor_shares` | Single/multi vendor, normalisation, blank/`None` vendors, zero values |
| `TestHhi` | `concentration.hhi` | Monopoly (10 000), uniform distribution, empty input |
| `TestBand` | `concentration.band` | All three bands, boundary values exactly at 1 000 and 1 800 |
| `TestTopVendor` | `concentration.top_vendor` | Single vendor, tie-break, empty shares sentinel |
| `TestNoncompetitiveShare` | `concentration.noncompetitive_share` | TN detection, case-insensitivity, whitespace, `None` procedure |
| `TestFlags` | `concentration.flags` | No flags, single-vendor flag at >40 %, low-competition flag at >30 %, both together |
| `TestHealthScore` | `analytics.health_score` | Perfect/zero scores, component sum, flagged-% cap |
| `TestHealthBand` | `analytics.health_band` | All three bands, boundary values |
| `TestSplitPurchaseClusters` | `analytics.split_purchase_clusters` | Within/outside 90-day window, threshold boundary |
| `TestAmendmentFlags` | `analytics.amendment_flags` | >$100 k and >50 % ratio, boundary values, zero original |
| `TestProvinceFromPostal` | `analytics.province_from_postal` | Key provinces, `None`, empty, case-insensitivity |
| `TestCompetitionBreakdown` | `analytics.competition_breakdown` | TC/TN classification, single-bid counting, label mapping, code-00 exclusion |
| `TestDedupeAmendments` | `analytics.dedupe_amendments` | Same `procurement_id` keeps latest period, tie-break on `reference_number`, blank PID fallback |
| `TestNullFieldSafety` | `analytics` (all functions) | All functions gracefully handle `None` and missing fields |
| `TestSampleData` | `analytics` + sample JSON | Real SSC data: contract count, HHI range, top-vendor share range |
| `TestH1RuleBasedBriefGuard` | `ai_brief._rule_based_brief` | ≤ 3 risks, no duplicate amendment risk, large-amendment risk appears when only risk |
| `TestH2NumberOfBidsIntegerSafe` | `analytics.competition_breakdown` | Integer `number_of_bids` counted/excluded correctly |
| `TestM2FallbackCorruptFile` | `data_client._fallback` | Corrupt JSON → `RuntimeError`; missing file → `RuntimeError` |
| `TestM1AuthStrip` | `auth._check_credentials` | `compare_digest` strips expected user whitespace |
| `TestCompareDepartments` | `analytics.compare_departments` | Sort order, empty-dept exclusion, band-score alignment, name resolution |
| `TestH1DepartmentsGetSafe` | `app.DEPARTMENTS` | `.get()` returns slug for unknown key; direct access raises |
| `TestH2DatetimeImport` | `analytics` | `datetime` module accessible without import hack |
| `TestH3FlaggedPctNoDeadGuard` | `app` logic (ported to test) | Correct flagged-% with non-empty recs; empty-org excluded before division |
| `TestM1WatsonxErrorTruncated` | `ai_brief.generate_brief` | Long exception message truncated to 120 chars; short message preserved |
| `TestM2OwnerOrgValidation` | `data_client.fetch_contracts` | Unknown slug raises `ValueError`; known slug passes; no-orgs-registered permits any slug |
| `TestM4SignOutClearsData` | `auth.render_signout_button` | All data keys enumerated; `ai_brief_*` prefix cleared |
| `TestM5MathImportRemoved` | `branding` | `math` not imported |

---

## Document

### README and inline documentation

**Prompt intent:** Produce complete documentation so the project can be deployed and maintained without Bob's involvement.

**Files created / changed:**  
- [`README.md`](README.md) — project overview, feature table, project-structure tree, local setup (clone → venv → secrets → run), test-runner commands, Streamlit Cloud deploy steps, secrets reference, data-source attribution, Mermaid architecture diagram, architecture notes.  
- All six Python modules have module-level docstrings explaining responsibilities, public API, and usage examples.  
- All public functions have NumPy-style or plain docstrings with parameter and return descriptions.

**Outcome:** README covers everything from prerequisites to production deployment. Inline docstrings are sufficient for IDE tooling (hover docs, auto-complete) without consulting the README.

---

## Code not written by Bob

| File | Origin | Notes |
|------|--------|-------|
| `sample_data/ssc-spc_latest1000.json` | Government of Canada Open Government Portal API | Real contract records licensed under the [Open Government Licence – Canada](https://open.canada.ca/en/open-government-licence-canada). Downloaded with Claude; the data itself is government-owned. |
| `sample_data/code_labels.json` | Government of Canada published dataset schema | Official solicitation-procedure, tendering-reason and commodity-type labels, extracted with Claude from the dataset's published schema. |
| `.venv/` | Python Package Index (pip) | Third-party dependencies installed by pip. |
| UI restyling and extensions | Claude (Anthropic) | Final login-page layout, heartbeat logo and header pill; the 12 additional departments (20 total) with parallel cross-department fetch; the welcome / "About this application" box and glossary wording; Streamlit version pin. |
| Planning and data investigation | Claude (Anthropic) | Project plan and the prompts given to Bob; diagnosis of the amendment double-counting and null-field crash (fixes implemented by Bob, see Debug). |

---

*Generated by IBM Bob · 2026-11-24*
