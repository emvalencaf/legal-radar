import ast
import inspect
import textwrap

import pytest

from legal_radar.domain.anchors import ANCHORS
from legal_radar.entrypoints.cli import app
from legal_radar.settings import Settings

SUBJECT = sorted(ANCHORS)[0]
ARGV = {
    "run": [],
    "ingest": [SUBJECT],
    "ingest-jurisprudencia": [SUBJECT],
    "run-all": [SUBJECT],
    "draft-concepts": [SUBJECT],
    "refresh-prompts": [],
    "ask": ["a question"],
    "eval": [SUBJECT],
    "index-rag": ["naive"],
    "compare-evals": [],
    "report": [],
    "export-seed": [],
    "seed": [],
}


HANDLERS = {**app.OFFLINE, **app.ONLINE, "run": app.run_skeleton}


def args_read_by(handler) -> set[str]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(handler)))
    return {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "args"
    }


def test_every_command_has_a_sample_so_a_new_one_is_not_left_untested():
    assert set(ARGV) == set(HANDLERS)


@pytest.mark.parametrize("command", sorted(ARGV))
def test_a_command_defines_every_argument_its_handler_reads(command):
    handler = HANDLERS[command]
    parsed = app.build_parser(Settings()).parse_args([command, *ARGV[command]])
    missing = args_read_by(handler) - set(vars(parsed))
    assert not missing, (
        f"{command} reads args.{', args.'.join(sorted(missing))} the parser never sets"
    )
