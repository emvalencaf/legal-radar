# Does LangGraph/LangChain ship built-in complexity-based query routing?

- **Ticket**: [#20](https://github.com/emvalencaf/legal-radar/issues/20) — Research: does LangGraph/LangChain provide built-in complexity-based query routing? (child of #1)
- **Sources**: LangChain/LangGraph official docs (`docs.langchain.com`, `python.langchain.com`), `langchain-ai/langchain` GitHub source (deprecation decorators read directly from `libs/langchain/langchain_classic/chains/router/multi_prompt.py`), and `aurelio-labs/semantic-router` (third-party, noted as such). The JEV/LAYA blog post is cited only for the framing, not as a technical source.

## Question

Issue [#8](https://github.com/emvalencaf/legal-radar/issues/8) (model-routing architecture) deferred **complexity-based query routing** — classifying a query's difficulty and routing harder queries to a bigger/more capable model, the JEV/LAYA framing (see [blog.beerandcode.com.br](https://blog.beerandcode.com.br/noticias/laya-vs-jev-ia-decisao-open-source), a community blog post) — to keep the initial routing design simple. Does LangChain/LangGraph already ship a first-class primitive for this?

## 1. Does a built-in mechanism exist?

**No, not for complexity-based routing specifically.** What exists instead:

- **`RouterChain` / `MultiPromptChain`** (legacy `langchain.chains.router`) route by **task type / prompt template**, not by difficulty, and are **deprecated**:

  ```python
  @deprecated(
      since="0.2.12",
      removal="2.0.0",
      alternative="langchain.agents.create_agent",
      ...
  )
  class MultiPromptChain(MultiRouteChain):
  ```
  — [`multi_prompt.py`](https://github.com/langchain-ai/langchain/blob/master/libs/langchain/langchain_classic/chains/router/multi_prompt.py). `RouterChain`/`LLMRouterChain` carry the same marker, now under the legacy `langchain_classic` namespace ([reference.langchain.com/python/langchain-classic/chains/router](https://reference.langchain.com/python/langchain-classic/chains/router)), superseded by `create_agent` with subagents or prompt-selection middleware.

- **LangGraph conditional edges** (`add_conditional_edges`) — the modern, recommended branching mechanism, but generic: you supply the routing function yourself ([docs.langchain.com/oss/python/langgraph/graph-api](https://docs.langchain.com/oss/python/langgraph/graph-api)). LangChain's own [multi-source router cookbook](https://docs.langchain.com/oss/python/langchain/multi-agent/router-knowledge-base) uses an LLM structured-output call + conditional edge to route by **knowledge source/topic**, not difficulty — a pattern to assemble, not a shipped router object.

- **`RunnableBranch`** (`langchain_core.runnables.branch`) — a generic if/elif/else over `Runnable`s keyed on a predicate you write ([API reference](https://python.langchain.com/api_reference/core/runnables/langchain_core.runnables.branch.RunnableBranch.html)). Same story.

**Conclusion**: no shipped "difficulty classifier → bigger model" primitive. Everything available is either deprecated and scoped to task-type routing, or a generic branching primitive expecting the classification logic to be supplied.

## 2. Integration shape and cost against #8's design

- The closest built-ins (`create_agent`, conditional edges, `RunnableBranch`) all assume LangChain's `Runnable`/LangGraph `StateGraph` object model. Adopting them as the routing layer means routing decisions live as LangChain constructs, not as calls into `ProviderPort.complete()` from #8 — either duplicating routing logic or letting LangChain own orchestration and reducing the port to a thin adapter.
- Any complexity-classification step is itself an **extra LLM call before the "real" call** — it competes for quota/RPM against completion calls, directly interacting with #8's free-tier budgets and auto-fallback logic. It's compatible in shape with `complete()` (just a second stateless call), but doubles call volume per user query.
- No need to abandon the hexagonal port/adapter design — a classifier is just another `complete()` call — but pulling in `langchain`/`langgraph` as a dependency for `create_agent`/conditional edges is a much heavier footprint than #8 needs today, and buys nothing built-in for the classification step itself.

## 3. Closest applicable pattern and recommendation

- **LLM-as-judge / classifier-first routing** — LangChain's own knowledge-base router cookbook pattern (cheap model classifies via structured output, then dispatch) generalizes directly to a difficulty classifier.
- **`semantic-router`** ([aurelio-labs/semantic-router](https://github.com/aurelio-labs/semantic-router), third-party) routes by embedding similarity to example utterances, not an inherent difficulty score — an indirect fit requiring curated "hard query" utterances per route, plus an embeddings dependency.
- **`RunnableBranch`/conditional edges with a hand-written scorer** — the most direct fit for #8's architecture: a small function (heuristics or a cheap classifier call) returns a routing decision, then the existing `complete()` port is called with a different configured model/provider. No new framework dependency.

**Recommendation**: no built-in mechanism to adopt; no existing framework primitive is a strong fit. The practical path is a **custom lightweight classifier/heuristic** sitting in front of #8's existing router — not `RouterChain` (deprecated, task-type only), not full LangChain/LangGraph adoption (heavy dependency, no complexity-specific payoff), and not `semantic-router` (solves intent/topic matching, not difficulty scoring).

**Worth a future ticket: yes**, scoped narrowly to: (a) define what "complex" means for this domain (multi-hop legal reasoning vs. simple lookup), (b) decide rule-based heuristic vs. a cheap classifier call, and (c) how the routing decision plugs into #8's config-driven provider-priority list (an extra selection axis, not a replacement). This is a design question — no existing library solves the classification part, only the "dispatch once decided" part, which #8's router already does.

## Sources

- [`langchain-ai/langchain` — `multi_prompt.py` source (deprecation decorator)](https://github.com/langchain-ai/langchain/blob/master/libs/langchain/langchain_classic/chains/router/multi_prompt.py)
- [LangChain Classic reference — router chains](https://reference.langchain.com/python/langchain-classic/chains/router)
- [LangChain migration guide / `create_agent` overview](https://docs.langchain.com/oss/python/langchain/overview)
- [LangGraph — conditional edges (`add_conditional_edges`)](https://docs.langchain.com/oss/python/langgraph/graph-api)
- [LangChain cookbook — multi-source router with knowledge bases](https://docs.langchain.com/oss/python/langchain/multi-agent/router-knowledge-base)
- [LangChain Core — `RunnableBranch` API reference](https://python.langchain.com/api_reference/core/runnables/langchain_core.runnables.branch.RunnableBranch.html)
- [`aurelio-labs/semantic-router` (GitHub, third party)](https://github.com/aurelio-labs/semantic-router)
- [JEV/LAYA framing (community blog, secondary source, cited for context only)](https://blog.beerandcode.com.br/noticias/laya-vs-jev-ia-decisao-open-source)
