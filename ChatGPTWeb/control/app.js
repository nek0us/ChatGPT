(() => {
  "use strict";

  const UI_VERSION = "2026.07.31.2";
  const STORAGE_KEY = "chatgptweb-control-key-v2";
  const LANGUAGE_KEY = "chatgptweb-control-language";
  const VIEW_KEY = "chatgptweb-control-view";
  const REFRESH_INTERVAL_MS = 5000;
  const REQUEST_TIMEOUT_MS = 15000;

  const translations = {
    zh: {
      console: "运维控制台",
      operations: "OPERATIONS",
      overview: "运行概览",
      verification: "登录验证",
      access: "访问密钥",
      logs: "运行日志",
      notConnected: "尚未连接",
      connecting: "正在连接",
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
      attentionAccounts: "需要处理",
      loginOrRecovery: "登录、验证或恢复中",
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
      accountSummary: "{ready} 个可用，共 {total} 个",
      recentActivity: "最近活动",
      activitySubtitle: "当前核心进程内的运维事件",
      noActivity: "当前进程还没有运维事件",
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
      secondsRemaining: "剩余约 {count} 秒",
      minutesRemaining: "剩余约 {count} 分钟",
      enable: "启用",
      disable: "停用",
      retryLogin: "重试登录",
      retryNow: "立即重试",
      refreshCapabilities: "刷新账户能力",
      accountUpdated: "账户状态已更新",
      eventChat: "对话已完成",
      eventControl: "账户设置已更新",
      eventLogin: "登录状态已更新",
      eventRuntime: "浏览器环境已恢复",
      eventGeneric: "运维事件",
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
      operations: "OPERATIONS",
      overview: "Overview",
      verification: "Verification",
      access: "API keys",
      logs: "Runtime logs",
      notConnected: "Not connected",
      connecting: "Connecting",
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
      attentionAccounts: "Attention",
      loginOrRecovery: "Login, verification, or recovery",
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
      accountSummary: "{ready} available of {total}",
      recentActivity: "Recent activity",
      activitySubtitle: "Operational events from this core process",
      noActivity: "No operational events in this process",
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
      secondsRemaining: "about {count}s",
      minutesRemaining: "about {count}m",
      enable: "Enable",
      disable: "Disable",
      retryLogin: "Retry login",
      retryNow: "Retry now",
      refreshCapabilities: "Refresh capabilities",
      accountUpdated: "Account state updated",
      eventChat: "Chat completed",
      eventControl: "Account settings changed",
      eventLogin: "Login state updated",
      eventRuntime: "Browser runtime recovered",
      eventGeneric: "Operational event",
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
      accountRows: document.querySelector("#account-rows"),
      activityList: document.querySelector("#activity-list"),
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
    elements.refresh.classList.toggle("is-spinning", kind === "loading");
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
    if (item.manual_disabled) return { label: t("disabled"), className: "disabled" };
    if (item.login_retry_pending || item.status === "Login") {
      return { label: t("working"), className: "working" };
    }
    if (item.status === "Recovering") {
      return { label: t("recovering"), className: "working" };
    }
    if (isAccountReady(item)) return { label: t("ready"), className: "ready" };
    if (item.login_failure_kind === "need_verification") {
      return { label: t("needsVerification"), className: "attention" };
    }
    if (item.login_failure_kind === "rate_limited") {
      return { label: t("coolingDown"), className: "attention" };
    }
    if (item.login_failure_kind === "transient") {
      return { label: t("recovering"), className: "attention" };
    }
    if (item.login_failure_kind) return { label: t("needsLogin"), className: "error" };
    return { label: t("unavailable"), className: "attention" };
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

  function accountDiagnostics(item) {
    const plan = item.account_plan && item.account_plan !== "unknown"
      ? `${item.account_plan} (${t("observed")})`
      : `${t("unknown")} (${t("legacy")} ${item.gptplus ? "plus" : "free"})`;
    const parts = [
      `${t("mode")}: ${item.mode || "--"}`,
      `${t("plan")}: ${plan}`,
      `${t("models")}: ${item.observed_model_count || 0} (${item.observed_models_source || t("sourceUnavailable")})`,
      `${t("login")}: ${item.login_state ? t("loginReady") : t("loginNotReady")}`,
    ];
    if (item.login_guidance) parts.push(String(item.login_guidance));
    if (item.login_failure_kind) {
      parts.push(`${t("failure")}: ${item.login_failure_kind} (${item.login_fail_count || 0}/${item.max_login_failures || "--"})`);
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
    const sessions = list.reduce((total, item) => total + Number(item.conversation_count || 0), 0);
    elements.total.textContent = String(list.length);
    elements.ready.textContent = String(ready);
    elements.attention.textContent = String(list.length - ready);
    elements.sessions.textContent = String(sessions);
    elements.accountSummary.textContent = t("accountSummary", { ready, total: list.length });
    elements.accountRows.replaceChildren();
    if (!list.length) {
      emptyTable(elements.accountRows, 6, t("noAccounts"));
      return;
    }
    for (const item of list) {
      const row = document.createElement("tr");
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
    if (name === "account_control") return t("eventControl");
    if (name.includes("login")) return t("eventLogin");
    if (name.includes("runtime") || name.includes("context")) return t("eventRuntime");
    return name || t("eventGeneric");
  }

  function renderActivity() {
    const list = Array.isArray(state.activity?.events) ? state.activity.events : [];
    elements.activityList.replaceChildren();
    if (!list.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = t("noActivity");
      elements.activityList.append(empty);
      return;
    }
    for (const item of list.slice(0, 30)) {
      const row = document.createElement("div");
      row.className = "activity-item";
      const time = document.createElement("time");
      time.textContent = formatTime(item.at);
      const account = document.createElement("span");
      account.className = "activity-account";
      account.textContent = item.account || "--";
      const event = document.createElement("span");
      event.className = "activity-event";
      event.textContent = activityLabel(item.event);
      const detail = document.createElement("span");
      detail.className = "activity-detail";
      detail.textContent = item.message || "--";
      row.append(time, account, event, detail);
      elements.activityList.append(row);
    }
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
    try {
      const payload = await api(`/v1/runtime/logs?lines=${encodeURIComponent(elements.logLines.value)}`);
      if (!payload.available) {
        elements.logMessage.textContent = payload.message || t("logUnavailable");
        elements.runtimeLog.textContent = payload.message || t("logUnavailable");
        return;
      }
      const lines = Array.isArray(payload.lines) ? payload.lines : [];
      elements.logMessage.textContent = t("logsSubtitle");
      elements.runtimeLog.textContent = lines.length ? lines.join("\n") : t("noLogLines");
      elements.runtimeLog.scrollTop = elements.runtimeLog.scrollHeight;
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
    if (state.refreshing) return;
    if (!force && state.submitting.size) return;
    if (!force && document.activeElement?.closest?.(".challenge")) return;
    state.refreshing = true;
    setConnection("loading", state.connected ? "refreshing" : "connecting");
    elements.refresh.disabled = true;
    try {
      state.status = normalizeStatus(await api("/v1/account/status"));
      state.connected = true;
      sessionStorage.setItem(STORAGE_KEY, currentKey());
      setConnection("ready", "connected");
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
      state.lastUpdated = new Date();
      renderCurrentState();
      if (state.view === "logs") await refreshLogs();
    } catch (error) {
      state.connected = false;
      setConnection("error", "connectionFailed");
      setNotice(error.message, "error");
      if (error.status === 401) sessionStorage.removeItem(STORAGE_KEY);
    } finally {
      state.refreshing = false;
      elements.refresh.disabled = false;
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
    const allowed = new Set(["overview", "verification", "access", "logs"]);
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
      sessionStorage.removeItem(STORAGE_KEY);
      elements.adminKey.value = "";
      resetData();
      setNotice(t("disconnected"), "success");
    });
    elements.refresh.addEventListener("click", () => refreshAll(true));
    elements.clientKeyForm.addEventListener("submit", createClientKey);
    elements.copySecret.addEventListener("click", copySecret);
    elements.refreshLogs.addEventListener("click", refreshLogs);
    elements.logLines.addEventListener("change", refreshLogs);
    window.addEventListener("hashchange", () => activateView(location.hash.slice(1), false));
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
      if (state.connected && document.visibilityState === "visible") refreshAll(false);
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
