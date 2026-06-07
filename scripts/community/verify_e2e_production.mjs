#!/usr/bin/env node
/**
 * Production E2E: register (or login fallback) → post → comment → like → report.
 * Env: community-site/.env (VITE_SUPABASE_*, optional COMMUNITY_TEST_USER_B + PASS_B for report)
 */
import { readFileSync, existsSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'

const __dirname = dirname(fileURLToPath(import.meta.url))
const ROOT = resolve(__dirname, '../..')
const requireFromSite = createRequire(resolve(ROOT, 'community-site/package.json'))
const { createClient } = requireFromSite('@supabase/supabase-js')
const ENV_PATH = resolve(ROOT, 'community-site/.env')
const PRODUCTION_SITE = 'https://community-site-two.vercel.app'
const AUTH_DOMAIN = 'danmuai.test'

function loadEnvFile() {
  if (!existsSync(ENV_PATH)) return
  for (const line of readFileSync(ENV_PATH, 'utf8').split('\n')) {
    const t = line.trim()
    if (!t || t.startsWith('#')) continue
    const i = t.indexOf('=')
    if (i < 0) continue
    const key = t.slice(0, i).trim()
    let val = t.slice(i + 1).trim()
    if (
      (val.startsWith('"') && val.endsWith('"')) ||
      (val.startsWith("'") && val.endsWith("'"))
    ) {
      val = val.slice(1, -1)
    }
    if (!process.env[key]) process.env[key] = val
  }
}

loadEnvFile()

const URL = process.env.VITE_SUPABASE_URL?.trim()
const ANON = process.env.VITE_SUPABASE_ANON_KEY?.trim()
const USER_B = process.env.COMMUNITY_TEST_USER_B?.trim()
const PASS_B = process.env.COMMUNITY_TEST_PASS_B

function emailFor(username) {
  return `${username.trim().toLowerCase()}@${AUTH_DOMAIN}`
}

async function invokeGuard(client, username, password, deviceId) {
  const { data, error } = await client.functions.invoke('community-register-guard', {
    body: { username, password, deviceId },
  })
  if (!error && data?.ok === true) return { ok: true }
  let msg = data?.error ?? error?.message ?? 'unknown'
  if (error?.context?.json) {
    try {
      const body = await error.context.json()
      msg = body?.error ?? msg
    } catch {
      /* ignore */
    }
  }
  return { ok: false, error: String(msg) }
}

function step(name, ok, detail = '') {
  const mark = ok ? 'PASS' : 'FAIL'
  console.log(`[${mark}] ${name}${detail ? `: ${detail}` : ''}`)
  return ok
}

async function fetchProductionHint() {
  try {
    const ctrl = new AbortController()
    const t = setTimeout(() => ctrl.abort(), 20000)
    const res = await fetch(PRODUCTION_SITE, { signal: ctrl.signal })
    clearTimeout(t)
    const html = await res.text()
    const mockBadge = html.includes('演示数据')
    return step(
      'Vercel 生产页可访问',
      res.ok,
      `status=${res.status} mockBadge=${mockBadge}`,
    )
  } catch (e) {
    return step('Vercel 生产页可访问', false, String(e.message || e))
  }
}

async function main() {
  if (!URL || !ANON) {
    console.error('Missing VITE_SUPABASE_URL or VITE_SUPABASE_ANON_KEY in community-site/.env')
    process.exit(2)
  }

  console.log('=== DanmuAI Community Production E2E ===\n')
  console.log(`Supabase: ${URL}`)
  console.log(`Vercel:   ${PRODUCTION_SITE}\n`)

  let allOk = true
  allOk = (await fetchProductionHint()) && allOk

  const runId = Date.now().toString(36)
  const username = `e2e_${runId}`
  const password = `E2ePass_${runId}!9`
  const deviceId = `e2e-${runId}-deviceid12`

  const client = createClient(URL, ANON, {
    auth: { persistSession: false, autoRefreshToken: false },
  })

  let activeUser = username
  let activePass = password
  let registeredFresh = false

  console.log('\n--- Auth ---')
  const reg = await invokeGuard(client, username, password, deviceId)
  if (reg.ok) {
    allOk = step('注册 (community-register-guard)', true, username) && allOk
    registeredFresh = true
  } else if (String(reg.error).includes('今天已经注册过')) {
    console.log(`[SKIP] 注册: IP 24h 限流 — ${reg.error}`)
    if (!process.env.COMMUNITY_TEST_USER_A || !process.env.COMMUNITY_TEST_PASS_A) {
      allOk = step('注册或回退测试账号', false, '无 COMMUNITY_TEST_USER_A/PASS_A') && allOk
    } else {
      activeUser = process.env.COMMUNITY_TEST_USER_A.trim()
      activePass = process.env.COMMUNITY_TEST_PASS_A
      allOk = step('注册跳过，使用已有测试账号', true, activeUser) && allOk
    }
  } else {
    allOk = step('注册 (community-register-guard)', false, reg.error) && allOk
  }

  const { data: signInData, error: signInErr } = await client.auth.signInWithPassword({
    email: emailFor(activeUser),
    password: activePass,
  })
  allOk =
    step(
      '登录 signInWithPassword',
      !signInErr && !!signInData.session,
      signInErr?.message ?? `uid=${signInData.session?.user?.id?.slice(0, 8)}…`,
    ) && allOk

  const uid = signInData.session?.user?.id
  if (!uid) {
    console.log('\nAbort: no session')
    process.exit(1)
  }

  const { data: profile, error: profErr } = await client
    .from('community_profiles')
    .select('username, role, status')
    .eq('user_id', uid)
    .maybeSingle()
  allOk =
    step(
      '读取 community_profiles',
      !profErr && profile?.username,
      profErr?.message ?? `${profile?.username} role=${profile?.role} status=${profile?.status}`,
    ) && allOk

  console.log('\n--- Content ---')
  const title = `E2E post ${runId}`
  const content = `Automated E2E at ${new Date().toISOString()}`
  const { data: postRow, error: postErr } = await client
    .from('community_posts')
    .insert({
      author_id: uid,
      title,
      content,
      category: 'experience',
      tags: ['e2e'],
    })
    .select('id')
    .single()
  allOk =
    step('发帖', !postErr && postRow?.id, postErr?.message ?? postRow?.id) && allOk
  const postId = postRow?.id

  if (postId) {
    const { error: cmtErr } = await client.from('community_comments').insert({
      post_id: postId,
      author_id: uid,
      content: `E2E comment ${runId}`,
    })
    allOk = step('评论', !cmtErr, cmtErr?.message) && allOk

    const { error: likeErr } = await client.from('community_post_likes').insert({
      post_id: postId,
      user_id: uid,
    })
    allOk = step('点赞', !likeErr, likeErr?.message) && allOk
  }

  console.log('\n--- Report (needs second user) ---')
  if (postId && USER_B && PASS_B) {
    const clientB = createClient(URL, ANON, {
      auth: { persistSession: false, autoRefreshToken: false },
    })
    const { error: bLoginErr } = await clientB.auth.signInWithPassword({
      email: emailFor(USER_B),
      password: PASS_B,
    })
    if (bLoginErr) {
      allOk = step('用户 B 登录（举报）', false, bLoginErr.message) && allOk
    } else {
      const bUid = (await clientB.auth.getSession()).data.session?.user?.id
      const { error: repErr } = await clientB.from('community_reports').insert({
        reporter_id: bUid,
        target_type: 'post',
        post_id: postId,
        reason: 'E2E 自动化验收举报',
      })
      allOk = step('举报', !repErr, repErr?.message) && allOk
      await clientB.auth.signOut()
    }
  } else {
    console.log('[SKIP] 举报: 未配置 COMMUNITY_TEST_USER_B/PASS_B 或发帖失败')
  }

  console.log('\n--- Session ---')
  const { error: outErr } = await client.auth.signOut()
  allOk = step('退出 signOut', !outErr, outErr?.message) && allOk

  const { data: reLogin, error: reErr } = await client.auth.signInWithPassword({
    email: emailFor(activeUser),
    password: activePass,
  })
  allOk =
    step('再次登录', !reErr && !!reLogin.session, reErr?.message) && allOk

  await client.auth.signOut()

  console.log('\n=== Summary ===')
  console.log(`Fresh register: ${registeredFresh}`)
  console.log(`User: ${activeUser}`)
  console.log(allOk ? 'ALL E2E CHECKS PASSED' : 'SOME CHECKS FAILED')
  process.exit(allOk ? 0 : 1)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
