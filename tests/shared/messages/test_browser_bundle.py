"""The browser bundle carries only what the web app can ask for, as compact text-only JSON, and leaves out empty translations
(the web helper then falls back to English per message)."""
import json
from pathlib import Path

from shared.messages.registry import MessageRegistry

YAML = """
UI_A:
  severity: INFO
  surface: [UI]
  variables: [n]
  en: "Hello {n}"
  hi: "नमस्ते {n}"
UI_B:
  severity: INFO
  surface: [UI]
  variables: []
  en: "Only English"
  hi: ""
API_ONLY:
  severity: ERROR
  surface: [UI]
  variables: []
  en: "Never shown by a screen"
  hi: ""
"""


def _registry(tmp_path: Path) -> MessageRegistry:
    f = tmp_path / "messages.yaml"
    f.write_text(YAML, encoding="utf-8")
    return MessageRegistry(messages_file=f)


def test_only_the_keys_the_web_app_references_are_written(tmp_path):
    _registry(tmp_path).build(output_dir=tmp_path / "out", browser_keys={"UI_A", "UI_B"})
    assert set(json.loads((tmp_path / "out/messages.en.json").read_text(encoding="utf-8"))) == {"UI_A", "UI_B"}


def test_an_empty_translation_is_left_out_so_english_is_used(tmp_path):
    _registry(tmp_path).build(output_dir=tmp_path / "out", browser_keys={"UI_A", "UI_B"})
    assert set(json.loads((tmp_path / "out/messages.hi.json").read_text(encoding="utf-8"))) == {"UI_A"}


def test_the_bundle_is_compact_and_holds_only_the_text(tmp_path):
    _registry(tmp_path).build(output_dir=tmp_path / "out", browser_keys={"UI_A"})
    raw = (tmp_path / "out/messages.en.json").read_text(encoding="utf-8")
    assert "\n" not in raw and json.loads(raw) == {"UI_A": {"text": "Hello {n}"}}


def test_without_a_key_list_every_message_is_written_as_before(tmp_path):
    _registry(tmp_path).build(output_dir=tmp_path / "out")
    assert set(json.loads((tmp_path / "out/messages.en.json").read_text(encoding="utf-8"))) == {"UI_A", "UI_B", "API_ONLY"}


def test_web_keys_are_found_by_name_and_by_template_prefix(tmp_path):
    from shared.messages.browser_keys import web_message_keys
    src = tmp_path / "src"
    (src / "locales").mkdir(parents=True)
    (src / "Page.jsx").write_text("const a = msg('UI_A'); const b = msg(`UI_PREFIX_${x}`); const c = 'UI_PLAIN' + y", encoding="utf-8")
    (src / "Page.test.jsx").write_text("msg('UI_ONLY_IN_TEST')", encoding="utf-8")
    (src / "locales/messages.en.json").write_text('{"UI_FROM_BUNDLE": {}}', encoding="utf-8")
    keys = web_message_keys(src, {"UI_A", "UI_B", "UI_PREFIX_ONE", "UI_PREFIX_TWO", "UI_PLAIN", "UI_ONLY_IN_TEST", "UI_FROM_BUNDLE"})
    assert keys == {"UI_A", "UI_PREFIX_ONE", "UI_PREFIX_TWO", "UI_PLAIN"}
