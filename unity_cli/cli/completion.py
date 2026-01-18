"""
Shell Completion Script Generator
=================================

Generate static shell completion scripts for bash, zsh, fish, and powershell.

Usage:
    unity-cli completion bash >> ~/.bashrc
    unity-cli completion zsh >> ~/.zshrc
    unity-cli completion fish > ~/.config/fish/completions/unity-cli.fish
"""

from __future__ import annotations

# Supported shells
SUPPORTED_SHELLS = ("bash", "zsh", "fish", "powershell")

# Static completion scripts

ZSH_SCRIPT = """\
#compdef unity-cli

_unity_cli() {
    local -a commands
    local -a global_opts

    global_opts=(
        '--relay-host[Relay server host]:host:'
        '--relay-port[Relay server port]:port:'
        '--instance[Target Unity instance]:instance:'
        '-i[Target Unity instance]:instance:'
        '--timeout[Timeout in seconds]:timeout:'
        '-t[Timeout in seconds]:timeout:'
        '--json[Output JSON format]'
        '-j[Output JSON format]'
        '--help[Show help]'
    )

    commands=(
        'instances:List connected Unity instances'
        'state:Get editor state'
        'play:Enter play mode'
        'stop:Exit play mode'
        'pause:Toggle pause'
        'refresh:Refresh asset database'
        'open:Open Unity project'
        'completion:Generate shell completion script'
        'console:Console log commands'
        'scene:Scene management commands'
        'tests:Test execution commands'
        'gameobject:GameObject commands'
        'component:Component commands'
        'menu:Menu item commands'
        'asset:Asset commands'
        'config:Configuration commands'
        'project:Project information'
        'editor:Unity Editor management'
    )

    _arguments -C \\
        $global_opts \\
        '1:command:->command' \\
        '*::arg:->args'

    case $state in
        command)
            _describe -t commands 'unity-cli command' commands
            ;;
        args)
            case $words[1] in
                console)
                    local -a console_cmds
                    console_cmds=('get:Get console logs' 'clear:Clear console logs')
                    _describe -t commands 'console command' console_cmds
                    ;;
                scene)
                    local -a scene_cmds
                    scene_cmds=('active:Get active scene' 'hierarchy:Get scene hierarchy' 'load:Load scene' 'save:Save scene')
                    _describe -t commands 'scene command' scene_cmds
                    ;;
                tests)
                    local -a tests_cmds
                    tests_cmds=('run:Run tests' 'list:List tests' 'status:Test status')
                    _describe -t commands 'tests command' tests_cmds
                    ;;
                gameobject)
                    local -a go_cmds
                    go_cmds=('find:Find GameObjects' 'create:Create GameObject' 'modify:Modify GameObject' 'delete:Delete GameObject')
                    _describe -t commands 'gameobject command' go_cmds
                    ;;
                component)
                    local -a comp_cmds
                    comp_cmds=('list:List components' 'inspect:Inspect component' 'add:Add component' 'remove:Remove component')
                    _describe -t commands 'component command' comp_cmds
                    ;;
                menu)
                    local -a menu_cmds
                    menu_cmds=('exec:Execute menu item' 'list:List menu items' 'context:Execute ContextMenu')
                    _describe -t commands 'menu command' menu_cmds
                    ;;
                asset)
                    local -a asset_cmds
                    asset_cmds=('prefab:Create prefab' 'scriptable-object:Create ScriptableObject' 'info:Asset info')
                    _describe -t commands 'asset command' asset_cmds
                    ;;
                config)
                    local -a config_cmds
                    config_cmds=('show:Show config' 'init:Initialize config')
                    _describe -t commands 'config command' config_cmds
                    ;;
                project)
                    local -a project_cmds
                    project_cmds=('info:Project info' 'version:Unity version' 'packages:List packages' 'tags:Tags and layers' 'quality:Quality settings' 'assemblies:Assembly definitions')
                    _describe -t commands 'project command' project_cmds
                    ;;
                editor)
                    local -a editor_cmds
                    editor_cmds=('list:List editors' 'install:Install editor')
                    _describe -t commands 'editor command' editor_cmds
                    ;;
                completion)
                    local -a shells
                    shells=('bash' 'zsh' 'fish' 'powershell')
                    _describe -t shells 'shell' shells
                    ;;
            esac
            ;;
    esac
}

compdef _unity_cli unity-cli
"""

BASH_SCRIPT = """\
_unity_cli() {
    local cur prev commands
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"

    commands="instances state play stop pause refresh open completion console scene tests gameobject component menu asset config project editor"

    case "${prev}" in
        unity-cli)
            COMPREPLY=( $(compgen -W "${commands}" -- ${cur}) )
            return 0
            ;;
        console)
            COMPREPLY=( $(compgen -W "get clear" -- ${cur}) )
            return 0
            ;;
        scene)
            COMPREPLY=( $(compgen -W "active hierarchy load save" -- ${cur}) )
            return 0
            ;;
        tests)
            COMPREPLY=( $(compgen -W "run list status" -- ${cur}) )
            return 0
            ;;
        gameobject)
            COMPREPLY=( $(compgen -W "find create modify delete" -- ${cur}) )
            return 0
            ;;
        component)
            COMPREPLY=( $(compgen -W "list inspect add remove" -- ${cur}) )
            return 0
            ;;
        menu)
            COMPREPLY=( $(compgen -W "exec list context" -- ${cur}) )
            return 0
            ;;
        asset)
            COMPREPLY=( $(compgen -W "prefab scriptable-object info" -- ${cur}) )
            return 0
            ;;
        config)
            COMPREPLY=( $(compgen -W "show init" -- ${cur}) )
            return 0
            ;;
        project)
            COMPREPLY=( $(compgen -W "info version packages tags quality assemblies" -- ${cur}) )
            return 0
            ;;
        editor)
            COMPREPLY=( $(compgen -W "list install" -- ${cur}) )
            return 0
            ;;
        completion)
            COMPREPLY=( $(compgen -W "bash zsh fish powershell" -- ${cur}) )
            return 0
            ;;
    esac
}

complete -F _unity_cli unity-cli
"""

FISH_SCRIPT = """\
# unity-cli fish completion

set -l commands instances state play stop pause refresh open completion console scene tests gameobject component menu asset config project editor

complete -c unity-cli -f
complete -c unity-cli -n "not __fish_seen_subcommand_from $commands" -a instances -d 'List connected Unity instances'
complete -c unity-cli -n "not __fish_seen_subcommand_from $commands" -a state -d 'Get editor state'
complete -c unity-cli -n "not __fish_seen_subcommand_from $commands" -a play -d 'Enter play mode'
complete -c unity-cli -n "not __fish_seen_subcommand_from $commands" -a stop -d 'Exit play mode'
complete -c unity-cli -n "not __fish_seen_subcommand_from $commands" -a pause -d 'Toggle pause'
complete -c unity-cli -n "not __fish_seen_subcommand_from $commands" -a refresh -d 'Refresh asset database'
complete -c unity-cli -n "not __fish_seen_subcommand_from $commands" -a open -d 'Open Unity project'
complete -c unity-cli -n "not __fish_seen_subcommand_from $commands" -a completion -d 'Generate shell completion'
complete -c unity-cli -n "not __fish_seen_subcommand_from $commands" -a console -d 'Console commands'
complete -c unity-cli -n "not __fish_seen_subcommand_from $commands" -a scene -d 'Scene commands'
complete -c unity-cli -n "not __fish_seen_subcommand_from $commands" -a tests -d 'Test commands'
complete -c unity-cli -n "not __fish_seen_subcommand_from $commands" -a gameobject -d 'GameObject commands'
complete -c unity-cli -n "not __fish_seen_subcommand_from $commands" -a component -d 'Component commands'
complete -c unity-cli -n "not __fish_seen_subcommand_from $commands" -a menu -d 'Menu commands'
complete -c unity-cli -n "not __fish_seen_subcommand_from $commands" -a asset -d 'Asset commands'
complete -c unity-cli -n "not __fish_seen_subcommand_from $commands" -a config -d 'Config commands'
complete -c unity-cli -n "not __fish_seen_subcommand_from $commands" -a project -d 'Project commands'
complete -c unity-cli -n "not __fish_seen_subcommand_from $commands" -a editor -d 'Editor commands'

# Subcommands
complete -c unity-cli -n "__fish_seen_subcommand_from console" -a "get clear"
complete -c unity-cli -n "__fish_seen_subcommand_from scene" -a "active hierarchy load save"
complete -c unity-cli -n "__fish_seen_subcommand_from tests" -a "run list status"
complete -c unity-cli -n "__fish_seen_subcommand_from gameobject" -a "find create modify delete"
complete -c unity-cli -n "__fish_seen_subcommand_from component" -a "list inspect add remove"
complete -c unity-cli -n "__fish_seen_subcommand_from menu" -a "exec list context"
complete -c unity-cli -n "__fish_seen_subcommand_from asset" -a "prefab scriptable-object info"
complete -c unity-cli -n "__fish_seen_subcommand_from config" -a "show init"
complete -c unity-cli -n "__fish_seen_subcommand_from project" -a "info version packages tags quality assemblies"
complete -c unity-cli -n "__fish_seen_subcommand_from editor" -a "list install"
complete -c unity-cli -n "__fish_seen_subcommand_from completion" -a "bash zsh fish powershell"

# Global options
complete -c unity-cli -l relay-host -d 'Relay server host'
complete -c unity-cli -l relay-port -d 'Relay server port'
complete -c unity-cli -l instance -s i -d 'Target Unity instance'
complete -c unity-cli -l timeout -s t -d 'Timeout in seconds'
complete -c unity-cli -l json -s j -d 'Output JSON format'
complete -c unity-cli -l help -d 'Show help'
"""

POWERSHELL_SCRIPT = """\
Register-ArgumentCompleter -Native -CommandName unity-cli -ScriptBlock {
    param($wordToComplete, $commandAst, $cursorPosition)

    $commands = @{
        '' = @('instances', 'state', 'play', 'stop', 'pause', 'refresh', 'open', 'completion', 'console', 'scene', 'tests', 'gameobject', 'component', 'menu', 'asset', 'config', 'project', 'editor')
        'console' = @('get', 'clear')
        'scene' = @('active', 'hierarchy', 'load', 'save')
        'tests' = @('run', 'list', 'status')
        'gameobject' = @('find', 'create', 'modify', 'delete')
        'component' = @('list', 'inspect', 'add', 'remove')
        'menu' = @('exec', 'list', 'context')
        'asset' = @('prefab', 'scriptable-object', 'info')
        'config' = @('show', 'init')
        'project' = @('info', 'version', 'packages', 'tags', 'quality', 'assemblies')
        'editor' = @('list', 'install')
        'completion' = @('bash', 'zsh', 'fish', 'powershell')
    }

    $elements = $commandAst.CommandElements
    $subcommand = ''
    if ($elements.Count -gt 1) {
        $subcommand = $elements[1].Extent.Text
    }

    $completions = $commands[$subcommand]
    if (-not $completions) {
        $completions = $commands['']
    }

    $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
        [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)
    }
}
"""


def get_completion_script(shell: str, prog_name: str = "unity-cli") -> str:
    """Generate shell completion script.

    Args:
        shell: Target shell (bash, zsh, fish, powershell)
        prog_name: Program name (unused, kept for compatibility)

    Returns:
        Shell completion script as string

    Raises:
        ValueError: If shell is not supported
    """
    shell = shell.lower()

    if shell not in SUPPORTED_SHELLS:
        raise ValueError(f"Unsupported shell: {shell}. Supported: {', '.join(SUPPORTED_SHELLS)}")

    scripts = {
        "bash": BASH_SCRIPT,
        "zsh": ZSH_SCRIPT,
        "fish": FISH_SCRIPT,
        "powershell": POWERSHELL_SCRIPT,
    }

    return scripts[shell]
