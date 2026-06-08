from importlib.metadata import version

import click

from promptgenie.commands.adapt import adapt_cmd
from promptgenie.commands.benchmark import benchmark_cmd
from promptgenie.commands.ci import ci_group
from promptgenie.commands.diff import diff_cmd
from promptgenie.commands.generate import generate
from promptgenie.commands.interactive import interactive_cmd
from promptgenie.commands.lint import lint_cmd
from promptgenie.commands.pack import pack_group
from promptgenie.commands.policy import policy
from promptgenie.commands.scan import scan_cmd
from promptgenie.commands.targets import list_targets_cmd, list_templates_cmd
from promptgenie.commands.test import test_cmd
from promptgenie.commands.validate import validate_cmd, validate_profiles_cmd
from promptgenie.commands.workflow import workflow_cmd


@click.group()
@click.version_option(version("promptgenie"), prog_name="promptgenie")
def cli():
    """PromptGenie — secure prompt engineering for AI agents and engineering teams."""


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


if __name__ == "__main__":
    cli()
