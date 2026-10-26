# 云琥 Android 1.3.8 验证记录

2026-10-26，版本 **1.3.8 / versionCode 10308** 修复本地模型启动即退，并加入 Android 17（API 37）支持。

## 本地模型启动

`llama-server` 的 argv 由已安装引擎 `--help` 实际声明的能力决定（`--no-webui`、`--parallel`、`--n-gpu-layers`、`--device`、`--prio`、`--no-mmap`），不再无条件传入可选参数；日志出现参数被拒特征时以最简 argv 重试一次。启动失败返回 `exit_code`、实际端口、`argument_rejected`、`log_tail`，并按内存不足、缺运行库、端口占用、模型无法加载、参数被拒翻译成下一步动作。请求端口被占用时在 18000–18999 内回退，真实端口写回模型配置与请求地址。就绪等待由 1.8 秒放宽到 20 秒，进程存活超时不判失败。设置页新增「查看引擎日志」。

## Android 17

`NativeSetupPolicy.MAX_SDK` 由 36 改为 37，欢迎页、部署校验与提示文案同步更新；三个模块 compileSdk 37.2 / Build Tools 37.0.0；`android.suppressUnsupportedCompileSdk=37.2` 显式接受 AGP 8.13 与 37.2 的版本差；设备诊断新增 `page_size`。`targetSdk` 保持 28。

16 KB 页设备未验收：APK 内 Chaquopy 的 10 个原生库均为 16 KB 对齐，`libtermux.so`（终端 JNI）仍是 4 KB 对齐，需要重新构建后才能在该类内核加载。

## 数字

Python **290 项运行、2 项跳过、零失败**（两项为本机文件系统静默忽略 `symlink_to`，确认链接未建立后主动跳过）。Edge 浏览器六组 **88 项**通过：smoke 16、readiness 6、功能/附件 13、执行卡 16、设置 UI 17、离线欢迎动画 20/20；`consoleErrors` 与 `pageErrors` 为空。Android JVM **70 项通过**；lint **66 个 warning、0 Error/Fatal**。debug/release ARM64 构建、APK 内容核验、来源清单绑定、v2/v3 与 zipalign 均通过；release 显式使用 Android debug 签名覆盖，仅供开发/测试，不能作为生产升级包。

## 新增测试

引擎只收到它声明支持的参数、最简回退丢弃全部可选项、GPU/NPU 设备参数随声明下发、`no-mmap` 仅在支持时使用、参数被拒可从日志识别、五类失败原因文案、日志尾部有界、空日志仍可读、引擎实际端口回写、引擎日志接口只回文本、Android 17 被兼容策略接受且 38 被拒绝。

## 证据

[Python 测试](<../artifacts/python-v1.3.8-final.txt>)、[浏览器 smoke](<../artifacts/browser-v1.3.8-smoke.txt>)、[readiness](<../artifacts/browser-v1.3.8-readiness.txt>)、[功能/附件](<../artifacts/browser-v1.3.8-features.txt>)、[执行卡](<../artifacts/browser-v1.3.8-cards.txt>)、[外观 UI](<../artifacts/browser-v1.3.8-ui.txt>)、[欢迎动画](<../artifacts/browser-v1.3.8-welcome.txt>)、[最终构建](<../artifacts/android-v1.3.8-final-build.txt>)、[APK 核验](<../artifacts/android-v1.3.8-artifact-verification.json>)、[签名及升级证书](<../artifacts/android-v1.3.8-signatures.txt>)。发行文件大小与 SHA-256 由 [发行清单](<../dist/AndroidAgent-1.3.8-manifest.json>)记录。

未连接 Android 真机；没有声称容器部署、软件包安装、GPU/NPU 推理或系统分享面板在设备上实测。Android 设备/系统级验收仍待实际设备验证。

## 历史验证

[1.3.7 构建](<../artifacts/android-v1.3.7-final-build.txt>)、[1.3.7 APK 核验](<../artifacts/android-v1.3.7-artifact-verification.json>)、[1.3.7 签名](<../artifacts/android-v1.3.7-signatures.txt>)、[1.3.6 构建](<../artifacts/android-v1.3.6-final-build.txt>)、[1.3.5 构建](<../artifacts/android-v1.3.5-final-build.txt>)。

# 历史记录：1.3.3

2026-10-20，**1.3.3 / versionCode 10303**。

在 eZ 时间线后半段复现 Canvas 丢图，确认是 `progressiveLoad=true` 导致嵌套合成未加载。改为完整加载，并为 Canvas 添加 DOMReady / ResizeObserver 尺寸重算。前后台暂停保留当前帧，Reduced Motion 单独显示静态帧；避免无变化偏好重建播放器并明确释放旧 WebView。

原生 JVM **55 项通过**；逐帧 Edge 像素专项 **20/20，零外部请求、零页面错误**，覆盖 9 个时间点、播放/暂停、循环和 resize。构建、APK 资源核验、v2/v3、zipalign 及 1.3.2 同证书升级检查通过；lint 62 Warning、0 Error/Fatal。无 Android 设备连接，未宣称真机测试。

证据：[逐帧日志](<../artifacts/browser-v1.3.3-welcome.txt>)、[构建](<../artifacts/android-v1.3.3-final-build.txt>)、[APK 核验](<../artifacts/android-v1.3.3-artifact-verification.json>)、[签名](<../artifacts/android-v1.3.3-signatures.txt>)。清单：`../dist/AndroidAgent-1.3.3-manifest.json`。
