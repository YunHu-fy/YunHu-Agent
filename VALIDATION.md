# 云琥 1.3.8 验证记录

2026-10-26，版本 **1.3.8 / versionCode 10308** 修复本地模型启动即退，并加入 Android 17（API 37）支持。

本地推理引擎的启动参数现在按已安装 `llama-server` 的 `--help` 实际声明的能力下发；引擎拒绝参数时自动用最简参数重试一次；启动失败附带退出码与日志末尾，并翻译成可操作原因；端口被占时在 18000–18999 内回退并把真实端口写回配置；就绪等待由 1.8 秒放宽到 20 秒。设置页新增「查看引擎日志」，接口只返回文本与字节数，不暴露沙箱路径。

Android 17 方面：兼容策略由 API 29–36 放宽到 API 29–37（欢迎页、部署校验、提示文案同步更新），编译目标升到 compileSdk 37.2 / Build Tools 37.0.0，AGP 8.13 对 37.2 的支持以 `android.suppressUnsupportedCompileSdk=37.2` 显式接受；设备诊断新增 `page_size`。`targetSdk` 保持 28，因为 Android 10+ 私有目录可执行依赖它。

Python **290 项运行、2 项跳过、零失败**。两项跳过是同一宿主限制：该文件系统静默忽略 `symlink_to` 且不抛错，测试改为确认“确实建成了符号链接”后跳过，而不是把未建立的链接当作通过。Edge 浏览器六组 **88 项**通过（smoke 16、readiness 6、功能/附件 13、执行卡 16、设置 UI 17、离线欢迎动画 20/20），`consoleErrors` 与 `pageErrors` 为空。Android JVM **70 项通过**（新增 8 项参数裁剪与失败诊断用例）；lint **66 个 warning、0 Error/Fatal**。

最终 debug/release ARM64 构建、APK 内容核验、来源清单绑定、v2/v3 与 zipalign 均通过。本次构建显式使用 Android debug 签名覆盖（证书 SHA-256 `d75741c6…c4bcdd`），仅供开发/测试，不应作为生产升级包；升级证书与 1.3.7 release 一致，但那只是证书比较，不是设备升级实测。

本版新增测试：引擎只收到它声明支持的参数、最简参数回退丢弃全部可选项、GPU/NPU 设备参数随声明下发、`no-mmap` 仅在支持时使用、参数被拒可从日志识别、五类失败原因文案、日志尾部有界、空日志仍可读、引擎实际端口回写、引擎日志接口只回文本、`reset` 相关容器用例沿用。

产物字节数与 SHA-256 以 [发行清单](<dist/AndroidAgent-1.3.8-manifest.json>) 为准；源码 ZIP 内嵌这些文档，因此不把 ZIP 自身哈希写进 ZIP 内部文档。

证据：[Python 测试](<artifacts/python-v1.3.8-final.txt>)、[浏览器 smoke](<artifacts/browser-v1.3.8-smoke.txt>)、[页面 readiness](<artifacts/browser-v1.3.8-readiness.txt>)、[功能附件](<artifacts/browser-v1.3.8-features.txt>)、[执行卡](<artifacts/browser-v1.3.8-cards.txt>)、[UI](<artifacts/browser-v1.3.8-ui.txt>)、[欢迎动画](<artifacts/browser-v1.3.8-welcome.txt>)、[构建日志](<artifacts/android-v1.3.8-final-build.txt>)、[APK 核验](<artifacts/android-v1.3.8-artifact-verification.json>)、[签名及升级证书](<artifacts/android-v1.3.8-signatures.txt>)、[构建来源清单](<artifacts/android-v1.3.8-build-source-sha256.json>)。

没有连接 Android 真机；构建与模拟浏览器验证不等同于设备端容器部署、软件包安装、GPU/NPU 推理、模型下载或系统分享面板验收。16 KB 页设备未实测：包内 Chaquopy 原生库均为 16 KB 对齐，`libtermux.so` 仍是 4 KB 对齐，需要重新构建该库才能在该类设备上加载终端 JNI。

# 历史记录：1.3.6

2026-10-26，版本 **1.3.6 / versionCode 10306**。Python 279 项运行、2 项跳过、零失败；浏览器 88 项通过；JVM 62 项；lint 66 Warning、0 Error/Fatal；来源集合 `0f6e9fb7…3cb17c6`。[构建](<artifacts/android-v1.3.6-final-build.txt>)、[APK 核验](<artifacts/android-v1.3.6-artifact-verification.json>)、[签名](<artifacts/android-v1.3.6-signatures.txt>)。

# 历史记录：1.3.5

2026-10-26，版本 **1.3.5 / versionCode 10305**。Python 259 项运行、2 项跳过、零失败；浏览器专项 87 项通过；JVM 55 项；lint 66 Warning、0 Error/Fatal。release APK SHA-256 `6a3c14dd1606d890a874d2c2a75b67925fc134d17e5702eb3a6fdfc4117bc6e8`，来源集合 `44526941515e2e9cc6622070b10ca0d052a3b6a281070dcb9421be2d35110dda`。[构建](<artifacts/android-v1.3.5-final-build.txt>)、[APK 核验](<artifacts/android-v1.3.5-artifact-verification.json>)、[签名](<artifacts/android-v1.3.5-signatures.txt>)。

# 历史记录：1.3.4

2026-10-20，版本 **1.3.4 / versionCode 10304**。欢迎页 Lottie 上移最多 16dp，问候文字中心由 62% 下移至 70%；两者区域间预留 24dp，小高度下收缩图形区域。通过 120–1000dp 可用场景高度与六档像素密度的 534 组边界计算，区域均不重叠。该计算不是设备截图。

本次原生 JVM **55 项通过，零失败/错误/跳过**；动画播放专项 **20/20**；lint 62 Warning、0 Error/Fatal。构建、APK 资源字节核验、v2/v3 与 zipalign 通过，升级证书与 1.3.3 匹配。没有可用 Android 设备，未宣称真机视觉验收。

证据：[动画回归](<artifacts/browser-v1.3.4-welcome.txt>)、[构建日志](<artifacts/android-v1.3.4-final-build.txt>)、[APK 核验](<artifacts/android-v1.3.4-artifact-verification.json>)、[签名](<artifacts/android-v1.3.4-signatures.txt>)。发行文件与哈希由 dist/AndroidAgent-1.3.4-manifest.json 记录。

# 历史记录：1.3.3

2026-10-20，**1.3.3 / versionCode 10303**。

- Canvas 对比回归确定了缺陷：Lottie `progressiveLoad=true` 在 375 帧后像素数骤降到 45/334×400，600 帧仅有少量静态线；关闭延迟加载后，600 帧为 8,932 像素、1100 帧为 1,619 像素。
- 新增时间线像素断言，180、315、390、450、600、900、1035、1100、1125 帧均有可见图像；暂停位置、减少动态静态帧、连续播放越过晚期合成、1120→开头循环和紧凑视口 resize 均验证通过。总计 **20/20，pageErrors=[]，requests=[]**。
- 修复 WebView resize 后 Canvas 重算，Activity 重复 onStart 时同值 UI 偏好不再重建页面；生命周期暂停保留帧。关闭设置、页面替换、Activity 销毁时释放 WebView。原始 eZ.json 不改字节。

最终构建 **BUILD SUCCESSFUL**；原生 JVM **55 项，0 失败/错误/跳过**；lint **62 Warning、0 Error/Fatal**。APK 资源核验、v2/v3 签名与 zipalign 通过；与 1.3.2 release 升级证书匹配。没有可用 Android 设备，未宣称真机验收。

证据：[逐帧渲染回归](<artifacts/browser-v1.3.3-welcome.txt>)、[构建日志](<artifacts/android-v1.3.3-final-build.txt>)、[APK 核验](<artifacts/android-v1.3.3-artifact-verification.json>)、[签名核验](<artifacts/android-v1.3.3-signatures.txt>)、[600 帧截图](<artifacts/welcome-frame600-v1.3.3.png>)、[1100 帧截图](<artifacts/welcome-frame1100-v1.3.3.png>)。发行文件哈希见 `dist/AndroidAgent-1.3.3-manifest.json`。

## 历史验证

1.3.2 与 1.3.1 的验证记录及 1.3.0 完整 Python/浏览器基线均为历史结果，不计入本次数据。
