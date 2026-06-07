#!/usr/bin/env node
/** One-off: create/promote admin. Reads community-site/.env (service role). */
import { readFileSync, existsSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'
import { randomBytes } from 'node:crypto'

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
const SERVICE = process.env.SUPABASE_SERVICE_ROLE_KEY?.trim()
const USERNAME = (process.env.ADMIN_USERNAME || 'danmu_admin').trim().toLowerCase()
const DOMAIN = 'danmuai.test'

async function main() {
  if (!URL || !SERVICE) {
    console.error('Need VITE_SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in community-site/.env')
    process.exit(2)
  }
  const admin = createClient(URL, SERVICE, {
    auth: { autoRefreshToken: false, persistSession: false },
  })

  const { data: existing } = await admin
    .from('community_profiles')
    .select('user_id, role')
    .eq('username', USERNAME)
    .maybeSingle()

  let password = process.env.ADMIN_PASSWORD?.trim()
  if (!password) password = randomBytes(12).toString('base64url')

  if (existing?.user_id) {
    await admin.from('community_profiles').update({ role: 'admin', status: 'active' }).eq('user_id', existing.user_id)
    if (process.env.ADMIN_RESET_PASSWORD === '1') {
      await admin.auth.admin.updateUserById(existing.user_id, { password })
    }
    console.log(JSON.stringify({ action: 'promoted', username: USERNAME, password: process.env.ADMIN_RESET_PASSWORD === '1' ? password : '(unchanged)' }))
    return
  }

  const email = `${USERNAME}@${DOMAIN}`
  const { data: created, error } = await admin.auth.admin.createUser({
    email,
    password,
    email_confirm: true,
  })
  if (error) {
    console.error(error.message)
    process.exit(1)
  }
  const uid = created.user.id
  await admin.from('community_profiles').insert({
    user_id: uid,
    username: USERNAME,
    avatar_key: 'default',
    role: 'admin',
    status: 'active',
  })
  console.log(JSON.stringify({ action: 'created', username: USERNAME, email, password }))
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
