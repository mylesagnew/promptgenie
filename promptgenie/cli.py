from importlib.metadata import version

import click

from promptgenie.commands.adapt import adapt_cmd
from promptgenie.commands.analyze import analyze_cmd
from promptgenie.commands.audit import audit_group
from promptgenie.commands.auth import auth_group
from promptgenie.commands.benchmark import benchmark_cmd
from promptgenie.commands.ci import ci_group
from promptgenie.commands.completion import completion_group
from promptgenie.commands.compress import compress_cmd, optimize_cmd
from promptgenie.commands.config_cmd import config_group
from promptgenie.commands.context import context_group
from promptgenie.commands.diff import diff_cmd
from promptgenie.commands.doctor import doctor_cmd
from promptgenie.commands.eval_cmd import eval_group
from promptgenie.commands.evaluate import evaluate_cmd
from promptgenie.commands.generate import generate
from promptgenie.commands.history_cmd import history_group
from promptgenie.commands.interactive import interactive_cmd
from promptgenie.commands.lint import lint_cmd
from promptgenie.commands.lock_cmd import lock_cmd
from promptgenie.commands.pack import pack_group
from promptgenie.commands.palette_cmd import palette_cmd
from promptgenie.commands.plugin_cmd import plugin_group
from promptgenie.commands.policy import policy
from promptgenie.commands.provider import provider_group
from promptgenie.commands.redact import redact_cmd
from promptgenie.commands.redteam import redteam_cmd
from promptgenie.commands.run import run_cmd
from promptgenie.commands.scan import scan_cmd
from promptgenie.commands.spec import spec_group
from promptgenie.commands.targets import list_targets_cmd, list_templates_cmd
from promptgenie.commands.template_cmd import template_group
from promptgenie.commands.test import test_cmd
from promptgenie.commands.tokens_cmd import tokens_cmd
from promptgenie.commands.trust import trust_group
from promptgenie.commands.tui_cmd import tui_cmd
from promptgenie.commands.validate import validate_cmd, validate_profiles_cmd
from promptgenie.commands.vars import vars_group
from promptgenie.commands.watch_cmd import watch_cmd
from promptgenie.commands.wizard_cmd import wizard_cmd
from promptgenie.commands.workflow import workflow_cmd
from promptgenie.core.errors import install_interrupt_handler
from promptgenie.renderers.rich import ColorMode, init_renderer


@click.group()
@click.version_option(version("promptgenie"), prog_name="promptgenie")
@click.option(
    "--color",
    "color_mode",
    default="auto",
    type=click.Choice(["auto", "always", "never"], case_sensitive=False),
    envvar="PG_COLOR",
    show_default=True,
    help="Color output: auto (TTY detect), always, or never. Also reads PG_COLOR env var.",
    is_eager=True,
    expose_value=True,
    callback=lambda ctx, param, value: value,
)
@click.pass_context
def cli(ctx: click.Context, color_mode: str) -> None:
    """PromptGenie — secure prompt engineering for AI agents and engineering teams."""
    init_renderer(ColorMode(color_mode))
    install_interrupt_handler()


cli.add_command(generate)
cli.add_command(lint_cmd)
cli.add_command(scan_cmd)
cli.add_command(diff_cmd)
cli.add_command(adapt_cmd)
cli.add_command(test_cmd)
cli.add_command(benchmark_cmd)
cli.add_command(workflow_cmd)
cli.add_command(ci_group)
cli.add_command(pack_group)
cli.add_command(policy)
cli.add_command(list_targets_cmd)
cli.add_command(list_templates_cmd)
cli.add_command(validate_cmd)
cli.add_command(validate_profiles_cmd)
cli.add_command(interactive_cmd)
cli.add_command(completion_group)
cli.add_command(context_group)
cli.add_command(doctor_cmd)
cli.add_command(provider_group)
cli.add_command(run_cmd)
cli.add_command(spec_group)
cli.add_command(trust_group)
cli.add_command(vars_group)
cli.add_command(compress_cmd)
cli.add_command(optimize_cmd)
cli.add_command(tokens_cmd)
# Phase 3 — SecDevOps Guardrails
cli.add_command(analyze_cmd)
cli.add_command(redact_cmd)
cli.add_command(redteam_cmd)
cli.add_command(auth_group)
cli.add_command(audit_group)
cli.add_command(config_group)
# Phase 4 — Evaluation and Regression Testing
cli.add_command(evaluate_cmd)
cli.add_command(eval_group)
# Phase 5 — Advanced TUI and Ecosystem
cli.add_command(plugin_group)
cli.add_command(template_group)
cli.add_command(history_group)
cli.add_command(watch_cmd)
cli.add_command(lock_cmd)
cli.add_command(tui_cmd)
cli.add_command(wizard_cmd)
cli.add_command(palette_cmd)


if __name__ == "__main__":
    cli()
