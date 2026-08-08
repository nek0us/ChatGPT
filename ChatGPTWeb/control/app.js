(() => {
  "use strict";

  const UI_VERSION = "2026.08.09.1";
  const STORAGE_KEY = "chatgptweb-control-key-v2";
  const LANGUAGE_KEY = "chatgptweb-control-language";
  const VIEW_KEY = "chatgptweb-control-view";
  const REFRESH_INTERVAL_MS = 5000;
  const REQUEST_TIMEOUT_MS = 15000;
  const RECONNECT_INITIAL_DELAY_MS = 1000;
  const RECONNECT_MAX_DELAY_MS = 30000;

  const translations = {
    zh: {
      console: "运维控制台",
      consoleNavigation: "控制台导航",
      languageSelector: "语言",
      accountMetrics: "账户汇总",
      accountQuickIndex: "账户快速索引",
      operations: "运维管理",
      overview: "运行概览",
      activity: "最近活动",
      verification: "登录验证",
      access: "访问密钥",
      logs: "运行日志",
      notConnected: "尚未连接",
      connecting: "正在连接",
      reconnecting: "核心暂不可达，正在重连",
      refreshing: "正在刷新",
      connected: "连接正常",
      connectionFailed: "连接失败",
      adminConnection: "管理员连接",
      enterAdminKey: "输入控制台管理密钥",
      connectedToCore: "管理接口认证成功",
      adminKey: "控制台管理密钥",
      show: "显示",
      hide: "隐藏",
      connect: "连接",
      clear: "清除",
      refresh: "刷新",
      configuredAccounts: "配置账户",
      accountsRegistered: "已注册到当前核心",
      availableAccounts: "当前可用",
      readyForRequests: "可接受新请求",
      attentionAccounts: "需人工处理",
      loginOrRecovery: "验证、凭据或账号异常",
      activeSessions: "逻辑会话",
      retainedSessions: "核心保留的会话",
      accounts: "账户",
      accountsSubtitle: "登录、用量与浏览器状态",
      account: "账户",
      state: "状态",
      sessions: "会话",
      usage: "用量",
      diagnostics: "诊断",
      actions: "操作",
      connectToLoad: "连接后加载数据",
      noAccounts: "当前核心没有配置账户",
      accountSummary: "{ready} 可用 · {working} 处理中 · {recovering} 恢复中 · {attention} 需处理 · 共 {total}",
      searchAccounts: "搜索或定位账户",
      visibleAccounts: "显示 {visible} / {total}",
      recentActivity: "最近活动",
      activitySubtitle: "聊天、附件、登录与运行状态",
      activityPageSubtitle: "查看请求、附件、登录和浏览器恢复事件",
      viewAllActivity: "查看全部",
      activityLevel: "等级",
      allLevels: "全部",
      warningsAndErrors: "警告及错误",
      errorsOnly: "仅错误",
      noActivity: "当前进程还没有请求或运维事件",
      verificationSubtitle: "处理等待中的邮箱验证码与账户验证",
      pendingCount: "{count} 项等待处理",
      noVerification: "没有等待处理的验证",
      verificationCode: "验证码",
      submit: "提交",
      cancel: "取消",
      accessSubtitle: "创建、轮换与吊销客户端 API 密钥",
      keyName: "密钥名称",
      keyNamePlaceholder: "例如：生产机器人",
      permissionScope: "权限范围",
      scopeChat: "聊天 / Responses",
      scopeAgent: "智能体协议",
      scopeBot: "机器人桥接",
      concurrency: "并发数",
      createKey: "创建密钥",
      secretOnce: "新密钥仅显示一次",
      copy: "复制",
      copied: "已复制",
      lastUsed: "最后使用",
      never: "从未使用",
      rotate: "轮换",
      revoke: "吊销",
      noClientKeys: "没有活动的客户端密钥",
      keyManagementUnavailable: "当前核心未启用动态密钥管理",
      chooseScope: "至少选择一个权限范围",
      confirmRevoke: "确认吊销“{label}”吗？",
      keyCreated: "客户端密钥已创建",
      keyRotated: "客户端密钥已轮换",
      keyRevoked: "客户端密钥已吊销",
      logsSubtitle: "核心启动、登录与恢复日志",
      logLevel: "最低等级",
      levelDebug: "调试",
      levelInfo: "信息",
      levelWarning: "警告",
      levelError: "错误",
      followLogs: "自动跟随",
      lines: "行数",
      refreshLogs: "刷新日志",
      logUnavailable: "当前核心没有配置运行日志文件",
      noLogLines: "运行日志暂时为空",
      unavailable: "暂不可用",
      ready: "可用",
      working: "处理中",
      recovering: "恢复中",
      disabled: "已停用",
      needsLogin: "需要登录",
      needsVerification: "等待验证",
      coolingDown: "等待恢复",
      unknown: "未知",
      noUsage: "尚未观测到上游用量",
      capabilityUsage: "高级能力（本地估算）",
      uploadBudget: "上传",
      imageUploads: "图片",
      fileUploads: "文件",
      imageGeneration: "生图",
      observeOnly: "仅统计",
      capabilityCooling: "上游冷却",
      requestCount: "{count} 次请求",
      mode: "模式",
      plan: "套餐",
      models: "模型",
      login: "登录",
      failure: "状态",
      retryWait: "重试等待",
      recoveryCount: "恢复次数",
      authState: "认证状态",
      restored: "已恢复",
      enabled: "已启用",
      observed: "已观测",
      legacy: "旧配置",
      sourceUnavailable: "来源不可用",
      loginReady: "可用",
      loginNotReady: "未就绪",
      stateReady: "账户已准备好接收新请求。",
      stateChatInProgress: "账户正在处理一项对话请求。",
      stateLoginRecoveryRunning: "受控登录恢复正在运行。",
      stateVerificationPending: "正在等待提交服务商验证码。",
      stateChatQuotaCooldown: "新对话等待预计额度恢复。",
      stateReauthenticationRequired: "浏览器授权已失效，需要重新登录。",
      stateAccountUnavailable: "上游账户不可用，需要先在上游恢复。",
      stateCredentialsRejected: "配置的登录凭据被拒绝，需要更新。",
      stateVerificationRequired: "服务商要求先完成验证。",
      stateProviderSecurityCheck: "服务商触发安全检查，请等待后重试。",
      stateProviderLoginCooldown: "登录尝试正在冷却，请按提示等待。",
      stateBrowserBridgeUnavailable: "浏览器请求桥未就绪，核心将自动恢复。",
      stateBrowserPageStartupFailed: "浏览器页面启动失败，请检查运行环境。",
      stateLoginTransportFailure: "网络或浏览器异常中断了登录。",
      stateLoginUnrecognized: "当前登录页面状态无法识别，需要检查诊断。",
      stateLoginStarting: "浏览器登录流程正在启动。",
      stateManuallyDisabled: "账户已被管理员停用。",
      stateRuntimeNotReady: "账户运行环境尚未就绪。",
      stateBrowserRuntimeRecoveryNeeded: "浏览器页面或上下文已关闭，正在等待恢复。",
      stateLoginRecoveryPending: "账户正在等待下一次登录恢复。",
      stateNotInitialized: "账户尚未完成浏览器初始化。",
      failureAccountLocked: "账户不可用",
      failureNeedVerification: "需要验证",
      failureRiskBlocked: "安全检查",
      failureRateLimited: "登录冷却",
      failureTransient: "临时异常",
      failureBadCredentials: "凭据错误",
      failureUnknown: "未知异常",
      secondsRemaining: "剩余约 {count} 秒",
      minutesRemaining: "剩余约 {count} 分钟",
      enable: "启用",
      disable: "停用",
      retryLogin: "重试登录",
      retryNow: "立即重试",
      refreshCapabilities: "刷新账户能力",
      accountUpdated: "账户状态已更新",
      eventChat: "对话已完成",
      eventChatQueued: "请求排队中",
      eventChatStarted: "对话已开始",
      eventChatFailed: "对话失败",
      eventAttachment: "附件上传",
      eventImageGeneration: "图片生成",
      eventCapability: "高级能力",
      eventControl: "账户设置已更新",
      eventLogin: "登录状态已更新",
      eventRuntime: "浏览器环境已恢复",
      eventProject: "会话归档",
      eventGeneric: "运维事件",
      activityRequestAccepted: "请求已进入账户执行",
      activityRequestAcceptedWithUploads: "请求已进入账户执行，包含 {count} 个附件",
      activityRequestQueued: "正在等待可用账户",
      activityRequestAdmitted: "等待 {duration} 后已分配账户",
      activityRequestAdmissionFailed: "等待 {duration} 后仍未取得可用账户",
      activityWaitingAccount: "等待分配",
      activityChatCompleted: "对话完成，模型 {model}，耗时 {duration}",
      activityChatFailed: "请求失败：{kind}",
      activityAttachmentStarted: "开始上传 {count} 个附件",
      activityAttachmentCompleted: "已向上游提交 {count} 个附件",
      activityAttachmentFailed: "附件随本次请求一同失败，共 {count} 个",
      activityImageStarted: "已请求上游生成图片",
      activityImageCompleted: "已取得 {count} 张生成图片",
      activityImageFailed: "上游生图结束，但没有取得可回传图片",
      activityAccountControl: "账户控制设置已更新",
      activityLoginRetryCancelled: "受控登录恢复已取消",
      activityLoginRetryFailed: "受控登录恢复失败，请查看账户诊断",
      activityLoginRetryFinished: "受控登录恢复已结束",
      activityRuntimeClosed: "浏览器运行环境意外关闭",
      activityRuntimeRecovered: "浏览器运行环境已重建",
      activityProjectRoutingFailed: "对话归档项目定位失败",
      activityLoginRetryStarted: "已开始受控登录恢复",
      activityStreamBridgeWarmed: "浏览器请求桥已预热",
      activityCapabilityRecorded: "已更新高级能力使用统计",
      activityCapabilityRateLimited: "高级能力进入上游冷却",
      activityChatRateLimited: "聊天额度进入等待恢复状态",
      activityProjectCreated: "已创建会话归档项目",
      activityProjectRouted: "会话已归入指定项目",
      activitySource: "来源：{source}",
      invalidKey: "控制台管理密钥无效",
      forbidden: "当前密钥没有此操作权限",
      requestTimeout: "请求超时，核心可能仍在启动或恢复",
      networkError: "无法连接控制台后端",
      unexpectedResponse: "后端返回了无法识别的数据",
      disconnected: "已清除当前标签页的管理密钥",
      refreshComplete: "状态已刷新",
      frontendFailure: "控制台脚本发生错误，请重新打开页面或查看开发者控制台。",
    },
    en: {
      console: "Operations console",
      consoleNavigation: "Console navigation",
      languageSelector: "Language",
      accountMetrics: "Account summary",
      accountQuickIndex: "Account quick index",
      operations: "OPERATIONS",
      overview: "Overview",
      activity: "Activity",
      verification: "Verification",
      access: "API keys",
      logs: "Runtime logs",
      notConnected: "Not connected",
      connecting: "Connecting",
      reconnecting: "Core is unavailable, reconnecting",
      refreshing: "Refreshing",
      connected: "Connected",
      connectionFailed: "Connection failed",
      adminConnection: "Administrator connection",
      enterAdminKey: "Enter the console administrator key",
      connectedToCore: "Administrator API authenticated",
      adminKey: "Console administrator key",
      show: "Show",
      hide: "Hide",
      connect: "Connect",
      clear: "Clear",
      refresh: "Refresh",
      configuredAccounts: "Configured",
      accountsRegistered: "Registered with this core",
      availableAccounts: "Available",
      readyForRequests: "Ready for new requests",
      attentionAccounts: "Action required",
      loginOrRecovery: "Verification, credentials, or account issues",
      activeSessions: "Sessions",
      retainedSessions: "Retained by the core",
      accounts: "Accounts",
      accountsSubtitle: "Login, usage, and browser state",
      account: "Account",
      state: "State",
      sessions: "Sessions",
      usage: "Usage",
      diagnostics: "Diagnostics",
      actions: "Actions",
      connectToLoad: "Connect to load data",
      noAccounts: "No accounts are configured",
      accountSummary: "{ready} ready · {working} working · {recovering} recovering · {attention} action required · {total} total",
      searchAccounts: "Search or locate an account",
      visibleAccounts: "Showing {visible} / {total}",
      recentActivity: "Recent activity",
      activitySubtitle: "Chat, attachment, login, and runtime events",
      activityPageSubtitle: "Inspect requests, attachments, login, and browser recovery events",
      viewAllActivity: "View all",
      activityLevel: "Level",
      allLevels: "All",
      warningsAndErrors: "Warnings and errors",
      errorsOnly: "Errors only",
      noActivity: "No request or operational events in this process",
      verificationSubtitle: "Handle pending email codes and account checks",
      pendingCount: "{count} pending",
      noVerification: "No pending verification",
      verificationCode: "Verification code",
      submit: "Submit",
      cancel: "Cancel",
      accessSubtitle: "Create, rotate, and revoke client API keys",
      keyName: "Key name",
      keyNamePlaceholder: "For example: production bot",
      permissionScope: "Scopes",
      scopeChat: "Chat / Responses",
      scopeAgent: "Agent protocol",
      scopeBot: "Bot bridge",
      concurrency: "Concurrency",
      createKey: "Create key",
      secretOnce: "The new secret is shown once",
      copy: "Copy",
      copied: "Copied",
      lastUsed: "Last used",
      never: "Never",
      rotate: "Rotate",
      revoke: "Revoke",
      noClientKeys: "No active client keys",
      keyManagementUnavailable: "Dynamic key management is not enabled",
      chooseScope: "Choose at least one scope",
      confirmRevoke: "Revoke “{label}”?",
      keyCreated: "Client key created",
      keyRotated: "Client key rotated",
      keyRevoked: "Client key revoked",
      logsSubtitle: "Core startup, login, and recovery logs",
      logLevel: "Minimum level",
      levelDebug: "Debug",
      levelInfo: "Info",
      levelWarning: "Warning",
      levelError: "Error",
      followLogs: "Follow output",
      lines: "Lines",
      refreshLogs: "Refresh logs",
      logUnavailable: "No runtime log file is configured",
      noLogLines: "The runtime log is empty",
      unavailable: "Unavailable",
      ready: "Ready",
      working: "Working",
      recovering: "Recovering",
      disabled: "Disabled",
      needsLogin: "Needs login",
      needsVerification: "Verification required",
      coolingDown: "Cooling down",
      unknown: "Unknown",
      noUsage: "No observed upstream usage",
      capabilityUsage: "Capabilities (local estimate)",
      uploadBudget: "Uploads",
      imageUploads: "images",
      fileUploads: "files",
      imageGeneration: "image generation",
      observeOnly: "observe only",
      capabilityCooling: "upstream cooldown",
      requestCount: "{count} request(s)",
      mode: "Mode",
      plan: "Plan",
      models: "Models",
      login: "Login",
      failure: "State",
      retryWait: "Retry after",
      recoveryCount: "Recoveries",
      authState: "Auth state",
      restored: "restored",
      enabled: "enabled",
      observed: "observed",
      legacy: "legacy",
      sourceUnavailable: "unavailable",
      loginReady: "ready",
      loginNotReady: "not ready",
      stateReady: "The account is ready for new work.",
      stateChatInProgress: "The account is serving a chat request.",
      stateLoginRecoveryRunning: "Controlled login recovery is running.",
      stateVerificationPending: "A provider verification code is awaiting submission.",
      stateChatQuotaCooldown: "New chats are waiting for the estimated quota reset.",
      stateReauthenticationRequired: "Browser authorization expired and requires a fresh sign-in.",
      stateAccountUnavailable: "The upstream account must be restored before retrying.",
      stateCredentialsRejected: "The configured credentials were rejected and must be updated.",
      stateVerificationRequired: "The provider requires verification before continuing.",
      stateProviderSecurityCheck: "The provider requested a security check; wait before retrying.",
      stateProviderLoginCooldown: "Login attempts are cooling down; wait before retrying.",
      stateBrowserBridgeUnavailable: "The browser request bridge is unavailable and will recover automatically.",
      stateBrowserPageStartupFailed: "The browser page failed to start; inspect the runtime.",
      stateLoginTransportFailure: "A browser or network failure interrupted login.",
      stateLoginUnrecognized: "The provider login state was not recognized; inspect diagnostics.",
      stateLoginStarting: "The browser sign-in flow is starting.",
      stateManuallyDisabled: "The account was disabled by an operator.",
      stateRuntimeNotReady: "The account runtime is not ready.",
      stateBrowserRuntimeRecoveryNeeded: "The browser page or context closed and is awaiting recovery.",
      stateLoginRecoveryPending: "The account is waiting for its next login recovery.",
      stateNotInitialized: "The account has not completed browser initialization.",
      failureAccountLocked: "account unavailable",
      failureNeedVerification: "verification required",
      failureRiskBlocked: "security check",
      failureRateLimited: "login cooldown",
      failureTransient: "temporary failure",
      failureBadCredentials: "credentials rejected",
      failureUnknown: "unknown failure",
      secondsRemaining: "about {count}s",
      minutesRemaining: "about {count}m",
      enable: "Enable",
      disable: "Disable",
      retryLogin: "Retry login",
      retryNow: "Retry now",
      refreshCapabilities: "Refresh capabilities",
      accountUpdated: "Account state updated",
      eventChat: "Chat completed",
      eventChatQueued: "Request queued",
      eventChatStarted: "Chat started",
      eventChatFailed: "Chat failed",
      eventAttachment: "Attachment upload",
      eventImageGeneration: "Image generation",
      eventCapability: "Capabilities",
      eventControl: "Account settings changed",
      eventLogin: "Login state updated",
      eventRuntime: "Browser runtime recovered",
      eventProject: "Conversation project",
      eventGeneric: "Operational event",
      activityRequestAccepted: "The request was assigned to this account",
      activityRequestAcceptedWithUploads: "The request was assigned with {count} attachment(s)",
      activityRequestQueued: "Waiting for an available account",
      activityRequestAdmitted: "Assigned an account after {duration}",
      activityRequestAdmissionFailed: "No account became available after {duration}",
      activityWaitingAccount: "Awaiting assignment",
      activityChatCompleted: "Completed with {model} in {duration}",
      activityChatFailed: "Request failed: {kind}",
      activityAttachmentStarted: "Uploading {count} attachment(s)",
      activityAttachmentCompleted: "Submitted {count} attachment(s) upstream",
      activityAttachmentFailed: "The request failed with {count} attachment(s)",
      activityImageStarted: "Requested upstream image generation",
      activityImageCompleted: "Retrieved {count} generated image(s)",
      activityImageFailed: "Image generation ended without a retrievable image",
      activityAccountControl: "Account control settings were updated",
      activityLoginRetryCancelled: "Controlled login recovery was cancelled",
      activityLoginRetryFailed: "Controlled login recovery failed; inspect account diagnostics",
      activityLoginRetryFinished: "Controlled login recovery finished",
      activityRuntimeClosed: "The browser runtime closed unexpectedly",
      activityRuntimeRecovered: "The browser runtime was rebuilt",
      activityProjectRoutingFailed: "Conversation project routing failed",
      activityLoginRetryStarted: "Controlled login recovery started",
      activityStreamBridgeWarmed: "The browser request bridge was warmed",
      activityCapabilityRecorded: "Capability usage counters were updated",
      activityCapabilityRateLimited: "A capability entered upstream cooldown",
      activityChatRateLimited: "Chat quota entered its recovery window",
      activityProjectCreated: "A conversation project was created",
      activityProjectRouted: "The conversation was routed to its project",
      activitySource: "Source: {source}",
      invalidKey: "The console administrator key is invalid",
      forbidden: "This key cannot perform the requested operation",
      requestTimeout: "The request timed out while the core was starting or recovering",
      networkError: "The console backend could not be reached",
      unexpectedResponse: "The backend returned an unexpected response",
      disconnected: "The administrator key was cleared for this tab",
      refreshComplete: "State refreshed",
      frontendFailure: "The console script failed. Reopen the page or inspect the developer console.",
    },
  };

  const OPERATIONAL_STATE_KEYS = {
    ready: "stateReady",
    chat_in_progress: "stateChatInProgress",
    login_recovery_running: "stateLoginRecoveryRunning",
    verification_pending: "stateVerificationPending",
    chat_quota_cooldown: "stateChatQuotaCooldown",
    session_reauthentication_required: "stateReauthenticationRequired",
    account_unavailable: "stateAccountUnavailable",
    credentials_rejected: "stateCredentialsRejected",
    verification_required: "stateVerificationRequired",
    provider_security_check: "stateProviderSecurityCheck",
    provider_login_cooldown: "stateProviderLoginCooldown",
    browser_bridge_unavailable: "stateBrowserBridgeUnavailable",
    browser_page_startup_failed: "stateBrowserPageStartupFailed",
    login_transport_failure: "stateLoginTransportFailure",
    login_state_unrecognized: "stateLoginUnrecognized",
    login_starting: "stateLoginStarting",
    manually_disabled: "stateManuallyDisabled",
    runtime_not_ready: "stateRuntimeNotReady",
    browser_runtime_recovery_needed: "stateBrowserRuntimeRecoveryNeeded",
    login_recovery_pending: "stateLoginRecoveryPending",
    not_initialized: "stateNotInitialized",
  };

  const FAILURE_KIND_KEYS = {
    account_locked: "failureAccountLocked",
    need_verification: "failureNeedVerification",
    risk_blocked: "failureRiskBlocked",
    rate_limited: "failureRateLimited",
    transient: "failureTransient",
    bad_credentials: "failureBadCredentials",
    unknown: "failureUnknown",
  };

  class ApiError extends Error {
    constructor(message, status = 0) {
      super(message);
      this.name = "ApiError";
      this.status = status;
    }
  }

  const language = localStorage.getItem(LANGUAGE_KEY);
  const state = {
    language: language === "en" ? "en" : "zh",
    view: localStorage.getItem(VIEW_KEY) || location.hash.slice(1) || "overview",
    connected: false,
    connectionKind: "idle",
    connectionLabelKey: "notConnected",
    refreshing: false,
    logRefreshing: false,
    status: null,
    activity: null,
    verification: null,
    keys: null,
    keyManagementUnavailable: false,
    drafts: new Map(),
    submitting: new Set(),
    lastUpdated: null,
    accountFilter: "",
    activityLevel: "all",
    reconnectTimer: null,
    reconnectAttempts: 0,
    pendingRefresh: false,
  };

  const elements = {};

  function queryElements() {
    Object.assign(elements, {
      fatal: document.querySelector("#fatal-banner"),
      refresh: document.querySelector("#refresh"),
      connection: document.querySelector("#connection-state"),
      connectionLabel: document.querySelector("#connection-label"),
      lastUpdated: document.querySelector("#last-updated"),
      sidebarDot: document.querySelector("#sidebar-dot"),
      sidebarState: document.querySelector("#sidebar-state"),
      authStrip: document.querySelector(".auth-strip"),
      authDot: document.querySelector("#auth-dot"),
      authDescription: document.querySelector("#auth-description"),
      authForm: document.querySelector("#auth-form"),
      adminKey: document.querySelector("#admin-key"),
      toggleKey: document.querySelector("#toggle-key"),
      disconnect: document.querySelector("#disconnect"),
      notice: document.querySelector("#notice"),
      viewTitle: document.querySelector("#view-title"),
      viewEyebrow: document.querySelector("#view-eyebrow"),
      total: document.querySelector("#metric-total"),
      ready: document.querySelector("#metric-ready"),
      attention: document.querySelector("#metric-attention"),
      sessions: document.querySelector("#metric-sessions"),
      accountSummary: document.querySelector("#account-summary"),
      accountFilter: document.querySelector("#account-filter"),
      accountIndex: document.querySelector("#account-index"),
      accountRows: document.querySelector("#account-rows"),
      activityList: document.querySelector("#activity-list"),
      activityPreview: document.querySelector("#activity-preview"),
      activityLevel: document.querySelector("#activity-level"),
      openActivity: document.querySelector("#open-activity"),
      verificationBadge: document.querySelector("#verification-badge"),
      verificationCount: document.querySelector("#verification-count"),
      challengeList: document.querySelector("#challenge-list"),
      clientKeyForm: document.querySelector("#client-key-form"),
      clientKeyLabel: document.querySelector("#client-key-label"),
      clientKeyConcurrency: document.querySelector("#client-key-concurrency"),
      clientKeyRows: document.querySelector("#client-key-rows"),
      secretPanel: document.querySelector("#secret-panel"),
      clientKeySecret: document.querySelector("#client-key-secret"),
      copySecret: document.querySelector("#copy-secret"),
      logLines: document.querySelector("#log-lines"),
      logLevel: document.querySelector("#log-level"),
      logFollow: document.querySelector("#log-follow"),
      refreshLogs: document.querySelector("#refresh-logs"),
      logMessage: document.querySelector("#log-message"),
      runtimeLog: document.querySelector("#runtime-log"),
    });
  }

  function t(name, variables = {}) {
    const source = translations[state.language][name] || translations.en[name] || name;
    return source.replace(/\{(\w+)\}/g, (_, key) => variables[key] ?? "");
  }

  function applyTranslation() {
    document.documentElement.lang = state.language === "zh" ? "zh-CN" : "en";
    document.title = state.language === "zh" ? "ChatGPTWeb 控制台" : "ChatGPTWeb Control";
    document.querySelectorAll("[data-i18n]").forEach((node) => {
      node.textContent = t(node.dataset.i18n);
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach((node) => {
      node.placeholder = t(node.dataset.i18nPlaceholder);
    });
    document.querySelectorAll("[data-i18n-title]").forEach((node) => {
      const value = t(node.dataset.i18nTitle);
      node.title = value;
      node.setAttribute("aria-label", value);
    });
    document.querySelectorAll("[data-i18n-aria-label]").forEach((node) => {
      node.setAttribute("aria-label", t(node.dataset.i18nAriaLabel));
    });
    document.querySelectorAll("[data-language]").forEach((node) => {
      node.setAttribute("aria-pressed", String(node.dataset.language === state.language));
    });
    renderCurrentState();
    setConnection(state.connectionKind, state.connectionLabelKey);
    activateView(state.view, false);
  }

  function setNotice(message = "", kind = "") {
    elements.notice.hidden = !message;
    elements.notice.textContent = message;
    elements.notice.className = `notice${kind ? ` is-${kind}` : ""}`;
  }

  function setConnection(kind, labelKey) {
    state.connectionKind = kind;
    state.connectionLabelKey = labelKey;
    elements.connection.dataset.state = kind;
    elements.connectionLabel.textContent = t(labelKey);
    elements.sidebarState.textContent = t(labelKey);
    elements.sidebarDot.className = `status-dot${kind === "ready" ? " is-ready" : kind === "loading" ? " is-loading" : kind === "error" ? " is-error" : ""}`;
    elements.authDot.className = elements.sidebarDot.className;
    elements.authStrip.classList.toggle("is-ready", kind === "ready");
    elements.authStrip.classList.toggle("is-error", kind === "error");
    if (kind === "ready") {
      elements.authDescription.textContent = t("connectedToCore");
    } else if (kind === "error") {
      elements.authDescription.textContent = t("connectionFailed");
    } else {
      elements.authDescription.textContent = t("enterAdminKey");
    }
  }

  function formatTime(value) {
    if (!value) return "--";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat(state.language === "zh" ? "zh-CN" : "en", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    }).format(date);
  }

  function updateLastUpdated() {
    elements.lastUpdated.textContent = state.lastUpdated ? formatTime(state.lastUpdated) : "";
  }

  function currentKey() {
    return elements.adminKey.value.trim();
  }

  function clearReconnectTimer() {
    if (state.reconnectTimer !== null) {
      window.clearTimeout(state.reconnectTimer);
      state.reconnectTimer = null;
    }
  }

  function setRefreshing(refreshing) {
    elements.refresh.classList.toggle("is-spinning", refreshing);
    elements.refresh.setAttribute("aria-busy", String(refreshing));
  }

  function shouldReconnect(error) {
    if (!currentKey()) return false;
    const status = Number(error?.status || 0);
    return status === 0 || status === 408 || status === 429 || status >= 500;
  }

  function scheduleReconnect(error) {
    if (!shouldReconnect(error) || state.reconnectTimer !== null) return;
    const delay = Math.min(
      RECONNECT_MAX_DELAY_MS,
      RECONNECT_INITIAL_DELAY_MS * (2 ** state.reconnectAttempts),
    );
    state.reconnectAttempts += 1;
    if (!state.connected) setConnection("loading", "reconnecting");
    state.reconnectTimer = window.setTimeout(() => {
      state.reconnectTimer = null;
      refreshAll(true);
    }, delay);
  }

  async function api(path, options = {}) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    const headers = {
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    };
    if (currentKey()) headers.Authorization = `Bearer ${currentKey()}`;
    try {
      const response = await fetch(path, {
        ...options,
        headers,
        signal: controller.signal,
        cache: "no-store",
        credentials: "omit",
      });
      if (!response.ok) {
        const detail = (await response.text()).trim();
        if (response.status === 401) throw new ApiError(t("invalidKey"), 401);
        if (response.status === 403) throw new ApiError(t("forbidden"), 403);
        throw new ApiError(detail || `${response.status} ${response.statusText}`, response.status);
      }
      if (response.status === 204) return null;
      const contentType = response.headers.get("content-type") || "";
      if (!contentType.includes("application/json")) {
        throw new ApiError(t("unexpectedResponse"), response.status);
      }
      return await response.json();
    } catch (error) {
      if (error.name === "AbortError") throw new ApiError(t("requestTimeout"));
      if (error instanceof ApiError) throw error;
      throw new ApiError(t("networkError"));
    } finally {
      window.clearTimeout(timeout);
    }
  }

  function emptyTable(target, colspan, message) {
    target.replaceChildren();
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = colspan;
    cell.className = "empty-row";
    cell.textContent = message;
    row.append(cell);
    target.append(row);
  }

  function textCell(row, value, className = "") {
    const cell = document.createElement("td");
    cell.className = className;
    cell.textContent = value === undefined || value === null || value === "" ? "--" : String(value);
    row.append(cell);
    return cell;
  }

  function isAccountReady(item) {
    if (typeof item.available === "boolean") return item.available;
    return Boolean(item.login_state && !item.manual_disabled);
  }

  function normalizeStatus(payload) {
    if (!payload || typeof payload !== "object") {
      throw new ApiError(t("unexpectedResponse"));
    }
    if (Array.isArray(payload.accounts)) return payload;
    if (Array.isArray(payload.account)) {
      return {
        ...payload,
        accounts: payload.account.map((item) => (
          typeof item === "string" ? { email: item, status: "unknown" } : item
        )),
      };
    }
    return { ...payload, accounts: [] };
  }

  function accountState(item) {
    const operational = String(item.operational_state || "");
    if (item.manual_disabled) return { label: t("disabled"), className: "disabled" };
    if (item.status === "Working" || operational === "chat_in_progress") {
      return { label: t("working"), className: "working" };
    }
    if (item.login_retry_pending || item.status === "Login" || operational === "login_starting") {
      return { label: t("recovering"), className: "recovering" };
    }
    if (item.status === "Recovering" || [
      "login_recovery_running",
      "browser_bridge_unavailable",
      "browser_page_startup_failed",
      "login_transport_failure",
      "browser_runtime_recovery_needed",
      "login_recovery_pending",
      "not_initialized",
    ].includes(operational)) {
      return { label: t("recovering"), className: "recovering" };
    }
    if (isAccountReady(item)) return { label: t("ready"), className: "ready" };
    if (["verification_pending", "verification_required"].includes(operational)
        || item.login_failure_kind === "need_verification") {
      return { label: t("needsVerification"), className: "attention" };
    }
    if (["chat_quota_cooldown", "provider_login_cooldown"].includes(operational)
        || item.login_failure_kind === "rate_limited") {
      return { label: t("coolingDown"), className: "attention" };
    }
    if (item.login_failure_kind === "transient") {
      return { label: t("recovering"), className: "attention" };
    }
    if (item.login_failure_kind) return { label: t("needsLogin"), className: "error" };
    return { label: t("unavailable"), className: "attention" };
  }

  function accountNeedsAttention(item) {
    const operational = String(item.operational_state || "");
    if (["Working", "Login", "Recovering"].includes(item.status)) return false;
    if ([
      "ready",
      "chat_in_progress",
      "login_recovery_running",
      "login_starting",
      "chat_quota_cooldown",
      "provider_login_cooldown",
      "provider_security_check",
      "browser_bridge_unavailable",
      "browser_page_startup_failed",
      "login_transport_failure",
      "browser_runtime_recovery_needed",
      "login_recovery_pending",
      "not_initialized",
    ].includes(operational)) return false;
    if ([
      "manually_disabled",
      "verification_pending",
      "verification_required",
      "session_reauthentication_required",
      "account_unavailable",
      "credentials_rejected",
      "login_state_unrecognized",
    ].includes(operational)) return true;
    if (item.manual_disabled || isAccountReady(item)) return false;
    return ["account_locked", "bad_credentials", "need_verification", "unknown"]
      .includes(item.login_failure_kind);
  }

  function accountIndexLabel(email) {
    const [local = "--", domain = ""] = String(email || "--").split("@", 2);
    const compactLocal = local.length > 10 ? `${local.slice(0, 9)}…` : local;
    const compactDomain = domain.split(".", 1)[0];
    return compactDomain ? `${compactLocal}@${compactDomain}` : compactLocal;
  }

  function focusAccount(index) {
    state.accountFilter = "";
    elements.accountFilter.value = "";
    renderAccounts();
    requestAnimationFrame(() => {
      const row = document.querySelector(`[data-account-index="${index}"]`);
      if (!row) return;
      row.scrollIntoView({ behavior: "smooth", block: "center" });
      row.classList.add("is-located");
      window.setTimeout(() => row.classList.remove("is-located"), 1800);
    });
  }

  function renderAccountIndex(list) {
    elements.accountIndex.replaceChildren();
    for (const [index, item] of list.entries()) {
      const status = accountState(item);
      const button = document.createElement("button");
      button.type = "button";
      button.className = `account-index-item ${status.className.split(" ")[0]}`;
      button.title = `${item.email || "--"} · ${status.label}`;
      button.setAttribute("aria-label", button.title);
      const dot = document.createElement("span");
      dot.className = "account-index-dot";
      dot.setAttribute("aria-hidden", "true");
      const label = document.createElement("span");
      label.className = "account-index-label";
      label.textContent = accountIndexLabel(item.email);
      button.append(dot, label);
      button.addEventListener("click", () => focusAccount(index));
      elements.accountIndex.append(button);
    }
  }

  function formatUsage(usage) {
    if (!usage || !usage.requests) return t("noUsage");
    const models = Object.entries(usage.models || {}).map(([name, value]) => {
      const tokens = ["input_tokens", "output_tokens", "total_tokens"]
        .filter((key) => typeof value[key] === "number")
        .map((key) => `${key.replace("_tokens", "")}: ${value[key]}`)
        .join(", ");
      return `${name} · ${t("requestCount", { count: value.requests })}${tokens ? ` · ${tokens}` : ""}`;
    });
    return models.join("\n") || t("requestCount", { count: usage.requests });
  }

  function retryTime(item) {
    const seconds = Number(item.retry_after_seconds || 0);
    if (!seconds) return "";
    if (seconds < 60) return t("secondsRemaining", { count: seconds });
    return t("minutesRemaining", { count: Math.ceil(seconds / 60) });
  }

  function capabilityDiagnostics(item) {
    const quota = item.capability_quota;
    if (!quota || !quota.enabled) return "";
    const imageUpload = quota.image_upload || {};
    const fileUpload = quota.file_upload || {};
    const imageGeneration = quota.image_generation || {};
    const uploadLimit = Number(imageUpload.limit || fileUpload.limit || 0);
    const uploadUsed = Number(quota.upload_total || 0);
    const generationLimit = Number(imageGeneration.limit || 0);
    const generationUsed = Number(imageGeneration.budget_used || 0);
    const lines = [
      `${t("capabilityUsage")}:`,
      `${t("uploadBudget")}: ${uploadUsed}/${uploadLimit || t("observeOnly")} (${t("imageUploads")} ${Number(imageUpload.used || 0)}, ${t("fileUploads")} ${Number(fileUpload.used || 0)})`,
      `${t("imageGeneration")}: ${generationUsed}/${generationLimit || t("observeOnly")}`,
    ];
    const cooling = [imageUpload, fileUpload, imageGeneration]
      .filter((value) => value.limit_reason === "upstream")
      .map((value) => Number(value.retry_after_seconds || 0))
      .filter(Boolean);
    if (cooling.length) {
      lines.push(`${t("capabilityCooling")}: ${t("minutesRemaining", { count: Math.ceil(Math.min(...cooling) / 60) })}`);
    }
    return lines.join("\n");
  }

  function operationalGuidance(item) {
    const key = OPERATIONAL_STATE_KEYS[String(item.operational_state || "")];
    if (key) return t(key);
    if (item.status === "Working") return t("stateChatInProgress");
    if (item.status === "Recovering" || item.status === "Login") return t("stateLoginRecoveryRunning");
    if (isAccountReady(item)) return t("stateReady");
    return t("stateRuntimeNotReady");
  }

  function failureLabel(kind) {
    const key = FAILURE_KIND_KEYS[String(kind || "")];
    return key ? t(key) : t("failureUnknown");
  }

  function accountDiagnostics(item) {
    const plan = item.account_plan && item.account_plan !== "unknown"
      ? `${item.account_plan} (${t("observed")})`
      : `${t("unknown")} (${t("legacy")} ${item.gptplus ? "plus" : "free"})`;
    const parts = [
      `${t("mode")}: ${item.mode || "--"}`,
      `${t("plan")}: ${plan}`,
      `${t("models")}: ${item.observed_model_count || 0} (${item.observed_models_source || t("sourceUnavailable")})`,
      `${t("login")}: ${item.login_state ? t("loginReady") : t("loginNotReady")}`,
      operationalGuidance(item),
    ];
    if (item.login_failure_kind && item.status !== "Working" && item.operational_state !== "chat_in_progress") {
      parts.push(`${t("failure")}: ${failureLabel(item.login_failure_kind)} (${item.login_fail_count || 0}/${item.max_login_failures || "--"})`);
    }
    const wait = retryTime(item);
    if (wait) parts.push(`${t("retryWait")}: ${wait}`);
    if (item.persist_auth_state) {
      parts.push(`${t("authState")}: ${item.auth_state_loaded ? t("restored") : t("enabled")}`);
    }
    if (item.runtime?.recovery_count) {
      parts.push(`${t("recoveryCount")}: ${item.runtime.recovery_count}`);
    }
    const capabilityUsage = capabilityDiagnostics(item);
    if (capabilityUsage) parts.push(capabilityUsage);
    return parts.join("\n");
  }

  function smallButton(label, action, danger = false) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `button${danger ? " danger" : ""}`;
    button.textContent = label;
    button.addEventListener("click", action);
    return button;
  }

  async function changeAccount(item, action, button) {
    button.disabled = true;
    setNotice();
    try {
      await api(`/v1/accounts/${encodeURIComponent(item.email)}/control`, {
        method: "POST",
        body: JSON.stringify({ action }),
      });
      setNotice(t("accountUpdated"), "success");
      await refreshAll(true);
    } catch (error) {
      setNotice(error.message, "error");
    } finally {
      button.disabled = false;
    }
  }

  function renderAccounts() {
    const list = Array.isArray(state.status?.accounts) ? state.status.accounts : [];
    const ready = list.filter(isAccountReady).length;
    const attention = list.filter(accountNeedsAttention).length;
    const presentedStates = list.map(accountState);
    const working = presentedStates.filter((value) => value.className === "working").length;
    const recovering = presentedStates.filter((value) => value.className === "recovering").length;
    const sessions = list.reduce((total, item) => total + Number(item.conversation_count || 0), 0);
    elements.total.textContent = String(list.length);
    elements.ready.textContent = String(ready);
    elements.attention.textContent = String(attention);
    elements.attention.closest(".metric")?.classList.toggle("is-zero", attention === 0);
    elements.sessions.textContent = String(sessions);
    const query = state.accountFilter.trim().toLocaleLowerCase();
    const visible = list
      .map((item, index) => ({ item, index }))
      .filter(({ item }) => !query || String(item.email || "").toLocaleLowerCase().includes(query));
    elements.accountSummary.textContent = query
      ? t("visibleAccounts", { visible: visible.length, total: list.length })
      : t("accountSummary", { ready, working, recovering, attention, total: list.length });
    renderAccountIndex(list);
    elements.accountRows.replaceChildren();
    if (!list.length) {
      emptyTable(elements.accountRows, 6, t("noAccounts"));
      return;
    }
    if (!visible.length) {
      emptyTable(elements.accountRows, 6, t("noAccounts"));
      return;
    }
    for (const { item, index } of visible) {
      const row = document.createElement("tr");
      row.dataset.accountIndex = String(index);
      textCell(row, item.email, "account-name");
      const statusCell = document.createElement("td");
      statusCell.className = "status-cell";
      const status = accountState(item);
      const pill = document.createElement("span");
      pill.className = `status-pill ${status.className}`;
      pill.textContent = status.label;
      statusCell.append(pill);
      row.append(statusCell);
      textCell(row, item.conversation_count || 0);
      textCell(row, formatUsage(item.usage), "usage-cell");
      textCell(row, accountDiagnostics(item), "diagnostics-cell");
      const controlCell = document.createElement("td");
      controlCell.className = "controls-cell";
      const controls = document.createElement("div");
      controls.className = "controls";
      if (item.manual_disabled) {
        const button = smallButton(t("enable"), () => changeAccount(item, "enable", button));
        controls.append(button);
      } else {
        const disable = smallButton(t("disable"), () => changeAccount(item, "disable", disable), true);
        controls.append(disable);
        if (!item.login_state && item.can_retry_login && !item.login_retry_pending) {
          const retryLabel = item.retry_mode === "cooldown" ? t("retryNow") : t("retryLogin");
          const retry = smallButton(retryLabel, () => changeAccount(item, "retry_login", retry));
          controls.append(retry);
        }
      }
      const capabilities = smallButton(
        t("refreshCapabilities"),
        () => changeAccount(item, "refresh_capabilities", capabilities),
      );
      controls.append(capabilities);
      controlCell.append(controls);
      row.append(controlCell);
      elements.accountRows.append(row);
    }
  }

  function activityLabel(event) {
    const name = String(event || "");
    if (name === "chat_completed") return t("eventChat");
    if (name === "chat_queued") return t("eventChatQueued");
    if (name === "chat_started") return t("eventChatStarted");
    if (name === "chat_failed") return t("eventChatFailed");
    if (name.includes("attachment_upload")) return t("eventAttachment");
    if (name.includes("image_generation")) return t("eventImageGeneration");
    if (name.includes("capability")) return t("eventCapability");
    if (name === "account_control") return t("eventControl");
    if (name.includes("login")) return t("eventLogin");
    if (name.includes("runtime") || name.includes("context") || name.includes("bridge")) return t("eventRuntime");
    if (name.includes("project")) return t("eventProject");
    return t("eventGeneric");
  }

  function formatDuration(value) {
    const milliseconds = Number(value || 0);
    if (!Number.isFinite(milliseconds) || milliseconds <= 0) return "--";
    if (milliseconds < 1000) return `${Math.round(milliseconds)} ms`;
    return `${(milliseconds / 1000).toFixed(milliseconds < 10000 ? 1 : 0)} s`;
  }

  function activityDescription(item) {
    const details = item.details && typeof item.details === "object" ? item.details : {};
    const event = String(item.event || "");
    const count = Number(details.count ?? details.uploads ?? 0);
    if (event === "chat_queued") {
      if (details.pending) return t("activityRequestQueued");
      const key = details.outcome === "admitted"
        ? "activityRequestAdmitted"
        : "activityRequestAdmissionFailed";
      return t(key, { duration: formatDuration(details.admission_ms) });
    }
    if (event === "chat_started") {
      return count > 0
        ? t("activityRequestAcceptedWithUploads", { count })
        : t("activityRequestAccepted");
    }
    if (event === "chat_completed") {
      return t("activityChatCompleted", {
        model: details.model || "--",
        duration: formatDuration(details.duration_ms),
      });
    }
    if (event === "chat_failed") {
      return t("activityChatFailed", { kind: details.error_kind || item.message || "unknown" });
    }
    if (event === "attachment_upload_started") {
      return t("activityAttachmentStarted", { count });
    }
    if (event === "attachment_upload_completed") {
      return t("activityAttachmentCompleted", { count });
    }
    if (event === "attachment_upload_failed") {
      return t("activityAttachmentFailed", { count });
    }
    if (event === "image_generation_started") return t("activityImageStarted");
    if (event === "image_generation_completed") {
      return t("activityImageCompleted", { count });
    }
    if (event === "image_generation_failed") return t("activityImageFailed");
    if (event === "account_control") return t("activityAccountControl");
    if (event === "login_retry_cancelled") return t("activityLoginRetryCancelled");
    if (event === "login_retry_failed") return t("activityLoginRetryFailed");
    if (event === "login_retry_finished") return t("activityLoginRetryFinished");
    if (event === "runtime_closed") return t("activityRuntimeClosed");
    if (event === "bridge_context_recovery") return t("activityRuntimeRecovered");
    if (event === "project_routing_failed") return t("activityProjectRoutingFailed");
    if (event === "login_retry_started") return t("activityLoginRetryStarted");
    if (event === "stream_bridge_warmed") return t("activityStreamBridgeWarmed");
    if (event === "capability_usage_recorded") return t("activityCapabilityRecorded");
    if (event === "capability_rate_limited") return t("activityCapabilityRateLimited");
    if (event === "chat_rate_limited") return t("activityChatRateLimited");
    if (event === "project_created") return t("activityProjectCreated");
    if (event === "project_routed") return t("activityProjectRouted");
    return item.message || "--";
  }

  function renderActivityList(target, list) {
    target.replaceChildren();
    if (!list.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = t("noActivity");
      target.append(empty);
      return;
    }
    for (const item of list) {
      const row = document.createElement("div");
      const severity = ["debug", "info", "warning", "error", "critical"].includes(item.severity)
        ? item.severity
        : "info";
      row.className = `activity-item severity-${severity}`;
      const time = document.createElement("time");
      time.textContent = formatTime(item.at);
      const account = document.createElement("span");
      account.className = "activity-account";
      account.textContent = item.account || (
        item.event === "chat_queued" ? t("activityWaitingAccount") : "--"
      );
      const event = document.createElement("span");
      event.className = "activity-event";
      event.textContent = activityLabel(item.event);
      const detail = document.createElement("span");
      detail.className = "activity-detail";
      const details = item.details && typeof item.details === "object" ? item.details : {};
      const source = typeof details.source === "string" ? details.source : "";
      detail.textContent = `${activityDescription(item)}${source ? ` · ${t("activitySource", { source })}` : ""}`;
      row.append(time, account, event, detail);
      target.append(row);
    }
  }

  function renderActivity() {
    const list = Array.isArray(state.activity?.events) ? state.activity.events : [];
    const severityRank = { debug: 10, info: 20, warning: 30, error: 40, critical: 50 };
    const minimum = state.activityLevel === "warning" ? 30 : state.activityLevel === "error" ? 40 : 0;
    const filtered = list.filter((item) => (
      (severityRank[String(item.severity || "info")] || 20) >= minimum
    ));
    renderActivityList(elements.activityPreview, list.slice(0, 8));
    renderActivityList(elements.activityList, filtered.slice(0, 100));
  }

  async function submitChallenge(item, code, form) {
    if (!code.trim()) {
      setNotice(t("verificationCode"), "error");
      return;
    }
    state.submitting.add(item.id);
    form.querySelectorAll("button").forEach((button) => { button.disabled = true; });
    try {
      await api(`/v1/verification/${encodeURIComponent(item.id)}`, {
        method: "POST",
        body: JSON.stringify({ code: code.trim() }),
      });
      state.drafts.delete(item.id);
      await refreshAll(true);
    } catch (error) {
      setNotice(error.message, "error");
    } finally {
      state.submitting.delete(item.id);
      form.querySelectorAll("button").forEach((button) => { button.disabled = false; });
    }
  }

  async function cancelChallenge(item, form) {
    state.submitting.add(item.id);
    form.querySelectorAll("button").forEach((button) => { button.disabled = true; });
    try {
      await api(`/v1/verification/${encodeURIComponent(item.id)}`, { method: "DELETE" });
      state.drafts.delete(item.id);
      await refreshAll(true);
    } catch (error) {
      setNotice(error.message, "error");
    } finally {
      state.submitting.delete(item.id);
      form.querySelectorAll("button").forEach((button) => { button.disabled = false; });
    }
  }

  function renderVerification() {
    const list = Array.isArray(state.verification?.challenges) ? state.verification.challenges : [];
    elements.verificationBadge.hidden = list.length === 0;
    elements.verificationBadge.textContent = String(list.length);
    elements.verificationCount.textContent = t("pendingCount", { count: list.length });
    elements.challengeList.replaceChildren();
    if (!list.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = t("noVerification");
      elements.challengeList.append(empty);
      return;
    }
    for (const item of list) {
      const form = document.createElement("form");
      form.className = "challenge";
      const identity = document.createElement("div");
      identity.className = "challenge-account";
      const account = document.createElement("strong");
      account.textContent = item.account || "--";
      const provider = document.createElement("span");
      provider.textContent = item.provider || "--";
      identity.append(account, provider);
      const field = document.createElement("label");
      field.className = "field";
      const label = document.createElement("span");
      label.textContent = t("verificationCode");
      const input = document.createElement("input");
      input.inputMode = "numeric";
      input.autocomplete = "one-time-code";
      input.maxLength = 12;
      input.value = state.drafts.get(item.id) || "";
      input.addEventListener("input", () => state.drafts.set(item.id, input.value));
      field.append(label, input);
      const submit = smallButton(t("submit"), () => {});
      submit.type = "submit";
      submit.classList.add("primary");
      const cancel = smallButton(t("cancel"), () => cancelChallenge(item, form), true);
      form.append(identity, field, submit, cancel);
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        submitChallenge(item, input.value, form);
      });
      elements.challengeList.append(form);
    }
  }

  function scopeLabel(scope) {
    return t({ chat: "scopeChat", agent: "scopeAgent", bot: "scopeBot" }[scope] || scope);
  }

  function revealSecret(secret) {
    elements.secretPanel.hidden = !secret;
    elements.clientKeySecret.textContent = secret || "";
  }

  async function rotateClientKey(item, button) {
    button.disabled = true;
    try {
      const value = await api(`/v1/keys/${encodeURIComponent(item.id)}/rotate`, { method: "POST" });
      revealSecret(value.secret);
      setNotice(t("keyRotated"), "success");
      await refreshClientKeys();
    } catch (error) {
      setNotice(error.message, "error");
    } finally {
      button.disabled = false;
    }
  }

  async function revokeClientKey(item, button) {
    if (!window.confirm(t("confirmRevoke", { label: item.label }))) return;
    button.disabled = true;
    try {
      await api(`/v1/keys/${encodeURIComponent(item.id)}`, { method: "DELETE" });
      setNotice(t("keyRevoked"), "success");
      await refreshClientKeys();
    } catch (error) {
      setNotice(error.message, "error");
    } finally {
      button.disabled = false;
    }
  }

  function renderClientKeys() {
    if (state.keyManagementUnavailable) {
      emptyTable(elements.clientKeyRows, 5, t("keyManagementUnavailable"));
      elements.clientKeyForm.querySelectorAll("input, button").forEach((node) => { node.disabled = true; });
      return;
    }
    elements.clientKeyForm.querySelectorAll("input, button").forEach((node) => { node.disabled = false; });
    const list = Array.isArray(state.keys?.keys) ? state.keys.keys : [];
    elements.clientKeyRows.replaceChildren();
    if (!list.length) {
      emptyTable(elements.clientKeyRows, 5, t("noClientKeys"));
      return;
    }
    for (const item of list) {
      const row = document.createElement("tr");
      textCell(row, item.label, "account-name");
      const scopes = document.createElement("td");
      scopes.className = "api-key-scopes";
      for (const scope of item.scopes || []) {
        const tag = document.createElement("span");
        tag.className = "scope-tag";
        tag.textContent = scopeLabel(scope);
        scopes.append(tag);
      }
      row.append(scopes);
      textCell(row, `${item.active_requests || 0} / ${item.max_concurrency || "--"}`);
      textCell(row, item.last_used_at ? formatTime(item.last_used_at) : t("never"));
      const controlCell = document.createElement("td");
      const controls = document.createElement("div");
      controls.className = "controls";
      const rotate = smallButton(t("rotate"), () => rotateClientKey(item, rotate));
      const revoke = smallButton(t("revoke"), () => revokeClientKey(item, revoke), true);
      controls.append(rotate, revoke);
      controlCell.append(controls);
      row.append(controlCell);
      elements.clientKeyRows.append(row);
    }
  }

  function renderCurrentState() {
    if (state.status) renderAccounts();
    if (state.activity) renderActivity();
    if (state.verification) renderVerification();
    if (state.keys || state.keyManagementUnavailable) renderClientKeys();
    updateLastUpdated();
  }

  async function refreshClientKeys() {
    try {
      state.keys = await api("/v1/keys");
      state.keyManagementUnavailable = false;
    } catch (error) {
      if (error.status === 501) {
        state.keys = null;
        state.keyManagementUnavailable = true;
      } else {
        throw error;
      }
    }
    renderClientKeys();
  }

  async function refreshLogs() {
    if (!state.connected || state.logRefreshing) return;
    state.logRefreshing = true;
    elements.refreshLogs.disabled = true;
    const wasNearBottom = (
      elements.runtimeLog.scrollHeight - elements.runtimeLog.scrollTop - elements.runtimeLog.clientHeight
    ) < 48;
    try {
      const query = new URLSearchParams({
        lines: elements.logLines.value,
        level: elements.logLevel.value,
      });
      const payload = await api(`/v1/runtime/logs?${query}`);
      if (!payload.available) {
        elements.logMessage.textContent = payload.message || t("logUnavailable");
        elements.runtimeLog.textContent = payload.message || t("logUnavailable");
        return;
      }
      const entries = Array.isArray(payload.entries)
        ? payload.entries
        : (Array.isArray(payload.lines) ? payload.lines.map((text) => ({ text, level: "info" })) : []);
      elements.logMessage.textContent = t("logsSubtitle");
      elements.runtimeLog.replaceChildren();
      if (!entries.length) {
        elements.runtimeLog.textContent = t("noLogLines");
      } else {
        for (const entry of entries) {
          const line = document.createElement("span");
          const level = ["debug", "info", "warning", "error", "critical"].includes(entry.level)
            ? entry.level
            : "info";
          line.className = `log-line log-${level}`;
          line.dataset.level = level;
          line.textContent = String(entry.text || "");
          elements.runtimeLog.append(line);
        }
      }
      if (elements.logFollow.checked || wasNearBottom) {
        elements.runtimeLog.scrollTop = elements.runtimeLog.scrollHeight;
      }
    } catch (error) {
      elements.logMessage.textContent = error.message;
      elements.runtimeLog.textContent = error.message;
      setNotice(error.message, "error");
    } finally {
      state.logRefreshing = false;
      elements.refreshLogs.disabled = false;
    }
  }

  async function refreshAll(force = false) {
    if (state.refreshing) {
      if (force) state.pendingRefresh = true;
      return;
    }
    const wasConnected = state.connected;
    state.refreshing = true;
    setRefreshing(true);
    if (!wasConnected) setConnection("loading", "connecting");
    try {
      state.status = normalizeStatus(await api("/v1/account/status"));
      state.connected = true;
      clearReconnectTimer();
      state.reconnectAttempts = 0;
      sessionStorage.setItem(STORAGE_KEY, currentKey());
      setConnection("ready", "connected");
      state.lastUpdated = new Date();
      renderCurrentState();
      const optional = await Promise.allSettled([
        api("/v1/activity?limit=50"),
        api("/v1/verification"),
        refreshClientKeys(),
      ]);
      if (optional[0].status === "fulfilled") state.activity = optional[0].value;
      if (optional[1].status === "fulfilled") state.verification = optional[1].value;
      for (const result of optional) {
        if (result.status === "rejected" && result.reason?.status !== 501) {
          setNotice(result.reason.message, "error");
        }
      }
      renderCurrentState();
      if (state.view === "logs") await refreshLogs();
    } catch (error) {
      if (error.status === 401 || error.status === 403) {
        state.connected = false;
        setConnection("error", "connectionFailed");
        setNotice(error.message, "error");
        clearReconnectTimer();
        state.reconnectAttempts = 0;
        if (error.status === 401) sessionStorage.removeItem(STORAGE_KEY);
      } else {
        const keepHealthyAppearance = wasConnected && state.reconnectAttempts === 0;
        if (!keepHealthyAppearance) {
          state.connected = false;
          setConnection("loading", "reconnecting");
          setNotice(error.message, "error");
        }
        scheduleReconnect(error);
      }
    } finally {
      state.refreshing = false;
      setRefreshing(false);
      if (state.pendingRefresh) {
        state.pendingRefresh = false;
        window.queueMicrotask(() => refreshAll(true));
      }
    }
  }

  function resetData() {
    state.connected = false;
    state.status = null;
    state.activity = null;
    state.verification = null;
    state.keys = null;
    state.keyManagementUnavailable = false;
    state.lastUpdated = null;
    elements.total.textContent = "--";
    elements.ready.textContent = "--";
    elements.attention.textContent = "--";
    elements.sessions.textContent = "--";
    elements.accountSummary.textContent = "";
    emptyTable(elements.accountRows, 6, t("connectToLoad"));
    elements.activityList.innerHTML = "";
    const activityEmpty = document.createElement("div");
    activityEmpty.className = "empty-state";
    activityEmpty.textContent = t("connectToLoad");
    elements.activityList.append(activityEmpty);
    elements.activityPreview.replaceChildren(activityEmpty.cloneNode(true));
    elements.verificationBadge.hidden = true;
    elements.verificationCount.textContent = "";
    elements.challengeList.replaceChildren(activityEmpty.cloneNode(true));
    emptyTable(elements.clientKeyRows, 5, t("connectToLoad"));
    elements.runtimeLog.textContent = t("connectToLoad");
    elements.logMessage.textContent = t("logsSubtitle");
    revealSecret("");
    updateLastUpdated();
    setConnection("idle", "notConnected");
  }

  function activateView(name, updateLocation = true) {
    const allowed = new Set(["overview", "activity", "verification", "access", "logs"]);
    state.view = allowed.has(name) ? name : "overview";
    document.querySelectorAll("[data-view]").forEach((node) => {
      node.classList.toggle("is-active", node.dataset.view === state.view);
    });
    document.querySelectorAll("[data-panel]").forEach((node) => {
      node.classList.toggle("is-active", node.dataset.panel === state.view);
    });
    elements.viewTitle.textContent = t(state.view);
    elements.viewEyebrow.textContent = t("operations");
    localStorage.setItem(VIEW_KEY, state.view);
    if (updateLocation) history.replaceState(null, "", `#${state.view}`);
    if (state.view === "logs" && state.connected) refreshLogs();
  }

  async function createClientKey(event) {
    event.preventDefault();
    const scopes = [...elements.clientKeyForm.querySelectorAll('input[name="client-key-scope"]:checked')]
      .map((node) => node.value);
    if (!scopes.length) {
      setNotice(t("chooseScope"), "error");
      return;
    }
    const button = elements.clientKeyForm.querySelector('button[type="submit"]');
    button.disabled = true;
    try {
      const value = await api("/v1/keys", {
        method: "POST",
        body: JSON.stringify({
          label: elements.clientKeyLabel.value.trim(),
          scopes,
          max_concurrency: Number(elements.clientKeyConcurrency.value),
        }),
      });
      elements.clientKeyLabel.value = "";
      revealSecret(value.secret);
      setNotice(t("keyCreated"), "success");
      await refreshClientKeys();
    } catch (error) {
      setNotice(error.message, "error");
    } finally {
      button.disabled = false;
    }
  }

  async function copySecret() {
    const value = elements.clientKeySecret.textContent;
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
    } catch (_) {
      const input = document.createElement("textarea");
      input.value = value;
      input.style.position = "fixed";
      input.style.opacity = "0";
      document.body.append(input);
      input.select();
      document.execCommand("copy");
      input.remove();
    }
    elements.copySecret.textContent = t("copied");
    window.setTimeout(() => { elements.copySecret.textContent = t("copy"); }, 1600);
  }

  function bindEvents() {
    document.querySelectorAll("[data-view]").forEach((node) => {
      node.addEventListener("click", () => activateView(node.dataset.view));
    });
    document.querySelectorAll("[data-language]").forEach((node) => {
      node.addEventListener("click", () => {
        state.language = node.dataset.language;
        localStorage.setItem(LANGUAGE_KEY, state.language);
        applyTranslation();
      });
    });
    elements.authForm.addEventListener("submit", (event) => {
      event.preventDefault();
      setNotice();
      refreshAll(true);
    });
    elements.adminKey.addEventListener("input", () => {
      if (state.connected && currentKey() !== sessionStorage.getItem(STORAGE_KEY)) {
        setConnection("idle", "notConnected");
        state.connected = false;
      }
      clearReconnectTimer();
      state.reconnectAttempts = 0;
    });
    elements.adminKey.addEventListener("keydown", (event) => {
      if (event.key === "Escape") elements.adminKey.blur();
    });
    elements.toggleKey.addEventListener("click", () => {
      const visible = elements.adminKey.type === "text";
      elements.adminKey.type = visible ? "password" : "text";
      elements.toggleKey.textContent = t(visible ? "show" : "hide");
    });
    elements.disconnect.addEventListener("click", () => {
      clearReconnectTimer();
      state.reconnectAttempts = 0;
      sessionStorage.removeItem(STORAGE_KEY);
      elements.adminKey.value = "";
      resetData();
      setNotice(t("disconnected"), "success");
    });
    elements.refresh.addEventListener("click", () => refreshAll(true));
    elements.accountFilter.addEventListener("input", () => {
      state.accountFilter = elements.accountFilter.value;
      if (state.status) renderAccounts();
    });
    elements.openActivity.addEventListener("click", () => activateView("activity"));
    elements.activityLevel.addEventListener("change", () => {
      state.activityLevel = elements.activityLevel.value;
      renderActivity();
    });
    elements.clientKeyForm.addEventListener("submit", createClientKey);
    elements.copySecret.addEventListener("click", copySecret);
    elements.refreshLogs.addEventListener("click", refreshLogs);
    elements.logLines.addEventListener("change", refreshLogs);
    elements.logLevel.addEventListener("change", refreshLogs);
    window.addEventListener("hashchange", () => activateView(location.hash.slice(1), false));
    window.addEventListener("online", () => {
      if (!state.connected && currentKey()) {
        clearReconnectTimer();
        refreshAll(true);
      }
    });
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible" && currentKey()) refreshAll(true);
    });
    window.addEventListener("pageshow", () => {
      if (currentKey()) refreshAll(true);
    });
  }

  function showFatal(error) {
    if (!elements.fatal) return;
    elements.fatal.hidden = false;
    elements.fatal.textContent = `${t("frontendFailure")} ${error?.message || error || ""}`.trim();
  }

  function boot() {
    queryElements();
    elements.adminKey.value = sessionStorage.getItem(STORAGE_KEY) || "";
    bindEvents();
    applyTranslation();
    resetData();
    activateView(state.view, false);
    refreshAll(true);
    window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      if (state.connected) {
        refreshAll(false);
      } else if (currentKey() && state.reconnectTimer === null) {
        refreshAll(false);
      }
    }, REFRESH_INTERVAL_MS);
  }

  window.addEventListener("error", (event) => showFatal(event.error || event.message));
  window.addEventListener("unhandledrejection", (event) => showFatal(event.reason));

  try {
    boot();
  } catch (error) {
    showFatal(error);
    throw error;
  }

  window.ChatGPTWebControl = Object.freeze({
    version: UI_VERSION,
    refresh: () => refreshAll(true),
  });
})();
