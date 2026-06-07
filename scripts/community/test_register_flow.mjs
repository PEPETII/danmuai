#!/usr/bin/env node
/**
 * Simulate production register: invoke guard + signIn (no signUp).
 * Usage: node scripts/community/test_register_flow.mjs [username]
 */
import { readFileSync, existsSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'

const __dirname = dirname(fileURLToPath(import.meta.url))
const ROOT = resolve(__dirname, '../..')
const ENV_PATH = resolve(ROOT, 'community-site/.env')
const requireFromSite = createRequire(resolve(ROOT, 'community-site/package.json'))
const { createClient } = requireFromSite('@supabase/supabase-js')

function loadEnv() {
  if (!existsSync(ENV_PATH)) return
  for (const line of readFileSync(ENV_PATH, 'utf8').split('\n')) {
    const t = line.trim()
    if (!t || t.startsWith('#')) continue
    const i = t.indexOf('=')
    if (i < 0) continue
    const key = t.slice(0, i).trim()
    let val = t.slice(i + 1).trim()
    if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'")))
      val = val.slice(1, -1)
    if (!process.env[key]) process.env[key] = val
  }
}

loadEnv()

const URL = process.env.VITE_SUPABASE_URL?.trim()
const ANON = process.env.VITE_SUPABASE_ANON_KEY?.trim()
const username = (process.argv[2] || `probe_${Date.now().toString(36)}`).toLowerCase()
const password = 'ProbeTest_9x!'
const deviceId = `probe-device-${Date.now()}`.padEnd(20, '0')
const email = `${username}@danmuai.test`

async function trySignUp(client) {
  const { data, error } = await client.auth.signUp({ email, password })
  return { data, error: error?.message ?? null, code: error?.code ?? null }
}

async function registerViaGuard(client) {
  const { data, error } = await client.functions.invoke('community-register-guard', {
    body: { username, password, deviceId },
  })
  let msg = data?.error ?? null
  if (!msg && error?.context?.json) {
    try {
      const body = await error.context.json()
      msg = body?.error ?? error.message
    } catch {
      msg = error.message
    }
  } else if (!msg && error) msg = error.message
  return { ok: data?.ok === true, data, error: msg, fnError: error?.message ?? null }
}

async function main() {
  if (!URL || !ANON) {
    console.error('Missing VITE_SUPABASE_URL or VITE_SUPABASE_ANON_KEY')
    process.exit(2)
  }
  const client = createClient(URL, ANON, {
    auth: { persistSession: false, autoRefreshToken: false },
  })

  console.log('=== Register flow probe (same as Vercel + .env) ===')
  console.log('Supabase:', URL)
  console.log('User:', username, '→', email)

  console.log('\n1) Public auth.signUp (what browser 400 shows if called):')
  const su = await trySignUp(client)
  console.log('   result:', su.error ?? 'ok', su.code ? `code=${su.code}` : '')

  console.log('\n2) community-register-guard (correct path):')
  const reg = await registerViaGuard(client)
  console.log('   ok:', reg.ok)
  console.log('   error:', reg.error ?? reg.fnError ?? '(none)')
  if (reg.ok) {
    const { error: si } = await client.auth.signInWithPassword({ email, password })
    console.log('\n3) signInWithPassword after register:')
    console.log('   ', si ? `FAIL: ${si.message}` : 'PASS')
  }
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
