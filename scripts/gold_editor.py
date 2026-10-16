"""Edit the enrichment gold set in the browser: the graph plus a review panel (#67).

Usage: gold_editor.py [--port 8765] [--proposed FILE] [--gold FILE]

Serves the same page as `visualize_gold.py`, editable, on 127.0.0.1. Review one provision at a
time: accept, correct or reject each relation Claude Code inferred, add what it missed, then
confirm. A provision only counts once confirmed (a proposal with nothing is confirmed as a
negative), so none can be skipped; each confirmation is saved to the same `.progress.yml` the
terminal wizard (`annotate_gold.py`) uses, with the same accepted/corrected/added marks. When all
are confirmed the page writes the gold file, checked against the vocabulary hash. The metrics
measure agreement with a single annotator, not absolute truth.
"""

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml
from visualize_gold import ROOT, TEMPLATE, build_data

from legal_radar.application.concepts import load_vocabulary
from legal_radar.application.evaluation.enrichment_gold import GoldError, load_gold
from legal_radar.application.evaluation.gold_review import assemble


class Editor:
    def __init__(self, proposed: Path, gold: Path):
        self.vocabulary = load_vocabulary(ROOT / "concepts" / "desconsideracao_personalidade.yml")
        self.document = yaml.safe_load(proposed.read_text(encoding="utf-8"))
        if self.document.get("vocabulary_hash") != self.vocabulary.hash:
            raise SystemExit("the proposal was made against another vocabulary: regenerate it")
        self.order = [e["id"] for e in self.document["dispositivos"]]
        self.gold = gold
        self.progress = gold.with_suffix(".progress.yml")
        self.proposed = proposed

    def reviewed(self) -> list[dict]:
        if not self.progress.exists():
            return []
        return yaml.safe_load(self.progress.read_text(encoding="utf-8")) or []

    def page(self) -> str:
        data = build_data([self.proposed])
        data.update(editable=True, proposal=self.document["dispositivos"], progress=self.reviewed())
        text = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
        return TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", text)

    def save(self, entries: list[dict]) -> dict:
        unknown = [e.get("id") for e in entries if e.get("id") not in self.order]
        if unknown or any(not isinstance(e.get("edges"), list) for e in entries):
            return {"error": f"not a reviewed entry of this proposal: {unknown or entries}"}
        self.progress.write_text(
            yaml.safe_dump(entries, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        return {"ok": True, "reviewed": len(entries)}

    def finish(self) -> dict:
        try:
            reviewed = assemble(self.order, self.reviewed())
            text = yaml.safe_dump(
                {"vocabulary_hash": self.vocabulary.hash, "dispositivos": reviewed},
                allow_unicode=True,
                sort_keys=False,
                width=100,
            )
            load_gold(text, self.vocabulary)  # fail here, not at the first eval run
        except (ValueError, GoldError) as error:
            return {"error": str(error)}
        self.gold.write_text(text, encoding="utf-8")
        return {
            "ok": True,
            "path": str(
                self.gold.relative_to(ROOT) if self.gold.is_relative_to(ROOT) else self.gold
            ),
            "count": len(reviewed),
        }


def handler(editor: Editor, port: int):
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: bytes, kind: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", f"{kind}; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _allowed(self) -> bool:  # local-only: refuse DNS-rebinding and cross-site posts
            return self.headers.get("Host") in hosts

        def do_GET(self):
            if not self._allowed() or self.path != "/":
                return self._send(404, b"not found", "text/plain")
            self._send(200, editor.page().encode(), "text/html")

        def do_POST(self):
            if not self._allowed() or self.headers.get("Content-Type") != "application/json":
                return self._send(403, b"forbidden", "text/plain")
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            routes = {"/api/progress": lambda: editor.save(body), "/api/finish": editor.finish}
            if self.path not in routes:
                return self._send(404, b"not found", "text/plain")
            self._send(200, json.dumps(routes[self.path]()).encode(), "application/json")

        def log_message(self, *args):
            pass

    return Handler


def main(args: argparse.Namespace) -> int:
    editor = Editor(args.proposed, args.gold)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler(editor, args.port))
    print(f"editing the gold set at http://localhost:{args.port}  (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--proposed", type=Path, default=ROOT / "evaluation/enrichment_gold.proposed.yml"
    )
    parser.add_argument("--gold", type=Path, default=ROOT / "evaluation/enrichment_gold.yml")
    sys.exit(main(parser.parse_args()))
