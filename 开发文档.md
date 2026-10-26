# 云琥 Yunhu

**把一台 Android 手机变成能自己动手的 AI 智能体。**

云琥是一款运行在 Android 手机上的端侧 AI Agent。它不只是陪你聊天——它会在你授权的范围内**真的去执行**：跑 shell 命令、读写文件、装软件、部署 Linux 容器、调用系统接口，然后把结果读回来继续推理，直到任务真正完成。

整套运行时（终端、Python、包管理器、Linux 容器、本地推理引擎）都打包在一个 APK 里，不需要你先装 Termux，也不需要电脑辅助。

<p>
<img alt="platform" src="https://img.shields.io/badge/platform-Android%2010--17-3ddc84">
<img alt="abi" src="https://img.shields.io/badge/ABI-arm64--v8a-blue">
<img alt="version" src="https://img.shields.io/badge/version-1.3.8-informational">
<img alt="license" src="https://img.shields.io/badge/license-GPL--3.0-orange">
</p>

---

## 目录

- [它和普通 AI 聊天 App 有什么不同](#它和普通-ai-聊天-app-有什么不同)
- [核心能力](#核心能力)
- [工作原理](#工作原理)
- [快速开始](#快速开始)
- [功能详解](#功能详解)
- [支持范围](#支持范围)
- [已知限制](#已知限制)
- [从源码构建](#从源码构建)
- [项目结构](#项目结构)
- [安全与隐私](#安全与隐私)
- [许可证](#许可证)
- [免责声明](#免责声明)

---

## 它和普通 AI 聊天 App 有什么不同

|  | 普通 AI 聊天 App | 云琥 |
| --- | --- | --- |
| 能力边界 | 只能生成文字 | 能执行命令、改文件、装软件、部署系统 |
| 运行位置 | 全部在云端 | 推理可完全离线，执行永远在本机 |
| 需要额外环境 | 无 | 无需额外环境，运行时已内置 |
| 权限模型 | 无 | 普通 / Shizuku / Root 三级通道 |
| 执行审计 | 无 | 每条命令、参数、结果、时间可追溯 |
| 高危操作 | 无概念 | 默认逐条审批，黑名单硬拦截 |
| 可扩展性 | 固定功能 | MCP 服务 + 本地 Skills 动态扩展 |

一句话：它是一个**有手有脚**的模型外壳，而不是一个漂亮的输入框。

---

## 核心能力

### 1. 一体化运行环境，装完就能用

APK 内置了完整的 Termux 0.118.3 ARM64 bootstrap，开箱即得：

- **真实终端**：Termux 终端模拟器 + PTY（`libtermux.so`），不是模拟输出
- **完整用户态**：`bash`、`apt`、`pkg`、`curl`、`tar`、`gzip`、`setsid` 等一应俱全
- **Python 3.13**：通过 Chaquopy 内嵌 CPython，Agent 本体就跑在里面
- **固定前缀**：`$PREFIX=/data/data/com.termux/files/usr`，与 Termux 生态的路径约定一致

首次启动会把 bootstrap 解包到应用私有目录。这一步完全离线，不下载任何东西。

### 2. 三级权限执行通道

同一个 shell 工具，可以跑在三种权限层级上，随任务切换：

| 通道 | 权限级别 | 前置条件 | 能做什么 |
| --- | --- | --- | --- |
| **普通** | 应用沙盒 + 系统普通权限 | 无 | 文件读写、用户态命令、Termux 内一切操作 |
| **Shizuku** | ADB Shell 级（uid=shell） | 安装并激活 Shizuku | `pm`、`am`、`settings`、`input`、截图、装卸载应用 |
| **Root** | 系统最高权限 | Magisk / KernelSU / APatch 已授权 | 访问任意分区、改系统属性、备份应用私有数据 |

**完全权限（Full Access）是用户对"本次任务"的显式选择**，不是全局开关。即使开启，也不绕过本机权限模型和命令黑名单——它放大的是 Agent 的操作自由度，不是突破系统限制的能力。

### 3. 本地大模型，完全离线

内置 llama.cpp（`llama-server`），可以在手机上直接跑量化模型，全程不联网：

- **模型目录**：Qwen2.5-Instruct 的 0.5B 与 1.5B，共 10 个量化档位（Q2_K 到 Q5_K_M）
- **下载校验**：每个 GGUF 都绑定固定 revision 与 SHA-256，重定向只允许白名单 HTTPS 主机
- **上下文**：默认 4096，可调 512–8192
- **线程数**：可配，默认 4
- **硬件加速**：CPU / GPU / NPU 三档开关，**默认全部关闭**；GPU 与 NPU 互斥，且只有在已安装引擎实际枚举到对应后端时才允许勾选
- **Anima 低内存模式**：把有效上下文压到 2048，用于小内存设备
- **引擎日志**：启动失败时可直接在界面查看最近一次 `llama-server` 输出，不用连电脑抓 logcat

第三方模型地址 + 密钥的配置下，上述加速开关会**全部锁定为关闭**——它们只对本地模型有意义。

### 4. 任意 OpenAI 兼容接口

除了本地模型，也可以接入任何兼容 `/v1/chat/completions` 的服务：自建 vLLM、Ollama、LM Studio，或商业 API。

每个模型档位可独立配置：接口地址、模型名、上下文窗口、最大输出、是否支持图片、是否启用推理强度（低 / 中 / 高）。API Key 用 Android Keystore 加密保存，不落明文。

### 5. MCP 与 Skills 双重扩展

- **MCP（Model Context Protocol）**：动态发现远程工具、按 schema 校验参数、凭据加密保管、**每次调用逐次审批**。工具描述、结果和事件在展示前统一脱敏，密钥不会出现在对话里。
- **Skills**：本地技能文件，带 frontmatter 的 Markdown，可自由编写、导入、编辑。适合沉淀你自己的操作手册和固定流程。

两者都可以单独开关。

### 6. Linux 容器，手机上跑 Debian / Ubuntu

基于 `proot-distro`，可以部署完整的 Debian 或 Ubuntu 用户态：

- 缺 `proot-distro` 时自动安装，不需要手工前置
- 上次部署中断留下的残缺 rootfs 会被识别出来，界面提供「清理并重装」（二次确认后 `proot-distro remove` → `install`），而不是把 `container 'ubuntu' already exists` 原样抛给你
- PRoot 是用户态模拟，**不提供 Linux 内核，也没有 GPU / NPU 直通**——这是 PRoot 的固有限制，不是实现缺陷

### 7. 固定软件包目录

不接受任意包名、任意安装脚本或任意二进制。可装的就是这 12 项，每项都映射到 Termux `pkg` 或容器内 `apt` 的固定包：

| 包 | 内容 |
| --- | --- |
| `coreutils` | GNU coreutils |
| `jq` | jq |
| `yq` | yq (Go) |
| `curl` | curl |
| `build-essential` | clang / make / pkg-config（容器内为 build-essential） |
| `git` | git |
| `python` | Python 3 + pip |
| `nodejs` | Node.js LTS（安装后可回读实际 `node`/`npm` 版本） |
| `proot-distro` | PRoot + Debian/Ubuntu 安装器 |
| `apktool-jadx` | apktool + JADX（含 OpenJDK 17） |
| `adb` | Android platform tools |
| `ollama` | Ollama（仅容器内，ARM64 官方包，SHA-256 校验，需 ≥6 GiB 可用空间） |

### 8. 安全不是事后补的

| 机制 | 实现 |
| --- | --- |
| 本地闭环 | 服务只监听 `127.0.0.1:8686`，不对局域网或公网暴露 |
| 密钥鉴权 | 所有请求必须携带随机生成的 Bearer Token |
| 来源校验 | 校验 `Host` 与 `Origin`，拒绝跨站调用 |
| 频率限制 | 内置请求限速，防止本机恶意程序刷接口 |
| 逐条审批 | 默认模式下高危工具每次调用都要你点确认，且确认的是**完整命令原文** |
| 黑名单 | 用户自建命令黑名单，命中直接拒绝，完全权限也不例外 |
| 超时熔断 | 单命令默认 120 秒，单任务默认 3600 秒 |
| 输出上限 | 单次命令输出上限 256 KiB，超出截断并标注 |
| 路径沙箱 | 文件工具限制在私有工作区内，拒绝路径穿越与符号链接逃逸 |
| 自动备份 | `workspace.write` 覆盖前自动备份；重命名工作流生成回滚清单 |
| 审计 | 命令、参数、决策、结果、时间全部记录，可导出 |

### 9. 界面

- **中英双语**，可随时切换
- 主题（跟随系统 / 浅色 / 深色）与字号可调
- 流式输出，执行过程分四层呈现：思考摘要 / 工具调用 / 执行输出 / 错误信息
- 折叠执行卡，长输出不淹没有效信息
- 文件与图片附件（单文件 ≤20 MiB，单轮合计 ≤30 MiB）
- 会话列表、会话分享（导出为图片长图）、消息编辑与重发
- 任意执行中任务一键停止

---

## 工作原理

```
UI 层            Compose 宿主 + WebView（聊天 / 设置 / 终端入口）
   │
   │  本地回环 HTTP + SSE，携带 Bearer Token
   ▼
Agent 层         Python 3.13（Chaquopy 内嵌）
   │             推理循环 · 工具调度 · 上下文管理
   │             MCP 客户端 · 工作流引擎 · 审批与审计
   │
   │  Chaquopy 原生方法调用（不走 JavaScript Bridge）
   ▼
原生桥接层       DeviceBridge（Kotlin）
   │             命令执行通道 · 设备状态 · 本地模型进程
   │
   │  进程派生
   ▼
执行层           Termux 用户态 / Shizuku / su
   │             bash · apt · proot-distro · llama-server
   │
   ▼
Android 系统     /system/bin · SELinux · 硬件驱动
```

**一次任务的完整链路：**

1. 你在界面输入任务，经本地 HTTP 提交
2. Agent 组装上下文 → 请求模型（本地 llama-server 或第三方 API）
3. 模型返回工具调用意图 → Agent 校验参数、检查黑名单、判断是否需要审批
4. 审批通过后，通过原生桥接派生进程，在选定的权限通道里执行
5. `stdout` / `stderr` / `exit_code` 实时回传，SSE 流式推给界面
6. 结果回灌给模型，模型决定下一步或给出最终答复
7. 循环上限 40 轮；期间你随时可以中止

**长耗时任务**走异步模式：立即返回 `task_id`，后台执行并缓存输出片段，界面订阅进度，随时可发终止指令。

---

## 快速开始

### 安装

从 [Releases](https://github.com/2103517328/YunHu-Agent/releases) 下载对应版本的 `release.apk` 直接安装。

**要求：**

- Android 10 – 17（API 29 – 37）
- ARM64（arm64-v8a）设备，不支持 32 位 ARM 与 x86 模拟器
- 安装包约 40 MB，首次启动解包内置环境后占用 110 MB 以上，建议预留 300 MB


> 当前发行包使用 Android **debug 证书**签名，仅供开发与测试。正式分发前必须换成你自己的发布证书，否则后续版本无法覆盖升级。

### 首次启动

1. 通过免责声明确认
2. 阅读并接受风险说明
3. 选择权限模式（可先用普通模式，之后随时在设置里切换）
4. 等待内置环境初始化（离线解包，无需联网）

### 配置模型

**方案 A：本地离线**

设置 → 本地模型 → 安装引擎 → 从目录选一个模型下载 → 启动并激活。
下载有 SHA-256 校验，1.5B Q4_K_M 约 1.1 GB。

**方案 B：第三方接口**

设置 → 模型 → 新增档位 → 填写接口地址（如 `https://api.example.com/v1`）、模型名、API Key → 测试连通 → 启用。

首次使用第三方模型时会单独请求云端数据授权，明确告知哪些内容会离开设备。

### 授予权限（可选）

需要控制系统设置、安装卸载应用、访问系统分区时：

- **Shizuku**：安装 Shizuku 应用 → 按引导激活 → 在云琥设置中请求授权
- **Root**：确保 Magisk / KernelSU / APatch 已授权云琥 → 选择 Root 通道

不想给也不影响核心功能——普通模式已经能跑 Termux 内的一切操作。

### 第一次上手建议

按这个顺序试，能快速建立信任感：

1. 「看一下我的设备信息，告诉我存储还剩多少」
2. 「在工作区建一个 test.py，打印 1 到 10 的平方」
3. 「装一下 jq，然后用它处理一个 JSON 文件」
4. 「部署一个 Debian 容器，在里面装 python3」
5. 「把工作区里所有 png 按顺序重命名」

每步都会看到审批弹窗和执行输出——这正是它和聊天 App 的区别。

---

## 功能详解

### 内置工具

| 工具 | 作用 | 需要审批 |
| --- | --- | --- |
| `shell.execute` | 在真实设备上执行任意 POSIX shell 脚本，走当前任务授权的权限通道 | 是* |
| `workspace.list` | 列出私有工作区文件 | 是* |
| `workspace.read` | 读取工作区文本文件，单次上限 64 KiB | 是* |
| `workspace.write` | 创建或覆盖工作区文本文件，上限 256 KiB，覆盖前自动备份 | 是* |
| `environment.status` | 读取真实权限与运行时可用性，不执行命令、不申请权限 | 否 |
| `memory.recall` | 从当前会话的归档上下文中检索原文，只读 | 否 |

\* 完全权限模式下跳过审批，但黑名单、超时、取消与通道检查仍然生效。

**上下文管理**是自动的：对话超过模型窗口时，早期内容会被摘要并归档，摘要作为背景，原文仍可通过 `memory.recall` 按需取回。这意味着长对话不会因为压缩而丢失关键细节。

### 内置工作流

把多步高频操作封装成一次调用，减少模型出错空间：

| 工作流 | 做什么 |
| --- | --- |
| `workflow.install_apk` | 下载 HTTPS APK → **强制校验 SHA-256** → 用选定通道安装 → 可选启动 |
| `workflow.rename_images` | 按规则批量重命名图片，默认演练模式，实际执行时生成回滚清单，绝不覆盖同名文件 |
| `workflow.backup_app` | 停止应用 → 打包其私有数据到工作区 `.tar.gz` → 无论成败都尝试重启 |

后两个默认禁用，需要在设置中手动开启。

### 本地模型清单

| 模型 | 量化 | 大小 | 定位 |
| --- | --- | --- | --- |
| Qwen2.5 0.5B | Q2_K | ~396 MB | 低存储，质量较低 |
| | Q3_K_M | ~412 MB | 轻量均衡 |
| | Q4_0 | ~409 MB | 轻量均衡 |
| | Q4_K_M | ~469 MB | **推荐入门** |
| | Q5_0 | ~468 MB | 较高质量 |
| | Q5_K_M | ~498 MB | 较高质量 |
| Qwen2.5 1.5B | Q2_K | ~718 MB | 低存储，质量较低 |
| | Q3_K_M | ~882 MB | 中等存储 |
| | Q4_0 | ~1.02 GB | 中等存储 |
| | Q4_K_M | ~1.07 GB | **较佳均衡** |

所有本地模型上下文窗口 4096，仅支持文本输入。

### 设置项一览

| 分类 | 可配置内容 |
| --- | --- |
| 外观 | 主题、字号、界面语言 |
| 模型 | 多档位配置、接口地址、模型名、上下文窗口、最大输出、推理强度、图片支持、API Key、云端授权 |
| 本地模型 | 引擎安装、模型下载、上下文、线程数、CPU/GPU/NPU 加速、Anima 低内存、引擎日志 |
| 扩展 | MCP 服务增删改、全局开关、凭据、Skills 编辑与列表 |
| 运行时 | 环境状态、部署、打开终端、软件包安装、Debian/Ubuntu 部署与清理重装 |
| 权限 | 三通道切换、Shizuku 授权、审批策略 |
| 黑名单 | 手动编辑、导入、导出 |
| 通用 | 命令超时、任务超时、输出上限、自动检查更新 |

---

## 支持范围

| 项目 | 支持情况 |
| --- | --- |
| Android 版本 | 10 – 17（API 29 – 37） |
| CPU 架构 | 仅 arm64-v8a |
| 多用户 / 工作资料 | 支持主用户；工作资料受限 |
| 屏幕方向 | 竖屏为主，横屏可用 |
| Root 方案 | Magisk、KernelSU、APatch |
| 无 Root 方案 | Shizuku（ADB 级） |
| 发行语言 | 简体中文、English |
| 离线可用 | 是（本地模型 + 内置运行时） |

---

## 已知限制

**1. 16 KB 页内核设备无法加载终端**

APK 内 Chaquopy 的 10 个原生库均为 16 KB 对齐，但 vendored 的 `libtermux.so` 仍是 4 KB 对齐。在 16 KB 页内核的 Android 15+ 设备上，终端 JNI 会加载失败。修复需要用 NDK 重新构建该库。**本版未在 16 KB 设备上实测。**

**2. 没有真机验收的部分**

单元测试、lint、构建和桌面浏览器验证**不能**证明以下环节在真实设备上可用：Keystore 实际读写、系统文件选择器、首屏渲染、离线部署、PTY/JNI、Root/Shizuku 授权、各厂商 ROM 的后台生命周期。这些仍需设备端验收。

**3. PRoot 不是虚拟机**

容器内没有独立内核，不能加载内核模块、不能运行 Docker、没有 GPU/NPU 直通。需要这些能力的场景，PRoot 不是正确工具。

**4. 本地模型能力有限**

0.5B / 1.5B 是能在手机上流畅跑的量级，适合问答、摘要、简单指令。复杂多步自动化建议用第三方模型——本地小模型的工具调用可靠性不足以承担。

**5. 发行包使用 debug 证书**

当前所有 Release 都是 debug 签名，仅供开发测试，**不应作为生产升级包分发**。

**6. 包与工具受白名单约束**

只能安装固定目录里的 12 项软件包，只能调用已实现的工具。这是刻意的设计取舍——开放任意安装会让攻击面和故障面同时失控。

---

## 从源码构建

### 环境要求

- **JDK** 21（或 17）
- **Android SDK** 37.2 + Build Tools 37.0.0
- **Gradle** 8.13（仓库内已带 wrapper）
- **Python** 3.10+（仅用于测试与打包脚本）

固定依赖：AGP 8.13.0、Kotlin 2.3.0、Chaquopy 17.1.0 / Python 3.13、Shizuku 13.1.5、Compose Material3 1.3.2、WorkManager 2.10.5。

### 构建

```bash
cd android

# Windows
./build.ps1

# Linux / macOS
./gradlew assembleRelease
```

产物在 `android/app/build/outputs/apk/release/`。

### 运行测试

```bash
# Python 后端（290 项）
python -m unittest discover -s tests -v

# 原生 JVM 单测
cd android && ./gradlew testDebugUnitTest

# 浏览器端（需 Node）
node tests/browser_smoke.cjs
node tests/browser_page_ready.cjs
node tests/browser_features.cjs
node tests/browser_cards.cjs
node tests/browser_ui.cjs
node tests/browser_welcome.cjs
```

### 完整发布链

```bash
python scripts/build_release.py      # 构建 + 源码快照
python scripts/verify_v1_artifacts.py # 产物核验
python scripts/verify_signatures.py   # 签名与 ABI 校验
python scripts/package_v1.py          # 打包 APK + 源码 + 清单
```

### 关于内置二进制

`android/app/src/main/jniLibs/arm64-v8a/libtermux.so` 与 `android/app/src/main/assets/termux/bootstrap-aarch64.zip` 来自 Termux 官方 v0.118.3 ARM64 APK。二者哈希固定，可用下列方式复核或重建：

```powershell
powershell -File android/vendor/termux/extract.ps1
python android/vendor/termux/verify_bootstrap.py
```

来源 URL、SHA-256、上游 commit 全部记录在 `android/vendor/termux/PROVENANCE.json`。

---

## 项目结构

```
├── android/                    Android 客户端（Kotlin + Compose）
│   ├── app/src/main/java/      31 个 Kotlin 源文件
│   │   └── io/localagent/android/
│   │       ├── MainActivity.kt          宿主与 WebView
│   │       ├── DeviceBridge.kt          原生桥接入口
│   │       ├── TermuxRuntime.kt         Termux 环境管理
│   │       ├── LocalModelRuntime.kt     本地推理进程管理
│   │       ├── ShizukuUserService.kt    Shizuku AIDL 服务
│   │       └── TerminalActivity.kt      终端界面
│   ├── terminal-emulator/      Termux 终端模拟器（Apache-2.0）
│   ├── terminal-view/          终端视图组件（Apache-2.0）
│   └── vendor/termux/          Termux 源码、来源记录与提取脚本
├── android_agent/              Python Agent（20 个文件，约 7300 行）
│   ├── core.py                 推理循环、工具调度、审批
│   ├── server.py               本地 HTTP 服务与 SSE
│   ├── model_stream.py         流式解析与重试
│   ├── context_manager.py      上下文压缩与归档
│   ├── workflows.py            复合工作流引擎
│   ├── local_models.py         GGUF 目录与下载
│   ├── runtime_packages.py     Termux / 容器包管理
│   ├── extensions.py           MCP 与 Skills
│   ├── security.py             路径沙箱与黑名单
│   └── store.py                会话与消息持久化
├── web/                        内嵌前端（原生 JS，无框架）
├── tests/                      23 个 Python 测试文件 + 6 个浏览器测试
├── scripts/                    构建、核验、签名、打包脚本
├── docs/                       需求文档
└── workspace/                  私有工作区（初始为空）
```

---

## 安全与隐私

**数据不出设备。** 使用本地模型时，对话、文件、命令输出全部留在手机上，不经过任何服务器。

**用第三方模型时，只有对话内容会发给你自己配置的那个接口**。首次启用会单独询问授权，明确告知数据流向。云琥本身不收集任何个人信息、设备信息或使用统计。

**审计留痕。** 每条命令的命令原文、参数、审批决策、执行结果和时间戳都记录在本地数据库中，可随时查询导出。

**密钥加密。** API Key 与 MCP 凭据用 Android Keystore 加密存储，界面上只显示状态不显示明文，日志与事件中统一脱敏。

**服务不对外。** Python 服务只绑定 `127.0.0.1:8686`，带 Bearer Token、`Host`/`Origin` 校验和限速。局域网里的其他设备无法访问。

如果你发现安全问题，请通过 Issues 反馈；涉及可利用细节的请先私下联系，不要直接公开。

---

## 许可证

本项目以 **GPL-3.0** 分发，全文见 [LICENSE](LICENSE)。

这是被依赖链决定的：应用与 GPL-3.0-only 的 Termux `libtermux.so` 同进程链接，并打包 Termux bootstrap。因此整个 APK 必须以 GPL-3.0 分发，且必须向接收者提供对应源码——每个 Release 都同时提供 `source.zip`。

第三方组件及其许可：

| 组件 | 版本 | 许可 |
| --- | --- | --- |
| Termux app / 终端 | 0.118.3 | GPL-3.0-only |
| terminal-emulator / terminal-view | 0.118.3 | Apache-2.0（上游例外） |
| Chaquopy | 17.1.0 | MIT |
| CPython | 3.13 | PSF |
| Shizuku API / Provider | 13.1.5 | MIT |
| Lottie Web | 5.12.2 | MIT |
| AndroidX / Jetpack | 见 Gradle | Apache-2.0 |

完整声明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

云琥是独立项目，与 Termux、Shizuku、Magisk、KernelSU、APatch 等上游项目**没有官方从属关系**，也不得被声称为 Termux 官方产品。

---

## 免责声明

- 本工具是自动化技术工具，AI 的执行结果存在不确定性。
- 因 AI 误操作、权限滥用导致的设备损坏、数据丢失、账号异常，开发者不承担责任。
- 使用 Root / Shizuku 通道意味着你把设备的最高控制权交给了这个应用和它背后的模型。请自行评估风险。
- 请勿用于违法违规、侵犯他人权益或破坏他人设备的场景。

**先在小范围试，先备份重要数据，再放开权限。**
