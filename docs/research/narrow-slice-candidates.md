# Narrow-slice assunto candidates — survey for the graph-RAG demo

## Goal

legal-radar's demo needs one narrow but **completely covered** legal *assunto*
(subject) to anchor the graph: a *lei* (a law or specific article), *jurisprudência*
(case law applying it), and *doutrina* (academic commentary on it), ideally with
at least one *alteração legislativa* (amendment) that visibly reshaped how courts
apply the rule — a good demonstration of the graph-RAG's ability to link a
legislative change to its downstream case-law effects.

This document surveys three candidates against that bar. It does **not** make
the final pick — see the note at the bottom.

> **Note on CONTEXT.md**: the task brief asked to ground terminology in the
> repo's `CONTEXT.md`. That file does not exist in this worktree (this worktree's
> branch was created from a commit prior to `75b764e docs(context): seed domain
> glossary for graph-RAG spec`, which lives on `docs/context-glossary` in the
> main checkout). Terminology below (assunto/lei/jurisprudência/doutrina/alteração
> legislativa) follows the definitions given directly in the task brief.

> **Note on LexML access**: both the documented SRU endpoint
> (`https://www.lexml.gov.br/busca/SRU?operation=searchRetrieve&query=...`) and
> the web search UI (`https://www.lexml.gov.br/busca/search?keyword=...`) were
> fetched via WebFetch for all three candidates. In every case the response was
> **not** data — it was a Senado Federal bot-verification interstitial ("Estamos
> confirmando que este acesso é legítimo antes de liberar o conteúdo" /
> "Conexão verificada" / "Não foi possível verificar"), i.e. a JS-driven
> challenge page that WebFetch cannot pass. The LexML manual PDF
> (`https://projeto.lexml.gov.br/documentacao/ManualPesquisaWeb.pdf`) was also
> fetched but returned as unreadable binary/image content, so the documented
> CQL query syntax could not be confirmed this way either. Jusbrasil's
> jurisprudência search (`https://www.jusbrasil.com.br/jurisprudencia/busca?q=...`)
> returned HTTP 403 Forbidden for all three terms. **No fabricated result counts
> are reported below.** As a substitute jurisprudência-richness signal, this
> survey uses STJ's own curated case-law digest ("Jurisprudência em Teses",
> found via WebSearch against `site:stj.jus.br`) and, for candidate 1, a TJDFT
> thematic jurisprudence page that *did* load successfully via WebFetch. Anyone
> implementing the actual LexML ingestion pipeline should expect to need a
> real browser (Playwright) or an allow-listed API key/IP to get past this
> challenge — plan for that as a follow-up risk, not assume WebFetch/curl works.

---

## Candidate 1: Desconsideração da personalidade jurídica (piercing the corporate veil)

Anchor law: **Código Civil (Lei 10.406/2002), art. 50**.

### A) Jurisprudência richness

- LexML SRU: attempted
  `https://www.lexml.gov.br/busca/SRU?operation=searchRetrieve&query=dc.subject%3D%22desconsidera%C3%A7%C3%A3o+da+personalidade+jur%C3%ADdica%22&maximumRecords=5`
  via WebFetch — returned the Senado bot-verification interstitial, not XML.
  No `numberOfRecords` obtainable this way.
- LexML web UI: attempted
  `https://www.lexml.gov.br/busca/search?keyword=desconsidera%C3%A7%C3%A3o+da+personalidade+jur%C3%ADdica`
  via WebFetch — same bot-verification interstitial.
- Fallback signal — STJ's own curated jurisprudência digest: WebSearch for
  `site:stj.jus.br "jurisprudência em teses" desconsideração personalidade jurídica`
  surfaced **STJ Jurisprudência em Teses edição 162** ("Direito do Consumidor –
  VI"), which is specifically dedicated to teses on desconsideração da pessoa
  jurídica under the CDC (teoria menor vs. teoria maior), plus a **2024 STJ
  news item** explaining the "teoria menor" distinction
  (stj.jus.br/.../12052024-Teoria-menor-da-desconsideracao...) and an
  **August 2026 STJ news item** on honorários in cases where desconsideração is
  rejected (stj.jus.br/.../31082026-Rejeicao-de-desconsideracao...) — i.e. this
  is an actively litigated topic with STJ output as recently as 2026.
- Additional fallback — TJDFT's own thematic jurisprudência page loaded
  successfully via WebFetch:
  `https://www.tjdft.jus.br/consultas/jurisprudencia/jurisprudencia-em-temas/jurisprudencia-em-detalhes/personalidade-juridica/desconsideracao-da-personalidade-juridica-2013-abuso-de-personalidade-2013-desvio-de-finalidade-ou-confusao-patrimonial-2013-teoria-maior`.
  It presents a stated thesis ("teoria maior": disregard requires desvio de
  finalidade or confusão patrimonial) backed by **5 headline acórdãos** (TJDFT
  1370981, 1370077, 1368565, 1367448, 1365346) plus **5 more cited decisions**
  (1369154, 1353814, 1366614, 1363294, 1359689) — 10 concrete, citable
  TJDFT decisions on this exact narrow thesis from one page alone.
- **Verdict: rich.** Confirmed via two independent official-court sources
  (STJ, TJDFT), both curated and both current.

### B) Legislative history

- Confirmed via WebSearch + `normas.leg.br`: **art. 50 caput was amended, and
  five new paragraphs (§§1–5) were added, by Lei 13.874/2019** (the "Lei da
  Liberdade Econômica"), enacted 2019-09-20. Source:
  `https://normas.leg.br/?urn=urn:lex:br:federal:lei:2019-09-20;13874@2019-12-27!art7_cpt_alt1_art50`
  and corroborated by Jusbrasil Doutrina's article-by-article commentary
  (`jusbrasil.com.br/doutrina/.../a-desconsideracao-da-pessoa-juridica...`).
- The amendment is substantively meaningful, not cosmetic: it wrote the
  "teoria maior" standard (desvio de finalidade / confusão patrimonial) into
  statute, and added express limits — e.g. "a mera existência de grupo
  econômico... não autoriza a desconsideração" and "não constitui desvio de
  finalidade a mera expansão... da atividade econômica". These are exactly the
  kind of textual hooks that later show up as holdings in the TJDFT decisions
  above (the "teoria maior" thesis cited by TJDFT tracks the post-2019 text).
- **Verdict: strong.** One well-documented amending law (2019) with visible
  doctrinal and case-law uptake of the new statutory language.

### C) Doctrine coverage

- This is a first-year Brazilian civil law / business law topic — taught in
  every "Direito Civil — Parte Geral" and "Direito Empresarial" course, and
  covered in every major civilista treatise. WebSearch turned up doctrine-grade
  sources immediately and without effort: Migalhas ("A desconsideração da
  personalidade jurídica e o novo Código Civil"; "Desconsideração da
  personalidade jurídica e reforma do CC"), law-review pieces (ICESP, TRF1
  revista), a Jusbrasil Doutrina section dedicated article-by-article to Lei
  13.874/2019's changes to art. 50, and firm client-alert commentary (Tosto
  Advogados, "O abuso da personalidade jurídica").
- **Verdict: promising, high confidence.** Canonical, textbook topic; doctrine
  is abundant and easy to find.

---

## Candidate 2: Usucapião (adverse possession), focus on usucapião extrajudicial

Anchor law: **Código Civil, arts. 1.238–1.244** (general regime); procedural
anchor for the amendment story is **Lei de Registros Públicos (Lei 6.015/1973)
art. 216-A**, inserted by **art. 1.071 of the CPC/2015 (Lei 13.105/2015)**.

### A) Jurisprudência richness

- LexML SRU and web UI: attempted the same pattern as candidate 1
  (`keyword=usucapi%C3%A3o`) via WebFetch — same bot-verification interstitial,
  no data obtained.
- Jusbrasil jurisprudência search (`jusbrasil.com.br/jurisprudencia/busca?q=usucapi%C3%A3o`)
  via WebFetch: HTTP 403 Forbidden.
- Fallback signal — WebSearch for `site:stj.jus.br "jurisprudência em teses"
  usucapião` surfaced multiple STJ items: a **Dec/2023 STJ news piece**
  ("Jurisprudência em Teses traz novos entendimentos sobre registro de imóvel
  e ação reivindicatória") with usucapião-adjacent theses, an **Aug/2022 STJ
  ruling** that property in extrajudicial liquidation cannot be acquired by
  usucapião, and an **Apr/2026 STJ ruling** that a compra-e-venda receipt can
  serve as "justo título" for usucapião ordinária — again, current (2026)
  STJ output. Also found: STJ's own Súmulas search
  (`scon.stj.jus.br/SCON/pesquisar.jsp?b=SUMU&sumula=11`) and an "Informativo
  de Jurisprudência" hit specifically indexed on the term USUCAPIAO.
- **Verdict: rich, but more diffuse than Candidate 1.** Usucapião is a broad
  family of sub-regimes (ordinária, extraordinária, especial urbana, especial
  rural, familiar, extrajudicial, coletiva) — the case law is abundant but
  spread across those sub-topics, so a demo anchored on plain "usucapião"
  risks being less narrow than intended. Anchoring specifically on
  **usucapião extrajudicial / art. 216-A LRP** narrows it back down, but at
  the cost of a smaller, less battle-tested jurisprudência set (it is a newer,
  2015/2017-era procedure).

### B) Legislative history

- Confirmed via WebSearch: **Lei 13.465/2017 amended §2º of art. 1.071 of the
  CPC/2015** — the original 2015 text said silence from co-owners/confinantes
  during the extrajudicial usucapião notification procedure meant
  **discordância** (objection); the 2017 amendment flipped this so silence now
  means **concordância** (consent) — a substantive, practically important
  reversal that directly affects how many extrajudicial usucapião cases can
  proceed without going to court. Sources: Recivil
  ("Lei 13.465/2017: Mudanças do Usucapião Extrajudicial no Novo CPC"),
  Migalhas ("Da usucapião extrajudicial"), ConJur (Artur César de Souza,
  "Usucapião administrativa e a Lei 13.465/2017").
- **Verdict: strong, and arguably a cleaner "cascade" story** than Candidate 1
  — the amendment is a single, sharply-defined semantic flip (discordância →
  concordância) with an obvious mechanical effect on downstream case volume
  (fewer stalled extrajudicial cases forced into litigation).

### C) Doctrine coverage

- Usucapião broadly is a core Direito Civil — Direitos Reais topic, covered in
  every property-law treatise; usucapião extrajudicial specifically has a
  smaller but active doctrine footprint tied to notarial/registral law
  (Direito Registral/Notarial), visible in the WebSearch results: a
  peer-reviewed article (UEMS periodicals, "Usucapião extrajudicial e
  desburocratização"), Migalhas' dedicated "Migalhas Notariais e Registrais"
  column, and a full ConJur opinion piece.
- **Verdict: promising for broad usucapião; moderate for the extrajudicial
  narrow slice** — doctrine exists but is more practitioner/notarial-law
  flavored than the classic academic-treatise coverage of Candidate 1.

---

## Candidate 3: Guarda compartilhada (mandatory shared child custody)

Anchor law: **Código Civil, art. 1.584** (and related arts. 1.583, 1.585,
1.634), as rewritten by **Lei 13.058/2014**.

### A) Jurisprudência richness

- LexML SRU and web UI: attempted with `keyword=guarda+compartilhada` via
  WebFetch — same bot-verification interstitial as the other two candidates,
  no data obtained.
- Jusbrasil jurisprudência search: HTTP 403 Forbidden (same as above).
- Fallback signal — WebSearch for `site:stj.jus.br "jurisprudência em teses"
  guarda compartilhada` surfaced **STJ Jurisprudência em Teses edições 27**
  (guarda e adoção, ECA) and **253** (Direitos da Criança e do Adolescente IV),
  with two directly-quoted theses: shared custody is the rule and can only be
  set aside on specific grounds (declined by a parent, risk of domestic
  violence, or incompatibility with the child's best interest); and shared
  custody does **not** require equal physical time — courts have flexibility
  in fixing the arrangement. A separate WebSearch also surfaced TJDFT and
  jusbrasil.com.br material tying guarda compartilhada to alienação parental
  and to dano moral claims (REsp 1.887.697/RJ, 2021, on the shift away from
  presumed damage in alienação parental cases) — evidence of an active,
  evolving case-law thread, though this pulls the topic toward the
  adjacent (and separately litigated) alienação parental doctrine rather than
  staying narrowly on custody itself.
- **Verdict: rich**, comparable to Candidate 1 in having multiple dedicated
  STJ Jurisprudência em Teses editions, though the topic has a tendency to
  entangle with the neighboring alienação parental / dano moral case law,
  which could make "narrow" harder to enforce in a demo scope.

### B) Legislative history

- Confirmed via WebSearch: **Lei 13.058/2014** (2014-12-22) rewrote arts.
  1.583, 1.584, 1.585 and 1.634 of the Código Civil, making guarda
  compartilhada **compulsory by default** even absent parental agreement
  (art. 1.584, §2º) — a presumption in favor of shared custody unless a
  parent declines it before the judge. Sources: Jus.com.br ("Guarda
  compartilhada: alterações trazidas pela Lei nº 13.058/2014"), two IBDFAM
  pieces (including one titled "o que realmente muda"), Editora JC. The
  legislative history (Bill 117/2013) is explicitly framed, per these
  sources, as an anti-parental-alienation measure — a clean, well-documented
  "why" for the amendment.
- **Verdict: strong.** One clear amending law (2014) with an explicit,
  well-documented policy rationale and a specific statutory mechanism
  (presumption in §2º) that shows up directly in the STJ theses quoted above.

### C) Doctrine coverage

- Family law is one of the most doctrine-dense areas of Brazilian legal
  writing, and guarda compartilhada specifically has its own sub-literature —
  IBDFAM (Instituto Brasileiro de Direito de Família) alone produced at least
  three distinct articles surfaced in a single WebSearch, plus Jus.com.br and
  Editora JC pieces. This is a heavily taught topic in Direito de Família
  courses.
- **Verdict: promising**, on par with Candidate 1, with the caveat noted above
  that doctrine on this topic often blends into alienação parental
  commentary, so scoping doctrine documents narrowly to art. 1.584 itself
  will take some editorial discipline.

---

## Ranking

| Rank | Candidate | One-line rationale |
|---|---|---|
| 1 | **Desconsideração da personalidade jurídica (CC art. 50)** | Narrowest and cleanest of the three: a single article, one well-documented 2019 amendment with textually traceable effects on later case law (confirmed via two independent official-court sources, STJ and TJDFT), and canonical, easy-to-find doctrine — lowest risk of scope creep into adjacent topics. |
| 2 | **Guarda compartilhada (CC art. 1.584)** | Comparable richness on all three legs (multiple STJ Jurisprudência em Teses editions, a clear compulsory-custody amendment in 2014, dense IBDFAM/family-law doctrine), but the topic naturally entangles with alienação parental and dano moral case law, so it needs more careful scoping to stay "narrow." |
| 3 | **Usucapião extrajudicial (LRP art. 216-A, via CPC art. 1.071, amended by Lei 13.465/2017)** | Has the single cleanest legislative "cascade" story (a one-word discordância→concordância flip with an obvious mechanical effect), but jurisprudência and doutrina are thinner and more practitioner/notarial-flavored on the extrajudicial-specific slice; broad "usucapião" is rich but arguably too broad to stay narrow. |

**This is a survey only** — the final pick happens in a separate Wayfinder
ticket (**#9, "Grilling: pick the narrow-slice assunto"**) where the user
makes the call.
