"""Query-time LangGraph pipeline: resolve the assunto, traverse the knowledge graph, answer with
citations. The LangGraph only orchestrates these steps; the knowledge graph is read through
`GraphReader`."""

import copy
import json
import re
from dataclasses import dataclass, field
from typing import TypedDict

import jsonschema
from langgraph.graph import END, START, StateGraph

from legal_radar.adapters.prompt_lock import default_lock
from legal_radar.application.assunto import Resolution
from legal_radar.application.ports import GraphReader, Provider
from legal_radar.domain.complexity import DEFAULT_MAX_CONTEXT_TOKENS, classify
from legal_radar.domain.llm import CompletionParams, content_hash
from legal_radar.domain.model import Context, Hop, Jurisprudencia
from legal_radar.domain.prompts import PromptError, PromptLock
from legal_radar.domain.relations import extract_decision_relations
from legal_radar.domain.urn import FEDERAL_LEI

ANSWER_PROMPT = "cited-answer"
# The sources come first and the question last, so a provider can cache the fixed context block.
ANSWER_TEMPLATE = """Responda à pergunta usando apenas as fontes abaixo.

Regras:
- Use somente o que está nas fontes. Não use conhecimento externo e não mencione artigo, lei \
ou decisão que não esteja nelas.
- Em `citations`, liste só as fontes indispensáveis: a menor quantidade que sustenta a resposta. \
Prefira o dispositivo específico (parágrafo, inciso) ao artigo inteiro quando só ele responde. \
Não cite uma fonte só por ser do mesmo assunto.
- Se as fontes não respondem à pergunta, diga que não bastam e deixe `citations` vazio.
- Se duas fontes divergem, aponte a divergência.

Fontes:
{context}

Pergunta: {query}"""
ANSWER_SCHEMA = {  # published to the Hub as `cited-answer`'s structured output
    "title": "cited_answer",
    "type": "object",
    "description": "A resposta à pergunta, com os ids das fontes em que se apoia.",
    "properties": {
        "answer": {"type": "string", "minLength": 1},
        "citations": {
            "type": "array",
            "description": "Ids dos dispositivos e das jurisprudências do contexto citados.",
            "items": {"type": "string", "enum": ["placeholder"]},  # the context's ids at run time
            "uniqueItems": True,
        },
    },
    "required": ["answer", "citations"],
    "additionalProperties": False,
}


class CitationError(ValueError):
    """The LLM's reply is outside the pinned schema, or cites something it was not given."""


@dataclass(frozen=True)
class Citation:
    id: str
    kind: str  # "Dispositivo" | "Jurisprudencia": the label of the graph node `id` resolves to
    path: list[Hop]  # how the traversal reached it from the anchor lei
    text: str = ""  # the source text the answer was given, for grounding checks


@dataclass(frozen=True)
class CitedAnswer:
    query: str
    assunto: str | None  # None: the query matched no known assunto, so nothing was answered
    answer: str | None
    citations: list[Citation]
    retrieved: list[str] = field(default_factory=list)  # every node id the traversal reached
    unsupported: list[str] = field(default_factory=list)  # articles the answer names, not retrieved


class State(TypedDict, total=False):
    query: str
    resolution: Resolution | None
    context: Context
    answer: str | None
    cited: list[str]


def answer_schema(lock: PromptLock, context_ids: list[str]) -> dict:
    """The pinned schema, with the retrieved nodes' ids as the only citable values."""
    schema = lock.schema(ANSWER_PROMPT)
    if schema is None:
        raise PromptError(f"prompt {ANSWER_PROMPT!r} has no pinned schema: run `refresh-prompts`")
    schema = copy.deepcopy(schema)
    try:
        schema["properties"]["citations"]["items"]["enum"] = sorted(context_ids)
    except (KeyError, TypeError) as error:
        raise PromptError(f"prompt {ANSWER_PROMPT!r}: its schema has no citations") from error
    return schema


def jurisprudencia_text(j: Jurisprudencia) -> str:
    """The text a decision is shown as: its number, tese and ementa (never the decisão)."""
    return f"{j.number}. Tese: {j.tese or '-'}. Ementa: {j.ementa}"


def source_texts(context: Context) -> dict[str, str]:
    """Each retrieved node's id with the text the model is shown for it."""
    texts = {d.id: d.text for d in context.dispositivos}
    for j in context.jurisprudencias:
        texts[j.id] = jurisprudencia_text(j)
    return texts


_AMENDMENT = re.compile(
    r"\s*\((?:Redação|Inclu[ií]d|Vide|Regulamento|Vig[eê]ncia|Renumerad)[^)]*\)"
)


def strip_amendments(text: str) -> str:
    """The text without the `(Incluído pela Lei …)` marks: they add tokens and no meaning to an
    answer or an embedding."""
    return _AMENDMENT.sub("", text).strip()


def render_sources(texts: dict[str, str]) -> str:
    """The sources as shown to the model, without the amendment marks."""
    return "\n\n".join(f"[{id}] {strip_amendments(text)}" for id, text in texts.items())


def render_context(context: Context) -> str:
    return render_sources(source_texts(context))


def unsupported_mentions(answer: str, retrieved: list[str]) -> list[str]:
    """The dispositivos the answer names that the sources it was given do not contain. A mention
    that names no lei is not checked: it cannot be resolved."""
    mentions = extract_decision_relations(Jurisprudencia("", "", "", answer, ""))
    known = set(retrieved)
    return [r.target_id for r in mentions.relations if r.target_id and r.target_id not in known]


def parse_answer(text: str, schema: dict) -> tuple[str, list[str]]:
    try:
        reply = json.loads(text)
        jsonschema.validate(reply, schema)
    except (ValueError, jsonschema.ValidationError) as error:
        raise CitationError(f"the LLM did not answer the cited-answer schema: {error}") from error
    return reply["answer"], reply["citations"]


def anchor_ids_of(resolution: Resolution, urns: list[str]) -> list[str]:
    """The graph nodes the traversal starts from: for each anchor lei present in the graph (by
    number and year), its anchor dispositivos, or the whole lei when it names none."""
    found = []
    for urn in urns:
        m = FEDERAL_LEI.match(urn)
        for anchor in resolution.anchors:
            if m and (m[2], int(m[1])) == (anchor.numero, anchor.ano):
                found += [f"{urn}#{path}" for path in anchor.artigos] or [urn]
    return found


def answer_from(
    query: str,
    texts: dict[str, str],
    provider: Provider,
    lock: PromptLock,
    complexity: str | None = None,
) -> tuple[str | None, list[str]]:
    """The cited answer to `query` from the sources `texts` (id -> text) alone, with the ids it
    cites; `(None, [])` when there are none. Shared by the graph pipeline and the RAG baselines."""
    if not texts:
        return None, []
    schema = answer_schema(lock, list(texts))
    params = CompletionParams(
        pipeline_step="answer",
        complexity=complexity,
        response_schema=schema,
        prompt_snapshot=content_hash({"prompt": lock.prompt_hash(ANSWER_PROMPT), "schema": schema}),
    )
    prompt = lock.render(ANSWER_PROMPT, query=query, context=render_sources(texts))
    return parse_answer(provider.complete(prompt, params).text, schema)


def build_graph(
    resolve,
    reader: GraphReader,
    provider: Provider,
    lock: PromptLock,
    max_context_tokens: int = DEFAULT_MAX_CONTEXT_TOKENS,
):
    """Compile the pipeline; `resolve(query) -> Resolution | None` is the assunto resolver."""

    def resolve_assunto(state: State) -> State:
        return {"resolution": resolve(state["query"])}

    def traverse(state: State) -> State:
        leis = anchor_ids_of(state["resolution"], reader.lei_ids())
        return {"context": reader.traverse(leis)}

    def generate(state: State) -> State:
        context = state["context"]
        complexity = classify(context, max_context_tokens)
        answer, cited = answer_from(
            state["query"], source_texts(context), provider, lock, complexity
        )
        return {"answer": answer, "cited": cited}

    graph = StateGraph(State)
    graph.add_node("resolve_assunto", resolve_assunto)
    graph.add_node("traverse", traverse)
    graph.add_node("generate", generate)
    graph.add_edge(START, "resolve_assunto")
    graph.add_conditional_edges("resolve_assunto", lambda s: "traverse" if s["resolution"] else END)
    graph.add_edge("traverse", "generate")
    graph.add_edge("generate", END)
    return graph.compile()


def ask(
    query: str,
    resolve,
    reader: GraphReader,
    provider: Provider,
    lock: PromptLock | None = None,
    max_context_tokens: int = DEFAULT_MAX_CONTEXT_TOKENS,
) -> CitedAnswer:
    """Answers `query` from the knowledge graph, citing the dispositivos and jurisprudência used."""
    graph = build_graph(resolve, reader, provider, lock or default_lock(), max_context_tokens)
    state = graph.invoke({"query": query})
    resolution = state["resolution"]
    if resolution is None:
        return CitedAnswer(query, None, None, [])
    context = state["context"]
    kinds = {d.id: "Dispositivo" for d in context.dispositivos}
    kinds |= {j.id: "Jurisprudencia" for j in context.jurisprudencias}
    texts = source_texts(context)
    citations = [Citation(i, kinds[i], context.paths[i], texts[i]) for i in state["cited"]]
    unsupported = unsupported_mentions(state["answer"] or "", list(texts))
    return CitedAnswer(
        query, resolution.assunto, state["answer"], citations, list(texts), unsupported
    )
