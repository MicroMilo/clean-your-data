"""Local, secret-free configuration for optional AI commands."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
from pathlib import Path
from typing import Any, Optional


STATE_ENV = "CLEAN_YOUR_DATA_STATE_DIR"
AI_COMMAND_ENV = "CLEAN_YOUR_DATA_AI_COMMAND"
AI_CONFIG_FILE = "ai-config.json"
VALID_AI_MODES = {"auto", "codex", "command", "off"}


def state_dir() -> Path:
    configured = os.environ.get(STATE_ENV, "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".clean-your-data"


def ai_config_path() -> Path:
    return state_dir() / AI_CONFIG_FILE


def default_ai_config() -> dict[str, Any]:
    return {"version": 1, "mode": "auto", "command": []}


def normalize_ai_config(data: Any) -> dict[str, Any]:
    config = default_ai_config()
    if not isinstance(data, dict):
        return config
    mode = str(data.get("mode") or "auto").strip().lower()
    if mode not in VALID_AI_MODES:
        mode = "auto"
    command_value = data.get("command")
    if isinstance(command_value, str):
        try:
            command = shlex.split(command_value)
        except ValueError:
            command = []
    elif isinstance(command_value, list):
        command = [str(item) for item in command_value if str(item)]
    else:
        command = []
    if mode == "command" and not command:
        mode = "off"
    return {"version": 1, "mode": mode, "command": command[:64]}


def load_ai_config(path: Optional[Path] = None) -> dict[str, Any]:
    target = path or ai_config_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return default_ai_config()
    return normalize_ai_config(data)


def save_ai_config(config: dict[str, Any], path: Optional[Path] = None) -> dict[str, Any]:
    target = path or ai_config_path()
    normalized = normalize_ai_config(config)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(target.parent, 0o700)
    except OSError:
        pass
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    os.replace(temporary, target)
    return normalized


def parse_command(value: str) -> list[str]:
    if len(value) > 4096:
        raise ValueError("AI command is too long")
    try:
        command = shlex.split(value)
    except ValueError as exc:
        raise ValueError(f"invalid AI command: {exc}") from exc
    if not command:
        raise ValueError("AI command cannot be empty")
    if len(command) > 64:
        raise ValueError("AI command has too many arguments")
    return command


def config_for_display(
    config: Optional[dict[str, Any]] = None,
    *,
    reveal_command: bool = False,
) -> dict[str, Any]:
    configured_env = os.environ.get(AI_COMMAND_ENV, "").strip()
    if configured_env:
        try:
            command = parse_command(configured_env)
            provider = f"Environment command ({Path(command[0]).name})"
        except ValueError:
            command = []
            provider = "Invalid environment command"
        return {
            "mode": "environment",
            "command": shlex.join(command) if reveal_command and command else "",
            "command_configured": bool(command),
            "provider": provider,
            "has_api_key_field": False,
            "stores_command_arguments": False,
            "managed_by_environment": True,
        }
    normalized = normalize_ai_config(config or load_ai_config())
    command = normalized["command"]
    return {
        "mode": normalized["mode"],
        "command": shlex.join(command) if reveal_command and command else "",
        "command_configured": bool(command),
        "provider": provider_label(normalized),
        "has_api_key_field": False,
        "stores_command_arguments": bool(command),
        "managed_by_environment": False,
    }


def provider_label(config: Optional[dict[str, Any]] = None) -> str:
    normalized = normalize_ai_config(config or load_ai_config())
    mode = normalized["mode"]
    if mode == "off":
        return "AI disabled"
    if mode == "command":
        return f"Custom command ({Path(normalized['command'][0]).name})"
    if mode == "codex":
        return "Codex"
    return "Codex (auto)" if shutil.which("codex") else "No local AI command"


def resolve_ai_command(config_path: Optional[Path] = None) -> tuple[Optional[list[str]], str]:
    """Resolve a direct argv command; never invoke a shell."""
    configured_env = os.environ.get(AI_COMMAND_ENV, "").strip()
    if configured_env:
        try:
            command = parse_command(configured_env)
        except ValueError:
            return None, "Configured local AI command is invalid."
        return command, "Configured local AI"

    config = load_ai_config(config_path)
    mode = config["mode"]
    if mode == "off":
        return None, "AI disabled."
    if mode == "command":
        return list(config["command"]), provider_label(config)

    codex = shutil.which("codex")
    if codex:
        return (
            [
                codex,
                "exec",
                "--sandbox",
                "read-only",
                "--ephemeral",
                "--skip-git-repo-check",
                "--color",
                "never",
                "-C",
                "/tmp",
                "-",
            ],
            "Codex",
        )
    if mode == "codex":
        return None, "Codex CLI was not found."
    return None, "No local AI command."


def config_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="cyd config ai",
        description="Configure the optional local AI command without storing API keys.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--auto", action="store_true", help="Auto-detect a local Codex CLI.")
    group.add_argument("--codex", action="store_true", help="Require the local Codex CLI.")
    group.add_argument("--off", action="store_true", help="Disable AI while keeping the explorer available.")
    group.add_argument("--command", help="Direct argv command that reads a prompt from stdin and writes an answer to stdout.")
    group.add_argument("--show", action="store_true", help="Show the current secret-free configuration.")
    args = parser.parse_args(argv)

    if args.command is not None:
        try:
            command = parse_command(args.command)
        except ValueError as exc:
            parser.error(str(exc))
        config = save_ai_config({"version": 1, "mode": "command", "command": command})
    elif args.codex:
        config = save_ai_config({"version": 1, "mode": "codex", "command": []})
    elif args.off:
        config = save_ai_config({"version": 1, "mode": "off", "command": []})
    elif args.auto:
        config = save_ai_config({"version": 1, "mode": "auto", "command": []})
    else:
        config = load_ai_config()

    display = config_for_display(config, reveal_command=True)
    print(f"AI mode: {display['mode']}")
    print(f"Provider: {display['provider']}")
    if display["command"]:
        print(f"Command: {display['command']}")
    print("Dedicated API-key field: no")
    print("Saved custom-command arguments are stored verbatim; do not include secrets.")
    return 0
