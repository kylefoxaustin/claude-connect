# Related-Work Citation Verification (for the panel + camera-ready)

**Method:** one web-verification pass against primary sources. arXiv IDs below appeared in search
results and match the primary source EXCEPT where flagged UNCONFIRMED. **Every ID must be
re-checked against the primary source before camera-ready** — this pass is a lead, not a warrant.

## Per-claim verdicts
- **AutoGen** (2308.08155), **MetaGPT** (2308.00352, ICLR 2024 oral): declared-role routing — VERIFIED.
- **CrewAI**: no canonical paper (cite repo); "stateless **by default**" (optional memory exists) — soften.
- **LangGraph supervisor**: routes on worker name+description — VERIFIED for the routing claim.
- **Mixture-of-Agents** (2406.04692 — ⚠ ID UNCONFIRMED; Wang et al., ICLR 2025): **MISCLASSIFIED in v2/v1.**
  MoA **aggregates all proposers in parallel**, it does NOT route/select by fit. Reclassified as
  ensembling in draft-v3.
- **DyLAN** (2310.02170), **Captain-Agent** (2405.19425), **AutoAgents** (2309.17288, IJCAI 2024):
  inference-time dynamic selection/generation — VERIFIED.
- **RouteLLM** (2406.18665): routes between **strong vs weak *different* models** by predicted query
  difficulty — keep as a *query/model* router, NOT an example of "same-model agents."
- **Voyager** (2305.16291): single-agent skill library, compounding — VERIFIED.
- **ADAS** (2408.08435): searches agent *programs* — VERIFIED. **Darwin Gödel Machine** (2505.22954,
  2025): a **population/archive** of self-modifying coding agents (not a single agent) — fix wording.
- **MAPE-K**: VERIFIED analogue but was **uncited** — add Kephart & Chess, *The Vision of Autonomic
  Computing*, IEEE Computer 36(1), 2003 (and/or IBM 2006 blueprint; Arcaini et al., SEAMS 2015).

## ⭐ THE HEADLINE: the strong novelty form does NOT survive — reposition (done in draft-v3 §II)
A **2025 memory-augmented-MAS subfield** does cross-task team-competence accumulation:
- **G-Memory** (2506.07398, NeurIPS 2025) — nearest neighbour: hierarchical memory "nurturing the
  progressive evolution of agent teams," ~+20.9% success; this is our Distinction-2 almost verbatim.
  **MUST cite and distinguish.**
- **RCR-Router** (2508.04903, 2025) — routes *structured memory to agents within a task*; distinguish
  from our *tasks-to-peers-by-lived-history*.
- **MasRouter** (2502.11133, ACL 2025) — learned predicted-fit MAS routing (category 2 baseline).
- **Transactive memory** ("who knows what") — our future "expertise-inferred-from-the-bus registry"
  IS a transactive memory system; name it (strengthens, not weakens).

**Defensible wedge (repositioned):** (i) each peer is a **long-lived, HITL *session identity* that
lived the work** (not an ephemeral agent over a shared store); (ii) routing is a **lead's grounded
judgment over real artifacts** (bus/asset-cards/`CLAUDE.md`); (iii) it is an **experience report on a
running deployment**, studying the *trajectory* — where G-Memory/RCR-Router/MasRouter are benchmark
evaluations of a mechanism. Soften "the gap this paper fills" → "under-explored relative to X, from
which we differ in kind."

## Citations to ADD (verify IDs first)
G-Memory (2506.07398) · RCR-Router (2508.04903) · MasRouter (2502.11133) · MAPE-K (Kephart & Chess
2003) · a transactive-memory / agent-memory survey (*Memory in LLM-based Multi-Agent Systems*, 2025).

## TODO
- Apply the same fixes to the FULL `related-work.md` (draft-v3 §II is done; the long version still
  cites MoA as a router and omits G-Memory/RCR-Router/MasRouter/MAPE-K).
- Confirm every arXiv ID against the primary source (2406.04692 MoA especially; ChatDev 2307.07924
  was not re-verified this pass).
