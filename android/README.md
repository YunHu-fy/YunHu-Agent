# 云琥 Android 1.3.8

当前版本 **1.3.8 / versionCode 10308** 修复本地模型“启动即退出”，并加入 Android 17（API 37）支持。

**本地推理引擎**：启动参数按已安装 `llama-server` 的 `--help` 实际声明下发，`--no-webui`、`--parallel` 等可选参数不被接受时不再传入；日志显示参数被拒时自动用最简参数重试一次。启动失败返回退出码、实际端口与日志末尾，并翻译成内存不足、缺运行库、端口占用、模型无法加载、参数被拒等可操作原因；端口被占时在 18000–18999 内回退并把真实端口写回模型配置；就绪等待由 1.8 秒放宽到 20 秒。设置页新增「查看引擎日志」（只读桥接方法 `localModelLog`，上限 64 KiB，接口只回文本与字节数）。

**Android 17**：`NativeSetupPolicy` 兼容范围改为 API 29–37，欢迎页、部署校验与提示文案同步更新；三个模块的编译目标升到 compileSdk 37.2 / Build Tools 37.0.0（AGP 8.13 的支持以 `android.suppressUnsupportedCompileSdk=37.2` 显式接受），设备诊断新增 `page_size`。`targetSdk` 仍为 28：Android 10+ 应用私有目录可执行依赖它，上调会破坏 Termux 前缀。16 KB 页内核设备未实测，`libtermux.so` 仍为 4 KB 对齐，需要重新构建才能在该类设备加载终端 JNI。

安装包与对应源码：dist/AndroidAgent-1.3.8-{release.apk,source.zip,manifest.json}。版本、嵌入源码、签名与发行包核验见 [当前记录](<VALIDATION.md>)。没有可用 Android 真机；未宣称设备端容器部署、软件包安装、GPU/NPU 推理、下载或分享面板已实测。

## 1.3.7 修复沿用

上次部署中断后，`installed-rootfs/<distro>` 会留下不完整的 rootfs；`proot-distro` 拒绝重名安装，报 `container 'ubuntu' already exists`，而原流程只把这句话原样抛回界面，用户没有任何出口。现在部署前会先判断容器是否完整（以 `usr/bin/apt-get` 是否存在为准）：完整则直接复用；只有残留目录时给出明确说明，并在同一条命令组里加上“清理并重装”按钮，点击后二次确认，先执行 `proot-distro remove <distro>` 再 `proot-distro install <distro>`。安装过程若仍返回 `already exists`，也会被翻译成同一句可操作提示，而不是原始报错。

## 1.3.6 修复沿用

原生桥接补齐 Python 运行环境一直调用、但从未暴露的同步 `executeCommand`，这是“运行环境操作未成功：原生桥接不支持executeCommand”的直接原因；实现复用 `commandStart`/`commandPoll`/`commandCancel` 的排空逻辑，保留 1 MiB 输出上限、通道准入和取消语义，不另起一个执行器。容器部署不再因宿主缺少 `proot-distro` 直接失败，而是先在 Termux 内 `pkg install -y proot-distro` 再安装发行版；容器与运行时缺失、未部署时返回具体原因，设置页不再只显示“包状态暂不可用”。软件包目录覆盖 coreutils、jq、yq、curl、build-essential、git、apktool+JADX、adb、Node.js LTS 与 Ollama，其中 Ollama 只在 Debian/Ubuntu 容器内安装，来自固定版本的官方 ARM64 发布包并校验 SHA-256。Node.js LTS 安装后可用 `probe=true` 回读实际 node/npm 版本。

模型设置新增“硬件加速（仅本地模型）”分组：CPU 硬件加速、GPU 硬件加速、NPU 硬件加速和 Anima 低内存模式，默认全部关闭。选择第三方模型（有地址、有密钥）时四项一律锁定为关闭；选择本地模型后才可操作。GPU 与 NPU 互斥，且只有在本地引擎上报对应后端时才允许勾选，未上报时保持禁用并说明原因。

1.3.6 的发行包为 dist/AndroidAgent-1.3.6-{release.apk,source.zip,manifest.json}，验证结果保存在该版本的构建、核验与签名证据中。

## 1.3.5 功能沿用

1.3.5 / versionCode 10305 增加 10 个固定版本的 Qwen2.5 0.5B/1.5B GGUF 本地下载项，提供 Hugging Face 国内镜像或官方源选择、续传、SHA-256 校验和 Android ARM64 llama.cpp 部署。聊天新增 Android 系统分享的长对话分页图片、已完成回合的用户消息编辑/删除；编辑后仅准备由用户明确确认发送的草稿。撤回云端同意会取消后续远程调用和工具派发，本地推理不需要云端同意。

## 1.3.3 功能沿用

1.3.3 / versionCode 10303 修复 eZ 动画 Canvas 延迟加载导致后半段嵌套图层缺失的问题，并增加完整时间线像素回归。暂停保持播放帧；减少动态效果使用单独的静态帧行为。Lottie Canvas 在初次加载、WebView 尺寸变化及 Insets/分屏变化后重算大小。Activity 返回前台时不会因无变化的偏好重建动画；关闭设置、重建页面和销毁 Activity 时幂等释放旧 WebView。

欢迎页仍使用 [工作区 eZ 动画](<../eZ.json>)，中间“你好”和“hello”逐字交替，说明文案位于底部按钮上方。动画 JSON、Lottie Web 5.12.2 和 MIT 许可均随 APK 内置，不依赖网络。对应 APK、源码与哈希清单为 dist/AndroidAgent-1.3.3-{release.apk,source.zip,manifest.json}。验证见 [当前记录](<VALIDATION.md>)。

## 1.3.0 功能与验证基线

云琥 1.3.0 更新品牌资源、分步首次进入、主题 / 字号 / 界面语言及紧凑聊天布局，继续提供固定自动上下文整理、对话隔离记忆和折叠执行卡。完整后端运行 **186 项，184 通过、2 项 Windows symlink 跳过、0 失败/错误，51.036 秒**，包含 9 项新增界面配置专项，不重复相加。浏览器五组 **66/66**，本版原生 XML **51 项、0 失败/错误/跳过**；最终构建、24 个内嵌文件核验、v2/v3 与 zipalign 通过，与 1.2.0 release 同证书，lint **62 Warning、0 Error/Fatal**。最后构建复用本版已执行的 JVM XML，具体时间戳和边界见记录。当前版本的实际构建、测试、截图与签名证据见 [Android 验证](<VALIDATION.md>)和 [项目验证](<../VALIDATION.md>)。发行路径为 dist/AndroidAgent-1.3.0-{release.apk,debug.apk,source.zip}，实际大小与 SHA-256 由对应 manifest.json 记录；1.2.0 验证只作为历史基线。

云琥（Yunhu）**1.3.0 / versionCode 10300** 是 GPL-3.0-only 的独立 Termux 集成应用。原生 Compose Material3 宿主保留聊天 WebView，Python 服务只绑定 127.0.0.1:8686；认证后的 Python API 经 Chaquopy 调用原生方法，不使用 JavaScript bridge。

**安装兼容性：** 官方 bootstrap 固定前缀为 /data/data/com.termux/files/usr，所以 applicationId=com.termux、namespace=io.localagent.android。与官方 Termux 不能并存，签名不同不能覆盖安装；不会自动卸载、清除数据或覆盖未知环境。支持 Android 10–17/API 29–37、ARM64、主用户；不支持工作资料/次用户或 x86。targetSdk 28 用于保留私有目录执行能力，不符合当前 Google Play target API 要求，compileSdk 37.2 不改变这一点。已有数据应先备份；本项目旧发行包只在最终签名一致时支持覆盖升级。

## 首次引导与返回会话

首次进入分为 Hello 原创路径欢迎动画、许可与隐私、权限通道选择、明确授权与只读环境检查、就绪并进入对话。欢迎动画借鉴激活流程的分步节奏，使用原创 Bézier 路径逐笔显现与线条图案，遵循系统减少动态效果设置，不使用 Apple 图形或素材。FirstRunGate 仍在风险同意、通道确认和检查全部成功后保存完成标记；返回用户正常启动直接进入会话，不重复整套引导。权限设置可主动重新打开。仅当旧安装同时已有原生同意和启用服务状态、且缺少新完成标记时，才迁移为完成；显式未完成状态仍显示引导。

持久化的通道选择只用于界面，不重放 Root/Shizuku 授权。新进程从普通应用权限开始；服务恢复也不恢复提权，用户须明确配置。失败或断开的提权通道不静默回退为可执行普通通道；命令入口检查 channelReady，重新确认后才执行。普通服务恢复仅恢复应用自身权限，不执行 su、不启动 Shizuku 授权。

## 品牌、外观与界面语言

应用名固定为云琥，英文音译 Yunhu。[原始 ICO](<../图标.ico>)作为品牌图像来源，[生成脚本](<../scripts/generate_brand_assets.py>)提取最高 128×128 帧并原样保存为网页与原生品牌 PNG；启动图标为 48 / 72 / 96 / 144 / 192 像素五档，自适应前景以白底和 18% 留白避免文字裁切。它们保持同一品牌图像，不使用 Apple 或其他产品的图形资产；品牌名称不随语言设置变成自定义名称。

主题提供 system / light / dark，默认 system；字号 xs / sm / md / lg / xl 分别为小小 / 小 / 中 / 大 / 大大，对应 0.84 / 0.92 / 1 / 1.12 / 1.24 倍，默认 md；界面语言为 zh / en，默认 zh。语言设置只翻译应用界面文案，不翻译用户消息、模型回答、命令和工具输出，也不向模型加入语言提示。非秘密字段 ui_theme / ui_font_size / ui_language 由后端保存，启动、设置更新和配置导入时镜像到原生界面；主线程观察器只同步外观，不触发权限授权；AgentService 通知同步使用应用语言，Terminal 与 Licenses 页面也应用主题、字号和界面语言；这些值不是密钥、授权或模型参数。聊天页采用双横线极简页头入口，不重复头像、标题与状态，紧凑输入区保留模型选择和必要操作。

## 模型配置、凭据与附件

每个模型配置独立保存服务 URL、模型名、密钥引用、上下文窗口、最大输出、推理开关/默认 low/medium/high 级别和图片能力。任务提交时冻结模型配置与密钥选择；设置变更不改变在运行任务。上下文按 UTF-8 字节、工具定义、消息开销、图片预算和输出预留做保守估算，固定启用的 ContextSession 达可用输入预算 75% 后自动整理，目标约 58%，最终仍检查必要内容能否容纳；不是服务端 tokenizer 的精确计数，不通过随意缩小字节估算绕过窗口。普通模型用 max_tokens，推理模型用 max_completion_tokens 与 reasoning_effort，服务实际能力仍需用户正确配置。

Android 通过 [凭据存储](<app/src/main/java/io/localagent/android/KeyStoreCredentialStore.kt>) 在 Android Keystore 创建 AES-256 主密钥，以 AES-GCM、随机 96-bit IV、128-bit tag 和凭据引用 AAD 加密各配置 API 密钥。不同配置持有独立凭据记录，共用设备主密钥；不宣称每个配置一个 Keystore 主密钥或强制硬件/StrongBox。应用私有偏好只存密文，普通模型配置只存引用，启动数据/配置导出不含明文或可恢复凭据引用。解密/保存失败明确报错，不降级明文或会话内存。备份和设备迁移已禁用；桌面预览明确为 memory_session，重启需重新输入。

附件每条消息最多 **8 个，单文件 ≤20 MiB、合计 ≤30 MiB**（原始字节）。非图片文件若 **≤512 KiB、合法 UTF-8 且无 NUL** 则作为可内联文本；自动整理可先归档再改用摘录和记录 ID，完整附件文件仍保留。其余文件保存在私有工作区 attachments/<随机ID>/payload（显示文件名仅作元数据）并提供工具路径，不承诺解析任意二进制。PNG/JPEG/GIF/WebP 校验文件头，新图片要求当前模型支持图片，以 image_url 中的 data URL（detail=low）发送；历史图片遇到不支持图片的配置时只发送明确的“历史图片未发送”说明，不发送原图；自动整理也可归档历史图片并用有记录 ID 的文字替代，当前图片仍检查配置能力。[根使用说明](<../README.md>)说明完整的数据发送边界。

WebView 的系统文件选择器使用 ACTION_OPEN_DOCUMENT，仅接受用户明确选择的 content URI。只在当前本地文档/回调代次允许读取，导航、重建或渲染进程退出后撤销旧 URI 访问，不开放通用文件访问或外部导航。这是源码中的生命周期保护，真实系统文档提供器行为仍需设备验收。

## 自动上下文、记忆与恢复

Python 的 [ContextSession](<../android_agent/context_manager.py>)固定自动整理，不提供开关。长文本、旧轮次及历史图片先归档后换成摘录/摘要和原文 ID，工具调用与结果作为完整交换处理。除 memory.recall 外，每个工具实际返回的完整 JSON 经应用脱敏后保存到 SQLite `context_records`，与有限 SSE 事件缓存独立；原始结果大于 6000 字节时给模型摘录、状态和记录 ID；memory.recall 的原文分页不再次按 6000 字节摘录，页内容仍受总体上下文预算约束。原生/工具自身的输出上限依旧存在，归档不恢复此前已被执行器截断的输出。

`memory.recall` 是当前对话内的只读读取，不执行原文中的脚本，也不跨对话。省略 `record_id` 时按记录 `offset` 分页索引，每页 `min(40, limit)` 条，`query` 在当前对话所有档案正文做精确字串过滤，返回 `next_offset` / `total_records` / `has_more`。指定 32 位十六进制 ID 后按字符 `offset` 和 `limit`（1–8192，默认 4096）分页，`query` 定位该原文内的字串；偏移从 0 起，查询最多 200 字符。recall 的调用/返回不自行归档，避免索引漂移及反复复制；读取页不再次做 6000 字节摘录，仍受总上下文预算约束。原文保存在 SQLite，通过记录 ID 与工具参数读取；操作的实际 path/cwd 作为事实保留。删除对话会级联删除记忆、检查点和归档。

每轮、每工具后及终态写 `task_checkpoints` / `context_memories`，保存目标、摘要、操作、状态、文件路径、退出码和原文记录 ID，不把完全权限、原生授权或模型密钥作为可恢复权限保存。摘要以历史数据加入上下文，不是系统指令。语义摘要与真实任务复用同一不可变 ModelSelection，保留端点/模型/密钥/推理开关及级别；仅本次摘要请求输出上限设 min(768,max_output_tokens)，不改配置，静默 tools=[] 且不输出到用户回答；同样超预算或服务不兼容/不可用时回退摘录；取消、截止时间和网络中断归真实任务管理。

任务中断或服务重启不会自动重放历史修改操作。用户需提交新任务，模型先只读核对实际状态，再按本次权限继续；记忆不把一次尝试改写为成功，不自动恢复 Root/Shizuku 或完全权限。执行卡固定为小字浅灰单句摘要、可展开查看脚本和结果、不可配置；待审批命令完整内容、参数、通道/运行环境/工作目录/环境变量始终可见，审批结束后收回可展开历史。键盘展开、流更新/stream_reset、刷新恢复折叠、失败状态和审批例外的实际验证范围见 [项目验证](<../VALIDATION.md>)；旧版通过数不作为本版或真机证明。

助手正文完整累计，正常完成的完整回答保存到 assistant_response 归档；任务累计可见正文设 8 Mi 字符（8×1024×1024）显式上限，触限报可解释错误并保留此前内容，每轮解析另有更小动态限制。原生 stdout/stderr 既有上限继续有效，完整回答归档不能替代被执行器截断的设备输出。

## 流式响应边界

[标准库 parser](<../android_agent/model_stream.py>)用 read1 逐块解析 SSE/JSON，SSE 只保留当前事件，不缓存完整 wire；支持分块 UTF-8、CRLF/多行 data、注释/心跳、[DONE]/finish_reason/usage。首正文立即显示，后续约 2048 字符/0.1 秒的下一检查点合批，无后台刷新线程；reasoning 只计预算不展示。动态 wire 16–128 MiB、event 默认 8 MiB、JSON 8–16 MiB，wire 接收量不等于 RAM；正文 32chars/token 是安全预算，semantic 合计正文/推理/参数默认至少 300k、最多 8Mi 字符，每轮最多 8 工具且单个 arguments≤300000 字符。

EOF 无完整结束报 incomplete，仅尚无可见正文时允许重试；length 明确截断且不派发工具，malformed/部分调用组同样不派发。取消/任务截止时间与最长 90 秒请求 socket 中断继续有效。1.2.0 历史流解析专项为 **42 项、1.791 秒、exit 0**，包括 40 新增 parser 与 2 既有集成回归；[历史证据](<../artifacts/python-v1.2.0-stream.txt>)不替代当前版本的完整套件。

## 固定依赖与构建

Gradle 8.13、AGP 8.13.0、Kotlin 2.3.0、Chaquopy 17.1.0/Python 3.13、Shizuku 13.1.5、Compose Material3 1.3.2、WorkManager 2.10.5。JDK 17/21、源码目标 17，Android SDK 36.1/Build Tools 36.1.0。使用已装工具链，不自动安装 SDK。开发机没有 NDK；终端 JNI 来自 SHA-256 固定的官方 v0.118.3 ARM64 APK，匹配的 C/Android.mk 和 Java 源码已保留。

从本目录运行测试，不组装最终 APK：

~~~powershell
./build.ps1 -Check
./build.ps1 ':app:testDebugUnitTest' ':app:lintDebug' '--offline' '--console=plain' '--no-daemon'
python -B ../scripts/native_summary.py
~~~

从工程根目录完成后端/浏览器测试并冻结 Python/网页源码后，按下列顺序构建、核验和打包。源码修正后须重新生成匹配证据，证书显式比较旧 1.2.0 release：

~~~powershell
python -B scripts/build_release.py
python -B scripts/verify_v1_artifacts.py
# 需有效 JDK21；仅修正当前进程：
$env:JAVA_HOME='C:/Program Files/Zulu/zulu-21'
python -B scripts/verify_signatures.py --prior-apk dist/AndroidAgent-1.2.0-release.apk
python -B scripts/package_v1.py
~~~

[构建日志脚本](<../scripts/build_release.py>)同时运行原生 unit/lint、debug/release assemble，并按当前版本写构建日志。离线缓存不完整时应显式处理依赖，不把 --offline 失败写成通过。[构建入口](<build.ps1>)只在当前进程选择 Java/SDK/Gradle，不修改系统设置；缺 Gradle 时显式 -BootstrapGradle 下载并核对官方校验和。Linux/macOS 可用 bash gradlew。

Release 使用 R8/资源压缩及 Chaquopy/JNI 保留规则，debug/release 启用 APK v2/v3 签名。AGENT_KEYSTORE、AGENT_STORE_PASSWORD、AGENT_KEY_ALIAS、AGENT_KEY_PASSWORD 可提供发布密钥；未提供时 release 使用本机 Android Debug 证书。不要提交密钥/密码；正式签名必须稳定。验签默认固定本项目开发证书，换签名需显式设置 ANDROID_AGENT_EXPECTED_CERT_SHA256；debug 证书可用 ANDROID_AGENT_EXPECTED_DEBUG_CERT_SHA256。SDK 路径按 ANDROID_SDK_ROOT、ANDROID_HOME、LOCALAPPDATA/Android/Sdk 解析。--prior-apk（或 ANDROID_AGENT_PRIOR_APK）只比较显式指定旧包与 release 的证书，未指定时记录 not_run，不宣称验证覆盖升级；同证书比较也不等于设备升级实测。

stageEmbeddedSources 逐字复制 android_agent/**/*.py、web/index.html、web/static/**。[APK 检查](<verify_apk.py>)要求内嵌集合与全部冻结源码一致（含 context_manager/model_stream 及模型/附件模块），检查 ARM64、Python 3.13、bootstrap/JNI 固定哈希与完整许可证。[产物核验](<../scripts/verify_v1_artifacts.py>)从实际 JUnit XML 求和并保存各 suite 时间戳，不写死 32 或 43；同时检查 lint 与 v2/v3 签名块。SDK [验签脚本](<../scripts/verify_signatures.py>)另行验证真实签名、manifest 版本/min29/target28、ABI 和 zipalign，并将 APK 哈希绑定到版本日志。[打包脚本](<../scripts/package_v1.py>)要求同版本成功构建/核验/签名证据，重新比对 XML、APK 哈希和内嵌源码后才创建发行包；不收集运行工作区、密钥、构建缓存或旧版截图证据。

## 内置环境、命令与历史路径修复

官方 v0.118.3 来源/哈希与匹配源码在 [Termux 来源记录](<vendor/termux/PROVENANCE.json>)。离线 bootstrap 提供 bash/pkg/apt/curl 等；部署验证哈希、私有原子暂存、路径/符号链接和官方 second-stage，不安装或打开外部 Termux，不下载初始环境。额外 pkg/apt 只由明确命令触发。未知前缀或中断后已发布前缀保留并给出错误，手动重置前先备份。

完整 Linux 容器（PRoot）由 [runtime_packages](<../android_agent/runtime_packages.py>) 部署：缺少 `proot-distro` 时先在 Termux 内 `pkg install -y proot-distro`，再执行 `proot-distro install <debian|ubuntu>`，不会因为宿主状态直接判定失败。发行版解包在 `$PREFIX/var/lib/proot-distro/installed-rootfs/`，登录命令为 `proot-distro login <distro> -- sh -c …`。状态接口对未部署容器、未知发行版、运行时缺失分别返回明确 reason/detail，界面据此显示原因，不再笼统给出“包状态暂不可用”。

软件包目录把同一工具映射到 Termux 与容器两条安装路径：coreutils、jq、yq、curl、build-essential、git、apktool+jadx、adb 走 `pkg install -y` 或 `apt-get install -y`；Node.js LTS 与 Python 工具链同理；Ollama 标记为仅容器可用，安装时下载固定版本的官方 `ollama-linux-arm64.tar.zst`（v0.40.11，1,564,235,434 字节），先 `sha256sum -c -` 校验再解包，并要求至少 6 GiB 可用空间。安装完成后可选 `probe=true` 回读版本，例如 `curl 8.9.1`、`v22.9.0`。

命令通道新增同步 `executeCommand`：接受与 `commandStart` 相同的请求结构，内部排空 `commandStart`/`commandPoll`，返回退出码、时长、截断标记和结果，超时为请求超时加 3 秒，stdout+stderr 仍合计保留 1 MiB。它服务无法流式读取的调用方（软件包安装），不改变准入、黑名单、取消或并发语义，也不构成第二个执行器。

保留 1.0.3 的只读路径身份检查：Os.stat 核对实际 filesDir 与固定 /data/data/com.termux/files 的目录类型、UID、设备号和 inode，不比较 canonical 字符串。发布前复查，两端 rename 均使用固定父目录别名；不匹配或不可访问继续拒绝并保留 stat 错误。不创建探测文件、不执行 Root 修复、不关闭 SELinux。

TerminalActivity 使用 TerminalView/TerminalSession/libtermux 的真实 PTY。普通为应用 UID，Root 仅在显式配置后验证 su UID0；Shizuku UserService 运行系统 shell，但不能访问私有 Termux 前缀，不回退。切通道取消旧命令并关闭 PTY，epoch 防止旧 Root 会话复用。任意 shell 结构验证不等于沙箱；Python 执行用户黑名单/逐条或完全权限策略。

命令异步返回 ID、分流序号事件和退出码/状态/时长；原生 stdout+stderr 合计保留 1 MiB、事件环 256 KiB/256 条，4 并发、16 保留记录。Shizuku 每页最多 16 事件，最终结果切片跨 Binder。PID/starttime 核对后尽力 SIGTERM/SIGKILL；主动脱离进程组、Root 和 ROM 限制可能阻止完整后代终止。

## 本地模型与硬件加速

本地模型设置分两层：引擎与权重来自固定 GGUF 目录和 ARM64 llama.cpp，加速选项由“硬件加速（仅本地模型）”分组控制。CPU 硬件加速、GPU 硬件加速、NPU 硬件加速与 Anima 低内存模式默认全部关闭，只有当前生效的模型端点被识别为本地（`127.0.0.1:18000–18999` 的 `/v1` 端点，或已激活的本地模型）时才解锁；使用第三方模型（地址 + 密钥）时四项一律锁定为关闭。

GPU 与 NPU 互斥，同时勾选会被后端拒绝。两者还要等本地引擎上报对应后端才允许勾选：`/api/local-models/backends` 返回经 [EngineDevices](<app/src/main/java/io/localagent/android/EngineDevices.kt>) 分类的设备列表，未上报 GPU/NPU 时复选框保持禁用并显示原因。勾选结果以 `local_cpu_acceleration_enabled`、`local_gpu_acceleration_enabled`、`local_npu_acceleration_enabled`、`anima_low_memory_enabled` 保存，仅在本地作用域有效；切回第三方模型时后端会清除这些标记。这台开发机没有 Android 设备，PRoot 也不提供 GPU/NPU 直通，因此不声称 GPU/NPU 推理在真机实测通过。

## 页面、生命周期与法律

WebView 与不透明加载区填满宿主；本次导航编号、脚本/CSS/表单、主页面 commit 与 visual callback 都就绪才隐藏加载区。30 秒超时、关键资源失败和渲染退出显示重试。只读 evaluateJavascript 返回布尔值，无 addJavascriptInterface、不返回 token。

前台通知可停止；用户启用的 WorkManager 最低 15 分钟周期、最多 3 次/15 分钟恢复，主动停止禁用恢复。Wake/Wi-Fi 锁默认关，电池白名单由用户在系统设置选择。5 秒状态缓存报告时间、缺失/过期/错误，前台应用需 UsageStats 并注明历史来源。

完整 GPLv3/Apache-2.0/NOTICE/来源 JSON 随 APK 附带，bootstrap 各包许可证保留于 prefix。分发仍须提供所有覆盖二进制（含 bootstrap）的对应源码或有效 GPL 书面承诺，上游链接不能替代。见 [第三方声明](<../THIRD_PARTY_NOTICES.md>)、[原生契约](<NATIVE-v1.0.md>)及[验证记录](<VALIDATION.md>)。

本轮无连接 Android 设备或可用 AVD。单元、lint、构建和桌面浏览器验证不证明真机 Keystore、文件选择器、首屏、离线部署、PTY/JNI、Root/Shizuku 或 ROM 生命周期已成功；这些仍需设备验收。
