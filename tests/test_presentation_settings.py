"""A setting that only changes what Xeda or a tool prints (`PRESENTATION`) is no part of a run.

Changing `quiet` must not start a flow again, and it must not make a finished run stale. The
sweeps pair the marker with every flow, so a new flow that redeclares a presentation setting, or
a new marked setting, fails until it is reviewed here.
"""

import json
from pathlib import Path, PurePosixPath

import pytest

from xeda import Design
from xeda.dataclass import PRESENTATION, Field, XedaBaseModel, is_presentation
from xeda.flow import Flow, flowrun_hash
from xeda.flow.flow import identity_settings
from xeda.flow_runner import DefaultRunner
from xeda.remote.packaging import package_inputs

from . import tool_utils
from .settings_samples import flow_classes, minimal_settings
from .test_written_paths import _models

ECP5 = "LFE5U-25F-6BG381C"

#: The settings that only change what is printed, with the evidence for each (all of them are
#: fields of `Flow.Settings`). A flow reads each one only to pass a flag or to choose a stream:
#: no file that a flow reads or delivers depends on it.
#:   quiet: `-q` of yosys (log, `tee -o` files and netlist are byte-identical), `--quiet` of
#:     nextpnr (log and report identical but for times), `-quiet` of bsc compile and link (the
#:     log is read only to quote errors, which bsc still prints), `log_vcd -quiet` of vivado_sim
#:     (no longer passed: it would make the command ignore its errors).
#:   print_commands: only the line "Running `...`" on the console stream.
#:   redirect_stdout: only the Vivado flows read it; they send the tool output to a file that no
#:     flow reads (a flow that reads the output of a tool clears it with `derive`).
PRESENTATION_SETTINGS = {"quiet", "print_commands", "redirect_stdout"}

#: Settings of `Flow.Settings` that look like presentation and are not, with the reason.
NOT_PRESENTATION = {
    "verbose": "tool flags and script branches (ghdl, nvc, vcs, nextpnr, yosys, vivado)",
    "debug": "tool flags and script branches; modelsim records other signals, yosys echoes",
    "console_colors": "gives openFPGALoader a terminal, which changes the log that Xeda judges",
}

#: A flow class that redeclares a presentation setting as a setting of its own, and keeps it in
#: the identity because its tool may change what the flow reads.
REDECLARED = {
    ("vcs", "quiet"): "`-q` of `vcs -R` runs the simulation that writes the runtime log, which "
    "the finish evidence reads; no licensed VCS was available to show that it does not matter",
}


def _fields(settings_class):
    """`(owner model, field name)` of every field of a flow's settings, nested models too."""
    seen = []

    def walk(model):
        for name, info in model.model_fields.items():
            yield model, name
            for nested in _models(info.annotation):
                if nested not in seen:
                    seen.append(nested)
                    yield from walk(nested)

    yield from walk(settings_class)


CASES = [(cls, name) for cls, name in flow_classes()]


def _settings(cls, tmp_path, **given):
    return cls.Settings.from_input(
        {**minimal_settings(cls), **given}, design_root=tmp_path / "d", runner_cwd=tmp_path
    )


def test_the_marker_tells_the_marked_fields():
    assert PRESENTATION == {"x-xeda-presentation": True}
    assert is_presentation(Flow.Settings, "quiet")
    assert not is_presentation(Flow.Settings, "verbose")
    assert not is_presentation(Flow.Settings, "no_such_field")


@pytest.mark.parametrize("cls, name", CASES, ids=[name for _c, name in CASES])
def test_every_flow_marks_the_presentation_settings_it_has(cls, name):
    """The expectation is fixed here, not read from the marks: removing a mark fails."""
    for setting in sorted(PRESENTATION_SETTINGS):
        assert setting in cls.Settings.model_fields, f"{name}.{setting} is a setting of every flow"
        expected = (name, setting) not in REDECLARED
        assert is_presentation(cls.Settings, setting) is expected, f"{name}.{setting}"
    for setting in NOT_PRESENTATION:
        assert not is_presentation(cls.Settings, setting), f"{name}.{setting}"


def test_no_other_setting_is_marked():
    marked = {
        (name, field)
        for cls, name in CASES
        for owner, field in _fields(cls.Settings)
        if is_presentation(owner, field)
    }
    assert {field for _name, field in marked} == PRESENTATION_SETTINGS


def test_a_redeclaration_is_reviewed():
    """A flow that declares a field of the same name again drops the mark of the base."""
    redeclared = {
        (name, field)
        for cls, name in CASES
        for field in PRESENTATION_SETTINGS
        if not is_presentation(cls.Settings, field)
    }
    assert redeclared == set(REDECLARED)


@pytest.mark.parametrize("cls, name", CASES, ids=[name for _c, name in CASES])
def test_a_presentation_setting_is_no_part_of_the_identity(tmp_path, cls, name):
    """Every setting of the table, and every marked one: a mark that is missing fails here too."""
    base = flowrun_hash(name, _settings(cls, tmp_path), "d")
    marked = {field for owner, field in _fields(cls.Settings) if is_presentation(owner, field)}
    expected = {field for field in PRESENTATION_SETTINGS if (name, field) not in REDECLARED}
    for field in sorted(expected | marked):
        default = cls.Settings.model_fields[field].default
        assert isinstance(default, bool), f"{name}.{field}: extend this test for a non-boolean"
        changed = _settings(cls, tmp_path, **{field: not default})
        assert flowrun_hash(name, changed, "d") == base, f"{name}.{field}"
        # the identity works on a copy: the flow still gets the value
        assert getattr(changed, field) is (not default)


@pytest.mark.parametrize("cls, name", CASES, ids=[name for _c, name in CASES])
def test_a_setting_that_changes_what_a_tool_does_is_part_of_the_identity(tmp_path, cls, name):
    base = flowrun_hash(name, _settings(cls, tmp_path), "d")
    for field, value in (
        ("nthreads", 3),
        ("verbose", 1),
        ("debug", True),
        ("console_colors", False),
    ):
        assert flowrun_hash(name, _settings(cls, tmp_path, **{field: value}), "d") != base, field


def test_the_identity_of_a_model_resets_a_marked_field_to_its_default():
    class Inner(XedaBaseModel):
        loud: bool = Field(True, json_schema_extra=PRESENTATION)
        names: list[str] = Field(default_factory=list, json_schema_extra=PRESENTATION)
        kept: int = 0

    class Settings(Flow.Settings):
        inner: Inner = Inner()

    settings = Settings(inner={"loud": False, "names": ["a"], "kept": 1}, quiet=True)
    seen = identity_settings(settings)
    assert (seen.quiet, seen.inner.loud, seen.inner.names, seen.inner.kept) == (False, True, [], 1)
    assert (settings.quiet, settings.inner.loud, settings.inner.names) == (True, False, ["a"])


# ------------------------------------------------------------------ a launch, end to end


@pytest.fixture
def toolchain(tmp_path, monkeypatch):
    prefix = tool_utils.use_fake_fpga_tools(monkeypatch, tmp_path / "toolchain")
    monkeypatch.chdir(tmp_path)
    return prefix


def _design(tmp_path: Path) -> Design:
    root = tmp_path / "design"
    root.mkdir(exist_ok=True)
    (root / "top.v").write_text("module top(input clk, output q); assign q = clk; endmodule\n")
    return Design(name="top", design_root=root, rtl={"sources": ["top.v"], "top": "top"})


def _tools_started(tmp_path: Path) -> int:
    return sum(
        len(record.read_text().splitlines())
        for record in (tmp_path / "run").glob("top/*/fake_fpga.calls.jsonl")
    )


@pytest.mark.parametrize("flow", ["fpga_pack", "nextpnr"])
def test_changing_a_presentation_setting_does_not_run_a_finished_flow_again(
    tmp_path, toolchain, flow
):
    design = _design(tmp_path)
    runner = DefaultRunner(tmp_path / "run", display_results=False)

    def launch(**settings):
        result = runner.run(flow, design, flow_settings={"fpga": ECP5, **settings})
        assert result is not None and result.succeeded
        return result

    first = launch(quiet=True)
    assert not first.reused
    started = _tools_started(tmp_path)
    assert started
    recorded = json.loads((first.run_path / "settings.json").read_text())["flow_settings"]
    assert recorded["quiet"] is True, "settings.json keeps the value that was given"
    for settings in (
        {"quiet": False},
        {"print_commands": False},
        {"redirect_stdout": True},
        {"quiet": True, "print_commands": False},
        {},
    ):
        again = launch(**settings)
        assert again.reused and again.run_path == first.run_path, settings
        assert again.flow_hash == first.flow_hash
    assert _tools_started(tmp_path) == started, "no tool started again"


def test_a_setting_that_changes_what_a_tool_does_still_runs_the_flow_again(tmp_path, toolchain):
    design = _design(tmp_path)
    runner = DefaultRunner(tmp_path / "run", display_results=False)
    first = runner.run("nextpnr", design, flow_settings={"fpga": ECP5})
    again = runner.run("nextpnr", design, flow_settings={"fpga": ECP5, "verbose": 1})
    assert first is not None and again is not None and not again.reused


def test_a_remote_run_receives_the_presentation_settings(tmp_path):
    root = tmp_path / "design"
    root.mkdir()
    design = Design(name="d", design_root=root, rtl={"sources": [], "top": "t"})
    sections = {"nextpnr": {"quiet": True, "print_commands": False}}
    package = package_inputs(
        design,
        sections,
        set(sections),
        run_root=tmp_path / "xeda_run",
        remote_inputs=PurePosixPath("/remote/inputs/d"),
    )
    shipped = json.loads(package.generated[package.design_file])["flow"]["nextpnr"]
    assert shipped["quiet"] is True and shipped["print_commands"] is False
