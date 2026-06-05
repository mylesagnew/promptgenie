import click

from promptgenie.commands.generate import generate
from promptgenie.commands.lint import lint_cmd
from promptgenie.commands.scan import scan_cmd
from promptgenie.commands.diff import diff_cmd
from promptgenie.commands.adapt import adapt_cmd
from promptgenie.commands.test import test_cmd
from promptgenie.commands.benchmark import benchmark_cmd
from promptgenie.commands.workflow import workflow_cmd
from promptgenie.commands.ci import ci_group
from promptgenie.commands.pack import pack_group
from promptgenie.commands.targets import list_targets_cmd, list_templates_cmd


@click.group()
@click.version_option("1.0.0", prog_name="promptgenie")
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
cli.add_command(list_targets_cmd)
cli.add_command(list_templates_cmd)


if __name__ == "__main__":
    cli()
