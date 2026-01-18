"""
Shell Completion Script Generator
=================================

Generate shell completion scripts for bash, zsh, fish, and powershell.
Inspired by gh CLI's `gh completion` command.

Usage:
    unity-cli completion bash >> ~/.bashrc
    unity-cli completion zsh >> ~/.zshrc
    unity-cli completion fish > ~/.config/fish/completions/unity-cli.fish
"""

from __future__ import annotations

import click.shell_completion as sc

# PowerShell completion template (Click doesn't include this by default)
POWERSHELL_TEMPLATE = """\
Register-ArgumentCompleter -Native -CommandName %(prog_name)s -ScriptBlock {
    param($wordToComplete, $commandAst, $cursorPosition)
    $env:COMP_WORDS = $commandAst.ToString()
    $env:COMP_CWORD = $commandAst.CommandElements.Count - 1
    $env:%(complete_var)s = "powershell_complete"
    %(prog_name)s | ForEach-Object {
        $type, $value, $help = $_.Split(",", 3)
        if ($type -eq "plain") {
            [System.Management.Automation.CompletionResult]::new($value, $value, 'ParameterValue', ($help -replace '_', ' '))
        }
    }
    Remove-Item env:COMP_WORDS, env:COMP_CWORD, env:%(complete_var)s
}
"""

# Supported shells
SUPPORTED_SHELLS = ("bash", "zsh", "fish", "powershell")


class PowerShellComplete(sc.ShellComplete):
    """PowerShell completion support."""

    name = "powershell"
    source_template = POWERSHELL_TEMPLATE


def get_completion_script(shell: str, prog_name: str = "unity-cli") -> str:
    """Generate shell completion script.

    Args:
        shell: Target shell (bash, zsh, fish, powershell)
        prog_name: Program name for completion

    Returns:
        Shell completion script as string

    Raises:
        ValueError: If shell is not supported
    """
    shell = shell.lower()

    if shell not in SUPPORTED_SHELLS:
        raise ValueError(f"Unsupported shell: {shell}. Supported: {', '.join(SUPPORTED_SHELLS)}")

    # Map shell name to completion class
    completion_classes: dict[str, type[sc.ShellComplete]] = {
        "bash": sc.BashComplete,
        "zsh": sc.ZshComplete,
        "fish": sc.FishComplete,
        "powershell": PowerShellComplete,
    }

    cls = completion_classes[shell]

    # Generate completion script using Click's internal mechanism
    # The source_vars method generates the template variables
    complete_var = f"_{prog_name.upper().replace('-', '_')}_COMPLETE"

    vars_dict = {
        "prog_name": prog_name,
        "complete_var": complete_var,
        "complete_func": f"_{prog_name.replace('-', '_')}_completion",
    }

    return cls.source_template % vars_dict
