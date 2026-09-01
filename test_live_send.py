import sys, os, time, tempfile, uuid
sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright

raw_cookie_file = """# Netscape HTTP Cookie File
# https://curl.haxx.se/rfc/cookie_spec.html
# This is a generated file! Do not edit.

.instagram.com    TRUE    /    TRUE    1822793454    datr    7kaWal3CdTqySOKeDxy2l3wQ
.instagram.com    TRUE    /    TRUE    1819769454    ig_did    2CE5B7F6-483D-48CB-8B2A-052219F0988A
.instagram.com    TRUE    /    TRUE    1822793454    mid    apZG7gALAAEovxC_eAXZ1vZD4HLr
.instagram.com    TRUE    /    TRUE    1822841240    csrftoken    FWfDjqn2jlJlF7wevO3gglftEDHkhsEV
.instagram.com    TRUE    /    TRUE    1796057240    ds_user_id    37149924932
.instagram.com    TRUE    /    TRUE    1788885915    dpr    0.625
.instagram.com    TRUE    /    TRUE    1819817114    sessionid    37149924932%3Anfe1wNoQAPXLba%3A2%3AAYh8fhU0bmcsPLk0v4v27MIgNH9uZmeA6fsbKa30LQ
.instagram.com    TRUE    /    TRUE    1788886035    wd    3072x1347
.instagram.com    TRUE    /    TRUE    0    rur    "LLA\\05437149924932\\0541819817240:01ffd7397ab51a2f98971be6ccc2c55ecc4748ae7716ae5d25f7b5363ffd4e464573c2e5"
"""

group_url = "https://www.instagram.com/direct/t/953837224403204/"

sys.path.insert(0, r"C:\Users\Prince Kumar\Music\IGTGWP")
from importlib import import_module
mod = import_module("5")
parse_fn = getattr(mod, "parse_instagram_cookie_input")

cookies_dict, clean_sess, clean_csrf, user_id = parse_fn(raw_cookie_file)

user_data_dir = os.path.join(tempfile.gettempdir(), f"test_full_ua_{uuid.uuid4().hex[:6]}")

ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"

with sync_playwright() as p:
    browser = p.chromium.launch_persistent_context(
        user_data_dir,
        headless=True,
        user_agent=ua,
        viewport={"width": 1280, "height": 720},
        locale="en-US",
        timezone_id="Asia/Kolkata",
        args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--disable-notifications"]
    )
    cookie_list = []
    for k, v in cookies_dict.items():
        cookie_list.append({
            "name": k,
            "value": v,
            "domain": ".instagram.com",
            "path": "/",
            "secure": True
        })
    browser.add_cookies(cookie_list)
    page = browser.new_page()

    page.goto(group_url, wait_until="networkidle", timeout=45000)
    time.sleep(4)

    print("Final Page URL:", page.url)
    print("Final Page Title:", page.title())

    # Dismiss notification modal if present
    for btn_text in ["Not Now", "Cancel", "Not now", "Decline", "Dismiss", "Close"]:
        try:
            b = page.locator(f'button:has-text("{btn_text}")')
            if b.count() > 0 and b.first.is_visible():
                b.first.click(timeout=1000)
                time.sleep(0.5)
        except Exception:
            pass

    # Check for direct message textbox
    input_box = page.locator('div[aria-label="Message"], div[contenteditable="true"], div[role="textbox"]').first
    if input_box.count() > 0 and input_box.is_visible():
        input_box.click(timeout=3000, force=True)
        time.sleep(0.2)
        test_msg = "[SERVER GOD CLAN] ⚡ King Bot Live Strike Verified 👑🔥"
        input_box.fill(test_msg)
        time.sleep(0.5)
        page.keyboard.press("Enter")
        time.sleep(2)
        print("🎉 SUCCESS: Message successfully sent into the Group Chat!")
    else:
        print("Page text snippet:", page.locator("body").inner_text()[:300])

    browser.close()
