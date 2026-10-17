# Jurisprudência source discovery — hands-on spot-check (via real browser)

**Issue:** [#23](https://github.com/emvalencaf/legal-radar/issues/23) — "Research: jurisprudência source discovery" (child of #1, spun off from #10's decision
to scope jurisprudência ingestion out pending this research). Anchor `assunto` used
throughout: **desconsideração da personalidade jurídica, CC art. 50** (picked in #9).

**Method:** All checks below were done with a real Playwright/Chromium browser session
(`mcp__plugin_playwright_playwright__*` tools), not `WebFetch`, for the same reason as
#6's `lei` spot-check (`docs/research/lexml-sru-spotcheck.md`): `www.lexml.gov.br`
fronts a JS-challenge interstitial that WebFetch cannot execute past, and several court
portals below front Cloudflare-style "Just a moment…" checks with the same property —
passable by a real browser in a few seconds, opaque to a fetch-only client.

## TL;DR

- **LexML's own search UI does index jurisprudência** for this assunto — 27,382
  "Jurisprudência" hits (vs. 1,008 doutrina, 1 legislação) for the raw keyword query —
  but the top-relevance results are dominated by labor-court (TRT) acórdãos, not
  STF/STJ. Filtering by the `Sigla`/`acronimo` facet (e.g. `AREsp`) isolates real STJ
  acórdãos (645 hits) with usable URNs
  (`urn:lex:br:superior.tribunal.justica;turma.4:acordao;aresp:...`). The `/urn/<urn>`
  resolver returns the **full ementa and decisão text inline**, plus an outbound link
  to STJ's own system — richer than the `lei` case, where the resolver gave only
  metadata + outbound links.
- **STJ's own search (`scon.stj.jus.br/SCON/`) is the strongest surface found.** No
  CAPTCHA/bot-wall at all. It's a session-based SPA — a direct GET to the
  `pesquisar.jsp?...` result URL redirects to the homepage; the query must be
  submitted via the on-page form (fill + Enter) — but once submitted it returns full,
  server-rendered HTML with complete ementas, and directly surfaced **Tema Repetitivo
  1210**, a binding STJ precedent squarely interpreting CC art. 50, as the #1 hit for
  638 total acórdãos matched.
- **STF's own search (`jurisprudencia.stf.jus.br`) is the cleanest surface
  mechanically.** No bot-wall, and the query is bookmarkable as a plain GET URL. Under
  the hood it calls a public, unauthenticated JSON REST endpoint
  (`POST /api/search/search`) that accepts a raw Elasticsearch query body and returns
  structured JSON per hit (ementa text, ministro, órgão julgador, dates, and direct
  links to `inteiro_teor_url`/`dje_url`/`acompanhamento_processual_url`). It
  surfaced **RE 1387795 (Tema 1232)**, a 2025 repercussão-geral precedent explicitly
  citing "art. 50 do CC," with the complete ementa returned in the JSON payload. The
  `inteiro_teor_url` resolves directly to a PDF, no wall.
- **Outbound "full text" links from both courts work cleanly**: STJ's legacy
  `BuscaAcordaos` servlet link passes through a brief Cloudflare check
  (`scon.stj.jus.br`, ~5s, no CAPTCHA) and lands on `processo.stj.jus.br`'s HTML/PDF
  inteiro-teor page; STF's `inteiro_teor_url` is a direct, unwalled PDF.
- **JusBrasil** (aggregator, checked as the time-permitting fallback) has zero bot-wall
  and returns 10,000+ mixed-court results (including TST) with visible ementa text in
  the search snippet itself, no login required for that much — a good breadth
  fallback, but it isn't a primary/authoritative source and wasn't checked for how
  much of the full decision it gates behind a paywall/login.
- **DataJud/CNJ** does have a documented "API Pública" (linked from
  `cnj.jus.br/sistemas/datajud/`), confirmed to exist but not deep-tested here — it's
  described as **process metadata/movements**, not ementas or full-text decisions, so
  it answers a different question ("which cases exist / their status") than what this
  project needs (the actual precedent text).

## 1. LexML's own search UI (jurisprudência facet)

Base query (same pattern as #6):

```
https://www.lexml.gov.br/busca/search?keyword=desconsidera%C3%A7%C3%A3o+da+personalidade+jur%C3%ADdica
```

Passed the "Verificação de segurança — Senado Federal" interstitial exactly as in #6
(two 503s, then a clean 200 on the third navigation attempt — consistent with #6's
"treat 503 as transient, retry" finding). Result page title `LexML : Resultados`,
**28,405 total items**, broken out by the left-hand facet as:

```
Doutrina                (1008)
Jurisprudência         (27382)
Legislação                 (1)
Outras Manifestações        (2)
Proposições Legislativas  (12)
```

This confirms jurisprudência hits do exist in LexML's index for this assunto — #6
didn't check this facet for its (different) query. However, the raw keyword search's
top-relevance jurisprudência hits (filtered via
`f1-tipoDocumento=Jurisprud%C3%AAncia`) are dominated by Tribunal Regional do Trabalho
(labor court) acórdãos, e.g.:

```
/urn/urn:lex:br;justica.trabalho;regiao.3:tribunal.regional.trabalho;turma.8:acordao:2024-07-02;0115400-76.2008.5.03.0033
```

— relevant (they do cite "art. 50 do CCB") but not the STF/STJ civil-law precedents
the assunto is really anchored on. LexML also exposes a `Sigla` (acronym) facet
inside the jurisprudência filter, with a discoverable URL pattern:

```
;f1-tipoDocumento=Jurisprud%C3%AAncia;f2-acronimo=AREsp%C2%A0%E2%80%93%C2%A0Agravo%C2%A0em%C2%A0Recurso%C2%A0Especial
```

Filtering to `AREsp` (an STJ-specific acronym) narrows to **645 items**, all
`Superior Tribunal de Justiça`, e.g.:

```
Autoridade  Superior Tribunal de Justiça. 4ª Turma
Título      AgInt no AREsp 866305 / MA
URN         urn:lex:br:superior.tribunal.justica;turma.4:acordao;aresp:2018-02-27;866305-1697811
```

Note the important nuance: an earlier, unfiltered facet listing also showed
"Biblioteca do Superior Tribunal de Justiça (769)" and "do Supremo Tribunal Federal
(665)" counts — but those sit under the **Doutrina** classification section of the
facet tree (`f1-doutrinaBiblioteca=...`), i.e. they are doctrine items housed in the
STF/STJ libraries, not STF/STJ jurisprudência entries. Do not conflate the two when
designing facet-based filters.

### URN resolver — richer than the `lei` case

```
https://www.lexml.gov.br/urn/urn:lex:br:superior.tribunal.justica;turma.4:acordao;aresp:2018-02-27;866305-1697811
```

Result: `HTTP 200`, title `AgInt no AREsp 866305 / MA - 866305-1697811/18 ::
Jurisprudência::Acórdão 866305-1697811/2018 (...) ::`. Unlike the `lei` resolver
(metadata + outbound links only), this page inlines the **full ementa and decisão
text**:

```
Ementa      AGRAVO INTERNO. AGRAVO EM RECURSO ESPECIAL. EXECUÇÃO. DESCONSIDERAÇÃO
            DA PERSONALIDADE JURÍDICA. RESPONSABILIDADE DE EX-SÓCIOS. [... full
            ementa text ...]
Decisão     A Quarta Turma, por unanimidade, negou provimento ao agravo interno [...]
Nome Uniforme  urn:lex:br:superior.tribunal.justica;turma.4:acordao;aresp:2018-02-27;866305-1697811
Outras Publicações
  Superior Tribunal de Justiça (text/html)
    http://www.stj.jus.br/SCON/servlet/BuscaAcordaos?action=mostrar&num_registro=201600399256&dt_publicacao=08/03/2018
```

That outbound link redirected (via a brief Cloudflare "Just a moment..." challenge on
`scon.stj.jus.br`, resolved automatically in ~5s, no CAPTCHA) to
`processo.stj.jus.br/processo/revista/inteiroteor/?num_registro=...`, an STJ page
offering the full acórdão as HTML or PDF ("Clique no número do processo para buscar o
Inteiro Teor do Acórdão").

**Conclusion for this surface**: usable end-to-end (search → filter by court acronym
→ URN resolve → full ementa inline, or follow the outbound link for the complete
inteiro teor), but requires knowing the court-specific `acronimo` facet values
up front to separate STF/STJ hits from the much larger volume of lower-court noise.

## 2. STF's own jurisprudência search (`jurisprudencia.stf.jus.br`)

`https://jurisprudencia.stf.jus.br/` redirects (no interstitial, no CAPTCHA) to
`https://jurisprudencia.stf.jus.br/pages/search`, an Angular SPA. Typing a query and
submitting produces a **bookmarkable GET URL**:

```
https://jurisprudencia.stf.jus.br/pages/search?base=acordaos&pesquisa_inteiro_teor=false&sinonimo=true&plural=true&radicais=false&buscaExata=true&page=1&pageSize=10&queryString=desconsidera%C3%A7%C3%A3o%20personalidade%20jur%C3%ADdica%20art.%2050%20c%C3%B3digo%20civil&sort=_score&sortBy=desc
```

Inspecting network traffic (`browser_network_requests`) after the search shows the
page is backed by a **public, unauthenticated JSON API**:

```
POST https://jurisprudencia.stf.jus.br/api/search/search
```

The request body is a raw Elasticsearch `function_score`/`bool` query (query string
search across `ementa_texto`, `decisao_texto`, `sumula_texto`, `titulo`, etc., with a
recency-decay function score) — i.e. the frontend talks directly to an Elasticsearch
proxy with no auth header observed. The response (`200 OK`, `application/json`) is a
raw ES hits envelope:

```json
{"result":{"took":1203,"hits":{"total":{"value":20,"relation":"eq"},
  "hits":[{"_id":"sjur226446","_source":{"titulo":"AI 794836 ED", ...}}, ...]}}}
```

For this assunto's query, hit #3 was:

```
_id: sjur550030
titulo: RE 1387795
orgao_julgador: Tribunal Pleno
julgamento_data: 2025-10-13
inteiro_teor_url: https://portal.stf.jus.br/jurisprudencia/obterInteiroTeor.asp?idDocumento=793259514
dje_url: https://portal.stf.jus.br/servicos/dje/listarDiarioJustica.asp?...
```

`ementa_texto` in the JSON payload is the **complete ementa**, e.g. (excerpt):

> "Recurso extraordinário com repercussão geral reconhecida. Tema nº 1.232. [...]
> Admite-se, excepcionalmente, o redirecionamento da execução trabalhista a terceiro
> que não tenha participado do processo de conhecimento nas hipóteses de sucessão
> empresarial (art. 448-A da CLT) e **abuso da personalidade jurídica (art. 50 do
> CC)** [...]"

— i.e. **RE 1387795 / Tema 1232** is a live, 2025 repercussão-geral precedent
explicitly interpreting CC art. 50, surfaced directly by this query.

Following `inteiro_teor_url` redirects (no wall) to
`redir.stf.jus.br/paginadorpub/paginador.jsp?docTP=TP&docID=793259514`, which returns
`Content-Type: application/pdf` directly — the full acórdão PDF, no login, no
CAPTCHA.

**Conclusion for this surface**: this is the cleanest mechanism found in this
research — no bot-wall of any kind was encountered anywhere on `jurisprudencia.stf.jus.br`
or `portal.stf.jus.br`/`redir.stf.jus.br` in this pass, the search is a documented-shape
(if unofficial) JSON API reachable with plain HTTP semantics (a scripted client that
replays the same POST body would likely work without a browser at all, though that
should be verified separately since this pass only confirmed it via browser), and it
returns structured full-ementa text plus a direct PDF link for the complete decision.

## 3. STJ's own jurisprudência search (`scon.stj.jus.br/SCON/`)

`https://scon.stj.jus.br/SCON/` loads directly — **no bot-wall, no CAPTCHA** — title
`STJ - Jurisprudência do STJ`. This is a session-based JSP application (not a clean
SPA-with-bookmarkable-URL like STF): a **direct GET to the result URL
(`pesquisar.jsp?acao=pesquisar&livre=...&b=ACOR&...`) redirects back to the homepage**
if hit without first establishing the search via the on-page form. The working flow
is: fill the `Critério de pesquisa` textbox and submit (Enter) — this correctly lands
on the same `pesquisar.jsp?...` URL, but only works when driven through the page's
own JS, not as a bare link.

Once submitted, the result page is genuine **server-rendered HTML** with full ementa
text inline (not a client-side-rendered JSON API — no interesting JSON payload was
found beyond small facet-count endpoints like
`SCON/SearchFiltroBRS?...&campoFiltro=NOTA`, which returns `application/json` facet
counts, e.g. `[{"docs":"2","nome":"REP"},{"docs":"0","nome":"IAC"},...]`, and several
`pesquisaAjax.jsp?...&b=SUMU|DTXT|INFJ|TEMA` calls for the other-databases tab
counts — none of these carry the actual result documents).

For the query `desconsideração personalidade jurídica art. 50`, the result page
reported:

```
638 acórdãos encontrados com: desconsideração personalidade jurídica art. 50
```

The #1 result (by relevance) was:

```
RESP 1873187 / SP
RECURSO ESPECIAL — RECURSO REPETITIVO
Pesquisa de tema: Tema Repetitivo 1210
Situação do tema: Trânsito em Julgado
RELATOR: Ministro RAUL ARAÚJO
ÓRGÃO JULGADOR: S2 - SEGUNDA SEÇÃO
DATA DO JULGAMENTO: 07/05/2026
TESE JURÍDICA: "Nas relações jurídicas de direito civil e empresarial, a
  desconsideração da personalidade jurídica requer a efetiva comprovação de abuso da
  personalidade jurídica, caracterizado por desvio de finalidade ou por confusão
  patrimonial, nos termos exigidos pelo art. 50 do Código Civil (Teoria Maior) [...]"
```

— **Tema Repetitivo 1210**, a binding STJ precedent directly on CC art. 50, full
ementa (multiple paragraphs, "CASO EM EXAME" / "QUESTÃO EM DISCUSSÃO" / "RAZÕES DE
DECIDIR" structure) rendered inline in the HTML.

The earlier-found `/urn/...` outbound link
(`http://www.stj.jus.br/SCON/servlet/BuscaAcordaos?action=mostrar&num_registro=...`)
also belongs to this same `scon.stj.jus.br` domain family and, as noted in §1, passes
its brief Cloudflare check automatically and lands on
`processo.stj.jus.br/processo/revista/inteiroteor/` with HTML/PDF format choices for
the full acórdão.

**Conclusion for this surface**: no bot-wall, but requires a real browser (or a
client that can replicate the JS-driven form POST/session flow) rather than a
bookmarkable GET — a meaningfully different mechanism than STF's plain-URL SPA.
Returns full ementa text server-rendered in HTML and surfaces exactly the kind of
binding, art.-50-specific precedent (Tema 1210) the demo needs.

## 4. Aggregator fallback: JusBrasil

```
https://www.jusbrasil.com.br/jurisprudencia/busca?q=desconsidera%C3%A7%C3%A3o+da+personalidade+jur%C3%ADdica
```

No bot-wall, no CAPTCHA, no login prompt to view snippets. Page title
"Desconsideração da Personalidade Jurídica - Jurisprudência | Jusbrasil", reporting
"Mais de 10.000 resultados" across mixed courts/tribunals (top hit in this pass was a
TST — Tribunal Superior do Trabalho — acórdão, `RR XXXXX20095010057`, ementa visible
directly in the search-result snippet, again citing "artigo 50 do Código Civil").

This confirms JusBrasil is reachable and returns real, on-point content without a
wall, but it is a private aggregator (not an authoritative/primary source), its
result ranking mixes all courts and instances without the STF/STJ-specific precision
of §2/§3, and this pass did not check how much of a full acórdão (beyond the ementa
snippet) is paywalled or login-gated — that would need a follow-up check before
relying on it for anything beyond a breadth/cross-check signal.

**DataJud/CNJ**, checked only for existence per the task's "if time permits" note:
`https://www.cnj.jus.br/sistemas/datajud/` loads cleanly (no wall) and confirms a
documented "API Pública" section exists. However, DataJud is described there as the
"Base Nacional de Dados do Poder Judiciário," storing **process metadata and
movements** for the purpose of judiciary statistics (SIESPJ) — it is very unlikely to
carry ementa/full-decision text the way STF's and STJ's own jurisprudência search
engines do, so it answers a different question (case existence/status/metadata) than
this project needs (precedent text for the knowledge graph). Not deep-tested beyond
confirming the API's existence.

## Sources hit (exact URLs)

- https://www.lexml.gov.br/busca/search?keyword=desconsidera%C3%A7%C3%A3o+da+personalidade+jur%C3%ADdica
- https://www.lexml.gov.br/busca/search?keyword=desconsidera%C3%A7%C3%A3o+da+personalidade+jur%C3%ADdica;f1-tipoDocumento=Jurisprud%C3%AAncia
- https://www.lexml.gov.br/busca/search?keyword=desconsidera%C3%A7%C3%A3o+da+personalidade+jur%C3%ADdica;f1-tipoDocumento=Jurisprud%C3%AAncia;f2-acronimo=AREsp%C2%A0%E2%80%93%C2%A0Agravo%C2%A0em%C2%A0Recurso%C2%A0Especial
- https://www.lexml.gov.br/urn/urn:lex:br:superior.tribunal.justica;turma.4:acordao;aresp:2018-02-27;866305-1697811
- http://www.stj.jus.br/SCON/servlet/BuscaAcordaos?action=mostrar&num_registro=201600399256&dt_publicacao=08/03/2018 (redirects, via brief Cloudflare check, to:)
- https://processo.stj.jus.br/processo/revista/inteiroteor/?num_registro=201600399256&dt_publicacao=08/03/2018
- https://scon.stj.jus.br/SCON/ (search UI, session-form-driven; result page reached via on-page form submit, not a bare GET)
- https://scon.stj.jus.br/SCON/SearchFiltroBRS?livre=desconsidera%E7%E3o+personalidade+jur%EDdica+art.+50&b=ACOR&p=false&l=10&i=1&ordenacao=TEMA,-DTPB,@NUM,CLAS&tp=T&h=true&campoFiltro=NOTA (facet-count JSON, not the result documents)
- https://jurisprudencia.stf.jus.br/
- https://jurisprudencia.stf.jus.br/pages/search?base=acordaos&pesquisa_inteiro_teor=false&sinonimo=true&plural=true&radicais=false&buscaExata=true&page=1&pageSize=10&queryString=desconsidera%C3%A7%C3%A3o%20personalidade%20jur%C3%ADdica%20art.%2050%20c%C3%B3digo%20civil&sort=_score&sortBy=desc
- https://jurisprudencia.stf.jus.br/api/search/search (POST, JSON, unauthenticated)
- https://portal.stf.jus.br/jurisprudencia/obterInteiroTeor.asp?idDocumento=793259514 (redirects to a direct PDF)
- https://www.jusbrasil.com.br/jurisprudencia/busca?q=desconsidera%C3%A7%C3%A3o+da+personalidade+jur%C3%ADdica
- https://www.cnj.jus.br/sistemas/datajud/

## Recommendation for a follow-up jurisprudência-ingestion design ticket

**Build primarily against STF's `api/search/search` JSON endpoint and STJ's
`scon.stj.jus.br/SCON/` HTML search, not LexML, for this pillar.** Concretely:

1. **STF (`jurisprudencia.stf.jus.br/api/search/search`) is the best-fit mechanism.**
   No bot-wall, a bookmarkable/replayable query shape, and a real (if unofficial)
   JSON API returning structured fields (`ementa_texto`, `decisao_texto`, `ministro_facet`,
   `orgao_julgador`, `julgamento_data`, `inteiro_teor_url`, `dje_url`) plus a direct,
   unwalled PDF link for the full inteiro teor. A design ticket should scope: (a)
   whether the raw Elasticsearch-shaped POST body can be replayed with plain HTTP
   (no browser) — worth a quick spike, since nothing observed here required
   JavaScript execution to reach this specific endpoint — and (b) a stable/minimal
   query template for other assuntos, since the observed body is the full
   frontend-generated query (verbose, includes UI-specific boosts/decay functions
   that a backend client wouldn't need to replicate exactly).
2. **STJ (`scon.stj.jus.br/SCON/`) is the best-fit content**, since it directly
   surfaced the binding Tema Repetitivo 1210 precedent on CC art. 50, in full ementa
   text, server-rendered. But it requires **browser automation** (or reverse-
   engineering the JS-driven session/form-POST flow) rather than a bookmarkable GET —
   design for a headless-browser step (Playwright) in the ingestion pipeline for this
   source specifically, analogous to how #6 recommended for LexML's own bot-walled
   search.
3. **LexML is a usable secondary/cross-reference surface**, not the primary
   jurisprudência source: it does index STF/STJ acórdãos (confirmed via the
   `acronimo` facet, e.g. `AREsp` → 645 STJ hits) and its URN resolver returns full
   ementa/decisão text inline, which is genuinely more usable than the `lei` case.
   But separating STF/STJ signal from the much larger volume of lower-court
   (TRT/TJ) noise requires knowing court-specific acronym facet values up front, and
   it inherits the same JS-challenge bot-wall #6 already documented. Use it as a
   secondary lookup/cross-check (e.g. to find a URN for a citation already known from
   STF/STJ) rather than the primary discovery surface.
4. **JusBrasil is a reasonable breadth fallback** (no wall, real content, 10,000+
   results) for a demo that wants volume/diversity of citing cases, but it is not
   authoritative, mixes all courts/instances in its ranking, and its full-text
   access model (beyond the ementa snippet) was not verified here — treat as
   opportunistic supplementary data, not a design pillar.
5. **DataJud/CNJ is not a fit for this pillar** — it is process-metadata/statistics
   infrastructure, not a jurisprudência full-text source; skip it for graph
   ingestion purposes unless a future feature specifically needs case-status/
   caseload data.

**For the narrow-slice demo specifically**: the ingestion design ticket should target
STF's **RE 1387795 (Tema 1232)** and STJ's **REsp 1873187 (Tema Repetitivo 1210)** as
concrete, verified, art.-50-on-point seed precedents — both were found as top-relevance
hits in this pass, both are recent (2025/2026) binding precedents with full ementa
text already captured above, and both give the ingestion design ticket a real target
to build the fetch-and-parse mechanism against instead of a hypothetical one.
