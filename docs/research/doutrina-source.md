# Research: viable doutrina (doctrine) source

Resolves the research question in [issue #2](https://github.com/emvalencaf/legal-radar/issues/2)
(child of the map issue #1): LexML is a strong source for `lei` and
`jurisprudência` but is not a doctrine repository. This note investigates
whether an open/free source exists for `doutrina` — Brazilian legal
scholarship/commentary — to feed the knowledge graph's third pillar.

See `CONTEXT.md` (introduced on the `docs/context-glossary` branch, not
yet merged to `development` as of this writing) for the `assunto` / `lei` /
`jurisprudência` / `doutrina` vocabulary used below.

## Candidate 1: SciELO (scielo.br)

**What it is.** SciELO (Scientific Electronic Library Online) is a
cooperative open-access scholarly-journal platform covering Latin America,
the Caribbean, Spain and Portugal, including a Brazil collection
(scielo.br).

**Legal-scholarship coverage.** SciELO does carry a "Direito" (Law) segment
under its Applied Social Sciences area, but it is a **small, curated set**,
not a broad legal-journal index. Journals actually indexed there identified
directly on scielo.br include:
- [Revista Direito GV](https://www.scielo.br/j/rdgv/) (FGV Direito SP)
- [Revista Direito e Práxis](https://www.scielo.br/j/rdp/) (UERJ)
- [Veredas do Direito](https://www.scielo.br/j/vd/) (Editora Dom Helder)
- [Sequência](https://www.scielo.br/journal/seq/about/) (UFSC PPGD)

For scale comparison: an empirical study published in Revista Direito e
Práxis itself found **1,088 journal entries classified under Law by the
CAPES/Qualis system** (2015 cycle), of which 870 were in regular status and
**743 (85.4%) were open access** —
[Periódicos da área de Direito: uma abordagem empírica](https://www.scielo.br/j/rdp/a/67STYDTGG3gnxT5CDWxg77j/?lang=pt).
SciELO Brazil indexes only a handful of these — SciELO applies strict
editorial/quality admission criteria across all fields, so it is a
high-quality but thin slice of the total Brazilian legal-periódico
landscape.

**Access method.** SciELO exposes:
- [ArticleMeta](https://github.com/scieloorg/articlemeta) — a RESTful API
  for journal/issue/article metadata and full text by collection,
  journal, or article ID.
- [CitedBy](https://github.com/scieloorg/citedby) — a RESTful API for
  citation relationships between SciELO articles.

Both are genuine machine-queryable APIs (not scrape-only), which fits an
ingestion pipeline well for the journals that are indexed there.

**Licensing.** SciELO's
[Open Access Statement](https://www.scielo.org/en/about-scielo/open-access-statement/)
states SciELO adopted **CC-BY 4.0** as the standard license for indexed
journals since 2015, explicitly to "promote reuse and distribution of
journal documents." CC-BY permits redistribution and derivative works
(including ingestion into a knowledge graph) with attribution. Pre-2015
journals may retain other licenses, so per-journal license should be
checked at ingestion time, but the general posture is redistribution-
friendly.

**Verdict.** Legally clean, programmatically accessible, good quality —
but narrow: only a few Brazilian law journals, so topic coverage inside
SciELO is patchy and skewed toward whatever those ~4 journals publish on
(constitutional theory, law & development, law & society, sociology of
law). Not a broad doctrine source on its own.

## Candidate 2: Brazilian university institutional repositories (USP, UFRGS, UFMG, etc.)

**What they are.** Each major Brazilian university runs a repository of
theses, dissertations and (sometimes) faculty articles. Examples checked:
- USP: [Biblioteca Digital de Teses e Dissertações (BDTD-USP / teses.usp.br)](https://teses.usp.br/),
  described by USP's digital-collections agency ABCD as holding
  [over 142,600 records](https://www.abcd.usp.br/base/biblioteca-digital-teses-dissertacoes-usp-bdtd/)
  including a dedicated
  [Faculdade de Direito collection](https://teses.usp.br/index.php?option=com_jumi&fileid=30&Itemid=162&lang=pt-br&id=2).
- UFMG: law-school library page listing the
  [most reputable Brazilian legal journals](https://biblio.direito.ufmg.br/10-revistas-juridicas-brasileiras-mais-conceituadas/),
  most of which are self-described as `acesso livre` (open access).

**Access method.** USP's repository documentation states international
harvesting is available via the **OAI-PMH protocol**, which is how it feeds
metabuscadores like Google Scholar
([acessoaberto.usp.br](https://www.acessoaberto.usp.br/repositorio-institucional-da-usp/)).
OAI-PMH gives structured, programmatic (if metadata-only, standards-based)
access — no bespoke scraping needed for metadata; full text is typically a
PDF fetch per record.

**Licensing.** Brazilian institutional repositories generally publish
under Brazil's federal open-access mandates for publicly funded research
(theses/dissertations at public universities), but license terms are set
**per deposit**, not uniformly — some records are CC-licensed, others are
"all rights reserved, available for personal/research use only." This is
heterogeneous and would require per-record license checks before
redistribution in a demo, unlike SciELO's blanket CC-BY policy.

**Coverage.** Individually deep for the sponsoring university's output
(USP's Direito repository alone is large), but each is siloed —
querying "USP + UFRGS + UFMG + ..." separately does not scale for a
portfolio project. This is what the aggregators below exist to solve.

## Candidate 3: Brazilian OA aggregators — OASISBR / LA Referencia

**What they are.**
[OASISBR](https://oasisbr.ibict.br/vufind/about/home?lng=en) ("Portal
Brasileiro de Publicações e Dados Científicos em Acesso Aberto") is
IBICT's (Instituto Brasileiro de Informação em Ciência e Tecnologia)
national aggregator, harvesting from Brazilian institutional repositories,
journals, and thesis/dissertation libraries into one searchable index. It
is Brazil's node in [LA Referencia](https://www.lareferencia.info/), the
Latin American federated OA network, and was rebuilt in 2015 on LA
Referencia's own harvesting/interoperability platform.

Related, narrower aggregator:
[BDTD](https://bdtd.ibict.br/) (Biblioteca Digital Brasileira de Teses e
Dissertações) — IBICT's specific aggregator for theses/dissertations
nationwide, also OAI-PMH-based, feeding into the international NDLTD
network
([IBICT program page](https://antigo.ibict.br/informacao-para-a-pesquisa/bdtd)).

**Access method.** Both are built on OAI-PMH harvesting infrastructure
(that is literally how OASISBR/BDTD themselves acquire records from
university repositories), which strongly suggests they expose the same
protocol for downstream harvesting, consistent with LA Referencia's stated
mission to "provide interoperability standards and access to scientific
articles and theses" across the region. However, **the live OASISBR and
BDTD "about"/API pages returned only a bot-check interstitial when fetched
directly during this research** (Cloudflare-style "Verificando seu
navegador..." challenge), so the exact current REST/OAI-PMH endpoint and
its rate limits could not be independently confirmed in this pass — this
should be re-verified by a human or a headless-browser-capable agent
before building an ingestion pipeline against it.

**Licensing.** Aggregated content licensing is inherited from the
underlying institutional repository record (see Candidate 2) — OASISBR/BDTD
themselves are metadata aggregators, not license-granting parties, so the
same per-record license variability applies.

**Coverage.** Broadest of the candidates by construction (it aggregates
across all Brazilian institutions, not just one), including law faculties
across the country. But breadth of aggregation does not equal depth of
markup/structuring per record — this is a discovery layer, not a
clean bulk-export API, and confirming its actual query interface needs a
follow-up spike before committing engineering time to it.

## Other candidates considered

- **CONPEDI** (Conselho Nacional de Pesquisa e Pós-Graduação em Direito)
  publishes open-access conference proceedings/anais that are heavily
  cited in Brazilian legal academia (e.g. Revista de Direito Brasileira is
  CONPEDI-affiliated per the UFMG list above) — a plausible secondary
  source, not independently verified here beyond that reference.
- No single **dedicated open dataset for Brazilian legal doctrine**
  (analogous to how LexML is a dedicated legislative/jurisprudential
  dataset) was found. Doctrine is scattered across general-purpose
  scholarly-publishing infrastructure (SciELO, institutional repositories,
  OASISBR/BDTD), not a discipline-specific hub.

## Recommendation

**Full/broad doutrina ingestion is not realistic for a 2-4 week portfolio
build.** The candidates split into two shapes, and neither shape gives a
"LexML for doutrina":

1. **SciELO** is clean (CC-BY, real REST APIs, citable) but **narrow** —
   effectively ~4 Brazilian law journals, so it only has real depth on the
   handful of subjects those journals happen to publish on (constitutional
   theory, law & society/law & development, some administrative and
   procedural law). For most `assunto` values it would return nothing.
2. **Institutional repositories and OASISBR/BDTD** are **broad** in
   principle (all Brazilian legal scholarship, every university) but come
   with (a) per-record license heterogeneity that a demo can't legally
   paper over with a blanket policy, (b) an aggregator API that needs a
   verification spike (bot-walled during this research pass), and (c) no
   guarantee of full-text access vs. metadata-only for many records.

Given the project's stated portfolio scope, **doutrina should be a small,
curated/manual seed set** for the initial demo slice, not a live/broad
ingestion pipeline:

- Hand-pick a handful of open-access, CC-licensed articles from SciELO's
  ~4 Direito journals (or CONPEDI anais) that map directly onto whatever
  `assunto` the later narrow-slice ticket picks, store them as static
  seed documents with correct attribution, and wire the graph relationship
  (`doutrina` → cites → `lei`/`jurisprudência`) manually or via simple
  metadata extraction. This keeps the demo legally clean (CC-BY,
  attributed) and avoids building bot-evasion or per-record license
  triage into the MVP.
- A live OASISBR/BDTD harvesting integration is a reasonable **follow-up
  ticket**, not MVP scope — it needs its own spike to (a) confirm the
  actual current API/OAI-PMH endpoint past the bot-check encountered here,
  and (b) design per-record license filtering before any redistribution.

**Implication for the assunto-selection ticket:** pick a narrow-slice
`assunto` that overlaps with SciELO's actual Direito coverage to keep the
curated doctrine set non-trivial. Based on the journals found here
(Direito GV, Direito e Práxis, Veredas do Direito, Sequência), good
candidate *types* of assunto are:
- **Constitutional law / direitos fundamentais** topics — strong hits,
  these journals publish heavily here.
  - Reasonable candidate: a discrete constitutional doctrine like
    "prescrição intercorrente" (already used as the example `assunto` in
    `CONTEXT.md`) or a fundamental-rights topic.
- **Law & society / law & development / sociology of law** topics
  (Direito GV's specialty) — good coverage if the demo leans
  interdisciplinary.
- **Procedural/administrative law minutiae, tax law specifics, or
  highly technical/niche codes** (e.g. narrow regulatory subtopics) —
  **thin coverage**: these are exactly the kind of subject where the
  ~870 Qualis-classified law journals nationally might carry articles,
  but SciELO's ~4-journal slice likely does not, forcing a fallback to
  institutional-repository hand-picking per assunto (more manual effort
  per topic).

## Sources

- [SciELO Open Access Statement](https://www.scielo.org/en/about-scielo/open-access-statement/)
- [ArticleMeta API (scieloorg/articlemeta)](https://github.com/scieloorg/articlemeta)
- [CitedBy API (scieloorg/citedby)](https://github.com/scieloorg/citedby)
- [Revista Direito GV (SciELO)](https://www.scielo.br/j/rdgv/)
- [Revista Direito e Práxis (SciELO)](https://www.scielo.br/j/rdp/)
- [Veredas do Direito (SciELO)](https://www.scielo.br/j/vd/)
- [Sequência / UFSC PPGD (SciELO)](https://www.scielo.br/journal/seq/about/#about)
- [Periódicos da área de Direito: uma abordagem empírica (SciELO)](https://www.scielo.br/j/rdp/a/67STYDTGG3gnxT5CDWxg77j/?lang=pt)
- [Repositório Institucional da USP — Acesso Aberto](https://www.acessoaberto.usp.br/repositorio-institucional-da-usp/)
- [Biblioteca Digital de Teses e Dissertações da USP (ABCD)](https://www.abcd.usp.br/base/biblioteca-digital-teses-dissertacoes-usp-bdtd/)
- [USP Faculdade de Direito thesis collection](https://teses.usp.br/index.php?option=com_jumi&fileid=30&Itemid=162&lang=pt-br&id=2)
- [UFMG law library — top-rated Brazilian legal journals](https://biblio.direito.ufmg.br/10-revistas-juridicas-brasileiras-mais-conceituadas/)
- [OASISBR — About](https://oasisbr.ibict.br/vufind/about/home?lng=en)
- [LA Referencia](https://www.lareferencia.info/)
- [BDTD — IBICT program page](https://antigo.ibict.br/informacao-para-a-pesquisa/bdtd)
- [Registry of Open Access Repositories — BDTD entry](https://roar.eprints.org/129/)
