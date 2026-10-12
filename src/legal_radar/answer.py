"""Query-time LangGraph pipeline: resolve the assunto, traverse the knowledge graph, answer with
citations. The LangGraph only orchestrates these steps; the knowledge graph is read through
`GraphReader`."""

import copy
import json
from dataclasses import dataclass, field
from typing import TypedDict

import jsonschema
from langgraph.graph import END, START, StateGraph

from legal_radar.assunto import Resolution
from legal_radar.domain import Context, Hop
from legal_radar.lexml import FEDERAL_LEI
from legal_radar.llm import CompletionParams, content_hash
from legal_radar.ports import GraphReader, Provider
from legal_radar.prompts import PromptError, PromptLock, default_lock

ANSWER_PROMPT = "cited-answer"
ANSWER_TEMPLATE = (
    "Responda à pergunta usando apenas as fontes abaixo, e cite em `citations` o id de cada "
    "fonte em que a resposta se apoia. Se as fontes não bastarem, diga isso.\n\n"
    "Pergunta: {query}\n\nFontes:\n{context}"
)
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
            "minItems": 1,
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


def source_texts(context: Context) -> dict[str, str]:
    """Each retrieved node's id with the text the model is shown for it."""
    texts = {d.id: d.text for d in context.dispositivos}
    for j in context.jurisprudencias:
        texts[j.id] = f"{j.number}. Tese: {j.tese or '-'}. Ementa: {j.ementa}"
    return texts


def render_context(context: Context) -> str:
    return "\n\n".join(f"[{id}] {text}" for id, text in source_texts(context).items())


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


def build_graph(resolve, reader: GraphReader, provider: Provider, lock: PromptLock):
    """Compile the pipeline; `resolve(query) -> Resolution | None` is the assunto resolver."""

    def resolve_assunto(state: State) -> State:
        return {"resolution": resolve(state["query"])}

    def traverse(state: State) -> State:
        leis = anchor_ids_of(state["resolution"], reader.lei_ids())
        return {"context": reader.traverse(leis)}

    def generate(state: State) -> State:
        context = state["context"]
        ids = [d.id for d in context.dispositivos] + [j.id for j in context.jurisprudencias]
        if not ids:
            return {"answer": None, "cited": []}
        schema = answer_schema(lock, ids)
        params = CompletionParams(
            pipeline_step="answer",
            response_schema=schema,
            prompt_snapshot=content_hash(
                {"prompt": lock.prompt_hash(ANSWER_PROMPT), "schema": schema}
            ),
        )
        prompt = lock.render(ANSWER_PROMPT, query=state["query"], context=render_context(context))
        answer, cited = parse_answer(provider.complete(prompt, params).text, schema)
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
) -> CitedAnswer:
    """Answers `query` from the knowledge graph, citing the dispositivos and jurisprudência used."""
    state = build_graph(resolve, reader, provider, lock or default_lock()).invoke({"query": query})
    resolution = state["resolution"]
    if resolution is None:
        return CitedAnswer(query, None, None, [])
    context = state["context"]
    kinds = {d.id: "Dispositivo" for d in context.dispositivos}
    kinds |= {j.id: "Jurisprudencia" for j in context.jurisprudencias}
    texts = source_texts(context)
    citations = [Citation(i, kinds[i], context.paths[i], texts[i]) for i in state["cited"]]
    return CitedAnswer(query, resolution.assunto, state["answer"], citations, list(texts))
