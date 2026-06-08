/**
 * DanmuAI community registration guard (005). Used only by community-site;
 * not part of desktop main.py / web/static supabase-config.js.
 */
import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "npm:@supabase/supabase-js@2";

const AUTH_DOMAIN = "danmuai.test";
const RATE_LIMIT_MESSAGE = "今天已经注册过账号，请明天再试";
const USERNAME_TAKEN_MESSAGE = "用户名已存在";

/**
 * W-SECURITY-003: CORS Origin 从环境变量读取，支持多域名（逗号分隔）。
 * 未配置时使用默认值 https://community.danmuai.com
 */
function getAllowedOrigins(): string[] {
  const raw = Deno.env.get("COMMUNITY_CORS_ORIGIN") ?? "https://community.danmuai.com";
  return raw.split(",").map((s) => s.trim()).filter((s) => s.length > 0);
}

function getCorsHeaders(origin: string | null): Record<string, string> {
  const allowed = getAllowedOrigins();
  const allowedOrigin = origin && allowed.includes(origin) ? origin : allowed[0] ?? "*";
  return {
    "Access-Control-Allow-Origin": allowedOrigin,
    "Access-Control-Allow-Headers":
      "authorization, x-client-info, apikey, content-type",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
  };
}

function jsonResponse(body: Record<string, unknown>, status: number, origin: string | null = null) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...getCorsHeaders(origin), "Content-Type": "application/json" },
  });
}

async function sha256Hex(value: string): Promise<string> {
  const data = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

function clientIp(req: Request): string {
  const forwarded = req.headers.get("x-forwarded-for");
  if (forwarded) {
    const first = forwarded.split(",")[0]?.trim();
    if (first) return first;
  }
  const realIp = req.headers.get("x-real-ip")?.trim();
  if (realIp) return realIp;
  const cfIp = req.headers.get("cf-connecting-ip")?.trim();
  if (cfIp) return cfIp;
  return "unknown";
}

/** Comma-separated public IPs; bypass 24h IP/device registration limits. */
function registrationIpWhitelist(): Set<string> {
  const raw = Deno.env.get("COMMUNITY_REGISTRATION_IP_WHITELIST") ?? "";
  return new Set(
    raw.split(",").map((s) => s.trim()).filter((s) => s.length > 0),
  );
}

function isRegistrationWhitelisted(req: Request): boolean {
  const ip = clientIp(req);
  if (!ip || ip === "unknown") return false;
  return registrationIpWhitelist().has(ip);
}

function isValidDeviceId(deviceId: unknown): deviceId is string {
  if (typeof deviceId !== "string") return false;
  const t = deviceId.trim();
  return t.length >= 16 && t.length <= 128 && /^[a-zA-Z0-9_-]+$/.test(t);
}

function isValidPassword(password: unknown): password is string {
  return typeof password === "string" && password.length >= 6 &&
    password.length <= 128;
}

Deno.serve(async (req: Request) => {
  const origin = req.headers.get("origin");

  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: getCorsHeaders(origin) });
  }

  if (req.method !== "POST") {
    return jsonResponse({ error: "Method not allowed" }, 405, origin);
  }

  const supabaseUrl = Deno.env.get("SUPABASE_URL");
  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!supabaseUrl || !serviceRoleKey) {
    console.error("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY");
    return jsonResponse({ error: "Server configuration error" }, 500);
  }

  let body: { username?: unknown; password?: unknown; deviceId?: unknown };
  try {
    body = await req.json();
  } catch {
    return jsonResponse({ error: "Invalid JSON body" }, 400, origin);
  }

  const rawUsername = body.username;
  const password = body.password;
  const deviceId = body.deviceId;

  if (typeof rawUsername !== "string" || !rawUsername.trim()) {
    return jsonResponse({ error: "请输入用户名" }, 400, origin);
  }
  if (!isValidPassword(password)) {
    return jsonResponse({ error: "密码至少 6 位" }, 400, origin);
  }
  if (!isValidDeviceId(deviceId)) {
    return jsonResponse({ error: "无效的设备标识" }, 400, origin);
  }

  const admin = createClient(supabaseUrl, serviceRoleKey, {
    auth: { autoRefreshToken: false, persistSession: false },
  });

  let normalizedUsername: string;
  try {
    const { data, error } = await admin.rpc("community_normalize_username", {
      raw: rawUsername,
    });
    if (error) throw error;
    if (typeof data !== "string" || !data) {
      throw new Error("username normalization failed");
    }
    normalizedUsername = data;
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    if (msg.includes("username must be") || msg.includes("username required")) {
      return jsonResponse({
        error: "用户名为 3–24 位小写字母、数字或下划线",
      }, 400, origin);
    }
    console.error("normalize username:", msg);
    return jsonResponse({ error: "用户名格式无效" }, 400, origin);
  }

  const email = `${normalizedUsername}@${AUTH_DOMAIN}`;
  const pepper = Deno.env.get("COMMUNITY_REGISTRATION_PEPPER") ?? "";
  const ipHash = await sha256Hex(`${pepper}|ip|${clientIp(req)}`);
  const deviceHash = await sha256Hex(`${pepper}|device|${deviceId.trim()}`);
  const ua = req.headers.get("user-agent") ?? "";
  const userAgentHash = ua
    ? await sha256Hex(`${pepper}|ua|${ua}`)
    : null;

  const since = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
  const skipRateLimit = isRegistrationWhitelisted(req);

  const { data: existingProfile } = await admin
    .from("community_profiles")
    .select("user_id")
    .eq("username", normalizedUsername)
    .maybeSingle();

  if (existingProfile?.user_id) {
    return jsonResponse({ error: USERNAME_TAKEN_MESSAGE }, 409, origin);
  }

  if (!skipRateLimit) {
    const { count: ipCount, error: ipCountError } = await admin
      .from("community_registration_logs")
      .select("id", { count: "exact", head: true })
      .eq("ip_hash", ipHash)
      .gte("created_at", since);

    if (ipCountError) {
      console.error("ip rate check:", ipCountError.message);
      return jsonResponse({ error: "注册服务暂时不可用，请稍后重试" }, 500, origin);
    }
    if ((ipCount ?? 0) >= 1) {
      return jsonResponse({ error: RATE_LIMIT_MESSAGE }, 429, origin);
    }

    const { count: deviceCount, error: deviceCountError } = await admin
      .from("community_registration_logs")
      .select("id", { count: "exact", head: true })
      .eq("device_hash", deviceHash)
      .gte("created_at", since);

    if (deviceCountError) {
      console.error("device rate check:", deviceCountError.message);
      return jsonResponse({ error: "注册服务暂时不可用，请稍后重试" }, 500, origin);
    }
    if ((deviceCount ?? 0) >= 1) {
      return jsonResponse({ error: RATE_LIMIT_MESSAGE }, 429, origin);
    }
  }

  const { data: authUser, error: createError } = await admin.auth.admin
    .createUser({
      email,
      password,
      email_confirm: true,
    });

  if (createError) {
    const m = createError.message.toLowerCase();
    if (
      m.includes("already") || m.includes("registered") ||
      m.includes("exists")
    ) {
      return jsonResponse({ error: USERNAME_TAKEN_MESSAGE }, 409, origin);
    }
    if (
      m.includes("email rate limit") ||
      m.includes("over_email_send_rate_limit") ||
      m.includes("rate limit exceeded")
    ) {
      return jsonResponse({
        error:
          "认证邮件发送过于频繁（Supabase 默认约 2 封/小时）。请约 1 小时后再试，或在控制台关闭 Confirm email / 配置自定义 SMTP。",
      }, 429, origin);
    }
    console.error("createUser:", createError.message);
    return jsonResponse({ error: "注册失败，请稍后重试" }, 500, origin);
  }

  const uid = authUser.user?.id;
  if (!uid) {
    return jsonResponse({ error: "注册失败，请稍后重试" }, 500, origin);
  }

  const { error: profileError } = await admin.from("community_profiles").insert({
    user_id: uid,
    username: normalizedUsername,
    display_name: null,
    avatar_key: "default",
    role: "user",
    status: "active",
  });

  if (profileError) {
    console.error("profile insert:", profileError.message);
    await admin.auth.admin.deleteUser(uid);
    if (profileError.code === "23505") {
      return jsonResponse({ error: USERNAME_TAKEN_MESSAGE }, 409, origin);
    }
    return jsonResponse({ error: "注册失败，请稍后重试" }, 500, origin);
  }

  const { error: logError } = await admin.from("community_registration_logs")
    .insert({
      username: normalizedUsername,
      auth_user_id: uid,
      ip_hash: ipHash,
      device_hash: deviceHash,
      user_agent_hash: userAgentHash,
    });

  if (logError) {
    console.error("registration log:", logError.message);
    // User exists; do not fail registration for audit write failure.
  }

  return jsonResponse({ ok: true }, 200, origin);
});
