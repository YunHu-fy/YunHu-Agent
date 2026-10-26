(() => {
  "use strict";
  const catalog = {
  "ui_001": {
    "zh": "排队中",
    "en": "Queued"
  },
  "ui_002": {
    "zh": "正在执行",
    "en": "Running"
  },
  "ui_003": {
    "zh": "等待你的确认",
    "en": "Waiting for your approval"
  },
  "ui_004": {
    "zh": "已完成",
    "en": "Completed"
  },
  "ui_005": {
    "zh": "执行失败",
    "en": "Failed"
  },
  "ui_006": {
    "zh": "已停止",
    "en": "Stopped"
  },
  "ui_007": {
    "zh": "执行超时",
    "en": "Timed out"
  },
  "ui_008": {
    "zh": "普通权限",
    "en": "App permissions"
  },
  "ui_009": {
    "zh": "未命名模型",
    "en": "Unnamed model"
  },
  "ui_010": {
    "zh": " · 请求发送到已配置服务",
    "en": " · Sent to your configured service"
  },
  "ui_011": {
    "zh": "尚未配置模型 · 请前往设置",
    "en": "No model configured · Open settings"
  },
  "ui_012": {
    "zh": "尚未添加模型配置。",
    "en": "No model profiles yet."
  },
  "ui_013": {
    "zh": "模型详情",
    "en": "Model details"
  },
  "ui_014": {
    "zh": "未设置地址",
    "en": "No URL configured"
  },
  "ui_015": {
    "zh": " · 已配置密钥",
    "en": " · Key configured"
  },
  "ui_016": {
    "zh": "当前",
    "en": "Active"
  },
  "ui_017": {
    "zh": "已标记清除当前模型密钥，保存设置后生效。",
    "en": "Key marked for removal. Save to apply."
  },
  "ui_018": {
    "zh": "服务已配置密钥。留空保留；密钥不会回传到页面。",
    "en": "A key is configured. Leave blank to keep it; it is never returned to this page."
  },
  "ui_019": {
    "zh": "尚未配置密钥，本地服务可不填写。",
    "en": "No key configured. Local services may not require one."
  },
  "ui_020": {
    "zh": "显示 API 密钥",
    "en": "Show API key"
  },
  "ui_021": {
    "zh": "模型配置加载失败：",
    "en": "Could not load model profiles: "
  },
  "ui_022": {
    "zh": "请先添加模型配置。",
    "en": "Add a model profile first."
  },
  "ui_023": {
    "zh": "请输入有效的模型服务地址。",
    "en": "Enter a valid model service URL."
  },
  "ui_024": {
    "zh": "模型服务地址须为 HTTP(S)，不能包含密钥、查询或片段。",
    "en": "Use an HTTP(S) model URL without credentials, query parameters or fragments."
  },
  "ui_025": {
    "zh": "每个模型配置都需要模型名称。",
    "en": "Every profile needs a model name."
  },
  "ui_026": {
    "zh": "上下文窗口必须为 256～2097152 的整数。",
    "en": "Context window must be an integer from 256 to 2097152."
  },
  "ui_027": {
    "zh": "最大输出 tokens 必须为 1～1048576 的整数，且严格小于上下文窗口。",
    "en": "Maximum output must be an integer from 1 to 1048576 and smaller than the context window."
  },
  "ui_028": {
    "zh": "API 密钥格式无效。",
    "en": "Invalid API key format."
  },
  "ui_029": {
    "zh": "服务地址已改变，请为该模型重新输入 API 密钥，或明确清除已保存密钥后再保存。",
    "en": "The service URL changed. Enter a new API key or explicitly clear the saved key before saving."
  },
  "ui_030": {
    "zh": "当前模型不支持图片，请切换模型或移除图片后发送。",
    "en": "This model does not support images. Switch models or remove images before sending."
  },
  "ui_031": {
    "zh": "移除附件「",
    "en": "Remove attachment “"
  },
  "ui_032": {
    "zh": " / 8 个附件 · ",
    "en": " / 8 attachments · "
  },
  "ui_033": {
    "zh": " / 30 MiB · 单文件不超过 20 MiB",
    "en": " / 30 MiB · Up to 20 MiB per file"
  },
  "ui_034": {
    "zh": "请等待当前任务结束后再添加附件。",
    "en": "Wait for the current task to finish before adding attachments."
  },
  "ui_035": {
    "zh": "每次最多添加 8 个附件。",
    "en": "You can add up to 8 attachments."
  },
  "ui_036": {
    "zh": "单个附件不得超过 20 MiB。",
    "en": "Each attachment must be 20 MiB or smaller."
  },
  "ui_037": {
    "zh": "附件总大小不得超过 30 MiB。",
    "en": "Attachments must total 30 MiB or less."
  },
  "ui_038": {
    "zh": "请选择图片文件。",
    "en": "Choose an image file."
  },
  "ui_039": {
    "zh": "当前模型不支持图片，请先选择支持图片的模型。",
    "en": "Choose a model that supports images first."
  },
  "ui_040": {
    "zh": "仅支持 PNG、JPEG、WebP 或 GIF 图片。",
    "en": "Only PNG, JPEG, WebP and GIF images are supported."
  },
  "ui_041": {
    "zh": "无法读取附件「",
    "en": "Could not read attachment “"
  },
  "ui_042": {
    "zh": "运行令牌已失效，请从应用重新打开授权页面。",
    "en": "The session token expired. Reopen this page from the app."
  },
  "ui_043": {
    "zh": "请求失败（",
    "en": "Request failed ("
  },
  "ui_044": {
    "zh": "请求超时，请检查本地服务后重试。",
    "en": "Request timed out. Check the local service and retry."
  },
  "ui_045": {
    "zh": "服务返回了无法解析的数据。",
    "en": "The service returned invalid data."
  },
  "ui_046": {
    "zh": "服务运行中",
    "en": "Service running"
  },
  "ui_047": {
    "zh": "连接已断开",
    "en": "Disconnected"
  },
  "ui_048": {
    "zh": "无法连接本地服务，会话与任务仍保留。",
    "en": "Cannot connect to the local service. Conversations and tasks are preserved."
  },
  "ui_049": {
    "zh": "设置",
    "en": "Settings"
  },
  "ui_050": {
    "zh": "云琥 · ",
    "en": "Yunhu · "
  },
  "ui_051": {
    "zh": "新对话",
    "en": "New conversation"
  },
  "ui_052": {
    "zh": "保存在本机",
    "en": "Saved on this device"
  },
  "ui_053": {
    "zh": "没有找到匹配的对话",
    "en": "No matching conversations"
  },
  "ui_054": {
    "zh": "从新对话开始吧",
    "en": "Start a new conversation"
  },
  "ui_055": {
    "zh": "未命名对话",
    "en": "Untitled conversation"
  },
  "ui_056": {
    "zh": "任务进行中 · ",
    "en": "Task running · "
  },
  "ui_057": {
    "zh": "重命名「",
    "en": "Rename “"
  },
  "ui_058": {
    "zh": "对话",
    "en": "Conversation"
  },
  "ui_059": {
    "zh": "删除「",
    "en": "Delete “"
  },
  "ui_060": {
    "zh": "这段对话有任务正在运行。请先打开对话停止或等待任务完成后再删除。",
    "en": "A task is running in this conversation. Open it and stop the task or wait until it finishes before deleting."
  },
  "ui_061": {
    "zh": "」删除后无法恢复。",
    "en": "” cannot be recovered once deleted."
  },
  "ui_062": {
    "zh": "命令未执行",
    "en": "Command was not executed"
  },
  "ui_063": {
    "zh": "任务执行失败",
    "en": "Task failed"
  },
  "ui_064": {
    "zh": "今天，想完成什么？",
    "en": "What would you like to do?"
  },
  "ui_065": {
    "zh": "从一个想法开始，让设备为你行动。",
    "en": "Start with an idea. Let your device help."
  },
  "ui_066": {
    "zh": "了解设备状态",
    "en": "Check device status"
  },
  "ui_067": {
    "zh": "查看系统、电量和环境",
    "en": "System, battery and environment"
  },
  "ui_068": {
    "zh": "整理工作文件",
    "en": "Organize work files"
  },
  "ui_069": {
    "zh": "先查看，再制定方案",
    "en": "Inspect first, then plan"
  },
  "ui_070": {
    "zh": "执行自动化任务",
    "en": "Automate a task"
  },
  "ui_071": {
    "zh": "描述目标，由 AI 规划",
    "en": "Describe a goal for AI to plan"
  },
  "ui_072": {
    "zh": "云琥",
    "en": "Yunhu"
  },
  "ui_073": {
    "zh": "完全权限任务",
    "en": "Full access task"
  },
  "ui_074": {
    "zh": "模型提供的推理摘要",
    "en": "Reasoning summary from the model"
  },
  "ui_075": {
    "zh": "模型正在响应",
    "en": "Model is responding"
  },
  "ui_076": {
    "zh": "准备执行",
    "en": "Preparing"
  },
  "ui_077": {
    "zh": "执行中",
    "en": "Running"
  },
  "ui_078": {
    "zh": "待确认",
    "en": "Awaiting approval"
  },
  "ui_079": {
    "zh": "执行完成",
    "en": "Completed"
  },
  "ui_080": {
    "zh": "已拒绝",
    "en": "Denied"
  },
  "ui_081": {
    "zh": "通道 · ",
    "en": "Channel · "
  },
  "ui_082": {
    "zh": "运行时 runtime · ",
    "en": "Runtime · "
  },
  "ui_083": {
    "zh": "系统 Shell",
    "en": "System shell"
  },
  "ui_084": {
    "zh": "目录 cwd · ",
    "en": "Directory · cwd · "
  },
  "ui_085": {
    "zh": "默认工作目录",
    "en": "Default working directory"
  },
  "ui_086": {
    "zh": "环境变量 environment · ",
    "en": "Environment variables · "
  },
  "ui_087": {
    "zh": "未额外设置",
    "en": "None added"
  },
  "ui_088": {
    "zh": "执行前确认",
    "en": "Approve before execution"
  },
  "ui_089": {
    "zh": "核对以下完整命令、参数和执行环境后，仅批准这一次执行。",
    "en": "Review the exact command, arguments and execution environment below. Approval applies only to this execution."
  },
  "ui_090": {
    "zh": "方法 · ",
    "en": "Method · "
  },
  "ui_091": {
    "zh": "拒绝",
    "en": "Deny"
  },
  "ui_092": {
    "zh": "批准本次",
    "en": "Approve once"
  },
  "ui_093": {
    "zh": "已批准本次执行",
    "en": "This execution was approved"
  },
  "ui_094": {
    "zh": "已拒绝本次执行",
    "en": "This execution was denied"
  },
  "ui_095": {
    "zh": "审批已随任务结束",
    "en": "Approval closed with task"
  },
  "ui_096": {
    "zh": "调用工具",
    "en": "Call tool"
  },
  "ui_097": {
    "zh": "执行工具",
    "en": "Run tool"
  },
  "ui_098": {
    "zh": "；展开或收起完整执行详情",
    "en": "; expand or collapse full execution details"
  },
  "ui_099": {
    "zh": " · 状态 · ",
    "en": " · Status · "
  },
  "ui_100": {
    "zh": "标准输出 stdout",
    "en": "Standard output · stdout"
  },
  "ui_101": {
    "zh": "错误输出 stderr",
    "en": "Error output · stderr"
  },
  "ui_102": {
    "zh": "（无输出）",
    "en": "(No output)"
  },
  "ui_103": {
    "zh": "输出已达到保留上限，仅展示执行器返回的内容。",
    "en": "Output reached the capture limit. Only data returned by the executor is shown."
  },
  "ui_104": {
    "zh": "退出码 · ",
    "en": "Exit code · "
  },
  "ui_105": {
    "zh": "未提供",
    "en": "Not provided"
  },
  "ui_106": {
    "zh": "待返回",
    "en": "Pending"
  },
  "ui_107": {
    "zh": "耗时 · ",
    "en": "Duration · "
  },
  "ui_108": {
    "zh": " 秒",
    "en": " s"
  },
  "ui_109": {
    "zh": "执行后返回",
    "en": "Available after execution"
  },
  "ui_110": {
    "zh": "任务进行中",
    "en": "Task running"
  },
  "ui_111": {
    "zh": "完全权限",
    "en": "Full access"
  },
  "ui_112": {
    "zh": "审查模式",
    "en": "Review mode"
  },
  "ui_113": {
    "zh": " · 切换对话后仍继续运行",
    "en": " · Keeps running when you switch conversations"
  },
  "ui_114": {
    "zh": "已开启",
    "en": "On"
  },
  "ui_115": {
    "zh": "未开启",
    "en": "Off"
  },
  "ui_116": {
    "zh": "新任务免逐次确认 · 仍受系统权限约束",
    "en": "No per-command approval for new tasks · System permissions still apply"
  },
  "ui_117": {
    "zh": "审查模式 · 执行前确认命令",
    "en": "Review mode · Approve commands before execution"
  },
  "ui_118": {
    "zh": "请先保存并选择模型配置。",
    "en": "Save and select a model profile first."
  },
  "ui_119": {
    "zh": "当前模型不支持图片，请切换模型或移除图片。",
    "en": "This model does not support images. Switch models or remove images."
  },
  "ui_120": {
    "zh": "服务未返回任务标识。",
    "en": "The service did not return a task ID."
  },
  "ui_121": {
    "zh": "附件任务",
    "en": "Attachment task"
  },
  "ui_122": {
    "zh": "任务事件数据损坏，正在尝试恢复。",
    "en": "Task event data is invalid. Attempting recovery."
  },
  "ui_123": {
    "zh": "事件历史已重置，正在从服务恢复任务。",
    "en": "Event history reset. Restoring the task from the service."
  },
  "ui_124": {
    "zh": "历史执行详情加载失败：",
    "en": "Could not load execution history: "
  },
  "ui_125": {
    "zh": "任务连接中断：",
    "en": "Task connection interrupted: "
  },
  "ui_126": {
    "zh": "连接中断，正在续传任务…",
    "en": "Disconnected. Reconnecting to task…"
  },
  "ui_127": {
    "zh": "已发送停止请求，正在等待执行器退出。",
    "en": "Stop requested. Waiting for the executor to exit."
  },
  "ui_128": {
    "zh": "Android · 本地桥梁服务",
    "en": "Android · Local bridge service"
  },
  "ui_129": {
    "zh": "桌面预览 · 本地桥梁服务",
    "en": "Desktop preview · Local bridge service"
  },
  "ui_130": {
    "zh": "当前版本 ",
    "en": "Version "
  },
  "ui_131": {
    "zh": "Web v1.0 · 服务 ",
    "en": "Web · Service "
  },
  "ui_132": {
    "zh": "已授权",
    "en": "Authorized"
  },
  "ui_133": {
    "zh": "待授权",
    "en": "Authorization required"
  },
  "ui_134": {
    "zh": "桌面预览",
    "en": "Desktop preview"
  },
  "ui_135": {
    "zh": "未连接 / 未授权",
    "en": "Disconnected / Not authorized"
  },
  "ui_136": {
    "zh": "命令超时必须为 1～3600 秒的整数。",
    "en": "Command timeout must be an integer from 1 to 3600 seconds."
  },
  "ui_137": {
    "zh": "请输入有效的更新清单地址。",
    "en": "Enter a valid update manifest URL."
  },
  "ui_138": {
    "zh": "设置已保存",
    "en": "Settings saved"
  },
  "ui_139": {
    "zh": " · 正在重试…",
    "en": " · Retrying…"
  },
  "ui_140": {
    "zh": "运行环境部署失败",
    "en": "Runtime deployment failed"
  },
  "ui_141": {
    "zh": "正在部署内嵌运行环境… ",
    "en": "Deploying embedded runtime… "
  },
  "ui_142": {
    "zh": " · 已就绪",
    "en": " · Ready"
  },
  "ui_143": {
    "zh": "当前环境不支持内嵌 Termux",
    "en": "Embedded Termux is not supported here"
  },
  "ui_144": {
    "zh": "运行环境尚未部署",
    "en": "Runtime is not deployed"
  },
  "ui_145": {
    "zh": "检查 / 重新部署",
    "en": "Check / Redeploy"
  },
  "ui_146": {
    "zh": "一键部署",
    "en": "Deploy runtime"
  },
  "ui_147": {
    "zh": "当前任务唤醒锁已启用。完成任务后请按需关闭。",
    "en": "Task wake lock is enabled. Turn it off when no longer needed."
  },
  "ui_148": {
    "zh": "当前唤醒锁未启用。仅在你明确开启后申请。",
    "en": "Wake lock is off. It is requested only when you explicitly enable it."
  },
  "ui_149": {
    "zh": "后台与电池策略由系统控制，点击下方按钮查看或申请。",
    "en": "The system controls background and battery policies. Use the buttons below to view or request access."
  },
  "ui_150": {
    "zh": "检查项目",
    "en": "Check"
  },
  "ui_151": {
    "zh": "自检已返回，但未提供检查项目。",
    "en": "Self-test returned no check items."
  },
  "ui_152": {
    "zh": "取消",
    "en": "Cancel"
  },
  "ui_153": {
    "zh": "确认继续",
    "en": "Confirm and continue"
  },
  "ui_154": {
    "zh": "系统操作请求失败",
    "en": "System request failed"
  },
  "ui_155": {
    "zh": "已向系统提交请求，请检查设备实际状态。",
    "en": "Request sent to the system. Check the device for the actual result."
  },
  "ui_156": {
    "zh": "打开系统电池优化设置？",
    "en": "Open battery optimization settings?"
  },
  "ui_157": {
    "zh": "将在系统设置中显示本应用的电池策略。是否忽略优化由你在系统中确认，可能增加耗电。",
    "en": "System settings will show this app's battery policy. You decide whether to exempt it from optimization, which may increase battery use."
  },
  "ui_158": {
    "zh": "启用任务唤醒锁？",
    "en": "Enable task wake lock?"
  },
  "ui_159": {
    "zh": "后台任务可能持续占用 CPU / 网络并增加耗电。仅在你明确同意后向系统申请，不保证系统不会终止应用。",
    "en": "Background tasks may keep the CPU and network active and use more battery. Access is requested only with your consent; the system may still terminate the app."
  },
  "ui_160": {
    "zh": "关闭任务唤醒锁？",
    "en": "Disable task wake lock?"
  },
  "ui_161": {
    "zh": "关闭后，系统可能暂停后台执行中的任务。",
    "en": "The system may pause background tasks after you disable it."
  },
  "ui_162": {
    "zh": "配置文件不得超过 256 KB。",
    "en": "Configuration files must be 256 KB or smaller."
  },
  "ui_163": {
    "zh": "导入并覆盖应用配置？",
    "en": "Import and replace app configuration?"
  },
  "ui_164": {
    "zh": "将更新模型地址、命令黑名单和默认执行参数。不会导入密钥、数据发送授权或完全权限；不会中断当前任务。",
    "en": "This updates model URLs, the command blacklist and execution defaults. Keys, data-sharing consent and full access are not imported. Running tasks are not interrupted."
  },
  "ui_165": {
    "zh": "配置已导入",
    "en": "Configuration imported"
  },
  "ui_166": {
    "zh": " 字节",
    "en": " bytes"
  },
  "ui_167": {
    "zh": "恢复",
    "en": "Restore"
  },
  "ui_168": {
    "zh": "恢复文件备份？",
    "en": "Restore file backup?"
  },
  "ui_169": {
    "zh": "将用此备份覆盖「",
    "en": "This backup will replace “"
  },
  "ui_170": {
    "zh": "」。请确保当前没有任务修改该文件，此操作只恢复已选择的文件。",
    "en": "”. Make sure no task is modifying it. Only the selected file will be restored."
  },
  "ui_171": {
    "zh": "恢复失败",
    "en": "Restore failed"
  },
  "ui_172": {
    "zh": "备份已恢复",
    "en": "Backup restored"
  },
  "ui_173": {
    "zh": "当前没有可恢复的文件备份。",
    "en": "No file backups are available."
  },
  "ui_174": {
    "zh": "请输入对话标题。",
    "en": "Enter a conversation title."
  },
  "ui_175": {
    "zh": "无法打开权限通道选择。",
    "en": "Could not open permission channel selection."
  },
  "ui_176": {
    "zh": "已请求重新选择权限通道",
    "en": "Permission channel selection requested"
  },
  "ui_177": {
    "zh": "清除当前模型的已保存密钥？",
    "en": "Clear the saved key for this model?"
  },
  "ui_178": {
    "zh": "只会清除「",
    "en": "Only the key for “"
  },
  "ui_179": {
    "zh": "当前模型",
    "en": "Current model"
  },
  "ui_180": {
    "zh": "」的密钥，保存设置后生效。需要密钥的服务将要求重新填写。",
    "en": "” will be cleared when you save. Services requiring a key will need a new one."
  },
  "ui_181": {
    "zh": "隐藏 API 密钥",
    "en": "Hide API key"
  },
  "ui_182": {
    "zh": "请先明确同意向配置的模型服务发送数据。",
    "en": "First consent to sending data to your configured model service."
  },
  "ui_183": {
    "zh": "正在测试连接…",
    "en": "Testing connection…"
  },
  "ui_184": {
    "zh": "模型连接失败",
    "en": "Model connection failed"
  },
  "ui_185": {
    "zh": "模型连接成功",
    "en": "Model connected"
  },
  "ui_186": {
    "zh": "部署请求失败",
    "en": "Deployment request failed"
  },
  "ui_187": {
    "zh": "终端无法打开",
    "en": "Could not open terminal"
  },
  "ui_188": {
    "zh": "已请求打开内嵌终端",
    "en": "Embedded terminal requested"
  },
  "ui_189": {
    "zh": "申请失败",
    "en": "Request failed"
  },
  "ui_190": {
    "zh": "请在系统授权窗口中确认，随后刷新状态。",
    "en": "Confirm in the system authorization dialog, then refresh status."
  },
  "ui_191": {
    "zh": "通道切换任务已提交，请在当前对话确认。",
    "en": "Channel switch task submitted. Confirm it in the current conversation."
  },
  "ui_192": {
    "zh": "通道切换失败",
    "en": "Channel switch failed"
  },
  "ui_193": {
    "zh": "权限通道已更新",
    "en": "Permission channel updated"
  },
  "ui_194": {
    "zh": "自检已完成",
    "en": "Self-test completed"
  },
  "ui_195": {
    "zh": "规则文件不得超过 128 KB。",
    "en": "Rule files must be 128 KB or smaller."
  },
  "ui_196": {
    "zh": "JSON 应为字符串数组或包含 blacklist 数组。",
    "en": "JSON must be a string array or an object with a blacklist array."
  },
  "ui_197": {
    "zh": "已导入规则，保存设置后生效。",
    "en": "Rules imported. Save settings to apply."
  },
  "ui_198": {
    "zh": "诊断日志已导出",
    "en": "Diagnostic log exported"
  },
  "ui_199": {
    "zh": "更新检查失败",
    "en": "Update check failed"
  },
  "ui_200": {
    "zh": "请先填写可信的 HTTPS 更新清单地址。",
    "en": "Enter a trusted HTTPS update manifest URL first."
  },
  "ui_201": {
    "zh": "发现新版本 ",
    "en": "New version available: "
  },
  "ui_202": {
    "zh": "当前已是最新版本",
    "en": "You are up to date"
  },
  "ui_203": {
    "zh": "查看下载地址",
    "en": "View download"
  },
  "ui_204": {
    "zh": "请从应用打开带有运行令牌的授权页面。",
    "en": "Open this authorized page from the app."
  },
  "ui_205": {
    "zh": "缺少运行令牌，请从应用重新打开页面。",
    "en": "Session token missing. Reopen this page from the app."
  },
  "static_206": {
    "zh": "打开侧边栏",
    "en": "Open sidebar"
  },
  "static_207": {
    "zh": "正在连接本地服务",
    "en": "Connecting to local service"
  },
  "static_208": {
    "zh": "刷新状态",
    "en": "Refresh status"
  },
  "static_209": {
    "zh": "新建对话",
    "en": "New conversation"
  },
  "static_210": {
    "zh": "重试连接",
    "en": "Reconnect"
  },
  "static_211": {
    "zh": "执行记录默认收起。聚焦记录后按回车或空格展开完整详情。待确认的命令与执行环境始终显示。",
    "en": "Execution records start collapsed. Press Enter or Space to view full details. Pending approval commands and execution context stay visible."
  },
  "static_212": {
    "zh": "对话内容",
    "en": "Conversation content"
  },
  "static_213": {
    "zh": "输入任务",
    "en": "Enter a task"
  },
  "static_214": {
    "zh": "描述任务，让 AI 帮你完成…",
    "en": "Describe a task for AI to help with…"
  },
  "static_215": {
    "zh": "▤ 添加文件",
    "en": "▤ Add files"
  },
  "static_216": {
    "zh": "▧ 添加图片",
    "en": "▧ Add images"
  },
  "static_217": {
    "zh": "本地服务连接中",
    "en": "Connecting to local service"
  },
  "static_218": {
    "zh": "添加文件或图片",
    "en": "Add files or images"
  },
  "static_219": {
    "zh": "选择模型",
    "en": "Choose model"
  },
  "static_220": {
    "zh": "选择推理级别",
    "en": "Choose reasoning level"
  },
  "static_221": {
    "zh": "低推理",
    "en": "Low"
  },
  "static_222": {
    "zh": "中推理",
    "en": "Medium"
  },
  "static_223": {
    "zh": "高推理",
    "en": "High"
  },
  "static_224": {
    "zh": "停止当前任务",
    "en": "Stop current task"
  },
  "static_225": {
    "zh": "停止",
    "en": "Stop"
  },
  "static_226": {
    "zh": "发送任务",
    "en": "Send task"
  },
  "static_227": {
    "zh": "← 返回对话",
    "en": "← Back to conversation"
  },
  "static_228": {
    "zh": "连接你的模型，掌控设备与运行环境。",
    "en": "Connect your models. Manage your device and runtime."
  },
  "static_229": {
    "zh": "保存设置",
    "en": "Save settings"
  },
  "static_230": {
    "zh": "设置分类",
    "en": "Settings categories"
  },
  "static_231": {
    "zh": "模型",
    "en": "Models"
  },
  "static_232": {
    "zh": "主题",
    "en": "Appearance"
  },
  "static_233": {
    "zh": "运行环境",
    "en": "Runtime"
  },
  "static_234": {
    "zh": "权限",
    "en": "Permissions"
  },
  "static_235": {
    "zh": "命令安全",
    "en": "Command safety"
  },
  "static_236": {
    "zh": "执行与后台",
    "en": "Execution & background"
  },
  "static_237": {
    "zh": "诊断",
    "en": "Diagnostics"
  },
  "static_238": {
    "zh": "备份",
    "en": "Backups"
  },
  "static_239": {
    "zh": "更新",
    "en": "Updates"
  },
  "static_240": {
    "zh": "关于",
    "en": "About"
  },
  "static_241": {
    "zh": "外观与主题",
    "en": "Appearance & theme"
  },
  "static_242": {
    "zh": "选择后即时预览，保存后应用到下次启动。",
    "en": "Preview changes instantly. Save to keep them for next time."
  },
  "static_243": {
    "zh": "跟随系统",
    "en": "System"
  },
  "static_244": {
    "zh": "浅色",
    "en": "Light"
  },
  "static_245": {
    "zh": "深色",
    "en": "Dark"
  },
  "static_246": {
    "zh": "字号",
    "en": "Font size"
  },
  "static_247": {
    "zh": "小小号",
    "en": "Extra small"
  },
  "static_248": {
    "zh": "小号",
    "en": "Small"
  },
  "static_249": {
    "zh": "中号",
    "en": "Medium"
  },
  "static_250": {
    "zh": "大号",
    "en": "Large"
  },
  "static_251": {
    "zh": "大大号",
    "en": "Extra large"
  },
  "static_252": {
    "zh": "界面语言",
    "en": "Interface language"
  },
  "static_253": {
    "zh": "简体中文",
    "en": "简体中文"
  },
  "static_254": {
    "zh": "仅改变界面显示，不改变对话、模型语言或推理指令。",
    "en": "Changes the interface only. Conversation content and model language or reasoning instructions stay the same."
  },
  "static_255": {
    "zh": "恢复外观默认值",
    "en": "Reset appearance"
  },
  "static_256": {
    "zh": "取消外观预览",
    "en": "Cancel preview"
  },
  "static_257": {
    "zh": "保存外观",
    "en": "Save appearance"
  },
  "static_258": {
    "zh": "模型服务",
    "en": "Model service"
  },
  "static_259": {
    "zh": "按用途管理多个模型，分别配置上下文、输出、推理和图片能力。",
    "en": "Manage model profiles with their own context, output, reasoning and image capabilities."
  },
  "static_260": {
    "zh": "模型配置",
    "en": "Model profiles"
  },
  "static_261": {
    "zh": "＋ 添加模型",
    "en": "＋ Add model"
  },
  "static_262": {
    "zh": "模型配置列表",
    "en": "Model profile list"
  },
  "static_263": {
    "zh": "删除",
    "en": "Delete"
  },
  "static_264": {
    "zh": "服务地址",
    "en": "Service URL"
  },
  "static_265": {
    "zh": "模型名称",
    "en": "Model name"
  },
  "static_266": {
    "zh": "例如 qwen3",
    "en": "For example, qwen3"
  },
  "static_267": {
    "zh": "上下文窗口",
    "en": "Context window"
  },
  "static_268": {
    "zh": "最大输出 tokens",
    "en": "Maximum output tokens"
  },
  "static_269": {
    "zh": "能力",
    "en": "Capabilities"
  },
  "static_270": {
    "zh": "支持推理",
    "en": "Reasoning support"
  },
  "static_271": {
    "zh": "允许在对话中选择推理级别",
    "en": "Choose reasoning levels in conversations"
  },
  "static_272": {
    "zh": "支持图片",
    "en": "Image support"
  },
  "static_273": {
    "zh": "允许发送图片附件",
    "en": "Allow image attachments"
  },
  "static_274": {
    "zh": "默认推理级别",
    "en": "Default reasoning level"
  },
  "static_275": {
    "zh": "低",
    "en": "Low"
  },
  "static_276": {
    "zh": "中",
    "en": "Medium"
  },
  "static_277": {
    "zh": "高",
    "en": "High"
  },
  "static_278": {
    "zh": "API 密钥",
    "en": "API key"
  },
  "static_279": {
    "zh": "留空保留现有密钥；本地服务可不填写",
    "en": "Leave blank to keep the saved key; local services may not need one"
  },
  "static_280": {
    "zh": "密钥只在保存请求中短暂使用，不写入浏览器存储或启动数据。",
    "en": "Keys are used briefly in save requests, never stored in browser storage or bootstrap data."
  },
  "static_281": {
    "zh": "测试当前模型",
    "en": "Test this model"
  },
  "static_282": {
    "zh": "清除已保存密钥",
    "en": "Clear saved key"
  },
  "static_283": {
    "zh": "允许向配置的模型服务发送数据",
    "en": "Allow data to be sent to configured model services"
  },
  "static_284": {
    "zh": "将发送对话、任务上下文及命令结果。云端服务由其隐私政策约束；本应用不附加遥测。",
    "en": "Conversations, task context and command results will be sent. Cloud services follow their own privacy policies. This app adds no telemetry."
  },
  "static_285": {
    "zh": "启用模型服务",
    "en": "Enable model service"
  },
  "static_286": {
    "zh": "保存后服务端只返回脱敏配置；密钥输入框会清空，留空表示保留已有密钥。",
    "en": "The server returns redacted settings after saving. Key fields are cleared; leaving them blank keeps existing keys."
  },
  "static_287": {
    "zh": "内嵌 Termux 运行环境",
    "en": "Embedded Termux runtime"
  },
  "static_288": {
    "zh": "在 APK 内部署和使用，不跳转外部终端。",
    "en": "Deploy and use it inside this app without opening an external terminal."
  },
  "static_289": {
    "zh": "正在获取环境状态…",
    "en": "Loading runtime status…"
  },
  "static_290": {
    "zh": "运行环境部署进度",
    "en": "Runtime deployment progress"
  },
  "static_291": {
    "zh": "打开内嵌终端",
    "en": "Open embedded terminal"
  },
  "static_292": {
    "zh": "刷新运行环境",
    "en": "Refresh runtime"
  },
  "static_293": {
    "zh": "若当前构建使用 Termux 官方包名，可能与已安装的 Termux 冲突。请先备份个人环境；程序不会自动卸载已有应用。",
    "en": "This build may conflict with an existing Termux installation if it uses the same package name. Back up your environment first. The app never uninstalls existing apps automatically."
  },
  "static_294": {
    "zh": "设备权限通道",
    "en": "Device permission channels"
  },
  "static_295": {
    "zh": "完全权限模式不会授予 Root 或绕过系统限制。",
    "en": "Full access does not grant Root or bypass system restrictions."
  },
  "static_296": {
    "zh": "普通应用权限",
    "en": "Normal app permissions"
  },
  "static_297": {
    "zh": "检测中",
    "en": "Checking"
  },
  "static_298": {
    "zh": "当前运行通道",
    "en": "Current execution channel"
  },
  "static_299": {
    "zh": "重新选择权限通道",
    "en": "Choose permission channel again"
  },
  "static_300": {
    "zh": "申请 Shizuku 授权",
    "en": "Request Shizuku authorization"
  },
  "static_301": {
    "zh": "应用通道",
    "en": "Apply channel"
  },
  "static_302": {
    "zh": "Shizuku 需已启动服务；Root 需设备已解锁并在系统授权窗口中许可。",
    "en": "Shizuku must already be running. Root requires an unlocked device and approval in the system authorization dialog."
  },
  "static_303": {
    "zh": "命令黑名单",
    "en": "Command blacklist"
  },
  "static_304": {
    "zh": "每行一条规则：普通文本为区分大小写的子串匹配；glob: 前缀为整条命令的通配匹配。完全权限模式也遵守黑名单。",
    "en": "One rule per line. Plain text matches a case-sensitive substring; the glob: prefix matches the whole command with wildcards. The blacklist also applies in full access mode."
  },
  "static_305": {
    "zh": "命令黑名单规则",
    "en": "Command blacklist rules"
  },
  "static_306": {
    "zh": "每行输入一条需要禁止的命令或匹配规则",
    "en": "Enter one blocked command or matching rule per line"
  },
  "static_307": {
    "zh": "导入规则",
    "en": "Import rules"
  },
  "static_308": {
    "zh": "导出规则",
    "en": "Export rules"
  },
  "static_309": {
    "zh": "任务超时与设备后台策略。",
    "en": "Task timeouts and device background policies."
  },
  "static_310": {
    "zh": "默认命令超时（秒）",
    "en": "Default command timeout (seconds)"
  },
  "static_311": {
    "zh": "默认运行时",
    "en": "Default runtime"
  },
  "static_312": {
    "zh": "Android 系统 Shell",
    "en": "Android system shell"
  },
  "static_313": {
    "zh": "内嵌 Termux",
    "en": "Embedded Termux"
  },
  "static_314": {
    "zh": "后台与电池策略由系统控制，不默认申请唤醒权限。",
    "en": "The system controls background and battery policies. Wake access is not requested by default."
  },
  "static_315": {
    "zh": "电池优化设置",
    "en": "Battery optimization settings"
  },
  "static_316": {
    "zh": "启用任务唤醒锁",
    "en": "Enable task wake lock"
  },
  "static_317": {
    "zh": "关闭唤醒锁",
    "en": "Disable wake lock"
  },
  "static_318": {
    "zh": "开启唤醒锁可能增加耗电。系统授权与前台服务状态以设备实际结果为准。",
    "en": "A wake lock may increase battery use. Check actual system authorization and foreground service status on the device."
  },
  "static_319": {
    "zh": "诊断与日志",
    "en": "Diagnostics & logs"
  },
  "static_320": {
    "zh": "本地检查环境、服务与权限状态。",
    "en": "Check environment, service and permission status locally."
  },
  "static_321": {
    "zh": "点击自检查看设备状态与修复建议。",
    "en": "Run self-test for device status and repair suggestions."
  },
  "static_322": {
    "zh": "运行自检",
    "en": "Run self-test"
  },
  "static_323": {
    "zh": "导出诊断日志",
    "en": "Export diagnostic log"
  },
  "static_324": {
    "zh": "导出前请检查内容，日志可能包含设备信息和命令参数。",
    "en": "Review the log before sharing it. It may contain device information and command arguments."
  },
  "static_325": {
    "zh": "配置与文件备份",
    "en": "Configuration & file backups"
  },
  "static_326": {
    "zh": "配置导出不含密钥、令牌或完全权限。导入前会要求确认。",
    "en": "Configuration exports exclude keys, tokens and full access. Importing requires confirmation."
  },
  "static_327": {
    "zh": "导出配置",
    "en": "Export configuration"
  },
  "static_328": {
    "zh": "导入配置",
    "en": "Import configuration"
  },
  "static_329": {
    "zh": "查看文件备份",
    "en": "View file backups"
  },
  "static_330": {
    "zh": "恢复备份会覆盖对应文件；请先停止会修改目标文件的任务。",
    "en": "Restoring a backup replaces its target file. Stop any task that might modify it first."
  },
  "static_331": {
    "zh": "版本更新",
    "en": "Version updates"
  },
  "static_332": {
    "zh": "当前版本 —",
    "en": "Version —"
  },
  "static_333": {
    "zh": "更新清单地址",
    "en": "Update manifest URL"
  },
  "static_334": {
    "zh": "仅在你点击检查时访问该地址，不自动安装、不打断正在运行的任务。",
    "en": "This URL is accessed only when you check for updates. Nothing is installed automatically and running tasks are not interrupted."
  },
  "static_335": {
    "zh": "检查更新",
    "en": "Check for updates"
  },
  "static_336": {
    "zh": "关于云琥",
    "en": "About Yunhu"
  },
  "static_337": {
    "zh": "让 AI 与你的设备协同工作。",
    "en": "Let AI work with your device."
  },
  "static_338": {
    "zh": "支持任意命令的后端执行器，不以工具开关限制 AI。实际能力取决于设备、所选通道、系统授权和可用运行时。",
    "en": "The backend executor supports arbitrary commands. Actual capabilities depend on your device, selected channel, system authorization and available runtimes."
  },
  "static_339": {
    "zh": "隐私与数据",
    "en": "Privacy & data"
  },
  "static_340": {
    "zh": "会话与执行记录保存在本机。页面只连接本地桥梁；模型请求由桥梁发送至你配置且同意的服务。远程模型可能收到任务上下文、命令及其输出。API 密钥不写入浏览器持久存储；会话恢复缓存仅保留在当前标签页会话中。",
    "en": "Conversations and execution records stay on this device. This page connects only to the local bridge, which sends model requests to services you configure and consent to. Remote models may receive task context, commands and output. API keys are never stored in browser persistent storage; recovery cache lasts only for this tab session."
  },
  "static_341": {
    "zh": "关闭标签页后，完全权限的风险确认失效。请勿在非本人设备或未经授权的目标上执行自动化。",
    "en": "Closing the tab invalidates full access risk consent. Use automation only on devices and targets you are authorized to manage."
  },
  "static_342": {
    "zh": "开源许可与组件",
    "en": "Open source licenses & components"
  },
  "static_343": {
    "zh": "前端未使用外部 CDN 或第三方 Markdown 依赖，安全 Markdown 渲染器随应用本地加载。Termux、Python、Chaquopy、Shizuku 及其他内嵌组件的完整版权、许可证及源代码信息见安装包内第三方许可清单。",
    "en": "The interface uses no external CDN or third-party Markdown dependencies. Its safe Markdown renderer loads locally. Full copyrights, licenses and source information for Termux, Python, Chaquopy, Shizuku and other bundled components are in the app's third-party license list."
  },
  "static_344": {
    "zh": "Termux：GPLv3；Python：PSF License；Shizuku API：MIT。安装包随附第三方版权与许可证文件。",
    "en": "Termux: GPLv3; Python: PSF License; Shizuku API: MIT. Third-party copyright and license files are included in the app."
  },
  "static_345": {
    "zh": "你的设备，你来掌控",
    "en": "Your device. Your control."
  },
  "static_346": {
    "zh": "关闭侧边栏",
    "en": "Close sidebar"
  },
  "static_347": {
    "zh": "＋ 新建对话",
    "en": "＋ New conversation"
  },
  "static_348": {
    "zh": "搜索对话",
    "en": "Search conversations"
  },
  "static_349": {
    "zh": "最近对话",
    "en": "Recent conversations"
  },
  "static_350": {
    "zh": "仅连接本地桥梁服务",
    "en": "Local bridge connection only"
  },
  "static_351": {
    "zh": "欢迎使用",
    "en": "Welcome"
  },
  "static_352": {
    "zh": "开始前，请了解执行边界",
    "en": "Understand execution limits before you start"
  },
  "static_353": {
    "zh": "AI 可以通过后端执行器提出任意系统命令，可能造成数据丢失、设备异常或隐私泄露。默认采用审查模式，执行前向你展示准确命令。",
    "en": "AI can propose arbitrary system commands through the backend executor. They may cause data loss, device problems or privacy exposure. Review mode is the default and shows exact commands before execution."
  },
  "static_354": {
    "zh": "Root / Shizuku 必须由系统实际授权。完全权限模式仅跳过本应用的逐次人工审查，不会突破 Android、SELinux、黑名单或超时限制。模型数据只发往你配置并同意的服务。",
    "en": "Root and Shizuku require actual system authorization. Full access only skips this app's per-command review. Android, SELinux, blacklist and timeout restrictions still apply. Model data goes only to services you configure and consent to."
  },
  "static_355": {
    "zh": "请先备份重要数据，仅用于合法且获得授权的任务。",
    "en": "Back up important data first. Use this app only for lawful, authorized tasks."
  },
  "static_356": {
    "zh": "我已阅读并理解上述说明",
    "en": "I have read and understood this information"
  },
  "static_357": {
    "zh": "确认并继续",
    "en": "Confirm and continue"
  },
  "static_358": {
    "zh": "本标签页首次开启 · 高风险",
    "en": "First use in this tab · High risk"
  },
  "static_359": {
    "zh": "将命令审查交给 AI？",
    "en": "Let AI execute without per-command review?"
  },
  "static_360": {
    "zh": "AI 可能修改或删除文件、读取敏感数据、影响系统设置，且操作可能无法撤销。",
    "en": "AI may change or delete files, read sensitive data or affect system settings. These actions may be irreversible."
  },
  "static_361": {
    "zh": "完全权限开启后，新提交任务中的命令将不再逐条征求你的批准。",
    "en": "After full access is enabled, commands in new tasks will no longer ask for approval individually."
  },
  "static_362": {
    "zh": "仅影响提交时标记为完全权限的任务，执行中的任务模式不变。选择只在当前标签页会话内保存，不等于授予 Root，也不能绕过操作系统、黑名单、认证或超时。",
    "en": "Only tasks submitted with full access are affected. Running tasks keep their mode. The choice lasts only in this tab session, does not grant Root and cannot bypass the OS, blacklist, authentication or timeout."
  },
  "static_363": {
    "zh": "我理解风险，并明确允许本会话的新任务免逐次审查",
    "en": "I understand the risk and explicitly allow new tasks in this session to run without per-command review"
  },
  "static_364": {
    "zh": "保留审查模式",
    "en": "Keep review mode"
  },
  "static_365": {
    "zh": "确认开启完全权限",
    "en": "Enable full access"
  },
  "static_366": {
    "zh": "重命名对话",
    "en": "Rename conversation"
  },
  "static_367": {
    "zh": "对话标题",
    "en": "Conversation title"
  },
  "static_368": {
    "zh": "保存标题",
    "en": "Save title"
  },
  "static_369": {
    "zh": "删除这段对话？",
    "en": "Delete this conversation?"
  },
  "static_370": {
    "zh": "删除后无法恢复。运行中的任务不会因离开列表而中止。",
    "en": "Deletion is permanent. Leaving the list does not stop running tasks."
  },
  "static_371": {
    "zh": "保留对话",
    "en": "Keep conversation"
  },
  "static_372": {
    "zh": "删除对话",
    "en": "Delete conversation"
  },
  "server_001": {
    "zh": "模型连接成功；未执行任何命令。",
    "en": "Model connected. No commands were executed."
  },
  "server_002": {
    "zh": "Python版本",
    "en": "Python version"
  },
  "server_003": {
    "zh": "Workspace目录",
    "en": "Workspace directory"
  },
  "server_004": {
    "zh": "SQLite存储",
    "en": "SQLite storage"
  },
  "server_005": {
    "zh": "回环绑定",
    "en": "Loopback binding"
  },
  "server_006": {
    "zh": "本地持久化对话与任务",
    "en": "Conversations and tasks are stored locally"
  },
  "server_007": {
    "zh": "只监听127.0.0.1；严格Bearer/Host/Origin",
    "en": "Listens only on 127.0.0.1; strict Bearer, Host and Origin checks"
  },
  "server_008": {
    "zh": "模型发送需明确同意",
    "en": "Sending data to models requires explicit consent"
  },
  "server_009": {
    "zh": "Android权限桥接",
    "en": "Android permission bridge"
  },
  "server_010": {
    "zh": "已集成",
    "en": "Integrated"
  },
  "server_011": {
    "zh": "桌面预览不执行命令",
    "en": "Desktop preview does not execute commands"
  },
  "server_012": {
    "zh": "此能力仅在Android APK内可用。",
    "en": "This capability is available only inside the Android app."
  },
  "server_013": {
    "zh": "尚未获取设备状态。",
    "en": "Device status has not been loaded yet."
  },
  "server_014": {
    "zh": "尚未配置更新清单地址。",
    "en": "No update manifest URL configured."
  },
  "server_015": {
    "zh": "请在设置中填写发布者的HTTPS更新清单地址。",
    "en": "Enter the publisher’s HTTPS update manifest URL in settings."
  },
  "server_016": {
    "zh": "当前运行环境没有Android原生桥接；不会在开发机执行Android命令。",
    "en": "No native Android bridge is available. Android commands are never executed on this computer."
  },
  "server_017": {
    "zh": "此操作只能在Android APK中运行；未执行开发机命令。",
    "en": "This operation is available only in the Android app. No command was executed on this computer."
  },
  "server_018": {
    "zh": "命令超时必须为1～3600秒的整数。",
    "en": "Command timeout must be an integer from 1 to 3600 seconds."
  },
  "server_019": {
    "zh": "请先同意风险说明。",
    "en": "Accept the risk notice first."
  },
  "server_020": {
    "zh": "对话不存在。",
    "en": "Conversation not found."
  },
  "server_021": {
    "zh": "任务不存在。",
    "en": "Task not found."
  },
  "server_022": {
    "zh": "请求体必须是JSON对象。",
    "en": "The request body must be a JSON object."
  },
  "server_023": {
    "zh": "只允许HTTP或HTTPS模型地址。",
    "en": "Model URLs must use HTTP or HTTPS."
  },
  "server_024": {
    "zh": "命令黑名单",
    "en": "Command blacklist"
  },
  "server_025": {
    "zh": "模型服务",
    "en": "Model service"
  },
  "server_026": {
    "zh": "Root权限",
    "en": "Root access"
  },
  "server_027": {
    "zh": "Shizuku权限",
    "en": "Shizuku access"
  },
  "server_028": {
    "zh": "权限通道已更新。",
    "en": "Permission channel updated."
  },
  "server_029": {
    "zh": "服务重启，未完成任务已停止。",
    "en": "The service restarted. Unfinished tasks were stopped."
  }
};
  Object.assign(catalog, {drawer_brand: {zh:"云琥Agent", en:"Yunhu Agent"}, code_label: {zh:"代码", en:"Code"}, copy: {zh:"复制", en:"Copy"}, copy_done: {zh:"已复制", en:"Copied"}, copy_failed: {zh:"复制失败", en:"Copy failed"}, share_transcript:{zh:"分享长图",en:"Share transcript"}, composer_model_group:{zh:"模型与推理快捷选择",en:"Model and reasoning shortcuts"}, composer_model_summary:{zh:"先选模型，再选择推理级别；推理选择仅在当前模型支持时启用。",en:"Choose a model, then a reasoning level. Reasoning is available only when supported by the selected model."}, local_models_title:{zh:"本地模型下载",en:"Local model downloads"}, local_models_note:{zh:"下载 GGUF 模型到本机。模型文件较大，请确认可用存储空间及网络流量。首次安装 llama.cpp 需要联网并下载软件包，请在确认前检查网络流量与存储空间。",en:"Download GGUF models to this device. Model files are large; check free storage and data use. The first llama.cpp install needs an internet connection and package download; confirm available data and storage before continuing."}, local_refresh:{zh:"刷新状态",en:"Refresh status"}, local_engine_log:{zh:"查看引擎日志",en:"View engine log"},
    local_engine_log_title:{zh:"本地引擎日志",en:"Local engine log"},
    local_engine_log_hint:{zh:"最近一次 llama-server 的输出（最多保留 4 MiB），启动失败时先看这里。",en:"Output from the most recent llama-server run (up to 4 MiB retained); check here first when a start fails."},
    local_engine_log_empty:{zh:"暂无日志：本地引擎还没有启动过。",en:"No log yet: the local engine has not been started."},
    local_install_engine:{zh:"安装 llama.cpp",en:"Install llama.cpp"}, local_install_confirm_title:{zh:"安装 llama.cpp？",en:"Install llama.cpp?"}, local_install_confirm_body:{zh:"此操作会联网下载并安装本地推理软件包，可能消耗流量和存储空间。请确认网络可用且有足够空间后再继续。",en:"This downloads and installs the local inference package over the internet and may use data and storage. Continue only if your network and free space are sufficient."}, local_engine_progress:{zh:"本地引擎安装进度",en:"Local engine installation progress"}, local_stop:{zh:"停止模型",en:"Stop model"}, local_download:{zh:"下载模型",en:"Download model"}, local_cancel:{zh:"取消下载",en:"Cancel download"}, local_delete:{zh:"删除模型",en:"Delete model"}, local_activate:{zh:"启动并激活",en:"Start and activate"}, local_install_activate:{zh:"安装引擎并启动",en:"Install engine and start"}, local_source_mirror:{zh:"镜像源",en:"Mirror"}, local_source_original:{zh:"官方源",en:"Official source"}, local_license:{zh:"许可证",en:"License"}, local_quant:{zh:"量化",en:"Quantization"}, local_download_progress:{zh:"下载进度",en:"Download progress"}, local_status_loading:{zh:"正在获取本地模型状态…",en:"Loading local model status…"}, local_status_empty:{zh:"暂无可用模型目录。",en:"No local models are available."}, local_download_ready:{zh:"已下载",en:"Downloaded"}, local_engine_installed:{zh:"llama.cpp 已安装",en:"llama.cpp installed"}, local_engine_missing:{zh:"尚未安装 llama.cpp",en:"llama.cpp is not installed"}, local_running:{zh:"本地模型正在运行",en:"Local model is running"}, local_confirm_delete:{zh:"删除本地模型？",en:"Delete local model?"}, local_confirm_delete_body:{zh:"删除后需要重新下载该模型文件。",en:"Deleting this model means you will need to download it again."}, local_installed_model:{zh:"已安装模型",en:"Installed model"}, local_api_error:{zh:"本地模型服务暂不可用。",en:"Local model service is unavailable."}, message_edit:{zh:"编辑",en:"Edit"}, message_delete:{zh:"删除",en:"Delete"}, message_edit_heading:{zh:"编辑用户消息",en:"Edit user message"}, message_edit_label:{zh:"修改内容",en:"Edit content"}, message_edit_save:{zh:"保存并填入",en:"Save and fill composer"}, message_delete_title:{zh:"删除最近一轮？",en:"Delete the latest turn?"}, message_delete_body:{zh:"此操作会删除最近一轮的用户消息和对应回复，且无法撤销。",en:"This permanently deletes the latest user message and its reply."}, message_resend:{zh:"重新发送",en:"Resend"}, message_edit_saved:{zh:"消息已更新到输入框，请确认后点击“重新发送”。",en:"Message is ready in the composer. Review it, then click Resend."}, message_deleted:{zh:"消息已删除。",en:"Message deleted."}, transcript_empty:{zh:"当前对话没有可分享的文本消息。",en:"There are no text messages to share."}, transcript_downloaded:{zh:"已下载可读对话 HTML。",en:"Readable transcript HTML downloaded."}, transcript_title:{zh:"对话记录",en:"Conversation transcript"}, transcript_attachment:{zh:"附件",en:"Attachment"}, transcript_attachment_unknown:{zh:"未命名附件",en:"Unnamed attachment"}, transcript_share_failed:{zh:"原生分享失败",en:"Native sharing failed"}, transcript_share_timeout:{zh:"原生分享超时",en:"Native sharing timed out"}, message_edit_attachments_forbidden:{zh:"含附件的消息不可编辑；可删除该轮。",en:"Messages with attachments cannot be edited. You can delete this turn instead."}, message_edit_draft_cleared:{zh:"编辑草稿属于其他对话，已清除。",en:"The edited draft belonged to another conversation and was cleared."}, local_cancel_requested:{zh:"正在取消…",en:"Cancellation requested…"}, local_job_queued:{zh:"排队中",en:"Queued"}, local_job_downloading:{zh:"下载中",en:"Downloading"}, local_job_verifying:{zh:"校验中",en:"Verifying"}, local_job_completed:{zh:"已完成",en:"Completed"}, local_job_failed:{zh:"失败",en:"Failed"}, local_job_cancelled:{zh:"已取消",en:"Cancelled"}, local_job_cancel_requested:{zh:"正在取消",en:"Cancellation requested"}, local_note_low_storage:{zh:"低存储 · 质量较低",en:"Low storage · lower quality"}, local_note_light_balanced:{zh:"轻量均衡",en:"Lightweight balance"}, local_note_beginner:{zh:"推荐入门",en:"Recommended for beginners"}, local_note_higher_quality:{zh:"较高质量",en:"Higher quality"}, local_note_medium_storage:{zh:"中等存储",en:"Moderate storage"}, local_note_good_balance:{zh:"较佳均衡",en:"Good balance"}});
  Object.assign(catalog, {
    runtime_packages_title:{zh:"Termux 包管理器",en:"Termux package manager"},
    runtime_packages_intro:{zh:"从此设备的 Termux 仓库查看并安装可用软件包。",en:"Browse and install packages available from this device’s Termux repositories."},
    local_context_label:{zh:"本地模型上下文（512–8192）",en:"Local model context (512–8192)"},
    local_threads_label:{zh:"CPU 线程数（1–16）",en:"CPU threads (1–16)"},
    local_acceleration_title:{zh:"硬件加速（仅本地模型）",en:"Hardware acceleration (local models only)"},
    local_cpu_acceleration:{zh:"CPU 硬件加速",en:"CPU acceleration"},
    local_cpu_acceleration_hint:{zh:"使用内置引擎的 CPU 优化路径并保留线程设置；默认关闭。",en:"Uses the bundled engine’s optimized CPU path with your thread count; off by default."},
    local_gpu_acceleration:{zh:"GPU 硬件加速",en:"GPU acceleration"},
    local_gpu_acceleration_hint:{zh:"仅当已安装引擎枚举到 GPU 后端时可开启；与 NPU 互斥。",en:"Only available when the installed engine enumerates a GPU backend; mutually exclusive with NPU."},
    local_npu_acceleration:{zh:"NPU 硬件加速",en:"NPU acceleration"},
    local_npu_acceleration_hint:{zh:"仅当已安装引擎枚举到 NPU 后端时可开启；与 GPU 互斥。",en:"Only available when the installed engine enumerates an NPU backend; mutually exclusive with GPU."},
    local_low_memory:{zh:"Anima 低内存模式",en:"Anima low-memory mode"},
    local_low_memory_hint:{zh:"有效上下文保守限制为 2048；默认关闭。",en:"Caps effective context conservatively at 2048; off by default."},
    local_acceleration_remote:{zh:"当前使用第三方模型服务，所有加速选项均已关闭且不可开启。选择本地模型后这些选项才会解锁。",en:"A third-party model service is active, so every acceleration option stays off and locked. Select a local model to unlock them."},
    local_acceleration_engine_missing:{zh:"尚未安装 llama.cpp；安装引擎后会在此显示设备后端并允许开启加速。",en:"llama.cpp is not installed yet. Install the engine to detect device backends here."},
    local_acceleration_probe_failed:{zh:"无法读取引擎后端信息：{reason}。加速选项保持关闭。",en:"Could not read engine backends: {reason}. Acceleration stays off."},
    local_acceleration_detected:{zh:"引擎后端：GPU {gpu} · NPU {npu} · 已选 {active}",en:"Engine backends: GPU {gpu} · NPU {npu} · selected {active}"},
    local_acceleration_yes:{zh:"可用",en:"available"},
    local_acceleration_no:{zh:"不可用",en:"unavailable"},
    local_acceleration_off:{zh:"无（默认关闭）",en:"none (off)"},
    local_acceleration_active_cpu:{zh:"CPU",en:"CPU"},
    local_acceleration_active_gpu:{zh:"GPU",en:"GPU"},
    local_acceleration_active_npu:{zh:"NPU",en:"NPU"},
    local_acceleration_cpu_only:{zh:"当前引擎只提供 CPU 路径，GPU/NPU 不可开启。",en:"The installed engine offers only the CPU path, so GPU/NPU stay disabled."},
    local_context_invalid:{zh:"上下文窗口必须是 512 到 8192 的整数。",en:"Context window must be an integer from 512 to 8192."},
    local_threads_invalid:{zh:"CPU 线程数必须是 1 到 16 的整数。",en:"CPU threads must be an integer from 1 to 16."},
    runtime_packages_deploy:{zh:"部署 Linux",en:"Deploy Linux"},
    runtime_packages_reset:{zh:"清理并重装",en:"Clean up and redeploy"},
    runtime_packages_reset_title:{zh:"清理残留容器并重新部署？",en:"Remove the leftover container and redeploy?"},
    runtime_packages_reset_body:{zh:"上次中断可能留下了不完整的容器，proot-distro 会拒绝重名安装。此操作会先删除该容器（容器内的文件、已装软件与配置全部丢失），再重新下载部署。",en:"An interrupted run may have left an incomplete container, and proot-distro refuses to install over it. This removes that container first — all files, packages and settings inside it are lost — then downloads and deploys again."},
    runtime_packages_refresh:{zh:"刷新包状态",en:"Refresh package status"},
    runtime_packages_loading:{zh:"正在加载软件包状态…",en:"Loading package status…"},
    runtime_packages_unavailable:{zh:"包状态暂不可用。请确认内嵌 Termux 环境已部署，然后刷新。",en:"Package status is unavailable. Make sure the embedded Termux runtime is deployed, then refresh."},
    runtime_packages_status_error:{zh:"读取包状态失败",en:"Package status could not be read"},
    runtime_packages_runtime_missing:{zh:"尚未部署内嵌 Termux 环境；请先点击「一键部署」，完成后再刷新包状态。",en:"The embedded Termux runtime is not deployed yet. Use one-click deploy first, then refresh package status."},
    runtime_packages_unsupported:{zh:"此环境不支持内嵌 Termux（仅 Android APK 可用）。",en:"This environment does not support the embedded Termux runtime (Android APK only)."},
    runtime_packages_distro_missing:{zh:"所选容器尚未部署；点击「部署 Linux」创建容器，完成后即可安装软件包。",en:"The selected container is not deployed. Use Deploy Linux, then install packages."},
    runtime_packages_versions:{zh:"已检测版本：",en:"Detected versions: "},
    runtime_packages_versions_error:{zh:"版本探测失败：",en:"Version probe failed: "},
    runtime_packages_version:{zh:"版本",en:"Version"},
    runtime_packages_ready:{zh:"可选软件包 {available} 个 · 已安装 {installed} 个",en:"{available} available · {installed} installed"},
    runtime_packages_available:{zh:"可选软件包",en:"Available packages"},
    runtime_packages_installed:{zh:"已安装",en:"Installed"},
    runtime_packages_no_available:{zh:"此环境未提供可选软件包列表。",en:"No optional package list was provided by this environment."},
    runtime_packages_empty_installed:{zh:"尚未检测到已安装的软件包。",en:"No installed packages detected."},
    runtime_packages_install_selected:{zh:"安装所选软件包 ({count})",en:"Install selected ({count})"},
    runtime_packages_installing:{zh:"正在依次安装所选软件包…",en:"Installing selected packages one at a time…"},
    runtime_packages_install_success:{zh:"已完成 {count} 个软件包的安装请求；下方列表显示刷新后检测到的已安装软件包。",en:"Finished {count} package installation request(s). The list below shows packages detected as installed after refresh."},
    runtime_packages_deploy_success:{zh:"{distro} PRoot 部署任务已完成；正在刷新运行环境状态。",en:"The {distro} PRoot deployment task finished; refreshing runtime status."},
    runtime_packages_install_partial:{zh:"{succeeded} 个请求成功，{failed} 个失败：{details}",en:"{succeeded} request(s) succeeded and {failed} failed: {details}"},
    runtime_packages_ollama_note:{zh:"Ollama 只安装在 Debian/Ubuntu 容器内，来自固定版本的官方 ARM64 发布包并校验 SHA-256；Termux 环境下不可选。",en:"Ollama installs only inside a Debian/Ubuntu container, from a pinned official ARM64 release verified by SHA-256; it is not selectable for Termux."}
  });
  Object.assign(catalog, {
    extensions_tab:{zh:"技能与 MCP",en:"Skills & MCP"},
    extensions_title:{zh:"Skills 与 MCP",en:"Skills & MCP"},
    extensions_intro:{zh:"管理本地技能文件和模型上下文协议连接器。",en:"Manage skill files and Model Context Protocol connectors."},
    extensions_loading:{zh:"正在加载扩展…",en:"Loading extensions…"},
    extensions_loaded:{zh:"扩展列表已更新。",en:"Extension list updated."},
    extensions_load_error:{zh:"无法加载扩展列表。",en:"Could not load extensions."},
    extensions_refresh:{zh:"刷新",en:"Refresh"},
    extensions_empty:{zh:"尚未配置。",en:"Nothing configured yet."},
    extensions_delete_confirm:{zh:"确定删除“{name}”吗？此操作无法撤销。",en:"Delete “{name}”? This cannot be undone."},
    extensions_saved:{zh:"扩展已保存。",en:"Extension saved."},
    extensions_deleted:{zh:"扩展已删除。",en:"Extension deleted."},
    extensions_failed:{zh:"操作失败。",en:"Operation failed."},
    extension_updated:{zh:"更新于 {updated}",en:"Updated {updated}"},
    skill_upload:{zh:"上传 SKILL.md",en:"Upload SKILL.md"},
    skills_title:{zh:"Skills",en:"Skills"},
    skill_name:{zh:"名称",en:"Name"},
    skill_name_placeholder:{zh:"例如 browser-automation",en:"e.g. browser-automation"},
    skill_content:{zh:"SKILL.md 内容",en:"SKILL.md content"},
    skill_content_placeholder:{zh:"粘贴或上传完整的 SKILL.md",en:"Paste or upload a complete SKILL.md"},
    skill_frontmatter_hint:{zh:"前端只检查 YAML frontmatter，最终校验由服务端完成。",en:"The browser checks YAML frontmatter for feedback only; the server performs final validation."},
    skill_frontmatter_valid:{zh:"已找到 name 与 description frontmatter。",en:"Found name and description frontmatter."},
    skill_frontmatter_missing:{zh:"缺少有效的 YAML frontmatter（需要 name 和 description）；仍可提交，由服务端校验。",en:"Missing valid YAML frontmatter (name and description expected); you can still submit for server-side validation."},
    skill_save:{zh:"添加 / 更新 Skill",en:"Add / update skill"},
    skill_clear:{zh:"清空编辑器",en:"Clear editor"},
    skill_edit:{zh:"编辑",en:"Edit"},
    skill_delete:{zh:"删除",en:"Delete"},
    skill_saved:{zh:"Skill 已添加或更新。",en:"Skill added or updated."},
    skill_file_error:{zh:"无法读取 SKILL.md 文件。",en:"Could not read the SKILL.md file."},
    skill_file_too_large:{zh:"SKILL.md 不能超过 512 KiB。",en:"SKILL.md must be no larger than 512 KiB."},
    skill_name_error:{zh:"名称需为 1–64 个字母、数字、下划线或连字符，且以字母或数字开头。",en:"Use 1–64 letters, numbers, underscores or hyphens, starting with a letter or number."},
    skill_content_error:{zh:"请提供 SKILL.md 内容。",en:"Enter SKILL.md content."},
    skill_frontmatter_status:{zh:"Frontmatter 检查",en:"Frontmatter check"},
    skill_replace_hint:{zh:"编辑时不会从服务端读取技能内容。请上传新的 SKILL.md 或粘贴完整内容，再保存以替换。",en:"Skill contents are not read back from the server. Upload a replacement SKILL.md or paste its full contents, then save to replace it."},
    mcp_enabled:{zh:"启用 MCP 连接器",en:"Enable MCP connectors"},
    mcp_enabled_hint:{zh:"关闭后不会向模型提供已配置的 MCP 工具。",en:"Configured MCP tools will not be exposed to the model when disabled."},
    mcp_enabled_saved:{zh:"MCP 设置已更新。",en:"MCP setting updated."},
    mcp_saving:{zh:"正在更新 MCP 设置…",en:"Updating MCP setting…"},
    mcp_title:{zh:"MCP 连接器",en:"MCP connectors"},
    mcp_name:{zh:"名称",en:"Name"},
    mcp_name_placeholder:{zh:"例如 docs",en:"e.g. docs"},
    mcp_url:{zh:"服务 URL",en:"Server URL"},
    mcp_url_placeholder:{zh:"https://example.com/mcp",en:"https://example.com/mcp"},
    mcp_token:{zh:"令牌（可选）",en:"Token (optional)"},
    mcp_token_placeholder:{zh:"新建或更换令牌；留空保留现有令牌",en:"Set or replace the token; leave blank to keep the existing token"},
    mcp_token_hint:{zh:"令牌只在保存请求中使用；服务端不会回传，页面也不会显示或存储。",en:"The token is sent only when saving; it is never returned, displayed or stored by this page."},
    mcp_token_present:{zh:"已配置令牌（不会读取或显示）",en:"Token configured (never read or shown)"},
    mcp_token_absent:{zh:"未配置令牌",en:"No token configured"},
    mcp_save:{zh:"添加 / 更新连接器",en:"Add / update connector"},
    mcp_clear:{zh:"清空表单",en:"Clear form"},
    mcp_edit:{zh:"编辑",en:"Edit"},
    mcp_refresh:{zh:"刷新工具",en:"Refresh tools"},
    mcp_delete:{zh:"删除",en:"Delete"},
    mcp_saved:{zh:"MCP 连接器已添加或更新。",en:"MCP connector added or updated."},
    mcp_refreshed:{zh:"MCP 工具已刷新。",en:"MCP tools refreshed."},
    mcp_edit_hint:{zh:"正在编辑此连接器。令牌不会回读；令牌留空时将不发送 token 字段。",en:"Editing this connector. Its token is never read back; leaving the token empty omits the token field."},
    mcp_name_error:{zh:"请输入连接器名称。",en:"Enter a connector name."},
    mcp_url_error:{zh:"请输入有效的 HTTP 或 HTTPS URL。",en:"Enter a valid HTTP or HTTPS URL."},
    mcp_token_error:{zh:"令牌不能包含控制字符。",en:"The token cannot contain control characters."}
  });
  let language = window.YunhuPreferences.get().ui_language;
  const t = (key, params={}) => {
    const text = catalog[key]?.[language] ?? catalog[key]?.zh ?? key;
    return text.replace(/\{(\w+)\}/g, (_,name)=>String(params[name] ?? ""));
  };
  function apply(root=document) {
    const nodes = root.querySelectorAll("[data-i18n],[data-i18n-aria-label],[data-i18n-title],[data-i18n-placeholder]");
    for(const node of nodes) {
      if(node.dataset.i18n)node.textContent=t(node.dataset.i18n);
      for(const attr of ["aria-label","title","placeholder"]) {const key=node.getAttribute("data-i18n-"+attr); if(key)node.setAttribute(attr,t(key));}
    }
  }
  const known = {
  "模型连接成功；未执行任何命令。": "server_001",
  "Python版本": "server_002",
  "Workspace目录": "server_003",
  "SQLite存储": "server_004",
  "回环绑定": "server_005",
  "本地持久化对话与任务": "server_006",
  "只监听127.0.0.1；严格Bearer/Host/Origin": "server_007",
  "模型发送需明确同意": "server_008",
  "Android权限桥接": "server_009",
  "已集成": "server_010",
  "桌面预览不执行命令": "server_011",
  "此能力仅在Android APK内可用。": "server_012",
  "尚未获取设备状态。": "server_013",
  "尚未配置更新清单地址。": "server_014",
  "请在设置中填写发布者的HTTPS更新清单地址。": "server_015",
  "当前运行环境没有Android原生桥接；不会在开发机执行Android命令。": "server_016",
  "此操作只能在Android APK中运行；未执行开发机命令。": "server_017",
  "命令超时必须为1～3600秒的整数。": "server_018",
  "请先同意风险说明。": "server_019",
  "对话不存在。": "server_020",
  "任务不存在。": "server_021",
  "请求体必须是JSON对象。": "server_022",
  "只允许HTTP或HTTPS模型地址。": "server_023",
  "命令黑名单": "server_024",
  "模型服务": "server_025",
  "Root权限": "server_026",
  "Shizuku权限": "server_027",
  "权限通道已更新。": "server_028",
  "服务重启，未完成任务已停止。": "server_029"
};
  const knownMessage = value => typeof value === "string" && Object.prototype.hasOwnProperty.call(known,value) ? t(known[value]) : value;
  window.YunhuI18n=Object.freeze({t,apply,knownMessage,language:()=>language});
  window.addEventListener("yunhu:preferences",event=>{language=event.detail.ui_language;apply();});
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",()=>apply(),{once:true});else apply();
})();
