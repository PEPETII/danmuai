#!/usr/bin/env node
/**
 * Smoke test for community-register-guard Edge Function.
 * Env from community-site/.env: VITE_SUPABASE_URL, VITE_SUPABASE_ANON_KEY
 *
 * One run validates device + IP limits (same calendar IP within 24h).
 * Re-running within 24h may fail at step 1 — wait or use another network.
 *
 * Run: node scripts/community/verify_register_guard.mjs
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

async function invokeGuard(client, username, password, deviceId) {
  const { data, error } = await client.functions.invoke('community-register-guard', {
    body: { username, password, deviceId },
  })
  if (!error && data?.ok === true) {
    return { ok: true, error: null }
  }
  let msg = data?.error ?? null
  if (!msg && error?.context && typeof error.context.json === 'function') {
    try {
      const body = await error.context.json()
      msg = body?.error ?? error.message
    } catch {
      msg = error.message
    }
  }
  if (!msg && error?.message) msg = error.message
  return { ok: false, error: msg }
}

function isRateLimit(msg) {
  return String(msg).includes('今天已经注册过')
}

async function main() {
  if (!URL || !ANON) {
    console.error('Missing VITE_SUPABASE_URL or VITE_SUPABASE_ANON_KEY')
    process.exit(2)
  }

  const client = createClient(URL, ANON, {
    auth: { persistSession: false, autoRefreshToken: false },
  })

  const runId = Date.now().toString(36)
  const deviceA = `verify-${runId}-deviceaaaaaa`
  const deviceB = `verify-${runId}-devicebbbbbb`
  const password = 'VerifyPass_9x!'
  const user1 = `vg1_${runId}`
  const user2 = `vg2_${runId}`
  const user3 = `vg3_${runId}`

  console.log('1) First registration (expect ok)...')
  const r1 = await invokeGuard(client, user1, password, deviceA)
  if (!r1.ok) {
    if (isRateLimit(r1.error)) {
      console.log(
        'SKIP: IP already used in last 24h (re-run tomorrow or from another network).',
      )
      process.exit(0)
    }
    console.log(`FAIL: ${r1.error}`)
    process.exit(1)
  }
  console.log('PASS')

  console.log('2) Same device, new username (expect device rate limit)...')
  const r2 = await invokeGuard(client, user2, password, deviceA)
  if (!isRateLimit(r2.error)) {
    console.log(`FAIL: ${r2.error}`)
    process.exit(1)
  }
  console.log('PASS')

  console.log('3) New device, same IP, new username (expect IP rate limit)...')
  const r3 = await invokeGuard(client, user3, password, deviceB)
  if (!isRateLimit(r3.error)) {
    console.log(`FAIL: ${r3.error}`)
    process.exit(1)
  }
  console.log('PASS')

  console.log('4) Duplicate username (expect taken)...')
  const r4 = await invokeGuard(client, user1, password, deviceB)
  const taken = !r4.ok && String(r4.error).includes('用户名已存在')
  console.log(taken ? 'PASS' : `FAIL: ${r4.error}`)
  if (!taken) process.exit(1)

  console.log('\nAll registration guard checks passed.')
  process.exit(0)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
