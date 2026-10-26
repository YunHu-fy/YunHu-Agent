"""Android-only native adapter; there is deliberately no desktop shell fallback."""
from __future__ import annotations

import json
import re
import sys
from typing import Any

PACKAGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$")
KEYS = {"BACK", "HOME", "APP_SWITCH", "ENTER"}
CHANNELS = {"normal", "shizuku", "root"}


def definitions() -> list[dict[str, Any]]:
    def schema(properties=None, required=None):
        return {"type": "object", "properties": properties or {}, "required": required or [], "additionalProperties": False}
    integer = lambda low, high: {"type": "integer", "minimum": low, "maximum": high}
    package = {"type": "string", "pattern": PACKAGE_RE.pattern, "maxLength": 200}
    return [
        {"name":"android.status", "description":"查询Android权限通道状态，不触发提权授权。桌面返回unsupported。", "inputSchema":schema(), "requiresApproval":False},
        {"name":"android.battery", "description":"读取Android电池状态。", "inputSchema":schema(), "requiresApproval":True},
        {"name":"android.list_apps", "description":"列出当前权限可见的Android应用。普通应用权限的可见列表可能不完整。", "inputSchema":schema(), "requiresApproval":True},
        {"name":"android.launch_app", "description":"启动指定包名的Android应用，需逐次人工批准。", "inputSchema":schema({"package":package},["package"]), "requiresApproval":True},
        {"name":"android.tap", "description":"在屏幕坐标点击，需Shizuku或Root，并逐次人工批准。", "inputSchema":schema({"x":integer(0,16384),"y":integer(0,16384)},["x","y"]), "requiresApproval":True},
        {"name":"android.swipe", "description":"屏幕滑动，需Shizuku或Root，并逐次人工批准。", "inputSchema":schema({"x1":integer(0,16384),"y1":integer(0,16384),"x2":integer(0,16384),"y2":integer(0,16384),"duration_ms":integer(50,3000)},["x1","y1","x2","y2","duration_ms"]), "requiresApproval":True},
        {"name":"android.keyevent", "description":"发送BACK/HOME/APP_SWITCH/ENTER按键，需Shizuku或Root，逐次人工批准。", "inputSchema":schema({"key":{"type":"string","enum":sorted(KEYS)}},["key"]), "requiresApproval":True},
        {"name":"android.brightness", "description":"设置屏幕亮度0至255，需Shizuku或Root，逐次人工批准。", "inputSchema":schema({"value":integer(0,255)},["value"]), "requiresApproval":True},
        {"name":"android.force_stop", "description":"强制停止单个包名指定的应用；需Shizuku或Root，逐次人工批准。", "inputSchema":schema({"package":package},["package"]), "requiresApproval":True},
        {"name":"android.reboot", "description":"重启设备，需实际Root授权并遵守本任务的命令确认模式。", "inputSchema":schema({"confirm":{"type":"string","enum":["REBOOT"]}},["confirm"]), "requiresApproval":True},
    ]


def validate(name: str, arguments: Any) -> dict[str, Any]:
    definition = next((item for item in definitions() if item["name"] == name), None)
    if definition is None or not isinstance(arguments, dict):
        raise ValueError("Android工具或参数无效。")
    schema = definition["inputSchema"]
    properties = schema["properties"]
    if set(arguments) - set(properties) or set(schema["required"]) - set(arguments):
        raise ValueError("Android工具参数缺失或包含未定义字段。")
    for key, value in arguments.items():
        spec = properties[key]
        if spec["type"] == "integer":
            if type(value) is not int or not spec["minimum"] <= value <= spec["maximum"]:
                raise ValueError("Android数值参数超出范围。")
        elif not isinstance(value, str):
            raise ValueError("Android字符串参数无效。")
        if "enum" in spec and value not in spec["enum"]:
            raise ValueError("Android参数不在允许列表中。")
        if key == "package" and (len(value) > 200 or not PACKAGE_RE.fullmatch(value)):
            raise ValueError("Android包名格式无效。")
    return dict(arguments)


def command_for(name: str, arguments: dict[str, Any], channel: str) -> str:
    """Keep historical shortcuts on the general executor and its live command policy."""
    import shlex
    args = validate(name, arguments)
    if name in {"android.tap", "android.swipe", "android.keyevent", "android.brightness", "android.force_stop"} and channel not in {"root", "shizuku"}:
        raise PermissionError("此设备操作需要已选择并授权的Shizuku或Root通道。")
    if name == "android.reboot" and channel != "root":
        raise PermissionError("重启需要已选择并授权的Root通道。")
    if name == "android.battery":
        return "/system/bin/dumpsys battery"
    if name == "android.list_apps":
        return "/system/bin/pm list packages"
    if name == "android.launch_app":
        return "/system/bin/monkey -p " + shlex.quote(args["package"]) + " -c android.intent.category.LAUNCHER 1"
    if name == "android.tap":
        return "/system/bin/input tap {x} {y}".format(**args)
    if name == "android.swipe":
        return "/system/bin/input swipe {x1} {y1} {x2} {y2} {duration_ms}".format(**args)
    if name == "android.keyevent":
        return "/system/bin/input keyevent " + {"BACK":"4", "HOME":"3", "APP_SWITCH":"187", "ENTER":"66"}[args["key"]]
    if name == "android.brightness":
        return "/system/bin/settings put system screen_brightness " + str(args["value"])
    if name == "android.force_stop":
        return "/system/bin/am force-stop " + shlex.quote(args["package"])
    if name == "android.reboot":
        return "/system/bin/reboot"
    raise ValueError("此操作不是设备命令。")


class AndroidBridge:
    def __init__(self, native: Any = None):
        # Explicit injection is for tests. Production resolves the APK Java class.
        self._native = native
        if native is not None:
            return
        try:
            from java import jclass
            self._native = jclass("io.localagent.android.DeviceBridge")
        except Exception:
            self._native = None

    @property
    def available(self) -> bool:
        return self._native is not None

    def status(self) -> dict[str, Any]:
        if self._native is None:
            return {"supported":False,"platform":"desktop_preview" if sys.platform != "android" else "android", "selected_channel":"normal", "normal":{"available":False,"granted":False},"shizuku":{"available":False,"granted":False},"root":{"available":False,"granted":False,"checked":False},"summary":"当前运行环境没有Android原生桥接；不会在开发机执行Android命令。"}
        return json.loads(str(self._native.status()))

    def configure(self, channel: str) -> dict[str, Any]:
        if channel not in CHANNELS:
            raise ValueError("权限通道无效。")
        if self._native is None:
            if channel == "normal":
                return {"ok":True,"selected_channel":"normal","supported":False}
            raise ValueError("此环境无法使用Shizuku或Root；请在Android APK中配置。")
        result = json.loads(str(self._native.configureChannel(channel)))
        if not result.get("ok", False):
            error = result.get("error")
            raise ValueError(error.get("message", "权限通道配置失败。") if isinstance(error, dict) else error or "权限通道配置失败。")
        return result

    def request_shizuku(self) -> dict[str, Any]:
        if self._native is None:
            raise ValueError("Shizuku仅能从APK中的可见界面授权。")
        return json.loads(str(self._native.requestShizuku()))

    def execute(self, name: str, arguments: dict[str, Any], channel: str) -> dict[str, Any]:
        validated = validate(name, arguments)
        if name == "android.status":
            return {"ok": True, **self.status()}
        if self._native is None:
            return {"ok":False,"status":"unsupported","error":"Android原生工具仅可在APK内使用；未执行开发机命令。"}
        if channel not in CHANNELS:
            raise ValueError("权限通道无效。")
        operation = name.removeprefix("android.")
        if operation == "reboot":
            validated = {}
        result = json.loads(str(self._native.execute(operation, json.dumps(validated, ensure_ascii=False), channel)))
        error = result.get("error")
        if isinstance(error, dict):
            result["summary"] = error.get("message", "Android工具执行失败。")
        elif result.get("ok"):
            result["summary"] = "Android工具已完成：" + operation
        return result

    def _call(self, method: str, *args: Any) -> dict[str, Any]:
        if self._native is None:
            return {"ok": False, "supported": False, "status": "unsupported", "error": {"code": "unsupported", "message": "此操作只能在Android APK中运行；未执行开发机命令。"}}
        target = getattr(self._native, method, None)
        if target is None:
            return {"ok": False, "status": "unsupported", "error": {"code": "native_contract", "message": "原生桥接不支持" + method + "，请更新APK。"}}
        result = json.loads(str(target(*args)))
        if not isinstance(result, dict):
            raise ValueError("原生桥接返回了无效的JSON对象。")
        return result

    @property
    def streaming_commands(self) -> bool:
        return self._native is not None and all(callable(getattr(self._native, name, None)) for name in ("commandStart", "commandPoll", "commandCancel"))

    def command_start(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._call("commandStart", json.dumps(request, ensure_ascii=False))

    def command_poll(self, command_id: str, after: int = 0) -> dict[str, Any]:
        return self._call("commandPoll", command_id, after)

    def execute_command(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._call("executeCommand", json.dumps(request, ensure_ascii=False))

    def cancel_command(self, command_id: str) -> dict[str, Any]:
        # Never use cancelAll: another task may be using the same native bridge.
        method = "commandCancel" if callable(getattr(self._native, "commandCancel", None)) else "cancelCommand"
        return self._call(method, command_id)

    def runtime_status(self) -> dict[str, Any]:
        return self._call("runtimeStatus")

    def runtime_path_exists(self, path: str) -> bool:
        if not isinstance(path, str) or not path.startswith("/data/data/com.termux/files/usr/") or "\\" in path:
            return False
        if self._native is None or not callable(getattr(self._native, "runtimePathExists", None)):
            return False
        try:
            return bool(self._native.runtimePathExists(path))
        except Exception:
            return False

    def runtime_deploy(self) -> dict[str, Any]:
        return self._call("runtimeDeploy")

    def open_terminal(self) -> dict[str, Any]:
        return self._call("openTerminal")

    def local_model_status(self) -> dict[str, Any]:
        return self._call("localModelStatus")

    def local_model_install(self) -> dict[str, Any]:
        return self._call("localModelInstall")

    def local_model_start(self, model_path: str, alias: str, port: int, context_size: int, threads: int,
                          options: dict[str, Any] | None = None) -> dict[str, Any]:
        """Pass acceleration options through localModelStartEx when the bridge exposes it.

        Bridges that only implement the five-argument call keep working as long as no
        acceleration is requested; an explicit request against such a bridge fails
        loudly instead of silently starting a CPU-only engine.
        """
        requested = bool(options) and any(bool(value) for value in (options or {}).get("backend", {}).values())
        if requested and callable(getattr(self._native, "localModelStartEx", None)):
            return self._call("localModelStartEx", model_path, alias, port, context_size, threads,
                              json.dumps(options, ensure_ascii=False))
        if requested:
            raise ValueError("当前 APK 的原生桥接不支持本地模型加速选项；请更新 APK 或关闭硬件加速。")
        return self._call("localModelStart", model_path, alias, port, context_size, threads)

    def local_model_backends(self) -> dict[str, Any]:
        if self._native is None or not callable(getattr(self._native, "localModelBackends", None)):
            return {"ok": False, "status": "unsupported", "error": {"code": "unsupported", "message": "加速能力探测仅能在 Android APK 内使用。"}}
        return self._call("localModelBackends")

    def local_model_log(self) -> dict[str, Any]:
        if self._native is None or not callable(getattr(self._native, "localModelLog", None)):
            return {"ok": False, "error": {"code": "unsupported", "message": "引擎日志仅能在 Android APK 内读取。"}}
        return self._call("localModelLog")

    def local_model_stop(self) -> dict[str, Any]:
        return self._call("localModelStop")

    def _credential_native_required(self) -> None:
        if getattr(self, "_native", None) is None and (sys.platform == "android" or hasattr(sys, "getandroidapilevel")):
            raise ValueError("Android安全密钥库不可用，请更新或重新启动应用；密钥没有保存。")

    @property
    def credential_persistence(self) -> str:
        return "android_keystore" if getattr(self, "_native", None) is not None else "memory_session"

    def credential_get(self, profile_id: str) -> str:
        self._credential_native_required()
        if getattr(self, "_native", None) is None:
            return getattr(self, "_session_credentials", {}).get(profile_id, "")
        result = self._call("credentialRead", profile_id)
        if not result.get("ok"):
            raise ValueError(result.get("error", {}).get("message", "读取模型密钥失败。"))
        return str(result.get("value", ""))

    def credential_set(self, profile_id: str, value: str) -> None:
        self._credential_native_required()
        if getattr(self, "_native", None) is None:
            if not hasattr(self, "_session_credentials"):
                self._session_credentials = {}
            self._session_credentials[profile_id] = value
            return
        result = self._call("credentialWrite", profile_id, value)
        if not result.get("ok"):
            raise ValueError(result.get("error", {}).get("message", "保存模型密钥失败。"))

    def credential_delete(self, profile_id: str) -> None:
        self._credential_native_required()
        if getattr(self, "_native", None) is None:
            getattr(self, "_session_credentials", {}).pop(profile_id, None)
            return
        result = self._call("credentialDelete", profile_id)
        if not result.get("ok"):
            raise ValueError(result.get("error", {}).get("message", "删除模型密钥失败。"))

    def ui_preferences(self, values: dict[str, str]) -> dict[str, Any]:
        """Mirror display-only preferences; never execution authority or model language."""
        if self._native is None:
            return {"ok": True, "supported": False}
        return self._call("appUiPreferences", json.dumps(values, ensure_ascii=False))

    def open_permission_setup(self) -> dict[str, Any]:
        return self._call("openPermissionSetup")

    def device_state(self) -> dict[str, Any]:
        return self._call("deviceState")

    def diagnostics(self) -> dict[str, Any]:
        return self._call("diagnostics")

    def service_control(self, action: str) -> dict[str, Any]:
        if action not in {"stop", "restart", "battery_settings", "app_settings", "locks_on", "locks_off"}:
            raise ValueError("无效服务操作。")
        return self._call("serviceControl", action)

    def cancel_all(self) -> None:
        """Compatibility only. Managers cancel their own command IDs instead."""
        return None
