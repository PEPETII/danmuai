#!/usr/bin/env node
/** Probe production Vercel bundle for signUp vs community-register-guard */
const BASE = process.argv[2] || 'https://community-site-two.vercel.app'

async function main() {
  console.log('Fetching', BASE)
  const res = await fetch(BASE, { redirect: 'follow' })
  console.log('index status', res.status, res.url)
  const html = await res.text()
  const scripts = [...html.matchAll(/src="(\/assets\/[^"]+\.js)"/g)].map((m) => m[1])
  console.log('script assets', scripts.length ? scripts : '(none)')
  for (const path of scripts) {
    const url = new URL(path, BASE).href
    const jsRes = await fetch(url)
    const js = await jsRes.text()
    const hasGuard = js.includes('community-register-guard')
    const hasSignUpCall = /auth\.signUp|\.signUp\s*\(/.test(js)
    const hasSignupPath = js.includes('/signup')
    console.log('\n---', path, '---')
    console.log('  bytes:', js.length)
    console.log('  community-register-guard:', hasGuard)
    console.log('  auth.signUp / .signUp(:', hasSignUpCall)
    console.log('  "/signup" string:', hasSignupPath)
  }
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
