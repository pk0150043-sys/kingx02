import requests, sys, urllib.parse, time, os, tempfile, uuid
sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright

sessionid = '37149924932%3AjHE1UPkTC1c0CE%3A8%3AAYg9jrRe6vg4ACs5GozkmrOEmIfu61SfcBUZyLGInA'
csrftoken = 'FWfDjqn2jlJlF7wevO3gglftEDHkhsEV'
group_link = 'https://www.instagram.com/direct/t/953837224403204/'

clean_sess = urllib.parse.unquote(sessionid).strip()
user_data_dir = os.path.join(tempfile.gettempdir(), f"test_ig_pw_{uuid.uuid4().hex[:6]}")

print("Testing Playwright with your session credentials...")
with sync_playwright() as p:
    browser = p.chromium.launch_persistent_context(
        user_data_dir,
        headless=True,
        args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--disable-notifications"]
    )
    cookie_list = [{
        "name": "sessionid",
        "value": clean_sess,
        "domain": ".instagram.com",
        "path": "/",
        "secure": True,
        "httpOnly": True
    }]
    if csrftoken and csrftoken != "missing":
        cookie_list.append({
            "name": "csrftoken",
            "value": csrftoken,
            "domain": ".instagram.com",
            "path": "/",
            "secure": True,
            "httpOnly": False
        })
    browser.add_cookies(cookie_list)
    page = browser.new_page()
    page.goto(group_link, timeout=45000, wait_until="domcontentloaded")
    time.sleep(3)

    print("Page URL:", page.url)
    print("Page Title:", page.title())

    # Send 1 test message via Playwright browser context
    input_box = page.locator('div[aria-label="Message"], div[contenteditable="true"], div[role="textbox"]').first
    if input_box.is_visible():
        input_box.click()
        input_box.fill("[SERVER GOD CLAN] ⚡ Playwright Browser Verification Test 👑")
        page.keyboard.press("Enter")
        time.sleep(2)
        print("✅ Message successfully typed and sent via Playwright browser!")
    else:
        print("⚠️ Input box not found. Page text snippet:", page.locator("body").inner_text()[:300])

    browser.close()
