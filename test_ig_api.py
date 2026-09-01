import requests, sys, urllib.parse, time, json
sys.stdout.reconfigure(encoding='utf-8')

sessionid = '37149924932%3AjHE1UPkTC1c0CE%3A8%3AAYg9jrRe6vg4ACs5GozkmrOEmIfu61SfcBUZyLGInA'
csrftoken = 'FWfDjqn2jlJlF7wevO3gglftEDHkhsEV'
tid = '953837224403204'

clean_sess = urllib.parse.unquote(sessionid).strip()
user_id = clean_sess.split(':')[0]

# Instagram Private API standard broadcast payload format
client_context = str(int(time.time() * 1000))
post_data = {
    'action': 'send_item',
    'thread_ids': f'[{tid}]',
    'item_type': 'text',
    'text': '[SERVER GOD CLAN] Playwright Private API Online 🔥👑',
    'client_context': client_context,
    'mutation_token': client_context,
    'offline_threading_id': client_context,
    '_uuid': 'b5b85a3c-1b74-4b5b-8664-dfa053c9e6aa',
    '_csrftoken': csrftoken,
    '_uid': user_id,
    'device_id': 'android-b5b85a3c1b744b5b'
}

headers_mob = {
    'User-Agent': 'Instagram 275.0.0.27.98 Android (30/11; 480dpi; 1080x2400; samsung; SM-G998B; o1s; exynos2100; en_US; 455799757)',
    'Accept-Language': 'en-US',
    'X-IG-App-ID': '936619743392459',
    'X-IG-Capabilities': '3brBvw==',
    'X-IG-Connection-Type': 'WIFI',
    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
    'Host': 'i.instagram.com'
}

s_mob = requests.Session()
s_mob.cookies.set('sessionid', clean_sess, domain='.instagram.com')
s_mob.cookies.set('csrftoken', csrftoken, domain='.instagram.com')
s_mob.cookies.set('ds_user_id', user_id, domain='.instagram.com')
s_mob.headers.update(headers_mob)

# Test 1: Send Message
r_msg = s_mob.post('https://i.instagram.com/api/v1/direct_v2/threads/broadcast/text/', data=post_data, timeout=12)
print('[MSG SEND TEST] Status:', r_msg.status_code)
try:
    print('Response JSON:', r_msg.json())
except Exception:
    print('Response Text:', r_msg.text[:200])

# Test 2: Update Group Title (NC)
rename_data = {
    'title': 'SERVER GOD CLAN 👑'
}
r_nc = s_mob.post(f'https://i.instagram.com/api/v1/direct_v2/threads/{tid}/update_title/', data=rename_data, timeout=12)
print('[NC RENAME TEST] Status:', r_nc.status_code)
try:
    print('NC JSON:', r_nc.json())
except Exception:
    print('NC Text:', r_nc.text[:200])
