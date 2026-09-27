# LexML SRU API — hands-on spot-check (via real browser)

**Issue:** [#6](https://github.com/emvalencaf/legal-radar/issues/6) — "Task: spot-check LexML's SRU API hands-on" (child of #1, blocks #10).

**Method:** All checks below were done with a real Playwright/Chromium browser session
(`mcp__plugin_playwright_playwright__*` tools), not `WebFetch`, specifically to test
whether the Senado Federal bot-wall reported by a prior WebFetch-based research pass
(`docs/research/narrow-slice-candidates.md`) is a WebFetch-specific artifact or a
genuine hard blocker.

## TL;DR

- **The bot-wall is passable by a real browser.** `www.lexml.gov.br` fronts an
  interstitial titled *"Verificação de segurança — Senado Federal"* on the first hit to
  a given path/query. A real browser resolves it automatically (JS challenge + cookie,
  ~2–5s) and lands on the real application response — no CAPTCHA, no manual step.
- **The HTML search UI (`/busca/search`) and the URN resolver (`/urn/<urn>`) both work**
  end-to-end through the browser, returning real result lists and real document
  metadata.
- **The raw SRU endpoint could not be located.** Every plausible SRU URL guessed
  (`/busca/SRU`, `/busca/sru`, `/sru`, upper/lowercase, with/without query params)
  returned either a genuine Tomcat 404 ("resource is not available") or an
  intermittent 503 ("No server is available to handle this request") from the same
  origin — never SRU/XML content. `projeto.lexml.gov.br` (the documentation portal)
  has no dedicated SRU manual page (`ManualDeUsoDoServicoDeBuscaSRU` 404s) and its
  site search for "SRU" returns 0 results. The only API-adjacent doc found
  (`Parte 4a – Kit Provedor de Dados`, PDF) describes **OAI-PMH** for data providers
  pushing metadata in, not an SRU query endpoint for consumers.
- **Recommendation for #10:** do not design ingestion around a guessed SRU URL. Either
  (a) get the exact SRU base URL confirmed directly from the LexML/Prodasen team or a
  more authoritative doc than what's publicly linked from `projeto.lexml.gov.br`, or
  (b) build the narrow-slice ingestion against the **HTML search results + URN
  resolver + Dados Abertos** surfaces confirmed working here, which is a fully viable
  fallback.

## 1. Bot-wall behavior (confirmed via browser)

- `https://projeto.lexml.gov.br/` and its subpages (FAQ, downloads, esquemas) load
  directly, no challenge — this is a separate Plone-based site with no WAF challenge.
- `https://www.lexml.gov.br/` (the actual search/resolver app) shows, on the **first**
  navigation to a new path or query string in a session:
  - Page title: `Verificação de segurança — Senado Federal`
  - After a few seconds (JS executes, presumably sets a cookie), a re-navigation or
    the same load settles into the real app response (200 with content, 404, or 503
    depending on the target path/backend health).
- Once a session cookie is set, repeat hits to the **same working path**
  (`/busca/search`, `/urn/...`) succeeded reliably on subsequent tries in this
  session — no CAPTCHA was ever presented, and no rate-limit response (429) was
  observed at the request volumes used here (roughly 15–20 requests over ~10 minutes).
- Paths that don't correspond to a real route (`/robots.txt`, guessed SRU paths)
  intermittently returned `503 Service Unavailable` ("No server is available to
  handle this request") even after the challenge — this looks like a WAF/load-balancer
  fallback for unmapped routes rather than a bot block, since it also hit `/robots.txt`,
  a completely innocuous path.

**Conclusion: WebFetch was blocked by the interstitial page itself (no JS execution),
not because of IP/traffic-based banning. A real browser session gets through cleanly.**

## 2. Working example: HTML search (confirmed working)

Base URL: `https://www.lexml.gov.br/busca/search`

Full example hit (via clicking "Encontrar" in the UI and via direct navigation, both
worked):

```
https://www.lexml.gov.br/busca/search?keyword=guarda+compartilhada
```

Result: `HTTP 200`, page title `LexML : Resultados`, with a real result table
containing legislative and jurisprudential hits, e.g.:

```
/urn/urn:lex:br:federal:lei:2008-06-13;11698
/urn/urn:lex:br:federal:lei:2014-12-22;13058
/urn/urn:lex:br:camara.deputados:projeto.lei;pl:2002-03-20;6350
/urn/urn:lex:br:senado.federal:projeto.lei;plc:2006;58
```
plus several `rede.virtual.bibliotecas` (doutrina/livro/artigo) hits.

This confirms the search UI itself is a legitimate, scrapeable-via-browser surface,
and its result URNs are directly usable with the URN resolver (§3).

## 3. URN → URL resolver (confirmed working)

Pattern: `https://www.lexml.gov.br/urn/<urn>`

Tested:

```
https://www.lexml.gov.br/urn/urn:lex:br:federal:lei:2008-06-13;11698
```

Result: `HTTP 200` (after passing the interstitial), page title:

> `Lei nº 11.698, de 13 de Junho de 2008 - Lei da Guarda Compartilhada (2008) - 11698/08 :: Legislação::Lei 11698/2008 (Federal - Brasil) ::`

Rendered metadata (extracted via `browser_evaluate`, real page content, not the
interstitial):

```
Localidade        Brasil
Autoridade         Federal
Título             Lei nº 11.698, de 13 de Junho de 2008
Data               13/06/2008
Apelido            Lei da Guarda Compartilhada (2008)
Ementa             Altera os arts. 1.583 e 1.584 da Lei nº 10.406, de 10 de janeiro
                   de 2002 - Código Civil, para instituir e disciplinar a guarda
                   compartilhada.
Nome Uniforme      urn:lex:br:federal:lei:2008-06-13;11698

Publicação Oficial
  Imprensa Nacional (application/pdf)
    http://pesquisa.in.gov.br/imprensa/jsp/visualiza/index.jsp?jornal=1&pagina=8&data=16/06/2008
Texto Atualizado (Multivigente)
  Presidência da República (text/html)
    http://legislacao.planalto.gov.br/legisla/legislacao.nsf/websearch?openagent&tipo=LEI&codigo=11.698&ementa=2&data=20080613
  Câmara dos Deputados (text/html)
    http://www2.camara.gov.br/legin/fed/lei/2008/lei-11698-13-junho-2008-576514-publicacaooriginal-99684-pl.html
  Senado Federal (text/html)
    http://legis.senado.leg.br/norma/582120/publicacao/15744083
```

**The URN resolver pattern works and yields both metadata and working links to the
full text of the resolved document.** This is directly usable for ingestion: search
→ get URN → resolve URN → follow the `text/html` (or `application/pdf`) link for the
full text.

## 4. SRU raw endpoint — not located (open question for #10)

Every guess below was tried directly in the browser, both fresh (new interstitial
each time) and reused-session:

| URL tried | Result |
|---|---|
| `https://www.lexml.gov.br/busca/SRU?operation=searchRetrieve&version=1.1&query=...` | `404` — Tomcat: "The requested resource [/busca/SRU] is not available" (genuine app-level 404, confirmed twice, consistent) |
| `https://www.lexml.gov.br/busca/sru?operation=searchRetrieve&version=1.1&query=guarda` | `503` (x2) then `404` on repeat — inconsistent, but never returned XML |
| `https://www.lexml.gov.br/sru?operation=searchRetrieve&version=1.1&query=guarda` | `404` |
| `http://www.lexml.gov.br/busca/SRU?...` (http, no https) | redirects to https, same `404` |
| `https://projeto.lexml.gov.br/wiki/doc/ManualDeUsoDoServicoDeBuscaSRU` | `404` on the documentation portal itself |
| `https://projeto.lexml.gov.br/@@search?SearchableText=SRU` | `0 itens atendem ao seu critério` — the doc portal's own search index has nothing for "SRU" |

The only API/interop document discoverable from the `projeto.lexml.gov.br` homepage
(`Parte 4a – Kit Provedor de Dados`, PDF, fetched via `curl` since it's a static file
on the docs portal — no bot-wall there) documents **OAI-PMH** for providers pushing
metadata into LexML (`/oai/oai.war`, `Identify`, `ListMetadataFormats` operations),
not an SRU query API for consumers. No SRU manual, WSDL, or example URL was found
anywhere reachable from the public documentation site in this pass.

**This does not confirm SRU doesn't exist** — LexML is known publicly to expose SRU —
but this spot-check could not find the current, correct base URL from public docs
alone. The `/busca/SRU` 404 is a real application response (Tomcat, not a WAF page),
which suggests either the endpoint moved, was deprecated, or lives at a URL pattern
not covered by the guesses above.

## 5. Rate-limiting / CAPTCHA / session findings (for ingestion design)

- **No CAPTCHA encountered** at any point in ~20 requests across ~10 minutes.
- **No explicit rate-limit (429) observed**, but the JS interstitial re-appears on
  the first hit to any *new* path/query-string combination even within the same
  browser session — i.e., it's not purely IP-based or purely session-cookie-based;
  it looks per-URL-signature. A scripted (non-browser) client will need either a
  headless-browser-based warm-up per target URL pattern, or a way to reuse the
  session cookie across many querystring variants of the *same* path (which worked
  for `/busca/search` and `/urn/...` in this session).
- **503s were seen on both invalid paths and, once, on a valid path** (`/busca/search`
  before the challenge resolved) — treat 503 from this origin as possibly transient/
  challenge-related, not necessarily a hard failure; retry after a few seconds is
  effective in practice.
- No ToS/robots restriction could be checked — `/robots.txt` itself returned 503
  consistently (never resolved to real content in this session).

## Sources hit (exact URLs)

- https://projeto.lexml.gov.br/
- https://projeto.lexml.gov.br/faq
- https://projeto.lexml.gov.br/documentacao/faq-do-portal-lexml
- https://projeto.lexml.gov.br/@@search?SearchableText=SRU
- https://projeto.lexml.gov.br/wiki/doc/ManualDeUsoDoServicoDeBuscaSRU (404)
- https://projeto.lexml.gov.br/documentacao/LexML_Brasil-Parte_4a-Kit_Provedor_de_Dados%20v.pdf
- https://www.lexml.gov.br/
- https://www.lexml.gov.br/busca/search?keyword=guarda+compartilhada
- https://www.lexml.gov.br/busca/search?browse-all=yes
- https://www.lexml.gov.br/urn/urn:lex:br:federal:lei:2008-06-13;11698
- https://www.lexml.gov.br/busca/SRU?operation=searchRetrieve&version=1.1&query=... (404)
- https://www.lexml.gov.br/busca/sru?operation=searchRetrieve&version=1.1&query=guarda (404/503)
- https://www.lexml.gov.br/sru?operation=searchRetrieve&version=1.1&query=guarda (404)
- https://www.lexml.gov.br/robots.txt (503, never resolved)
