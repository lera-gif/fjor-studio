"""Keys arrive with the producer and leave with the process.

On 2026-09-02 one wrong argument in a throwaway script printed all six of this
studio's API keys, because `Config` was a plain dataclass whose repr carried
`auth`. That repr is fixed -- and a key that is not on the disk cannot be
printed off it at all, which is what a kit is for.
"""
import json
import os

import pytest

from fjor_studio import kit
from fjor_studio.kit import KitError

SECRET = "SK-TEST-KEY-NEVER-REAL-0001"


@pytest.fixture(autouse=True)
def _clean():
    kit.clear()
    os.environ.pop(kit.KIT_ENV, None)
    yield
    kit.clear()
    os.environ.pop(kit.KIT_ENV, None)


def test_our_own_shape(tmp_path):
    p = tmp_path / "kit.json"
    p.write_text(json.dumps({"kie": {"api_key": SECRET,
                                     "base_url": "https://api.kie.ai"},
                             "gemini": SECRET}))
    keys = kit.read(p)
    assert sorted(keys) == ["gemini", "kie"]
    assert keys["kie"]["base_url"] == "https://api.kie.ai"   # extras survive
    assert keys["gemini"]["api_key"] == SECRET               # a bare string works


def test_the_colleagues_own_export_is_read_unchanged(tmp_path):
    """The team already has one of these and passes it around. Ours reads that
    file rather than asking anyone to convert it."""
    p = tmp_path / "creative_pipeline_kit.json"
    p.write_text(json.dumps({
        "version": 3, "kind": "settings-kit",
        "localStorage": {"creative_pipeline_v1": json.dumps(
            {"keys": {"kie": SECRET, "gemini": SECRET, "replicate": SECRET},
             "analysisDepth": "default"})},
        "indexedDB": {"style_refs": [{"blob": "ignored"}]}}))
    keys = kit.read(p)
    assert sorted(keys) == ["gemini", "kie", "replicate"]
    # a kit is CREDENTIALS, not configuration: their settings do not leak in
    assert "analysisDepth" not in keys


def test_a_kit_that_would_load_nothing_is_refused(tmp_path):
    """'Loaded, and it did nothing' is the failure this is meant to end."""
    p = tmp_path / "kit.json"
    p.write_text(json.dumps({"style_refs": [], "notes": "hello"}))
    with pytest.raises(KitError, match="no usable API keys"):
        kit.read(p)
    p.write_text("{ not json")
    with pytest.raises(KitError, match="not readable JSON"):
        kit.read(p)
    with pytest.raises(KitError, match="no kit at"):
        kit.read(tmp_path / "absent.json")


def test_only_names_ever_leave_the_module(tmp_path):
    kit.use(kit.parse({"kie": {"api_key": SECRET}}))
    assert kit.providers() == ["kie"]
    assert SECRET not in "".join(kit.providers())
    assert SECRET not in kit.source()


def test_the_env_var_supplies_a_whole_shell(tmp_path):
    p = tmp_path / "kit.json"
    p.write_text(json.dumps({"kie": {"api_key": SECRET}}))
    os.environ[kit.KIT_ENV] = str(p)
    assert sorted(kit.current()) == ["kie"]
    assert kit.source() == "$" + kit.KIT_ENV


def test_a_kit_beats_a_key_file_on_disk(tmp_path):
    """The point of the change: what the producer brought wins over whatever the
    machine happens to be holding."""
    import yaml
    from fjor_studio import config
    home = tmp_path / "home"
    (home / "config").mkdir(parents=True)
    (home / "config" / "auth.yaml").write_text(
        yaml.safe_dump({"kie": {"api_key": "STALE-ON-DISK"},
                        "dashboard": {"token": "kept"}}))
    kit.use(kit.parse({"kie": {"api_key": SECRET}}))
    cfg = config.load(home)
    assert cfg.auth["kie"]["api_key"] == SECRET
    # merged, not replaced: the dashboard token is not a provider credential
    assert cfg.auth["dashboard"]["token"] == "kept"


def test_a_config_holding_kit_keys_still_refuses_to_print_them(tmp_path):
    from fjor_studio import config
    kit.use(kit.parse({"kie": {"api_key": SECRET}}))
    cfg = config.load(tmp_path)
    assert SECRET not in repr(cfg)
    assert SECRET not in json.dumps(cfg.redacted())
