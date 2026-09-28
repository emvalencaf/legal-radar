# Use Planalto HTML, not LexML XML, as the source for a lei's full text

LexML (lexml.gov.br) does not publicly expose a raw XML document per `lei`: there is no bulk export, and the only downloadable toolkit ("Kit Provedor de Dados") is an OAI-PMH server for data *providers* pushing metadata in, not a way for consumers to pull a document's XML out (spot-checked hands-on in issue #6). A resolved LexML URN page is metadata plus outbound links to the full text hosted elsewhere — for federal leis, that's overwhelmingly the Planalto portal's HTML rendition.

We decided ingestion treats **Planalto** (`planalto.gov.br/ccivil_03/leis/{law_id}.htm`) as the full-text source for the legal-document AST, reached by following the "Texto Atualizado" link off the resolved LexML URN page (never by guessing the Planalto filename from the lei's number). LexML's role narrows to assunto search and URN resolution/identity only. This reuses `PlanaltoFetcherAdapter` and `PlanaltoHtmlParser` from the sibling repo `ip_lawyer_consiglier` largely as-is, whose `LegalChunk.parent`/`children` already realize the graph's `PARTS` hierarchy edge (issue #7).

## Consequences

- Only leis whose "Texto Atualizado" resolves to Planalto are in scope; Câmara/Senado HTML or Imprensa Nacional PDF destinations have no parser and are out of scope for now (issue #10).
- The LexML **URN**, not Planalto's `law_id`, is the graph's canonical Lei node id; `law_id` is only an internal crosswalk field.
