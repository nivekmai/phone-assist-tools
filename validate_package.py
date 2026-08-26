"""Standalone structural validation for the custom integration package."""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).parent
COMPONENT = ROOT / "custom_components" / "phone_assist_tools"

REQUIRED_FILES = {
    "__init__.py",
    "application_credentials.py",
    "authorization.py",
    "config_flow.py",
    "const.py",
    "coordinator.py",
    "google_api.py",
    "intents.py",
    "llm.py",
    "manifest.json",
    "schema.py",
    "services.yaml",
    "timers.py",
}

REQUIRED_MANIFEST_KEYS = {
    "codeowners",
    "documentation",
    "domain",
    "issue_tracker",
    "name",
    "version",
}

EXPECTED_CONSTANTS = {
    "COMMAND_ALARM": "command_alarm",
    "COMMAND_TIMER": "command_timer",
    "ALARM_HOUR": "alarm_hour",
    "ALARM_MINUTE": "alarm_minute",
    "ALARM_MESSAGE": "alarm_message",
    "ALARM_SKIP_UI": "alarm_skip_ui",
    "TIMER_SECONDS": "timer_seconds",
    "TIMER_MESSAGE": "timer_message",
    "TIMER_SKIP_UI": "timer_skip_ui",
    "PHONE_TOOL_REQUEST_ID": "phone_tool_request_id",
    "SUPPORTED_DEVICE_COMMANDS": "supported_device_commands",
}


def main() -> None:
    """Validate files that do not require importing Home Assistant."""
    missing = sorted(REQUIRED_FILES - {path.name for path in COMPONENT.iterdir()})
    if missing:
        raise SystemExit(f"Missing required files: {', '.join(missing)}")

    for path in sorted(COMPONENT.glob("*.py")):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    missing_manifest_keys = sorted(REQUIRED_MANIFEST_KEYS - manifest.keys())
    if missing_manifest_keys:
        raise SystemExit(
            "manifest.json is missing keys: " + ", ".join(missing_manifest_keys)
        )
    if manifest.get("domain") != "phone_assist_tools":
        raise SystemExit("manifest.json has the wrong domain")
    if not manifest.get("version"):
        raise SystemExit("manifest.json is missing a version")
    if not {"application_credentials", "intent", "mobile_app", "websocket_api"}.issubset(
        manifest.get("dependencies", [])
    ):
        raise SystemExit(
            "manifest.json must depend on application_credentials, intent, "
            "mobile_app, and websocket_api"
        )

    hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    if hacs.get("name") != "Phone Assist Tools":
        raise SystemExit("hacs.json has the wrong name")
    if not (COMPONENT / "brand" / "icon.png").is_file():
        raise SystemExit("Integration brand icon is missing")

    const_tree = ast.parse(
        (COMPONENT / "const.py").read_text(encoding="utf-8"),
        filename=str(COMPONENT / "const.py"),
    )
    actual_constants: dict[str, object] = {}
    for node in const_tree.body:
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
            continue
        if node.target.id in EXPECTED_CONSTANTS and node.value is not None:
            actual_constants[node.target.id] = ast.literal_eval(node.value)

    for name, expected in EXPECTED_CONSTANTS.items():
        if actual_constants.get(name) != expected:
            raise SystemExit(
                f"{name} is {actual_constants.get(name)!r}; expected {expected!r}"
            )

    coordinator_tree = ast.parse(
        (COMPONENT / "coordinator.py").read_text(encoding="utf-8"),
        filename=str(COMPONENT / "coordinator.py"),
    )
    coordinator_const_imports = {
        alias.name
        for node in coordinator_tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "const"
        for alias in node.names
    }
    required_coordinator_imports = {
        "ATTR_REQUEST_ID",
        "ATTR_SUCCESS",
        "PHONE_TOOL_REQUEST_ID",
    }
    missing_imports = required_coordinator_imports - coordinator_const_imports
    if missing_imports:
        raise SystemExit(
            "coordinator.py is missing const imports: "
            + ", ".join(sorted(missing_imports))
        )

    coordinator_source = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")
    for required_fragment in (
        "def supports_phone_command(",
        "def native_mobile_app_commands(",
        "SUPPORTED_DEVICE_COMMANDS",
        "webhook_id_from_device_id",
    ):
        if required_fragment not in coordinator_source:
            raise SystemExit(
                f"coordinator.py is missing compatibility guard {required_fragment!r}"
            )

    llm_source = (COMPONENT / "llm.py").read_text(encoding="utf-8")
    if llm_source.count("supports_phone_command(") < 2:
        raise SystemExit("llm.py must gate alarm and timer tools independently")

    print("Phone Assist Tools package validation passed.")


if __name__ == "__main__":
    main()
