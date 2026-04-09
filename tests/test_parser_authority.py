from __future__ import annotations

import ast
from pathlib import Path

import app.normalizers as normalizers
import app.parsers as parsers


PARSERS_PATH = Path(__file__).resolve().parents[1] / "app" / "parsers.py"


def _module_ast() -> ast.Module:
    return ast.parse(PARSERS_PATH.read_text(encoding="utf-8"))


def _public_function_lines(name: str) -> list[int]:
    return [
        node.lineno
        for node in _module_ast().body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]


def _top_level_assignment_lines(name: str) -> list[int]:
    lines: list[int] = []
    for node in _module_ast().body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == name:
                lines.append(node.lineno)
    return lines


def test_parsers_module_has_single_public_parse_entry_points() -> None:
    assert _public_function_lines("parse_sections") == [parsers.parse_sections.__code__.co_firstlineno]
    assert _public_function_lines("parse_experience_section") == [parsers.parse_experience_section.__code__.co_firstlineno]
    assert _top_level_assignment_lines("parse_sections") == []
    assert _top_level_assignment_lines("parse_experience_section") == []


def test_runtime_parser_alias_chain_is_explicit() -> None:
    assert parsers._parse_sections_before_layout_fix is parsers._parse_sections_core
    assert parsers._parse_sections_before_table_guardrails is parsers._parse_sections_with_layout_fix
    assert parsers._parse_experience_section_before_layout_fix is parsers._parse_experience_section_consulting_final_eof
    assert parsers._parse_experience_section_before_labelled_tables is parsers._parse_experience_section_with_layout_fix


def test_parser_readiness_validator_delegates_to_normalizer(monkeypatch) -> None:
    calls = []
    sentinel = ["delegated"]

    def fake_validate(state):
        calls.append(state)
        return sentinel

    monkeypatch.setattr(normalizers, "validate_profile_readiness", fake_validate)

    sample_state = {"full_name": "Lerato Mokoena"}
    assert parsers.validate_profile_readiness(sample_state) is sentinel
    assert calls == [sample_state]
