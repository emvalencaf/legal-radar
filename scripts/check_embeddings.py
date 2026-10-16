"""Live check of an embedding provider: one embed call, then assunto resolution scores.

Usage: check_embeddings.py [gemini|lmstudio] (default gemini). Gemini needs GEMINI_API_KEY;
LM Studio reads LMSTUDIO_BASE_URL and needs its embedding model loaded.
Prints each query's best score so the resolver threshold
(`legal_radar.application.assunto.DEFAULT_THRESHOLD`) can be tuned against a real model.
"""

import sys

from legal_radar.adapters.router_config import build_router, load_config
from legal_radar.application.assunto import DEFAULT_THRESHOLD, AssuntoResolver, cosine

RELATED = [
    "desconsideração da personalidade jurídica",
    "pedido de desconsiderar a personalidade da pessoa jurídica",
    "quando o juiz pode ignorar a pessoa jurídica para atingir o patrimônio dos sócios",
    "abuso da personalidade jurídica por confusão patrimonial",
    "levantar o véu societário",
    "sócio responde com o patrimônio pessoal por dívidas da empresa",
    "confusão patrimonial entre sócio e sociedade",
]
# Same legal register as the assunto, so only meaning (not vocabulary) can reject them.
UNRELATED = [
    "prescrição intercorrente na execução fiscal",
    "usucapião extraordinária de imóvel urbano",
    "rescisão indireta do contrato de trabalho por falta grave do empregador",
    "imunidade tributária das pessoas jurídicas de direito público",
    "responsabilidade civil do médico por erro de diagnóstico",
    "regime de bens no casamento e partilha em divórcio",
    "receita de bolo de cenoura",
]


def main(provider: str) -> int:
    config = load_config("router.yaml")
    config["providers"] = [provider]
    router = build_router(config)
    probe = router.embed(["teste"])
    print(f"embed ok: {probe.provider}/{probe.model}, {len(probe.vectors[0])} dimensions")

    resolver = AssuntoResolver(router)
    catalog = list(resolver.catalog)
    vectors = router.embed(catalog).vectors
    for label, queries in (("related", RELATED), ("unrelated", UNRELATED)):
        for query, vector in zip(queries, router.embed(queries).vectors, strict=True):
            score = max(cosine(vector, candidate) for candidate in vectors)
            hit = resolver.resolve(query) is not None
            print(f"{label:9} {score:.3f} {'RESOLVED' if hit else 'rejected'}  {query}")
    print(f"threshold in use: {DEFAULT_THRESHOLD}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "gemini"))
