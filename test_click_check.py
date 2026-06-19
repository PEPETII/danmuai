"""Verify DanmuAI web console is fully functional after both fixes."""
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    errors = []
    page.on("console", lambda msg: errors.append(msg) if msg.type == "error" else None)

    page.goto("http://127.0.0.1:18765", timeout=15000)
    page.wait_for_load_state("networkidle", timeout=15000)

    # Test all sidebar navigation
    pages = ["overview", "persona", "danmu-pool", "pet", "settings", "logs"]
    all_ok = True
    for page_name in pages:
        btn = page.locator(f'#nav [data-page="{page_name}"]')
        if btn.count() == 0:
            print(f"  SKIP {page_name}: button not found")
            continue
        btn.click()
        page.wait_for_timeout(800)
        panel = page.locator(f"#page-{page_name}")
        cls = panel.get_attribute("class") or ""
        is_active = "active" in cls
        status = "OK" if is_active else "FAIL"
        if not is_active:
            all_ok = False
        print(f"  {page_name}: {status} (class='{cls[:60]}')")

    # Check for JS errors
    if errors:
        print(f"\n{len(errors)} JS errors:")
        for e in errors[:5]:
            print(f"  - {e.text[:200]}")
        all_ok = False
    else:
        print("\nNo JS errors!")

    print(f"\nOverall: {'PASS' if all_ok else 'FAIL'}")
    browser.close()
