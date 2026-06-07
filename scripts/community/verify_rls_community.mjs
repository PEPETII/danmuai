#!/usr/bin/env node
/**
 * DanmuAI community RLS acceptance (anon + user_a + user_b).
 *
 * Env (load from community-site/.env or shell):
 *   VITE_SUPABASE_URL, VITE_SUPABASE_ANON_KEY
 *   COMMUNITY_TEST_USER_A, COMMUNITY_TEST_PASS_A
 *   COMMUNITY_TEST_USER_B, COMMUNITY_TEST_PASS_B
 *   SUPABASE_SERVICE_ROLE_KEY (optional, for 9.x/10.x staff/admin setup)
 *
 * Run: node scripts/community/verify_rls_community.mjs
 * (from repo root; uses community-site/node_modules)
 */

import { readFileSync, existsSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { createRequire } from 'node:module'

const __dirname = dirname(fileURLToPath(import.meta.url))
const ROOT = resolve(__dirname, '../..')
const requireFromSite = createRequire(resolve(ROOT, 'community-site/package.json'))
const { createClient } = requireFromSite('@supabase/supabase-js')
const ENV_PATH = resolve(ROOT, 'community-site/.env')

function loadEnvFile() {
  if (!existsSync(ENV_PATH)) return
  const text = readFileSync(ENV_PATH, 'utf8')
  for (const line of text.split('\n')) {
    const t = line.trim()
    if (!t || t.startsWith('#')) continue
    const i = t.indexOf('=')
    if (i < 0) continue
    const key = t.slice(0, i).trim()
    let val = t.slice(i + 1).trim()
    if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
      val = val.slice(1, -1)
    }
    if (!process.env[key]) process.env[key] = val
  }
}

loadEnvFile()

const URL = process.env.VITE_SUPABASE_URL?.trim()
const ANON = process.env.VITE_SUPABASE_ANON_KEY?.trim()
const USER_A = process.env.COMMUNITY_TEST_USER_A?.trim() || 'user_a'
const PASS_A = process.env.COMMUNITY_TEST_PASS_A
const USER_B = process.env.COMMUNITY_TEST_USER_B?.trim() || 'user_b'
const PASS_B = process.env.COMMUNITY_TEST_PASS_B

const AUTH_DOMAIN = 'danmuai.test'
const results = []

function emailFor(username) {
  return `${username.trim().toLowerCase()}@${AUTH_DOMAIN}`
}

function fail(msg) {
  return { ok: false, detail: msg }
}

function pass(detail = 'ok') {
  return { ok: true, detail }
}

function record(id, scenario, expected, actual, ok) {
  results.push({ id, scenario, expected, actual, pass: ok ? 'YES' : 'NO' })
}

/** RLS often returns no error when 0 rows updated/deleted. */
function writeDenied(result) {
  if (result.error) return true
  if (Array.isArray(result.data)) return result.data.length === 0
  return false
}

function writeAllowed(result) {
  return !result.error && (!Array.isArray(result.data) || result.data.length > 0)
}

async function ensureSignedIn(client, username, password) {
  const email = emailFor(username)
  let { data, error } = await client.auth.signInWithPassword({ email, password })
  if (!error && data.session) return data.user

  const signUp = await client.auth.signUp({ email, password })
  if (signUp.error) throw new Error(`signUp ${username}: ${signUp.error.message}`)
  const uid = signUp.data.user?.id
  if (!uid) throw new Error(`signUp ${username}: no user id`)

  const { error: profErr } = await client.from('community_profiles').insert({
    user_id: uid,
    username: username.trim().toLowerCase(),
    avatar_key: 'default',
    role: 'user',
    status: 'active',
  })
  if (profErr && profErr.code !== '23505') {
    throw new Error(`profile ${username}: ${profErr.message}`)
  }

  ;({ data, error } = await client.auth.signInWithPassword({ email, password }))
  if (error || !data.session) throw new Error(`signIn ${username}: ${error?.message}`)
  return data.user
}

function postPayload(suffix = '') {
  return {
    title: `RLS测试帖${suffix}`.slice(0, 40),
    content: `这是一条用于 RLS 验收的测试正文，至少十个字。${suffix}`,
    category: 'experience',
    tags: ['rls_test'],
  }
}

async function main() {
  if (!URL || !ANON) {
    console.error('Missing VITE_SUPABASE_URL or VITE_SUPABASE_ANON_KEY')
    process.exit(2)
  }
  if (!PASS_A || !PASS_B) {
    console.error('Missing COMMUNITY_TEST_PASS_A or COMMUNITY_TEST_PASS_B')
    process.exit(2)
  }

  const anon = createClient(URL, ANON, { auth: { persistSession: false, autoRefreshToken: false } })
  const clientA = createClient(URL, ANON, { auth: { persistSession: false, autoRefreshToken: false } })
  const clientB = createClient(URL, ANON, { auth: { persistSession: false, autoRefreshToken: false } })

  const userA = await ensureSignedIn(clientA, USER_A, PASS_A)
  const userB = await ensureSignedIn(clientB, USER_B, PASS_B)

  // --- Setup: A creates post, B creates comment on it ---
  const { data: postRow, error: postErr } = await clientA
    .from('community_posts')
    .insert({ ...postPayload('_setup'), author_id: userA.id })
    .select('id')
    .single()
  if (postErr) throw new Error(`setup post: ${postErr.message}`)
  const postId = postRow.id

  const { data: commentRow, error: commentErr } = await clientB
    .from('community_comments')
    .insert({
      post_id: postId,
      author_id: userB.id,
      content: 'B 的验收评论内容',
    })
    .select('id')
    .single()
  if (commentErr) throw new Error(`setup comment: ${commentErr.message}`)
  const commentId = commentRow.id

  await clientA.from('community_post_likes').insert({ post_id: postId, user_id: userA.id })

  // ========== 1. Anonymous ==========
  {
    const { data, error } = await anon.from('community_posts').select('id').limit(1)
    record('1.1', '匿名可读未删帖子', '成功', error ? error.message : `${data?.length ?? 0} 行`, !error)
  }
  {
    const { data, error } = await anon.from('community_comments').select('id').limit(1)
    record('1.2', '匿名可读未删评论', '成功', error ? error.message : `${data?.length ?? 0} 行`, !error)
  }
  {
    const { error } = await anon.from('community_posts').insert({
      ...postPayload('_anon'),
      author_id: userA.id,
    })
    record('1.3', '匿名不能发帖', '拒绝', error?.message ?? 'insert ok', !!error)
  }
  {
    const { error } = await anon.from('community_comments').insert({
      post_id: postId,
      author_id: userB.id,
      content: '匿名评论',
    })
    record('1.4', '匿名不能评论', '拒绝', error?.message ?? 'insert ok', !!error)
  }
  {
    const { error } = await anon.from('community_post_likes').insert({
      post_id: postId,
      user_id: userA.id,
    })
    record('1.5', '匿名不能点赞', '拒绝', error?.message ?? 'insert ok', !!error)
  }
  {
    const r = await anon
      .from('community_posts')
      .update({ is_deleted: true })
      .eq('id', postId)
      .select('id')
    record(
      '1.6',
      '匿名不能删帖',
      '拒绝',
      r.error?.message ?? (writeDenied(r) ? '0 行' : 'update ok'),
      writeDenied(r),
    )
  }
  {
    const r = await anon
      .from('community_comments')
      .update({ is_deleted: true })
      .eq('id', commentId)
      .select('id')
    record(
      '1.7',
      '匿名不能删评',
      '拒绝',
      r.error?.message ?? (writeDenied(r) ? '0 行' : 'update ok'),
      writeDenied(r),
    )
  }

  // ========== 2. A post permissions ==========
  let aOwnPostId = postId
  {
    const { data, error } = await clientA
      .from('community_posts')
      .insert({ ...postPayload('_a2'), author_id: userA.id })
      .select('id')
      .single()
    record('2.1', 'A 可以发帖', '成功', error?.message ?? data?.id, !error && !!data?.id)
    if (data?.id) aOwnPostId = data.id
  }
  {
    const r = await clientA
      .from('community_posts')
      .update({ is_deleted: true, deleted_at: new Date().toISOString() })
      .eq('id', aOwnPostId)
      .select('id')
    record('2.2', 'A 可以软删自己的帖', '成功', r.error?.message ?? 'ok', writeAllowed(r))
  }
  // Recreate post for edit tests
  const { data: editPost } = await clientA
    .from('community_posts')
    .insert({ ...postPayload('_edit'), author_id: userA.id })
    .select('id')
    .single()
  const editPostId = editPost?.id
  for (const [id, field, val] of [
    ['2.3', 'title', '篡改标题'],
    ['2.4', 'content', '篡改正文但长度需够十个字以上才行'],
    ['2.5', 'category', 'help'],
    ['2.6', 'tags', ['x']],
  ]) {
    const { error } = await clientA.from('community_posts').update({ [field]: val }).eq('id', editPostId)
    record(id, `A 不能改自己帖子 ${field}`, '拒绝', error?.message ?? 'update ok', !!error)
  }

  // ========== 3. Cross-user posts ==========
  const { data: aPostForB } = await clientA
    .from('community_posts')
    .insert({ ...postPayload('_cross'), author_id: userA.id })
    .select('id')
    .single()
  const crossPostId = aPostForB.id
  {
    const r = await clientB
      .from('community_posts')
      .update({ is_deleted: true })
      .eq('id', crossPostId)
      .select('id')
    record(
      '3.1',
      'B 不能删 A 的帖',
      '拒绝',
      r.error?.message ?? (writeDenied(r) ? '0 行' : 'update ok'),
      writeDenied(r),
    )
  }
  {
    const r = await clientB
      .from('community_posts')
      .update({ title: 'B改标题' })
      .eq('id', crossPostId)
      .select('id')
    record(
      '3.2',
      'B 不能改 A 的帖',
      '拒绝',
      r.error?.message ?? (writeDenied(r) ? '0 行' : 'update ok'),
      writeDenied(r) || !!r.error,
    )
  }
  await clientA
    .from('community_posts')
    .update({ is_deleted: true, deleted_at: new Date().toISOString() })
    .eq('id', crossPostId)
  {
    const r = await clientB
      .from('community_posts')
      .update({ is_deleted: false })
      .eq('id', crossPostId)
      .select('id')
    record(
      '3.3',
      'B 不能恢复 A 已删帖',
      '拒绝',
      r.error?.message ?? (writeDenied(r) ? '0 行' : 'update ok'),
      writeDenied(r) || !!r.error,
    )
  }

  // ========== 4. Comments ==========
  const { data: commentPost } = await clientA
    .from('community_posts')
    .insert({ ...postPayload('_cmt'), author_id: userA.id })
    .select('id')
    .single()
  const cmtPostId = commentPost.id
  let bCommentId
  {
    const { error } = await clientA.from('community_comments').insert({
      post_id: cmtPostId,
      author_id: userA.id,
      content: 'A 的评论',
    })
    record('4.1', 'A 可以评论', '成功', error?.message ?? 'ok', !error)
  }
  {
    const { data, error } = await clientB
      .from('community_comments')
      .insert({
        post_id: cmtPostId,
        author_id: userB.id,
        content: 'B 在 A 帖下评论',
      })
      .select('id')
      .single()
    record('4.2', 'B 可以在 A 帖下评论', '成功', error?.message ?? data?.id, !error && !!data?.id)
    bCommentId = data?.id
  }
  {
    const r = await clientB
      .from('community_comments')
      .update({ is_deleted: true })
      .eq('id', bCommentId)
      .select('id')
    record('4.3', 'B 可以软删自己的评论', '成功', r.error?.message ?? 'ok', writeAllowed(r))
  }
  // New comment for post-owner delete
  const { data: bComment2 } = await clientB
    .from('community_comments')
    .insert({
      post_id: cmtPostId,
      author_id: userB.id,
      content: '待帖主删除的评论',
    })
    .select('id')
    .single()
  {
    const r = await clientA
      .from('community_comments')
      .update({ is_deleted: true })
      .eq('id', bComment2.id)
      .select('id')
    record('4.4', 'A 帖主可删 B 的评论', '成功', r.error?.message ?? 'ok', writeAllowed(r))
  }
  {
    const r = await anon
      .from('community_comments')
      .update({ is_deleted: true })
      .eq('id', bComment2.id)
      .select('id')
    record(
      '4.5',
      '匿名不能删评论',
      '拒绝',
      r.error?.message ?? (writeDenied(r) ? '0 行' : 'update ok'),
      writeDenied(r),
    )
  }
  const { data: aSelfCmt } = await clientA
    .from('community_comments')
    .insert({
      post_id: cmtPostId,
      author_id: userA.id,
      content: 'A 在自己帖下的评论',
    })
    .select('id')
    .single()
  {
    const r = await clientB
      .from('community_comments')
      .update({ is_deleted: true })
      .eq('id', aSelfCmt.id)
      .select('id')
    record(
      '4.7',
      'B 不能删 A 的评论（非帖主）',
      '拒绝',
      r.error?.message ?? (writeDenied(r) ? '0 行' : 'update ok'),
      writeDenied(r),
    )
  }
  const { data: bOwnCmt } = await clientB
    .from('community_comments')
    .insert({
      post_id: cmtPostId,
      author_id: userB.id,
      content: 'B 另一条评论',
    })
    .select('id')
    .single()
  {
    const { error } = await clientB
      .from('community_comments')
      .update({ content: '篡改评论' })
      .eq('id', bOwnCmt.id)
    record('4.6', 'B 不能编辑评论内容', '拒绝', error?.message ?? 'update ok', !!error)
  }

  // ========== 5. Likes ==========
  const { data: likePost } = await clientA
    .from('community_posts')
    .insert({ ...postPayload('_like'), author_id: userA.id })
    .select('id')
    .single()
  const likePostId = likePost.id
  {
    const { error } = await clientA.from('community_post_likes').insert({
      post_id: likePostId,
      user_id: userA.id,
    })
    record('5.1', '登录用户可点赞', '成功', error?.message ?? 'ok', !error)
  }
  {
    const { error } = await clientA.from('community_post_likes').insert({
      post_id: likePostId,
      user_id: userA.id,
    })
    const dup = !!error && (error.code === '23505' || error.message.includes('duplicate'))
    record('5.2', '不能重复点赞', '拒绝', error?.message ?? 'insert ok', dup)
  }
  {
    const r = await clientB
      .from('community_post_likes')
      .delete()
      .eq('post_id', likePostId)
      .eq('user_id', userA.id)
      .select('post_id')
    record(
      '5.3',
      '不能删别人的赞',
      '拒绝',
      r.error?.message ?? (writeDenied(r) ? '0 行' : 'delete ok'),
      writeDenied(r),
    )
  }
  {
    const r = await clientA
      .from('community_post_likes')
      .delete()
      .eq('post_id', likePostId)
      .eq('user_id', userA.id)
      .select('post_id')
    record('5.4', '可以取消自己的赞', '成功', r.error?.message ?? 'ok', writeAllowed(r))
  }

  // ========== 6. Soft-delete visibility ==========
  const { data: visPost } = await clientA
    .from('community_posts')
    .insert({ ...postPayload('_vis'), author_id: userA.id })
    .select('id')
    .single()
  const visPostId = visPost.id
  await clientA
    .from('community_posts')
    .update({ is_deleted: true, deleted_at: new Date().toISOString() })
    .eq('id', visPostId)
  {
    const { data, error } = await anon
      .from('community_posts')
      .select('id')
      .eq('id', visPostId)
      .maybeSingle()
    const hidden = !error && !data
    record('6.1', '已删帖不在列表查询', '0 行', hidden ? '0 行' : '仍可见', hidden)
  }
  {
    const { error } = await clientB.from('community_comments').insert({
      post_id: visPostId,
      author_id: userB.id,
      content: '评已删帖',
    })
    record('6.2', '不能评已删帖', '拒绝', error?.message ?? 'insert ok', !!error)
  }
  const { data: visCmt } = await clientB
    .from('community_comments')
    .insert({
      post_id: cmtPostId,
      author_id: userB.id,
      content: '待删可见性评论',
    })
    .select('id')
    .single()
  await clientB.from('community_comments').update({ is_deleted: true }).eq('id', visCmt.id)
  {
    const { data, error } = await anon
      .from('community_comments')
      .select('id')
      .eq('id', visCmt.id)
      .maybeSingle()
    const hidden = !error && !data
    record('6.3', '已删评不可读', '0 行', hidden ? '0 行' : '仍可见', hidden)
  }

  // ========== 7. Image restrictions ==========
  const { data: imgPost } = await clientA
    .from('community_posts')
    .insert({ ...postPayload('_img'), author_id: userA.id })
    .select('id')
    .single()
  const imgPostId = imgPost.id
  {
    const { error } = await clientB.from('community_comments').insert({
      post_id: imgPostId,
      author_id: userB.id,
      content: '看 ![x](http://y/z.png)',
    })
    record('7.1', '评论禁 markdown 图片', '拒绝', error?.message ?? 'insert ok', !!error)
  }
  {
    const { error } = await clientB.from('community_comments').insert({
      post_id: imgPostId,
      author_id: userB.id,
      content: '链接 https://example.com/a.png 不行',
    })
    record('7.2', '评论禁图片 URL', '拒绝', error?.message ?? 'insert ok', !!error)
  }
  {
    const { error } = await clientA.from('community_posts').insert({
      title: '图帖',
      content: '正文 ![bad](http://x/y.png) 至少十字',
      category: 'experience',
      tags: [],
      author_id: userA.id,
    })
    record('7.3', '帖子禁 markdown 图片', '拒绝', error?.message ?? 'insert ok', !!error)
  }
  {
    const { error } = await clientA.from('community_posts').insert({
      title: '图帖2',
      content: '正文见 https://example.com/a.png 至少十个字',
      category: 'experience',
      tags: [],
      author_id: userA.id,
    })
    record('7.4', '帖子禁图片 URL', '拒绝', error?.message ?? 'insert ok', !!error)
  }

  // ========== 8. Reports (006) ==========
  const { data: reportPost } = await clientA
    .from('community_posts')
    .insert({ ...postPayload('_rpt'), author_id: userA.id })
    .select('id')
    .single()
  const reportPostId = reportPost?.id
  {
    const { error } = await clientB.from('community_reports').insert({
      reporter_id: userB.id,
      target_type: 'post',
      post_id: reportPostId,
      reason: 'RLS 验收举报',
    })
    record('8.1', 'B 可举报 A 的帖', '成功', error?.message ?? 'ok', !error)
  }
  {
    const { error } = await clientB.from('community_reports').insert({
      reporter_id: userB.id,
      target_type: 'post',
      post_id: reportPostId,
      reason: '重复举报',
    })
    const dup = !!error && (error.code === '23505' || error.message.includes('duplicate'))
    record('8.2', '不能重复举报同一帖', '拒绝', error?.message ?? 'insert ok', dup)
  }
  {
    const { data, error } = await clientB
      .from('community_reports')
      .select('id')
      .eq('status', 'pending')
    const denied = !!error || (data ?? []).length === 0
    record(
      '8.3',
      '普通用户不能读举报列表',
      '0 行',
      error?.message ?? `${data?.length ?? 0} 行`,
      denied,
    )
  }
  {
    const { error } = await anon.from('community_reports').insert({
      reporter_id: userA.id,
      target_type: 'post',
      post_id: reportPostId,
    })
    record('8.4', '匿名不能举报', '拒绝', error?.message ?? 'insert ok', !!error)
  }

  // ========== 9–10. Staff / ban (006, needs service role setup) ==========
  const SERVICE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY?.trim()
  if (!SERVICE_KEY) {
    for (const [id, scenario] of [
      ['9.0', 'staff 用例需 SUPABASE_SERVICE_ROLE_KEY'],
      ['10.0', '封禁用例需 SUPABASE_SERVICE_ROLE_KEY'],
    ]) {
      record(id, scenario, 'SKIP', '未配置 service role', 'YES')
    }
  } else {
    const adminClient = createClient(URL, SERVICE_KEY, {
      auth: { persistSession: false, autoRefreshToken: false },
    })
    await adminClient
      .from('community_profiles')
      .update({ role: 'moderator' })
      .eq('user_id', userA.id)

    const { data: staffPost } = await clientA
      .from('community_posts')
      .insert({ ...postPayload('_staff'), author_id: userB.id })
      .select('id')
      .single()
    const staffPostId = staffPost?.id

    {
      const r = await clientA
        .from('community_posts')
        .update({ is_deleted: true, deleted_at: new Date().toISOString() })
        .eq('id', staffPostId)
        .select('id')
      record('9.1', '版主可软删他人帖子', '成功', r.error?.message ?? 'ok', writeAllowed(r))
    }
    {
      const r = await clientA
        .from('community_posts')
        .update({ is_featured: true })
        .eq('id', reportPostId)
        .select('id')
      record('9.2', '版主可设精华', '成功', r.error?.message ?? 'ok', writeAllowed(r))
    }
    {
      const { data, error } = await clientA
        .from('community_reports')
        .select('id')
        .eq('status', 'pending')
        .limit(5)
      record(
        '9.3',
        '版主可读举报列表',
        '成功',
        error?.message ?? `${data?.length ?? 0} 行`,
        !error && (data?.length ?? 0) > 0,
      )
    }

    await adminClient
      .from('community_profiles')
      .update({ role: 'admin' })
      .eq('user_id', userA.id)

    await adminClient
      .from('community_profiles')
      .update({ status: 'banned' })
      .eq('user_id', userB.id)

    {
      const { error } = await clientB.from('community_posts').insert({
        ...postPayload('_banned'),
        author_id: userB.id,
      })
      record('10.1', '封禁用户不能发帖', '拒绝', error?.message ?? 'insert ok', !!error)
    }
    {
      const { error } = await clientB.from('community_comments').insert({
        post_id: reportPostId,
        author_id: userB.id,
        content: '封禁评论',
      })
      record('10.2', '封禁用户不能评论', '拒绝', error?.message ?? 'insert ok', !!error)
    }
    {
      const { error } = await clientB.from('community_post_likes').insert({
        post_id: reportPostId,
        user_id: userB.id,
      })
      record('10.3', '封禁用户不能点赞', '拒绝', error?.message ?? 'insert ok', !!error)
    }
    {
      const { error } = await clientB.from('community_reports').insert({
        reporter_id: userB.id,
        target_type: 'post',
        post_id: reportPostId,
      })
      record('10.4', '封禁用户不能举报', '拒绝', error?.message ?? 'insert ok', !!error)
    }

    await adminClient
      .from('community_profiles')
      .update({ status: 'active', role: 'user' })
      .eq('user_id', userB.id)
    await adminClient
      .from('community_profiles')
      .update({ role: 'user' })
      .eq('user_id', userA.id)
  }

  // Summary
  console.log('\n=== DanmuAI Community RLS Acceptance ===\n')
  console.table(results)
  const failed = results.filter((r) => r.pass === 'NO')
  console.log(`\nTotal: ${results.length}, Pass: ${results.length - failed.length}, Fail: ${failed.length}`)
  if (failed.length) {
    console.log('\nFailed cases:')
    for (const f of failed) console.log(`  ${f.id} ${f.scenario}: ${f.actual}`)
    process.exit(1)
  }
  process.exit(0)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
