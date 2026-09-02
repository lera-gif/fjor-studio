"""The CLI, exercised by calling main() -- not by reading it."""
import json

import pytest
import yaml

from conftest import scene_plan, write_config, write_replies
from fjor_studio.cli import main


@pytest.fixture
def cli_home(home, reference):
    write_config(home, pipeline={"gates": {"skip": ["GATE_PLAN", "GATE_CLIPS"]}})
    write_replies(home, analysis="analysed", text=scene_plan(2),
                  **{"qa:plate": json.dumps({"passed": True, "severity": "ok"}),
                     "qa:clip": json.dumps({"passed": True, "severity": "ok"})})
    return home, reference


def run(home, *args):
    return main(["--home", str(home)] + list(args))


def test_new_run_approve_reaches_done(cli_home, capsys):
    home, reference = cli_home
    assert run(home, "new", "lipedema_pilates", str(reference), "--week", "34",
               "--concept", "ugc", "--scenes", "2", "--run") == 0
    out = capsys.readouterr().out
    assert "created LIPIL001" in out
    assert "GATE_PLATES" in out
    assert run(home, "approve", "LIPIL001") == 0
    assert run(home, "approve", "LIPIL001") == 0
    assert run(home, "status", "LIPIL001") == 0
    assert "done" in capsys.readouterr().out


def test_the_gate_prints_the_forecast_before_the_spend(cli_home, capsys):
    home, reference = cli_home
    run(home, "new", "lipedema_pilates", str(reference), "--week", "34",
               "--concept", "ugc", "--scenes", "2", "--run")
    out = capsys.readouterr().out
    assert "next stage forecast: 248.0 cr" in out


def test_config_never_prints_a_key(cli_home, capsys):
    home, _ref = cli_home
    (home / "config" / "auth.yaml").write_text(
        yaml.safe_dump({"kie": {"api_key": "sk-live-SECRET-VALUE-0001"}}))
    run(home, "config")
    out = capsys.readouterr().out
    assert "SECRET" not in out
    assert "sk-…01" in out


def test_a_failed_job_exits_nonzero(cli_home, capsys):
    home, reference = cli_home
    write_replies(home, analysis="a", text=json.dumps({"scenes": [
        {"idx": 0, "image_prompt": "__moderation__", "video_prompt": "m",
         "duration_s": 5}]}))
    assert run(home, "new", "lipedema_pilates", str(reference),
               "--week", "34", "--concept", "ugc", "--run") == 1


def test_a_configuration_mistake_is_a_sentence_not_a_traceback(home, reference, capsys):
    """On a new deployment most failures are somebody's config, and a traceback
    reads as a broken program. `cli()` is what the console script and `python -m`
    both call."""
    from fjor_studio.cli import cli
    write_config(home, delivery={"root": ""})
    code = cli(["--home", str(home), "new", "yoga", str(reference),
                "--week", "40", "--concept", "test"])
    out = capsys.readouterr()
    assert code == 2
    assert "Traceback" not in out.err
    assert "delivery root" in out.err
    assert "FJOR_STUDIO_DELIVERY_ROOT" in out.err


def test_setup_commands_run_before_any_key_exists(home, capsys):
    """`config` is what DEPLOY.md tells a new machine to run to see what is
    still missing. Building the backends first made it refuse to print the
    configuration until the configuration was already complete."""
    from fjor_studio.cli import cli
    write_config(home, models={"providers": {"analysis": "gemini", "text": "gemini",
                                             "image": "kie", "video": "kie",
                                             "speech": "gemini"}})
    (home / "config" / "auth.yaml").write_text("{}")      # no keys at all
    for cmd in ("config", "assets", "list"):
        assert cli(["--home", str(home), cmd]) == 0, f"`{cmd}` needed a key"
    out = capsys.readouterr().out
    assert "delivery" in out and "packshots" in out


def test_a_paid_command_still_refuses_without_the_backend(home, reference, capsys):
    """The other half: routing that cannot be built must still fail at startup,
    not in the middle of a stage that has been paid for."""
    from fjor_studio.cli import cli
    write_config(home, models={"providers": {"analysis": "gemini", "text": "gemini",
                                             "image": "kie", "video": "kie",
                                             "speech": "gemini"}})
    (home / "config" / "auth.yaml").write_text("{}")
    code = cli(["--home", str(home), "new", "yoga", str(reference),
                "--week", "40", "--concept", "test", "--run"])
    assert code == 2
    err = capsys.readouterr().err
    assert "api_key" in err and "Traceback" not in err


def test_a_config_it_cannot_read_is_a_sentence_too(home, reference, capsys):
    """The dashboard held its port for an hour on 2026-08-27 while every request
    failed on an unreadable pipeline.yaml. Whatever else that costs, it should
    not also cost a traceback."""
    import os
    from fjor_studio.cli import cli
    write_config(home)
    target = home / "config" / "pipeline.yaml"
    os.chmod(target, 0o000)
    try:
        code = cli(["--home", str(home), "list"])
        err = capsys.readouterr().err
    finally:
        os.chmod(target, 0o644)
    assert code == 2
    assert "Traceback" not in err
    assert "pipeline.yaml" in err


def test_the_cli_can_ask_for_everything_the_dashboard_can(cli_home, tmp_path):
    """Parity, checked rather than assumed. `--ref-kind`, `--morph` and
    `--text-card` reached the dashboard and never reached the CLI, because an
    edit asserted on a pattern that lives in the other file and silently wrote
    nothing. The deploy doc then told people to run flags that did not exist."""
    home, reference = cli_home
    from fjor_studio.engine.store import JobStore
    assert run(home, "new", "lipedema_pilates", str(reference),
               "--name", "n-LIPIL700_ch-fb_t-video_c-morph_pr-lp_ds-nano_w-34_s-1080x1350",
               "--ref-kind", "replica",
               "--morph", "her posture straightens",
               "--text-card", "5 minutes a day") == 0
    intake = JobStore(home / "jobs").load("LIPIL700").intake
    assert intake["ref_kind"] == "replica"
    assert intake["morph"] == "her posture straightens"
    assert intake["text_card"] == "5 minutes a day"


def test_an_unknown_reference_kind_is_refused_at_the_flag(cli_home):
    home, reference = cli_home
    with pytest.raises(SystemExit):
        run(home, "new", "lipedema_pilates", str(reference),
            "--name", "n-LIPIL701_ch-fb_t-video_c-ugc_pr-lp_ds-nano_w-34_s-1080x1350",
            "--ref-kind", "pixar")
