"""Offline regression coverage for Billing Portal flow gating."""

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent.parent

FLAG_PATTERN = re.compile(
    r"project_config\.project__custom__([A-Za-z_][A-Za-z0-9_]*)"
)


def _flags(condition):
    return set(FLAG_PATTERN.findall(condition))


def _steps(flow_name):
    data = yaml.safe_load((ROOT / "cumulusci.yml").read_text(encoding="utf-8"))
    return data["flows"][flow_name]["steps"]


def _task_steps(steps):
    return {number: step for number, step in steps.items() if "task" in step}


def test_every_billing_portal_task_requires_billing_and_portal_flags():
    steps = _steps("prepare_billing_portal")
    task_steps = _task_steps(steps)

    assert len(task_steps) == 5
    for step_number, step in task_steps.items():
        flags = _flags(step.get("when", ""))
        assert "billing" in flags, step_number
        assert "billing_portal" in flags, step_number


def test_only_bundle_deploy_steps_require_billing_portal_deploy():
    steps = _steps("prepare_billing_portal")

    for step_number in (2, 3, 4):
        assert "billing_portal_deploy" in _flags(steps[step_number]["when"])
    for step_number in (1, 5):
        assert "billing_portal_deploy" not in _flags(steps[step_number]["when"])


def test_lwr_site_flow_is_appended_without_shifting_the_aura_steps():
    steps = _steps("prepare_billing_portal")

    # Appended, not inserted: test_doc_build_steps audits docs by step coordinate, so
    # renumbering steps 1-5 would silently invalidate every citation that names them.
    assert steps[6] == {"flow": "prepare_billing_portal_lwr"}


def test_every_lwr_site_step_requires_billing_payments_and_lwr_flags():
    # The nested flow step in prepare_billing_portal carries no `when`, so every gate has to
    # live on the sub-flow's own steps — an ungated step here would run on every build.
    steps = _steps("prepare_billing_portal_lwr")
    task_steps = _task_steps(steps)

    assert len(task_steps) == len(steps) == 7
    for step_number, step in task_steps.items():
        flags = _flags(step.get("when", ""))
        assert "billing" in flags, step_number
        # The Self-Service Payment Sheet cannot take a payment without a merchant account,
        # which prepare_payments sets up.
        assert "payments" in flags, step_number
        assert "billing_portal_lwr" in flags, step_number


def test_only_lwr_bundle_deploy_steps_require_billing_portal_lwr_deploy():
    steps = _steps("prepare_billing_portal_lwr")

    for step_number in (2, 3, 4, 5, 6):
        assert "billing_portal_lwr_deploy" in _flags(steps[step_number]["when"])
    for step_number in (1, 7):
        assert "billing_portal_lwr_deploy" not in _flags(steps[step_number]["when"])


def test_lwr_placeholders_in_the_bundle_match_what_the_flow_substitutes():
    # A placeholder that drifts from the committed file fails the patch task at deploy time
    # with "Placeholder not found", after the site has already been created.
    steps = _steps("prepare_billing_portal_lwr")
    bundle = ROOT / "unpackaged" / "post_billing_portal_lwr"

    for step_number, option, tags in (
        (2, "network_meta_xml_path", ("emailSenderAddress",)),
        (3, "site_meta_xml_path", ("siteAdmin", "siteGuestRecordDefaultOwner")),
    ):
        options = steps[step_number]["options"]
        path = ROOT / options[option]
        assert bundle in path.parents, path
        xml = path.read_text(encoding="utf-8")
        placeholder = options.get("placeholder_email") or options["placeholder_username"]
        for tag in tags:
            assert f"<{tag}>{placeholder}</{tag}>" in xml, (step_number, tag)

    # The revert steps have to write back exactly what the patch steps looked for, or the
    # repo keeps the target org's real email and username after a successful deploy.
    # network_name is read from the org by the patch step alone, so the revert omits it.
    patch_network = dict(steps[2]["options"])
    patch_network.pop("network_name")
    assert steps[5]["options"] == patch_network
    assert steps[6]["options"] == steps[3]["options"]
