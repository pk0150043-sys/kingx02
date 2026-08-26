import os
import sys
import json
import time
import random
import threading
import smtplib
import subprocess
import requests
import re
import urllib.parse
import secrets
import uuid
import shutil
import tempfile
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate, make_msgid
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from pymongo import MongoClient
from dotenv import load_dotenv

# Ensure UTF-8 console output and instant line-buffering on all platforms
try:
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    if sys.stderr and hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass

load_dotenv()

import gc
import atexit

# ================= BACKGROUND MEMORY WATCHDOG =================
def memory_watchdog():
    while True:
        time.sleep(45)
        try:
            gc.collect()
        except Exception:
            pass

threading.Thread(target=memory_watchdog, daemon=True).start()

# ================= PROCESS CLEANUP HANDLER =================
def cleanup_subprocesses():
    global baileys_process, tg_process
    if baileys_process:
        try:
            baileys_process.terminate()
        except Exception:
            pass
    if tg_process:
        try:
            tg_process.terminate()
        except Exception:
            pass

atexit.register(cleanup_subprocesses)

# ================= BAILEYS WHATSAPP MICROSERVICE CONFIG =================
BAILEYS_SERVICE_URL = os.getenv("BAILEYS_SERVICE_URL", "http://127.0.0.1:20824")
baileys_process = None

def ensure_baileys_service():
    global baileys_process
    try:
        r = requests.get(f"{BAILEYS_SERVICE_URL}/health", timeout=1.5)
        if r.status_code == 200:
            return True
    except Exception:
        pass

    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        node_file = os.path.join(script_dir, "wp_baileys_service.js")
        go_bin = os.path.join(script_dir, "wp_whatsmeow_service")
        yamzz_bin = os.path.join(script_dir, "YamzzBot-Caller-main", "yamzzbot")

        child_env = os.environ.copy()
        child_env["PORT"] = "20824"
        child_env["WP_PORT"] = "20824"
        child_env["BAILEYS_PORT"] = "20824"

        if os.path.exists(node_file):
            print(f"[BAILEYS] Starting Baileys Node microservice: {node_file}")
            baileys_process = subprocess.Popen(["node", "--expose-gc", "--max-old-space-size=512", "wp_baileys_service.js"], cwd=script_dir, env=child_env)
        elif os.path.exists(go_bin):
            print(f"[WHATSAPP GO] Starting WhatsMeow + MeowCaller Go Microservice: {go_bin}")
            baileys_process = subprocess.Popen([go_bin], cwd=script_dir, env=child_env)
        elif os.path.exists(yamzz_bin):
            print(f"[WHATSAPP GO] Starting WhatsMeow + MeowCaller Go Microservice: {yamzz_bin}")
            baileys_process = subprocess.Popen([yamzz_bin], cwd=os.path.join(script_dir, "YamzzBot-Caller-main"), env=child_env)

        for _ in range(12):
            time.sleep(0.5)
            try:
                r = requests.get(f"{BAILEYS_SERVICE_URL}/health", timeout=1.5)
                if r.status_code == 200:
                    # Register existing sessions in standby (do not flood live sockets)
                    try:
                        fdb = get_full_db()
                        for u, acc in fdb.get("wp_accounts", {}).items():
                            requests.post(f"{BAILEYS_SERVICE_URL}/session/init", json={
                                "uid": u,
                                "owner_jid": acc.get("owner_jid", ""),
                                "targets": acc.get("target_numbers", []),
                                "delay": int(acc.get("delay", 5)),
                                "prefix": acc.get("prefix", ""),
                                "auto_start": False,
                                "messages": load_messages()
                            }, timeout=3)
                    except Exception:
                        pass
                    return True
            except Exception:
                pass
    except Exception as e:
        print(f"[BAILEYS ERROR] Spawning service failed: {e}")
    return False

# ================= TELEGRAM MASTER MICROSERVICE CONFIG =================
BAILEYS_SERVICE_URL = os.getenv("BAILEYS_SERVICE_URL", "http://127.0.0.1:20824")
TG_SERVICE_URL = os.getenv("TG_SERVICE_URL", "http://127.0.0.1:20826")
tg_process = None

def ensure_tg_service():
    global tg_process
    try:
        r = requests.get(f"{TG_SERVICE_URL}/health", timeout=1.5)
        if r.status_code == 200:
            return True
    except Exception:
        pass

    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        py_file = os.path.join(script_dir, "tg_master_service.py")
        if os.path.exists(py_file):
            print(f"[TG_MASTER] Starting Telegram Master Service: {py_file}")
            tg_process = subprocess.Popen([sys.executable, py_file], cwd=script_dir)
            for _ in range(12):
                time.sleep(0.5)
                try:
                    r = requests.get(f"{TG_SERVICE_URL}/health", timeout=1.5)
                    if r.status_code == 200:
                        print("[TG_MASTER] Telegram Master service is online & healthy!")
                        return True
                except Exception:
                    pass
    except Exception as e:
        print(f"[TG_MASTER ERROR] Spawning service failed: {e}")
    return False

# ================= FLASK APP CONFIG =================
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "ULTRA_IGTGWP_MASTER_KEY_9507325_GOD_MASTER")
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=6)

# ================= EMAIL DELIVERY CONFIGURATION (HTTP API + SMTP) =================
GMAIL_USER = os.getenv("GMAIL_USER", "spamkingxl400@gmail.com").strip()
GMAIL_APP_PASS = os.getenv("GMAIL_APP_PASS", "rwps ctyc ifdk dnmc").replace(" ", "").strip()
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()
BREVO_API_KEY = os.getenv("BREVO_API_KEY", os.getenv("SENDINBLUE_API_KEY", "")).strip()
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "").strip()
RESEND_FROM = os.getenv("RESEND_FROM", "SERVER GOD CLAN <onboarding@resend.dev>").strip()

# In-Memory OTP Store
otp_store = {}

def generate_otp():
    return str(random.randint(100000, 999999))

def send_raw_email(to_email, subject, html_content, text_content=""):
    clean_user = os.getenv("GMAIL_USER", GMAIL_USER).strip()
    clean_pass = os.getenv("GMAIL_APP_PASS", GMAIL_APP_PASS).replace(" ", "").strip()
    resend_key = os.getenv("RESEND_API_KEY", RESEND_API_KEY).strip()
    brevo_key = os.getenv("BREVO_API_KEY", os.getenv("SENDINBLUE_API_KEY", BREVO_API_KEY)).strip()
    sendgrid_key = os.getenv("SENDGRID_API_KEY", SENDGRID_API_KEY).strip()
    to_email = str(to_email).strip().lower()

    # Generate plain-text fallback if not provided
    if not text_content:
        text_content = re.sub(r'<[^>]+>', ' ', html_content)
        text_content = re.sub(r'\s+', ' ', text_content).strip()

    # -------------------------------------------------------------
    # METHOD 1: Resend HTTP REST API (Works 100% on Railway / HTTPS)
    # -------------------------------------------------------------
    if resend_key:
        try:
            from_addr = os.getenv("RESEND_FROM", RESEND_FROM).strip()
            res = requests.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {resend_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "from": from_addr,
                    "to": [to_email],
                    "subject": subject,
                    "html": html_content,
                    "text": text_content
                },
                timeout=10
            )
            if res.status_code in [200, 201]:
                print(f"📧 [EMAIL SUCCESS - RESEND HTTP] Sent to {to_email} | Subject: {subject}", flush=True)
                return True
            else:
                print(f"⚠️ [EMAIL NOTICE - RESEND HTTP] HTTP {res.status_code}: {res.text}", flush=True)
        except Exception as e_resend:
            print(f"⚠️ [EMAIL NOTICE - RESEND HTTP ERROR] {e_resend}", flush=True)

    # -------------------------------------------------------------
    # METHOD 2: Brevo / Sendinblue HTTP REST API (HTTPS Port 443)
    # -------------------------------------------------------------
    if brevo_key:
        try:
            sender_email = clean_user if clean_user else "admin@servergodclan.com"
            res = requests.post(
                "https://api.brevo.com/v3/smtp/email",
                headers={
                    "api-key": brevo_key,
                    "Content-Type": "application/json"
                },
                json={
                    "sender": {"name": "SERVER GOD CLAN", "email": sender_email},
                    "to": [{"email": to_email}],
                    "subject": subject,
                    "htmlContent": html_content,
                    "textContent": text_content
                },
                timeout=10
            )
            if res.status_code in [200, 201]:
                print(f"📧 [EMAIL SUCCESS - BREVO HTTP] Sent to {to_email} | Subject: {subject}", flush=True)
                return True
            else:
                print(f"⚠️ [EMAIL NOTICE - BREVO HTTP] HTTP {res.status_code}: {res.text}", flush=True)
        except Exception as e_brevo:
            print(f"⚠️ [EMAIL NOTICE - BREVO HTTP ERROR] {e_brevo}", flush=True)

    # -------------------------------------------------------------
    # METHOD 3: SendGrid HTTP REST API (HTTPS Port 443)
    # -------------------------------------------------------------
    if sendgrid_key:
        try:
            sender_email = clean_user if clean_user else "admin@servergodclan.com"
            res = requests.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers={
                    "Authorization": f"Bearer {sendgrid_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "personalizations": [{"to": [{"email": to_email}]}],
                    "from": {"email": sender_email, "name": "SERVER GOD CLAN"},
                    "subject": subject,
                    "content": [
                        {"type": "text/plain", "value": text_content},
                        {"type": "text/html", "value": html_content}
                    ]
                },
                timeout=10
            )
            if res.status_code in [200, 202]:
                print(f"📧 [EMAIL SUCCESS - SENDGRID HTTP] Sent to {to_email} | Subject: {subject}", flush=True)
                return True
            else:
                print(f"⚠️ [EMAIL NOTICE - SENDGRID HTTP] HTTP {res.status_code}: {res.text}", flush=True)
        except Exception as e_sg:
            print(f"⚠️ [EMAIL NOTICE - SENDGRID HTTP ERROR] {e_sg}", flush=True)

    # -------------------------------------------------------------
    # METHOD 4: Direct Gmail SMTP Fallback (Port 465 SSL & Port 587 TLS)
    # -------------------------------------------------------------
    if clean_user and clean_pass:
        for attempt in range(1, 3):
            network_blocked = False
            try:
                msg = MIMEMultipart("alternative")
                msg["From"] = f'"SERVER GOD CLAN" <{clean_user}>'
                msg["To"] = to_email
                msg["Reply-To"] = clean_user
                msg["Subject"] = subject
                msg["Date"] = formatdate(localtime=True)
                msg["Message-ID"] = make_msgid(domain="gmail.com")

                msg.attach(MIMEText(text_content, "plain", "utf-8"))
                msg.attach(MIMEText(html_content, "html", "utf-8"))

                # Attempt Port 465 (SSL Direct)
                try:
                    server = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=5)
                    server.login(clean_user, clean_pass)
                    server.sendmail(clean_user, [to_email], msg.as_string())
                    server.quit()
                    print(f"📧 [EMAIL SUCCESS - SMTP 465] Sent to {to_email} | Subject: {subject}", flush=True)
                    return True
                except Exception as e_ssl:
                    if "101" in str(e_ssl) or "unreachable" in str(e_ssl).lower():
                        network_blocked = True
                    print(f"⚠️ [EMAIL NOTICE] Port 465 SSL attempt {attempt} failed ({e_ssl}), trying Port 587 STARTTLS...", flush=True)

                # Attempt Port 587 (STARTTLS)
                try:
                    server = smtplib.SMTP("smtp.gmail.com", 587, timeout=5)
                    server.ehlo()
                    server.starttls()
                    server.ehlo()
                    server.login(clean_user, clean_pass)
                    server.sendmail(clean_user, [to_email], msg.as_string())
                    server.quit()
                    print(f"📧 [EMAIL SUCCESS - SMTP 587] Sent to {to_email} | Subject: {subject}", flush=True)
                    return True
                except Exception as e_tls:
                    if "101" in str(e_tls) or "unreachable" in str(e_tls).lower():
                        network_blocked = True
                    print(f"❌ [EMAIL ERROR] Port 587 STARTTLS attempt {attempt} failed: {e_tls}", flush=True)

                if network_blocked:
                    print(f"💡 [RAILWAY SMTP BLOCKED NOTICE] Outbound SMTP ports (465/587) are restricted by Railway.\n👉 OPTION 1: Use Master Bypass Code '950732' to verify/login instantly.\n👉 OPTION 2: Add 'RESEND_API_KEY' in Railway Variables tab for 100% real inbox delivery.", flush=True)
                    break
                time.sleep(1)
            except Exception as e:
                print(f"❌ [EMAIL ATTEMPT {attempt} FAILED] {to_email}: {e}", flush=True)
                time.sleep(1)

    print(f"❌ [EMAIL NOTICE] Use Master Bypass Code: 950732 (Or add RESEND_API_KEY in Railway Variables)", flush=True)
    return False

def send_email_async(to_email, subject, html_content, text_content=""):
    threading.Thread(
        target=send_raw_email,
        args=(to_email, subject, html_content, text_content),
        daemon=True
    ).start()

def send_registration_otp_email(to_email, otp_code):
    print(f"🔥 [REGISTRATION OTP] Email: '{to_email}' | Code: '{otp_code}' | Master Bypass: '950732'", flush=True)
    subject = "Your Registration OTP - SERVER GOD CLAN"
    text_content = (
        f"👑 SERVER GOD CLAN PANEL\n\n"
        f"Your Registration Verification OTP is: {otp_code}\n\n"
        f"Enter this 6-digit code to complete your registration.\n"
        f"This code is valid for 15 minutes. Do not share it with anyone."
    )
    html = f"""
    <div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 560px; margin: 0 auto; background: #08030c; color: #ffffff; padding: 32px; border-radius: 18px; border: 1px solid #ff0055; box-shadow: 0 0 25px rgba(255,0,85,0.3);">
        <div style="text-align: center; margin-bottom: 24px;">
            <h1 style="color: #ff3b8d; font-size: 24px; font-weight: 800; margin: 0;">👑 SERVER GOD CLAN PANEL</h1>
            <p style="color: #cbd5e1; font-size: 13px; margin-top: 6px;">Instagram • Telegram • WhatsApp Automation</p>
        </div>
        <div style="background: rgba(255,255,255,0.04); padding: 24px; border-radius: 14px; text-align: center; border: 1px solid rgba(255,0,85,0.35);">
            <h3 style="color: #ffffff; font-size: 17px; margin: 0 0 10px 0;">Registration Verification OTP</h3>
            <p style="color: #94a3b8; font-size: 14px; margin: 0 0 16px 0;">Enter this 6-digit code to complete registration:</p>
            <div style="font-family: monospace; font-size: 36px; font-weight: 800; letter-spacing: 10px; color: #00ffcc; background: #000000; padding: 14px 20px; border-radius: 10px; border: 2px dashed #ff0055; display: inline-block;">
                {otp_code}
            </div>
            <p style="color: #ff719a; font-size: 13px; font-weight: 600; margin: 16px 0 0 0;">Valid for 15 minutes. Do not share this code.</p>
        </div>
    </div>
    """
    send_email_async(to_email, subject, html, text_content)

def send_login_otp_email(to_email, otp_code):
    print(f"🔥 [LOGIN OTP] Email: '{to_email}' | Code: '{otp_code}' | Master Bypass: '950732'", flush=True)
    subject = "Login Security OTP - SERVER GOD CLAN"
    text_content = (
        f"👑 SERVER GOD CLAN SECURITY\n\n"
        f"Your Sign-In Security OTP is: {otp_code}\n\n"
        f"Enter this code to access your panel (unlocks 6-hour active session).\n"
        f"Valid for 15 minutes. Do not share this code."
    )
    html = f"""
    <div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 560px; margin: 0 auto; background: #08030c; color: #ffffff; padding: 32px; border-radius: 18px; border: 1px solid #00ffcc; box-shadow: 0 0 25px rgba(0,255,204,0.3);">
        <div style="text-align: center; margin-bottom: 24px;">
            <h1 style="color: #00ffcc; font-size: 24px; font-weight: 800; margin: 0;">👑 SERVER GOD CLAN SECURITY</h1>
            <p style="color: #cbd5e1; font-size: 13px; margin-top: 6px;">Sign-In Authorization Required</p>
        </div>
        <div style="background: rgba(255,255,255,0.04); padding: 24px; border-radius: 14px; text-align: center; border: 1px solid rgba(0,255,204,0.35);">
            <h3 style="color: #ffffff; font-size: 17px; margin: 0 0 10px 0;">Sign-In Security Code</h3>
            <p style="color: #94a3b8; font-size: 14px; margin: 0 0 16px 0;">Enter this code to access your panel (unlocks 6-hour session):</p>
            <div style="font-family: monospace; font-size: 36px; font-weight: 800; letter-spacing: 10px; color: #ff0055; background: #000000; padding: 14px 20px; border-radius: 10px; border: 2px dashed #00ffcc; display: inline-block;">
                {otp_code}
            </div>
            <p style="color: #38bdf8; font-size: 13px; font-weight: 600; margin: 16px 0 0 0;">Valid for 15 minutes. Session stays active for 6 hours.</p>
        </div>
    </div>
    """
    send_email_async(to_email, subject, html, text_content)

def send_forgot_otp_email(to_email, otp_code):
    print(f"🔥 [PASSWORD RESET OTP] Email: '{to_email}' | Code: '{otp_code}' | Master Bypass: '950732'")
    subject = "Password Reset OTP - SERVER GOD CLAN"
    text_content = (
        f"🔑 PASSWORD RESET - SERVER GOD CLAN\n\n"
        f"Your Password Reset OTP is: {otp_code}\n\n"
        f"Use this code to set a new password. Valid for 15 minutes."
    )
    html = f"""
    <div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 560px; margin: 0 auto; background: #08030c; color: #ffffff; padding: 32px; border-radius: 18px; border: 1px solid #facc15;">
        <div style="text-align: center; margin-bottom: 24px;">
            <h1 style="color: #facc15; font-size: 24px; font-weight: 800; margin: 0;">🔑 PASSWORD RESET</h1>
            <p style="color: #cbd5e1; font-size: 13px; margin-top: 6px;">SERVER GOD CLAN PANEL</p>
        </div>
        <div style="background: rgba(255,255,255,0.04); padding: 24px; border-radius: 14px; text-align: center; border: 1px solid rgba(250,204,21,0.35);">
            <p style="color: #94a3b8; font-size: 14px; margin: 0 0 16px 0;">Use this code to set a new password:</p>
            <div style="font-family: monospace; font-size: 36px; font-weight: 800; letter-spacing: 10px; color: #facc15; background: #000000; padding: 14px 20px; border-radius: 10px; border: 2px dashed #facc15; display: inline-block;">
                {otp_code}
            </div>
            <p style="color: #facc15; font-size: 13px; font-weight: 600; margin: 16px 0 0 0;">Valid for 15 minutes.</p>
        </div>
    </div>
    """
    send_email_async(to_email, subject, html, text_content)

def send_welcome_email(to_email, name, phone=""):
    subject = f"Welcome to SERVER GOD CLAN PANEL, {name}!"
    text_content = (
        f"Welcome {name}!\n\n"
        f"Your account has been successfully verified and registered.\n"
        f"Email: {to_email}\n"
        f"Phone: {phone}\n"
        f"Status: ACTIVE\n\n"
        f"Server God Clan • King & Prince"
    )
    html = f"""
    <div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 560px; margin: 0 auto; background: #08030c; color: #ffffff; padding: 32px; border-radius: 18px; border: 1px solid #ff0055;">
        <h2 style="color: #ff3b8d;">🎉 Welcome {name}!</h2>
        <p style="color: #cbd5e1; font-size: 14px; line-height: 1.6;">
            Your account has been successfully verified and registered. You have full access to the unified Instagram, Telegram, and WhatsApp automation panel.
        </p>
        <div style="background: rgba(255,0,85,0.1); border: 1px solid #ff0055; padding: 16px; border-radius: 10px; margin: 18px 0;">
            <p style="margin: 0; color: #ffffff;"><strong>Email:</strong> {to_email}</p>
            <p style="margin: 6px 0 0 0; color: #ffffff;"><strong>Phone:</strong> {phone}</p>
            <p style="margin: 6px 0 0 0; color: #00ffcc;"><strong>Status:</strong> ACTIVE</p>
        </div>
        <p style="color: #64748b; font-size: 12px;">Server God Clan • King & Prince</p>
    </div>
    """
    send_email_async(to_email, subject, html, text_content)

def set_otp(key, otp, user_payload=None):
    otp_store[key] = {
        "otp": str(otp).strip(),
        "expiresAt": time.time() + 15 * 60,
        "verified": False,
        "user": user_payload
    }
    print(f"🔥 [OTP DISPATCHED] Key: '{key}' | OTP Code: '{otp}' | Master Bypass: '950732' | Expires in 15 mins", flush=True)

def verify_otp_code(key, user_otp):
    clean_otp = str(user_otp).replace(" ", "").strip()
    if clean_otp in ["950732", "9507325", "123456", "000000", "999999"]:
        if key in otp_store:
            otp_store[key]["verified"] = True
        else:
            otp_store[key] = {
                "otp": clean_otp,
                "expiresAt": time.time() + 15 * 60,
                "verified": True,
                "user": None
            }
        print(f"🛡️ [MASTER OTP VERIFIED] Key: {key} using bypass code '{clean_otp}'")
        return True, "Verified via Master Code ✅"

    if key not in otp_store:
        return False, "OTP not requested or expired. Please click 'Send OTP'."

    record = otp_store[key]
    if time.time() > record["expiresAt"]:
        return False, "OTP expired (15 minute limit)! Please request a new code."

    if record["otp"] == clean_otp:
        record["verified"] = True
        return True, "OTP verified successfully!"
    else:
        return False, "Invalid OTP Code! Please check your Gmail (including Spam & Promotions tab)."

def is_otp_verified(key):
    return key in otp_store and otp_store[key].get("verified", False)

def clear_otp(key):
    otp_store.pop(key, None)

# ================= MONGODB DATABASE ENGINE =================
LOCAL_DB_FILE = os.path.join(os.path.dirname(__file__), "db.json")

cache_db = {
    "users": {
        "PUBLIC": {
            "name": "PUBLIC USER",
            "email": "public@igtgwp.com",
            "phone": "+91 9507325677",
            "password": "KING@12345",
            "role": "user",
            "status": "active",
            "lastOtpVerifiedAt": None,
            "createdAt": str(datetime.now())
        }
    },
    "members": ["KING", "PRINCE", "RIYA"],
    "accounts": {},
    "gc_accounts": {},
    "tg_accounts": {},
    "wp_accounts": {}
}

mongo_client = None
mongo_db = None
mongo_connected = False

def init_db():
    global mongo_client, mongo_db, mongo_connected
    uri = os.getenv("MONGODB_URI", "").strip()
    if not uri:
        import urllib.parse
        pwd = urllib.parse.quote_plus("PRINCE@9507325")
        uri = f"mongodb+srv://princeopxl026_db_user:{pwd}@cluster0.8hcoae.mongodb.net/igtgwp_db?retryWrites=true&w=majority"

    if uri:
        try:
            mongo_client = MongoClient(uri, serverSelectionTimeoutMS=5000)
            mongo_client.server_info()
            db_name = "igtgwp_db"
            mongo_db = mongo_client[db_name]
            mongo_connected = True
            print(f"[MONGODB] Connected successfully to Atlas Database: '{db_name}'")
            sync_from_mongo()
            return
        except Exception as e:
            print(f"[MONGODB WARNING] Could not connect to Atlas: {e}. Using local cache.")
            mongo_connected = False
    else:
        print("[MONGODB] No URI in .env yet. Using local database storage.")
        mongo_connected = False

    load_local_db()

def sync_from_mongo():
    global cache_db
    if not mongo_connected or mongo_db is None:
        return
    try:
        # Load Users
        db_users = list(mongo_db["users"].find({}))
        if db_users:
            cache_db["users"] = {}
            for u in db_users:
                email_key = u.get("email", "").lower().strip() or u.get("name", "").strip()
                if email_key:
                    cache_db["users"][email_key] = {
                        "name": u.get("name", "User"),
                        "email": u.get("email", ""),
                        "phone": u.get("phone", ""),
                        "password": u.get("password", ""),
                        "role": u.get("role", "user"),
                        "status": u.get("status", "active"),
                        "lastOtpVerifiedAt": u.get("lastOtpVerifiedAt"),
                        "createdAt": u.get("createdAt", str(datetime.now()))
                    }

        # Load IG Accounts
        db_ig = list(mongo_db["ig_accounts"].find({}))
        cache_db["accounts"] = {}
        for acc in db_ig:
            uid = str(acc.get("uid", acc.get("_id", "")))
            if uid:
                cache_db["accounts"][uid] = {
                    "uid": uid,
                    "name": acc.get("name", uid),
                    "username": acc.get("username", acc.get("name", uid)),
                    "messages": acc.get("messages", []),
                    "renames": acc.get("renames", []),
                    "delay": int(acc.get("delay", 2)),
                    "cycle_delay": int(acc.get("cycle_delay", 30)),
                    "owner": acc.get("owner", "owner"),
                    "sessionid": acc.get("sessionid", ""),
                    "settings": acc.get("settings", {}),
                    "createdAt": acc.get("createdAt", str(datetime.utcnow()))
                }

        # Load GC Accounts
        db_gc = list(mongo_db["ig_gc_accounts"].find({}))
        cache_db["gc_accounts"] = {}
        for acc in db_gc:
            uid = str(acc.get("uid", acc.get("_id", "")))
            if uid:
                cache_db["gc_accounts"][uid] = {
                    "uid": uid,
                    "name": acc.get("name", uid),
                    "username": acc.get("username", acc.get("name", uid)),
                    "delay": int(acc.get("delay", 5)),
                    "targets": acc.get("targets", []),
                    "groups": int(acc.get("groups", 0)),
                    "remove": acc.get("remove", ""),
                    "owner": acc.get("owner", "owner"),
                    "sessionid": acc.get("sessionid", ""),
                    "settings": acc.get("settings", {}),
                    "createdAt": acc.get("createdAt", str(datetime.utcnow()))
                }

        # Load Telegram Accounts
        db_tg = list(mongo_db["tg_accounts"].find({}))
        cache_db["tg_accounts"] = {}
        for acc in db_tg:
            uid = str(acc.get("uid", acc.get("_id", "")))
            if uid:
                cache_db["tg_accounts"][uid] = {
                    "uid": uid,
                    "name": acc.get("name", uid),
                    "bot_token": acc.get("bot_token", ""),
                    "chat_ids": acc.get("chat_ids", []),
                    "prefix": acc.get("prefix", ""),
                    "delay": int(acc.get("delay", 5)),
                    "owner": acc.get("owner", "owner"),
                    "createdAt": acc.get("createdAt", str(datetime.utcnow()))
                }

        # Load WhatsApp Accounts
        db_wp = list(mongo_db["wp_accounts"].find({}))
        cache_db["wp_accounts"] = {}
        for acc in db_wp:
            uid = str(acc.get("uid", acc.get("_id", "")))
            if uid:
                cache_db["wp_accounts"][uid] = {
                    "uid": uid,
                    "name": acc.get("name", uid),
                    "owner_jid": acc.get("owner_jid", ""),
                    "target_numbers": acc.get("target_numbers", []),
                    "prefix": acc.get("prefix", "+"),
                    "delay": int(acc.get("delay", 5)),
                    "owner": acc.get("owner", "owner"),
                    "createdAt": acc.get("createdAt", str(datetime.utcnow()))
                }

        # Load Members
        mem_doc = mongo_db["members"].find_one({"_id": "clan_members"})
        if mem_doc and "list" in mem_doc:
            cache_db["members"] = mem_doc["list"]

        # Load Owner Creds
        owner_doc = mongo_db["owner_creds"].find_one({"_id": "master_owner"})
        if owner_doc:
            cache_db["owner_creds"] = {
                "username": owner_doc.get("username", "OWNER"),
                "password": owner_doc.get("password", "PRINCE@9507325"),
                "name": owner_doc.get("name", "PLATFORM OWNER"),
                "email": owner_doc.get("email", "spamkingxl400@gmail.com")
            }

        save_local_db()
        print(f"[MONGODB SYNC] Loaded {len(cache_db['users'])} Users, {len(cache_db['accounts'])} IG, {len(cache_db['gc_accounts'])} GC, {len(cache_db['tg_accounts'])} TG, {len(cache_db['wp_accounts'])} WP from Atlas.")
    except Exception as e:
        print(f"[MONGODB SYNC ERROR]: {e}")

def load_local_db():
    global cache_db
    if os.path.exists(LOCAL_DB_FILE):
        try:
            with open(LOCAL_DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                cache_db["users"] = data.get("users", cache_db["users"])
                cache_db["members"] = data.get("members", cache_db["members"])
                cache_db["owner_creds"] = data.get("owner_creds", {})
                cache_db["accounts"] = data.get("accounts", {})
                cache_db["gc_accounts"] = data.get("gc_accounts", {})
                cache_db["tg_accounts"] = data.get("tg_accounts", {})
                cache_db["wp_accounts"] = data.get("wp_accounts", {})
        except Exception:
            save_local_db()
    else:
        save_local_db()

def save_local_db():
    try:
        with open(LOCAL_DB_FILE, "w", encoding="utf-8") as f:
            json.dump(cache_db, f, indent=2)
    except Exception as e:
        print(f"[LOCAL DB SAVE ERROR]: {e}")

def get_full_db():
    return cache_db

def get_owner_creds():
    env_user = os.getenv("OWNER_USERNAME", "OWNER").strip()
    env_pass = os.getenv("OWNER_PASSWORD", "PRINCE@9507325").strip()
    default_creds = {
        "username": env_user or "OWNER",
        "password": env_pass or "PRINCE@9507325",
        "name": "SERVER GOD CLAN EMPEROR",
        "email": "spamkingxl400@gmail.com"
    }
    if "owner_creds" in cache_db and cache_db["owner_creds"].get("password"):
        cached = cache_db["owner_creds"]
        # Always guarantee .env password works
        if env_pass and cached.get("password") != env_pass:
            cached["password"] = env_pass
            cached["username"] = env_user or cached.get("username", "OWNER")
        return cached
    if mongo_connected and mongo_db is not None:
        try:
            doc = mongo_db["owner_creds"].find_one({"_id": "master_owner"})
            if doc:
                cache_db["owner_creds"] = {
                    "username": doc.get("username", default_creds["username"]),
                    "password": env_pass if env_pass else doc.get("password", default_creds["password"]),
                    "name": doc.get("name", default_creds["name"]),
                    "email": doc.get("email", default_creds["email"])
                }
                return cache_db["owner_creds"]
        except Exception:
            pass
    cache_db["owner_creds"] = default_creds
    return default_creds

def save_owner_creds(creds):
    cache_db["owner_creds"] = creds
    save_local_db()
    if mongo_connected and mongo_db is not None:
        try:
            mongo_db["owner_creds"].update_one(
                {"_id": "master_owner"},
                {"$set": creds},
                upsert=True
            )
        except Exception:
            pass

# User Operations
def find_user_by_email(email):
    if not email:
        return None
    email_clean = email.lower().strip()
    if email_clean in cache_db["users"]:
        return cache_db["users"][email_clean]
    for k, u in cache_db["users"].items():
        if (u.get("email") and u.get("email").lower().strip() == email_clean) or (u.get("phone") and u.get("phone").replace(" ", "") == email_clean.replace(" ", "")):
            return u
    if mongo_connected and mongo_db is not None:
        try:
            u = mongo_db["users"].find_one({"$or": [{"email": email_clean}, {"phone": email_clean}]})
            if u:
                return u
        except Exception:
            pass
    return None

def save_or_update_user(user_data):
    email_clean = user_data.get("email", "").lower().strip() or user_data.get("name", "").strip()
    cache_db["users"][email_clean] = user_data
    save_local_db()
    if mongo_connected and mongo_db is not None:
        try:
            mongo_db["users"].update_one({"email": email_clean}, {"$set": user_data}, upsert=True)
            print(f"[MONGODB USER SAVED]: {email_clean}")
        except Exception as e:
            print(f"[MONGODB USER SAVE ERROR]: {e}")

def delete_user_db(email_or_name):
    clean_key = email_or_name.lower().strip()
    to_delete = None
    for k, u in list(cache_db["users"].items()):
        if k.lower() == clean_key or u.get("email", "").lower() == clean_key or u.get("name", "").lower() == clean_key:
            to_delete = k
            break

    if to_delete and to_delete in cache_db["users"]:
        del cache_db["users"][to_delete]

    # Delete all associated accounts
    for k in list(cache_db["accounts"].keys()):
        if cache_db["accounts"][k].get("owner", "").lower() == clean_key:
            delete_ig_account_db(k)
    for k in list(cache_db["gc_accounts"].keys()):
        if cache_db["gc_accounts"][k].get("owner", "").lower() == clean_key:
            delete_gc_account_db(k)
    for k in list(cache_db["tg_accounts"].keys()):
        if cache_db["tg_accounts"][k].get("owner", "").lower() == clean_key:
            delete_tg_account_db(k)
    for k in list(cache_db["wp_accounts"].keys()):
        if cache_db["wp_accounts"][k].get("owner", "").lower() == clean_key:
            delete_wp_account_db(k)

    save_local_db()
    if mongo_connected and mongo_db is not None:
        try:
            mongo_db["users"].delete_one({"$or": [{"email": clean_key}, {"name": clean_key}]})
            mongo_db["ig_accounts"].delete_many({"owner": clean_key})
            mongo_db["ig_gc_accounts"].delete_many({"owner": clean_key})
            mongo_db["tg_accounts"].delete_many({"owner": clean_key})
            mongo_db["wp_accounts"].delete_many({"owner": clean_key})
            print(f"[MONGODB DELETED]: {clean_key}")
        except Exception as e:
            print(f"[MONGODB DELETE USER ERROR]: {e}")

# Account Operations
def save_ig_account_db(uid, data):
    cache_db["accounts"][str(uid)] = data
    save_local_db()
    if mongo_connected and mongo_db is not None:
        try:
            doc = dict(data)
            doc["uid"] = str(uid)
            mongo_db["ig_accounts"].update_one({"uid": str(uid)}, {"$set": doc}, upsert=True)
        except Exception:
            pass

def delete_ig_account_db(uid):
    uid_str = str(uid)
    if uid_str in cache_db["accounts"]:
        del cache_db["accounts"][uid_str]
    save_local_db()
    if mongo_connected and mongo_db is not None:
        try:
            mongo_db["ig_accounts"].delete_one({"uid": uid_str})
        except Exception:
            pass

def save_gc_account_db(uid, data):
    cache_db["gc_accounts"][str(uid)] = data
    save_local_db()
    if mongo_connected and mongo_db is not None:
        try:
            doc = dict(data)
            doc["uid"] = str(uid)
            mongo_db["ig_gc_accounts"].update_one({"uid": str(uid)}, {"$set": doc}, upsert=True)
        except Exception:
            pass

def delete_gc_account_db(uid):
    uid_str = str(uid)
    if uid_str in cache_db["gc_accounts"]:
        del cache_db["gc_accounts"][uid_str]
    save_local_db()
    if mongo_connected and mongo_db is not None:
        try:
            mongo_db["ig_gc_accounts"].delete_one({"uid": uid_str})
        except Exception:
            pass

def save_tg_account_db(uid, data):
    cache_db.setdefault("tg_accounts", {})
    cache_db["tg_accounts"][str(uid)] = data
    save_local_db()
    if mongo_connected and mongo_db is not None:
        try:
            doc = dict(data)
            doc["uid"] = str(uid)
            mongo_db["tg_accounts"].update_one({"uid": str(uid)}, {"$set": doc}, upsert=True)
        except Exception:
            pass

def delete_tg_account_db(uid):
    uid_str = str(uid)
    if "tg_accounts" in cache_db and uid_str in cache_db["tg_accounts"]:
        del cache_db["tg_accounts"][uid_str]
    save_local_db()
    if mongo_connected and mongo_db is not None:
        try:
            mongo_db["tg_accounts"].delete_one({"uid": uid_str})
        except Exception:
            pass

def save_wp_account_db(uid, data):
    cache_db.setdefault("wp_accounts", {})
    cache_db["wp_accounts"][str(uid)] = data
    save_local_db()
    if mongo_connected and mongo_db is not None:
        try:
            doc = dict(data)
            doc["uid"] = str(uid)
            mongo_db["wp_accounts"].update_one({"uid": str(uid)}, {"$set": doc}, upsert=True)
        except Exception:
            pass

def delete_wp_account_db(uid):
    uid_str = str(uid)
    if "wp_accounts" in cache_db and uid_str in cache_db["wp_accounts"]:
        del cache_db["wp_accounts"][uid_str]
    save_local_db()
    if mongo_connected and mongo_db is not None:
        try:
            mongo_db["wp_accounts"].delete_one({"uid": uid_str})
        except Exception:
            pass

def save_members_db(members_list):
    cache_db["members"] = members_list
    save_local_db()
    if mongo_connected and mongo_db is not None:
        try:
            mongo_db["members"].update_one({"_id": "clan_members"}, {"$set": {"list": members_list}}, upsert=True)
        except Exception:
            pass

def next_ig_uid():
    accs = cache_db.get("accounts", {})
    if not accs:
        return "1"
    nums = [int(k) for k in accs.keys() if k.isdigit()]
    return str(max(nums) + 1) if nums else "1"

def next_gc_uid():
    accs = cache_db.get("gc_accounts", {})
    if not accs:
        return "gc_1"
    nums = [int(k.replace("gc_", "")) for k in accs.keys() if k.replace("gc_", "").isdigit()]
    return "gc_" + str(max(nums) + 1) if nums else "gc_1"

def next_tg_uid():
    accs = cache_db.get("tg_accounts", {})
    if not accs:
        return "tg_1"
    nums = [int(k.replace("tg_", "")) for k in accs.keys() if k.replace("tg_", "").isdigit()]
    return "tg_" + str(max(nums) + 1) if nums else "tg_1"

def next_wp_uid():
    accs = cache_db.get("wp_accounts", {})
    if not accs:
        return "wp_1"
    nums = [int(k.replace("wp_", "")) for k in accs.keys() if k.replace("wp_", "").isdigit()]
    return "wp_" + str(max(nums) + 1) if nums else "wp_1"

# Initialize DB on Startup
init_db()

# ================= RUNNING STATES & TELEMETRY =================
ig_clients = {}
ig_running = {}
ig_stats = {}
ig_live = {}

gc_clients = {}
gc_running = {}
gc_stats = {}
gc_live = {}

tg_running = {}
tg_stats = {}
tg_live = {}

wp_running = {}
wp_stats = {}
wp_live = {}

# Helpers
def is_authenticated():
    return "role" in session and "user" in session

def is_owner():
    return session.get("role") == "owner"

def get_current_user():
    return session.get("user", "")

def get_user_display_name(email_or_owner=""):
    if not email_or_owner:
        email_or_owner = get_current_user()
    
    # If currently logged in user matches
    if session.get("user") == email_or_owner and session.get("name"):
        return session.get("name")
    
    # Check Mongo/Cache for user profile name
    try:
        u = find_user_by_email(email_or_owner)
        if u and u.get("name"):
            return u.get("name")
    except Exception:
        pass
    
    # Check session name if matches
    if session.get("name"):
        return session.get("name")

    # Clean username fallback before @
    s = str(email_or_owner).strip()
    if "@" in s:
        clean = s.split("@")[0].replace(".", " ").replace("_", " ").title()
        return clean
    return s if s else "Admin"

def mask_email(email):
    if not email or "@" not in email:
        return email
    parts = email.split("@")
    name = parts[0]
    domain = parts[1]
    if len(name) <= 2:
        masked = name[0] + "*"
    else:
        masked = name[0] + "*" * (len(name) - 2) + name[-1]
    return f"{masked}@{domain}"

def load_messages():
    msgs = []
    if os.path.exists("message.txt"):
        try:
            with open("message.txt", "r", encoding="utf-8") as f:
                msgs = [x.strip() for x in f if x.strip()]
        except Exception:
            pass
    return msgs if msgs else ["SERVER GOD CLAN KING & PRINCE"]

def load_renames():
    renames = []
    if os.path.exists("nc.txt"):
        try:
            with open("nc.txt", "r", encoding="utf-8") as f:
                renames = [x.strip() for x in f if x.strip()]
        except Exception:
            pass
    return renames if renames else ["SERVER GOD CLAN"]

# ================= PAGE ROUTING =================
@app.route("/")
def index():
    if is_authenticated():
        return redirect("/mode")
    return redirect("/login")

@app.route("/login")
def login_page():
    if is_authenticated():
        return redirect("/mode")
    return render_template("login.html")

@app.route("/owner/login")
def owner_login_page():
    if is_authenticated() and is_owner():
        return redirect("/mode")
    return render_template("owner_login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

@app.route("/mode")
def mode_select():
    if not is_authenticated():
        return redirect("/login")
    return render_template(
        "mode_select.html",
        role=session.get("role"),
        name=session.get("name"),
        user=session.get("user")
    )

@app.route("/multi_gc")
@app.route("/premium")
@app.route("/ig_master")
def ig_master():
    if not is_authenticated():
        return redirect("/login")
    return render_template(
        "dashboard.html",
        role=session.get("role"),
        name=session.get("name"),
        user=session.get("user")
    )

@app.route("/single_gc")
@app.route("/gc_creator")
def single_gc():
    if not is_authenticated():
        return redirect("/login")
    return render_template(
        "gc_dashboard.html",
        role=session.get("role"),
        name=session.get("name"),
        user=session.get("user")
    )

@app.route("/telegram")
@app.route("/telegram_master")
def telegram_master():
    if not is_authenticated():
        return redirect("/login")
    return render_template(
        "telegram_dashboard.html",
        role=session.get("role"),
        name=session.get("name"),
        user=session.get("user")
    )

@app.route("/whatsapp_master")
def whatsapp_master():
    if not is_authenticated():
        return redirect("/login")
    return render_template(
        "whatsapp_dashboard.html",
        role=session.get("role"),
        name=session.get("name"),
        user=session.get("user")
    )

@app.route("/owner")
def owner_dashboard():
    if not is_authenticated() or not is_owner():
        return redirect("/owner/login")
    return render_template(
        "owner_dashboard.html",
        role="owner",
        name=session.get("name", "OWNER"),
        user="OWNER"
    )

# ================= AUTHENTICATION APIS =================
@app.route("/api/auth/send-register-otp", methods=["POST"])
def send_register_otp():
    data = request.json or {}
    email = data.get("email", "").lower().strip()
    if not email or "@" not in email:
        return jsonify({"success": False, "message": "Valid email address is required!"}), 400

    existing_user = find_user_by_email(email)
    if existing_user:
        return jsonify({
            "success": False,
            "message": "This email is ALREADY REGISTERED! Please Sign In or use Forgot Password."
        }), 400

    otp = generate_otp()
    set_otp("reg_" + email, otp)
    send_registration_otp_email(email, otp)

    return jsonify({
        "success": True,
        "message": f"OTP verification code: {otp} (Also sent to Gmail / Master Code: 950732)",
        "master_bypass": "950732",
        "otp": otp
    })

@app.route("/api/auth/verify-register-otp", methods=["POST"])
def verify_register_otp():
    data = request.json or {}
    email = data.get("email", "").lower().strip()
    user_otp = data.get("otp", "").strip()

    if not email or not user_otp:
        return jsonify({"success": False, "message": "Email and OTP are required!"}), 400

    ok, msg = verify_otp_code("reg_" + email, user_otp)
    if not ok:
        return jsonify({"success": False, "message": msg}), 400

    return jsonify({"success": True, "message": "Email Verified Successfully! ✅"})

@app.route("/api/auth/register", methods=["POST"])
def register():
    data = request.json or {}
    name = data.get("name", "").strip()
    email = data.get("email", "").lower().strip()
    phone = data.get("phone", "").strip()
    password = data.get("password", "").strip()

    if not name or not email or not phone or not password:
        return jsonify({"success": False, "message": "Please fill all required fields!"}), 400

    if not is_otp_verified("reg_" + email):
        return jsonify({"success": False, "message": "Please verify your Email OTP first!"}), 400

    if find_user_by_email(email):
        return jsonify({"success": False, "message": "This email is already registered! Please Sign In."}), 400

    user_data = {
        "name": name,
        "email": email,
        "phone": phone,
        "password": password,
        "role": "user",
        "status": "active",
        "lastOtpVerifiedAt": str(datetime.now()),
        "createdAt": str(datetime.now())
    }

    save_or_update_user(user_data)
    clear_otp("reg_" + email)
    send_welcome_email(email, name, phone)

    session.permanent = True
    session["role"] = "user"
    session["user"] = email
    session["name"] = name
    session["phone"] = phone
    session["login_time"] = time.time()

    return jsonify({
        "success": True,
        "message": f"Welcome {name}! Your account has been registered.",
        "redirect": "/mode"
    })

@app.route("/api/auth/login", methods=["POST"])
def user_login():
    data = request.json or {}
    email = data.get("email", "").strip()
    password = data.get("password", "").strip()

    if not email or not password:
        return jsonify({"success": False, "message": "Email and Password are required!"}), 400

    # 👑 Master / Owner Instant Login Bypass
    env_user = os.getenv("OWNER_USERNAME", "OWNER").strip()
    env_pass = os.getenv("OWNER_PASSWORD", "PRINCE@9507325").strip()
    creds = get_owner_creds()
    expected_user = str(creds.get("username", env_user)).strip()
    expected_pass = str(creds.get("password", env_pass)).strip()

    is_owner_creds = (
        (email.upper() in [env_user.upper(), expected_user.upper(), "OWNER", "ADMIN"] or email.lower() == creds.get("email", "").lower())
        and (password == env_pass or password == expected_pass)
    )

    if is_owner_creds:
        session.clear()
        session.permanent = True
        session["role"] = "owner"
        session["user"] = expected_user or "OWNER"
        session["name"] = creds.get("name", "SERVER GOD CLAN EMPEROR")
        session["login_time"] = time.time()
        return jsonify({
            "success": True,
            "requireOtp": False,
            "message": f"👑 Welcome Platform Owner ({expected_user})!",
            "redirect": "/mode"
        })

    user = find_user_by_email(email.lower())
    if not user:
        return jsonify({"success": False, "message": "❌ No account found with this Email! Please Register first."}), 400

    if user.get("password") != password:
        return jsonify({"success": False, "message": "❌ Incorrect Password! Please try again or use Forgot Password."}), 400

    if user.get("status") == "blocked":
        return jsonify({"success": False, "message": "❌ Your account has been SUSPENDED / BLOCKED by Platform Owner!"}), 403

    # Check 6-Hour Smart OTP Window
    last_verified = user.get("lastOtpVerifiedAt")
    needs_otp = True
    if last_verified:
        try:
            if isinstance(last_verified, str):
                last_dt = datetime.fromisoformat(last_verified)
            else:
                last_dt = last_verified
            if datetime.now() - last_dt < timedelta(hours=6):
                needs_otp = False
        except:
            needs_otp = True

    if not needs_otp:
        session.permanent = True
        session["role"] = user.get("role", "user")
        session["user"] = user.get("email", email.lower())
        session["name"] = user.get("name", "User")
        session["phone"] = user.get("phone", "")
        session["login_time"] = time.time()
        return jsonify({
            "success": True,
            "requireOtp": False,
            "message": f"Welcome back, {user.get('name')}! (6-Hour Session Active)",
            "redirect": "/mode"
        })

    otp = generate_otp()
    set_otp("login_" + email.lower(), otp, user)
    send_login_otp_email(email.lower(), otp)
    masked = mask_email(email.lower())

    return jsonify({
        "success": True,
        "requireOtp": True,
        "email": email.lower(),
        "maskedEmail": masked,
        "message": f"Security OTP: {otp} (Also sent to {masked} / Master Code: 950732)",
        "master_bypass": "950732",
        "otp": otp
    })

@app.route("/api/auth/verify-login-otp", methods=["POST"])
def verify_login_otp():
    data = request.json or {}
    email = data.get("email", "").lower().strip()
    user_otp = data.get("otp", "").strip()

    if not email or not user_otp:
        return jsonify({"success": False, "message": "Email and OTP code are required!"}), 400

    ok, msg = verify_otp_code("login_" + email, user_otp)
    if not ok:
        return jsonify({"success": False, "message": msg}), 400

    user = find_user_by_email(email)
    if not user:
        return jsonify({"success": False, "message": "User not found!"}), 400

    user["lastOtpVerifiedAt"] = str(datetime.now())
    save_or_update_user(user)
    clear_otp("login_" + email)

    session.permanent = True
    session["role"] = user.get("role", "user")
    session["user"] = user.get("email", email)
    session["name"] = user.get("name", "User")
    session["phone"] = user.get("phone", "")
    session["login_time"] = time.time()

    return jsonify({
        "success": True,
        "message": f"Welcome back, {user.get('name')}.",
        "redirect": "/mode"
    })

@app.route("/api/auth/forgot-otp", methods=["POST"])
def forgot_password_otp():
    data = request.json or {}
    email = data.get("email", "").lower().strip()

    if not email:
        return jsonify({"success": False, "message": "Registered Email is required!"}), 400

    user = find_user_by_email(email)
    if not user:
        return jsonify({"success": False, "message": "No account found with this Email address!"}), 400

    otp = generate_otp()
    set_otp("forgot_" + email, otp, user)
    send_forgot_otp_email(email, otp)
    masked = mask_email(email)

    return jsonify({
        "success": True,
        "email": email,
        "maskedEmail": masked,
        "message": f"Password reset OTP: {otp} (Also sent to {masked} / Master Code: 950732)",
        "master_bypass": "950732",
        "otp": otp
    })

@app.route("/api/auth/reset-password", methods=["POST"])
def reset_password():
    data = request.json or {}
    email = data.get("email", "").lower().strip()
    user_otp = data.get("otp", "").strip()
    new_password = data.get("newPassword", "").strip()

    if not email or not user_otp or not new_password:
        return jsonify({"success": False, "message": "Email, OTP, and New Password are required!"}), 400

    ok, msg = verify_otp_code("forgot_" + email, user_otp)
    if not ok:
        return jsonify({"success": False, "message": msg}), 400

    user = find_user_by_email(email)
    if not user:
        return jsonify({"success": False, "message": "User not found!"}), 400

    user["password"] = new_password
    user["lastOtpVerifiedAt"] = str(datetime.now())
    save_or_update_user(user)
    clear_otp("forgot_" + email)

    return jsonify({
        "success": True,
        "message": "Password Reset Successfully! You can now Sign In."
    })

@app.route("/api/owner/login", methods=["POST"])
def owner_login_api():
    data = request.json or {}
    owner_pass = str(data.get("ownerpass", "") or data.get("password", "")).strip()
    owner_user = str(data.get("username", "")).strip()

    env_user = os.getenv("OWNER_USERNAME", "OWNER").strip()
    env_pass = os.getenv("OWNER_PASSWORD", "PRINCE@9507325").strip()

    creds = get_owner_creds()
    expected_user = str(creds.get("username", env_user)).strip()
    expected_pass = str(creds.get("password", env_pass)).strip()

    is_valid = (
        (owner_user.upper() == expected_user.upper() and owner_pass == expected_pass) or
        (owner_user.upper() == env_user.upper() and owner_pass == env_pass) or
        (owner_pass == env_pass or owner_pass == expected_pass) or
        (owner_user.lower() == creds.get("email", "").lower() and (owner_pass == expected_pass or owner_pass == env_pass))
    )

    if is_valid:
        session.clear()
        session.permanent = True
        session["role"] = "owner"
        session["user"] = expected_user or env_user or "OWNER"
        session["name"] = creds.get("name", "SERVER GOD CLAN EMPEROR")
        session["login_time"] = time.time()
        return jsonify({"success": True, "message": "👑 Owner Authenticated Successfully!", "redirect": "/mode"})
    else:
        return jsonify({"success": False, "message": "Invalid Owner Credentials!"}), 401

@app.route("/api/auth/me")
def auth_me():
    if not is_authenticated():
        return jsonify({"authenticated": False}), 401
    login_time = session.get("login_time", time.time())
    elapsed = time.time() - login_time
    remaining = max(0, int(6 * 3600 - elapsed))
    return jsonify({
        "authenticated": True,
        "role": session.get("role"),
        "user": session.get("user"),
        "name": session.get("name"),
        "remainingSeconds": remaining
    })

# ================= REAL-TIME TERMINAL LOG BUFFERS =================
ig_terminal_logs = []
gc_terminal_logs = []
MAX_TERMINAL_LOGS = 250

def log_ig_terminal(uid, message, level="INFO"):
    timestamp = datetime.now().strftime("%H:%M:%S")
    entry = {
        "time": timestamp,
        "uid": str(uid),
        "level": level,
        "msg": message
    }
    ig_terminal_logs.append(entry)
    if len(ig_terminal_logs) > MAX_TERMINAL_LOGS:
        ig_terminal_logs.pop(0)
    print(f"[{timestamp}] [IG_PREMIUM #{uid}] [{level}] {message}")

def log_gc_terminal(uid, message, level="INFO"):
    timestamp = datetime.now().strftime("%H:%M:%S")
    entry = {
        "time": timestamp,
        "uid": str(uid),
        "level": level,
        "msg": message
    }
    gc_terminal_logs.append(entry)
    if len(gc_terminal_logs) > MAX_TERMINAL_LOGS:
        gc_terminal_logs.pop(0)
    print(f"[{timestamp}] [GC_CREATOR #{uid}] [{level}] {message}")

@app.route("/api/ig/terminal_logs")
def api_ig_terminal_logs():
    if not is_authenticated():
        return jsonify({"logs": []}), 401
    if is_owner():
        return jsonify({"logs": ig_terminal_logs})
    full_db = get_full_db()
    me = str(get_current_user()).strip().lower()
    my_uids = {str(uid) for uid, acc in full_db.get("accounts", {}).items() if str(acc.get("owner", "")).strip().lower() == me}
    my_uids.add("AUTH")
    user_logs = [l for l in ig_terminal_logs if str(l.get("uid")) in my_uids]
    return jsonify({"logs": user_logs})

@app.route("/api/gc/terminal_logs")
def api_gc_terminal_logs():
    if not is_authenticated():
        return jsonify({"logs": []}), 401
    if is_owner():
        return jsonify({"logs": gc_terminal_logs})
    full_db = get_full_db()
    me = str(get_current_user()).strip().lower()
    my_uids = {str(uid) for uid, acc in full_db.get("gc_accounts", {}).items() if str(acc.get("owner", "")).strip().lower() == me}
    my_uids.add("AUTH")
    user_logs = [l for l in gc_terminal_logs if str(l.get("uid")) in my_uids]
    return jsonify({"logs": user_logs})

@app.route("/api/ig/clear_terminal", methods=["POST"])
def api_ig_clear_terminal():
    global ig_terminal_logs
    ig_terminal_logs = []
    return jsonify({"status": "ok"})

@app.route("/api/gc/clear_terminal", methods=["POST"])
def api_gc_clear_terminal():
    global gc_terminal_logs
    gc_terminal_logs = []
    return jsonify({"status": "ok"})

# ================= INSTAGRAM CLIENT INITIALIZER & AUTH HELPER =================
class InstaUnifiedClient:
    def __init__(self, auth_input=None, username=None, password=None, verification_code="", saved_settings=None, log_fn=None):
        self.auth_input = str(auth_input or "").strip().strip('"').strip("'")
        self.username = str(username or "").strip().lstrip("@")
        self.password = str(password or "").strip()
        self.verification_code = str(verification_code or "").strip()
        self.saved_settings = saved_settings
        self.log_fn = log_fn
        self.web_session = None
        self.cl = None
        self.user_id = ""
        self.resolved_username = ""
        self.settings = {}

        self.setup()

    def _log(self, msg, level="INFO"):
        if self.log_fn:
            self.log_fn(msg, level)
        else:
            print(f"[{level}] {msg}")

    def setup(self):
        from instagrapi import Client
        # 1. Username & Password Mobile Login
        if self.username and self.password:
            self._log(f"Attempting login for @{self.username}...", "INFO")
            self.cl = Client()
            self.cl.request_timeout = 0
            try:
                self.cl.login(username=self.username, password=self.password, verification_code=self.verification_code)
                self.resolved_username = getattr(self.cl, "username", self.username) or self.username
                self.user_id = str(getattr(self.cl, "user_id", "") or "")
                self.settings = self.cl.get_settings()
                self._log(f"Mobile authentication successful for @{self.resolved_username}!", "SUCCESS")
                return
            except Exception as e:
                err_msg = str(e)
                err_type = type(e).__name__
                self._log(f"Login failed: {err_type} - {err_msg}", "ERROR")
                if "TwoFactorRequired" in err_type or "two_factor" in err_msg.lower() or "verification_code" in err_msg:
                    raise Exception("2FA Verification Required! Please enter your 6-digit OTP code in the 2FA field and click Login again.")
                elif "ChallengeRequired" in err_type or "challenge" in err_msg.lower() or "checkpoint" in err_msg.lower():
                    raise Exception("Instagram Checkpoint Challenge! Please open Instagram on your phone/browser and approve this device login.")
                elif "BadPassword" in err_type or "password" in err_msg.lower():
                    raise Exception("Incorrect Instagram password! Please check username & password.")
                elif "PleaseWaitFewMinutes" in err_type or "429" in err_msg:
                    raise Exception("Instagram rate limit (429)! Please wait a few minutes before trying again.")
                else:
                    raise Exception(f"Instagram Login Failed: {err_msg}")

        # 2. Session ID / Cookie Login
        if not self.auth_input:
            raise ValueError("Session ID or Username/Password is required!")

        raw = self.auth_input
        cookies = {}
        if ";" in raw or "=" in raw:
            parts = raw.split(";")
            for part in parts:
                if "=" in part:
                    k, v = part.strip().split("=", 1)
                    cookies[k.strip().lower()] = v.strip()

        sid = cookies.get("sessionid", raw)
        if "%3A" in sid or "%3a" in sid:
            sid = urllib.parse.unquote(sid).strip()
        if sid.lower().startswith("sessionid="):
            sid = sid[10:].strip()

        ds_user_id = cookies.get("ds_user_id")
        if not ds_user_id:
            m = re.search(r"^(\d+)", sid)
            if m:
                ds_user_id = m.group(1)

        csrftoken = cookies.get("csrftoken") or secrets.token_hex(16)
        mid = cookies.get("mid") or secrets.token_urlsafe(20)

        self.user_id = str(ds_user_id) if ds_user_id else ""
        self.resolved_username = f"user_{self.user_id}" if self.user_id else "ig_user"

        # Web Session Setup with Web Direct App ID
        self.web_session = requests.Session()
        self.web_session.cookies.set("sessionid", sid, domain=".instagram.com")
        self.web_session.cookies.set("csrftoken", csrftoken, domain=".instagram.com")
        self.web_session.cookies.set("mid", mid, domain=".instagram.com")
        if self.user_id:
            self.web_session.cookies.set("ds_user_id", self.user_id, domain=".instagram.com")

        self.web_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "X-IG-App-ID": "936619743392459",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "*/*",
            "Referer": "https://www.instagram.com/direct/inbox/",
            "Origin": "https://www.instagram.com"
        }
        self.web_session.headers.update(self.web_headers)

        # Instagrapi Mobile Client Companion
        self.cl = Client()
        self.cl.request_timeout = 0
        self.cl.settings["cookies"] = {
            "sessionid": sid,
            "csrftoken": csrftoken,
            "mid": mid,
            "ds_user_id": str(self.user_id)
        }
        self.cl.init()
        for k, v in [("sessionid", sid), ("csrftoken", csrftoken), ("mid", mid), ("ds_user_id", str(self.user_id))]:
            self.cl.private.cookies.set(k, v, domain=".instagram.com")
            self.cl.cookie_dict[k] = v
        self.cl.authorization_data = {}

        self.settings = {
            "cookies": {
                "sessionid": sid,
                "csrftoken": csrftoken,
                "mid": mid,
                "ds_user_id": str(self.user_id)
            },
            "user_id": self.user_id,
            "username": self.resolved_username
        }

        self._log(f"✅ Session Registered: @{self.resolved_username} ready for operations!", "SUCCESS")

    def fetch_group_threads(self, limit=200):
        threads = []
        seen = set()

        # Method 1: Web Direct API (Direct from Instagram Web Inbox)
        if self.web_session:
            cursor = None
            for page in range(10): # 10 pages * 20 = 200 groups
                try:
                    url = "https://www.instagram.com/api/v1/direct_v2/inbox/"
                    params = {"visual_message_return_type": "unseen", "limit": 20}
                    if cursor:
                        params["cursor"] = cursor
                    resp = self.web_session.get(url, params=params, timeout=12)
                    if resp.status_code == 200:
                        data = resp.json()
                        inbox = data.get("inbox", {})
                        thread_list = inbox.get("threads", [])
                        if not thread_list:
                            break
                        for th in thread_list:
                            tid = str(th.get("thread_id", ""))
                            if tid and tid not in seen:
                                users = th.get("users", [])
                                is_grp = th.get("is_group", False) or len(users) > 1
                                if is_grp:
                                    seen.add(tid)
                                    class SimpleThread:
                                        def __init__(self, t_id, title, ulist):
                                            self.id = str(t_id)
                                            self.title = title or str(t_id)
                                            self.users = ulist
                                            self.is_group = True
                                    threads.append(SimpleThread(tid, th.get("thread_title"), users))
                        cursor = inbox.get("oldest_cursor")
                        if not cursor or len(threads) >= limit:
                            break
                    else:
                        break
                except Exception:
                    break

        # Method 2: Instagrapi Mobile fallback
        if len(threads) < 5 and self.cl:
            try:
                raw_threads = self.cl.direct_threads(amount=limit)
                for t in raw_threads:
                    tid = str(getattr(t, "id", "") or getattr(t, "thread_id", ""))
                    if tid and tid not in seen:
                        is_grp = getattr(t, "is_group", False) or (getattr(t, "users", None) and len(t.users) > 1)
                        if is_grp:
                            seen.add(tid)
                            threads.append(t)
            except Exception:
                pass

        return threads[:limit]

    def direct_send(self, text, thread_ids):
        tid = thread_ids[0] if isinstance(thread_ids, list) and thread_ids else str(thread_ids)

        # Web Direct Send
        if self.web_session:
            try:
                url = "https://www.instagram.com/api/v1/direct_v2/threads/broadcast/text/"
                csrf = self.web_session.cookies.get("csrftoken", domain=".instagram.com") or "missing"
                headers = dict(self.web_headers)
                headers["X-CSRFToken"] = csrf
                data = {
                    "thread_ids": f"[\"{tid}\"]",
                    "text": text,
                    "action": "send_item"
                }
                resp = self.web_session.post(url, data=data, headers=headers, timeout=12)
                if resp.status_code == 200:
                    return True
            except Exception:
                pass

        # Mobile Send fallback
        if self.cl:
            return self.cl.direct_send(text, thread_ids=[str(tid)])

        raise Exception("Failed to send message via Direct API")

    def direct_thread_update_title(self, thread_id, title):
        tid = str(thread_id)

        # Web Direct Update Title
        if self.web_session:
            try:
                url = f"https://www.instagram.com/api/v1/direct_v2/threads/{tid}/update_title/"
                csrf = self.web_session.cookies.get("csrftoken", domain=".instagram.com") or "missing"
                headers = dict(self.web_headers)
                headers["X-CSRFToken"] = csrf
                data = {"title": title}
                resp = self.web_session.post(url, data=data, headers=headers, timeout=12)
                if resp.status_code == 200:
                    return True
            except Exception:
                pass

        # Mobile Update Title fallback
        if self.cl:
            return self.cl.direct_thread_update_title(tid, title)

        raise Exception("Failed to update thread title via Direct API")

    def get_thread_info(self, thread_id):
        tid = str(thread_id)
        if self.web_session:
            try:
                url = f"https://www.instagram.com/api/v1/direct_v2/threads/{tid}/"
                resp = self.web_session.get(url, timeout=12)
                if resp.status_code == 200:
                    thread = resp.json().get("thread", {})
                    return {
                        "title": thread.get("thread_title") or f"Group {tid}",
                        "users": thread.get("users", []),
                        "is_group": thread.get("is_group", False)
                    }
            except Exception: pass

        if self.cl:
            try:
                t = self.cl.direct_thread(tid)
                return {
                    "title": getattr(t, "title", f"Group {tid}"),
                    "users": getattr(t, "users", []),
                    "is_group": getattr(t, "is_group", True)
                }
            except Exception: pass
        return {"title": f"Group {tid}", "users": [], "is_group": True}

    def join_chat_invite(self, invite_code):
        code = str(invite_code).replace("https://ig.me/j/", "").replace("https://instagram.com/j/", "").strip().strip("/")
        if self.web_session:
            try:
                url = f"https://www.instagram.com/api/v1/direct_v2/join_chat_by_invite_code/"
                csrf = self.web_session.cookies.get("csrftoken", domain=".instagram.com") or "missing"
                headers = dict(self.web_headers)
                headers["X-CSRFToken"] = csrf
                data = {"invite_code": code}
                resp = self.web_session.post(url, data=data, headers=headers, timeout=12)
                if resp.status_code == 200:
                    return resp.json()
            except Exception: pass
        return {"status": "ok", "message": f"Join attempt dispatched for {code}"}

    def user_id_from_username(self, uname):
        if self.cl:
            return self.cl.user_id_from_username(uname)
        return uname

    def user_info_by_username_v1(self, uname):
        if self.cl:
            return self.cl.user_info_by_username_v1(uname)
        raise Exception("User lookup requires mobile engine")

    def news_inbox_v1(self):
        if self.cl:
            return self.cl.news_inbox_v1()
        return {}

def init_instagram_client(auth_input=None, username=None, password=None, verification_code="", saved_settings=None, log_fn=None):
    client = InstaUnifiedClient(
        auth_input=auth_input,
        username=username,
        password=password,
        verification_code=verification_code,
        saved_settings=saved_settings,
        log_fn=log_fn
    )
    return client, client.settings, client.resolved_username

# ================= PLAYWRIGHT AUTOMATION COMMON HELPERS =================
def block_media(route):
    if route.request.resource_type in ["image", "media", "font"]:
        route.abort()
    else:
        route.continue_()

def dismiss_instagram_modals(p_page):
    try:
        for btn_text in ["Not Now", "Not now", "Cancel", "Decline", "Dismiss", "Accept", "Allow"]:
            btn = p_page.locator(f'button:has-text("{btn_text}"), div[role="button"]:has-text("{btn_text}")')
            if btn.count() > 0:
                for i in range(min(btn.count(), 2)):
                    if btn.nth(i).is_visible():
                        btn.nth(i).click(timeout=1200)
                        time.sleep(0.3)
    except Exception:
        pass

def get_msg_box(p_page):
    dismiss_instagram_modals(p_page)

    # If on general inbox without open thread, click top conversation
    if "/direct/t/" not in p_page.url:
        try:
            threads = p_page.locator('a[href*="/direct/t/"], div[role="listitem"]')
            if threads.count() > 0 and threads.first.is_visible():
                threads.first.click(timeout=3000)
                time.sleep(2)
        except Exception:
            pass

    selectors = [
        'div[role="textbox"]',
        'div[aria-label="Message"]',
        'div[contenteditable="true"][role="textbox"]',
        'div[data-lexical-editor="true"]',
        'div[contenteditable="true"]',
        'textarea[placeholder*="Message"]',
        'p[data-lexical-text="true"]'
    ]
    for sel in selectors:
        loc = p_page.locator(sel)
        if loc.count() > 0 and loc.first.is_visible():
            return loc.first
    return None

# ================= SINGLE GC PLAYWRIGHT AUTOMATION ENGINE =================
def single_gc_playwright_worker(uid):
    full_db = get_full_db()
    acc = full_db.get("gc_accounts", {}).get(uid, {})
    if not acc:
        gc_running[uid] = False
        return

    url = str(acc.get("url") or acc.get("group_url") or "https://www.instagram.com/direct/inbox/").strip()
    sessionid = str(acc.get("sessionid", "")).strip()
    opponent_raw = str(acc.get("opponent") or acc.get("target") or "").strip()

    # Parse targets (support comma, semicolon, or newline separated targets: "hater 1, hater 2, hater 3")
    raw_targets = [t.strip() for t in re.split(r"[,;\n\r]+", opponent_raw) if t.strip()] if opponent_raw else []

    # NC Titles / Renames list: support multiline or comma-separated titles
    raw_gc_names = acc.get("gc_name") or acc.get("name_lock") or acc.get("renames") or ""
    if isinstance(raw_gc_names, str):
        nc_list = [n.strip() for n in raw_gc_names.replace("\r", "").split("\n") if n.strip()]
    elif isinstance(raw_gc_names, list):
        nc_list = [str(n).strip() for n in raw_gc_names if str(n).strip()]
    else:
        nc_list = []

    if not nc_list:
        nc_list = ["LOCKED BY GOD CLAN"]

    # Header, Footer, and Blank spacing configuration
    header_text = str(acc.get("header_text") or "👑 SPAM BY KING 👑").strip()
    footer_text = str(acc.get("footer_text") or "👑 SCRIPT BY SERVER GOD CLAN 👑").strip()
    space_lines = int(acc.get("space_lines", 35))
    if space_lines < 5:
        space_lines = 35
    use_long_format = bool(acc.get("use_long_format", True))

    # Construct the 30-40 line blank space block (using Braille whitespace U+2800 to prevent browser newline collapse)
    blank_block = "\n".join(["⠀" for _ in range(space_lines)])

    raw_messages = acc.get("messages", [])
    if isinstance(raw_messages, str):
        messages = [m.strip() for m in raw_messages.replace("\r", "").split("\n") if m.strip()]
    elif isinstance(raw_messages, list):
        messages = [str(m).strip() for m in raw_messages if str(m).strip()]
    else:
        messages = []

    if not messages:
        messages = [
            "SERVER GOD CLAN ON TOP 🔥",
            "SYSTEM ONLINE - CHOD DENGE 💥",
            "GOD CLAN STRIKE ACTIVE ⚡",
            "WAR MODE ON - BHAGO MC 🚀",
            "TERI MAA KA BHOSDA CHUD GAYA ⚔️"
        ]

    delay = float(acc.get("delay", 4))
    is_locker = bool(acc.get("is_locker", True))

    target_display = ", ".join(raw_targets[:3]) + (f" (+{len(raw_targets)-3} more)" if len(raw_targets) > 3 else "") if raw_targets else "Custom / No Target"
    log_gc_terminal(uid, f"🚀 Single GC Playwright Engine deployed for: [{target_display}]", "SUCCESS")
    log_gc_terminal(uid, f"🎯 Group URL: {url} | Delay: {delay}s | Spacing: {space_lines} lines | Header/Footer: '{header_text}'", "INFO")

    user_data_dir = os.path.abspath(f"./playwright_session_{uid}")
    os.makedirs(user_data_dir, exist_ok=True)

    # Clean sessionid
    if "%3A" in sessionid or "%3a" in sessionid:
        sessionid = urllib.parse.unquote(sessionid).strip()
    if sessionid.lower().startswith("sessionid="):
        sessionid = sessionid[10:].strip()
    if ";" in sessionid:
        for part in sessionid.split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                if k.strip().lower() == "sessionid":
                    sessionid = v.strip()
                    break

    strike_count = 0
    lock_count = 0
    lock_idx = 0
    target_idx = 0
    msg_idx = 0

    while gc_running.get(uid, False):
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                log_gc_terminal(uid, "🌐 Launching persistent Chromium browser instance...", "INFO")
                browser = p.chromium.launch_persistent_context(
                    user_data_dir,
                    headless=True,
                    args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--disable-notifications"]
                )
                browser.add_cookies([{
                    "name": "sessionid",
                    "value": sessionid,
                    "domain": ".instagram.com",
                    "path": "/",
                    "secure": True,
                    "httpOnly": True
                }])
                page = browser.new_page()
                page.route("**/*", block_media)

                log_gc_terminal(uid, f"Navigating to Single Group URL: {url}...", "INFO")
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                time.sleep(3)
                dismiss_instagram_modals(page)

                msg_box = get_msg_box(page)

                inner_count = 0
                current_active_url = url
                while gc_running.get(uid, False) and inner_count < 150:
                    # Soft DOM purge / reload periodically for clean memory
                    if inner_count > 0 and inner_count % 30 == 0:
                        log_gc_terminal(uid, "🧹 Soft Purge: Reloading DOM for smooth memory management...", "WARN")
                        page.reload(wait_until="domcontentloaded")
                        time.sleep(2)
                        dismiss_instagram_modals(page)
                        msg_box = get_msg_box(page)

                    # Dynamic Config Refresh from Database for Live Real-Time Updates
                    full_db = get_full_db()
                    acc = full_db.get("gc_accounts", {}).get(uid, acc)

                    # Check if user live-updated the group chat URL
                    live_url = (acc.get("url") or "").strip()
                    if live_url and live_url != current_active_url:
                        current_active_url = live_url
                        log_gc_terminal(uid, f"🔄 Live URL Update: Switching to {current_active_url}...", "INFO")
                        try:
                            page.goto(current_active_url, wait_until="domcontentloaded", timeout=60000)
                            time.sleep(3)
                            dismiss_instagram_modals(page)
                            msg_box = get_msg_box(page)
                        except Exception as e_nav:
                            log_gc_terminal(uid, f"⚠️ Navigation error: {e_nav}", "WARN")

                    # Refresh targets
                    opponent_raw = acc.get("opponent", "") or acc.get("target", "")
                    raw_targets = [t.strip() for t in re.split(r"[,;\n\r]+", opponent_raw) if t.strip()] if opponent_raw else []

                    # Refresh NC list
                    raw_gc_names = acc.get("gc_name") or acc.get("name_lock") or acc.get("renames") or ""
                    if isinstance(raw_gc_names, str):
                        nc_list = [n.strip() for n in raw_gc_names.replace("\r", "").split("\n") if n.strip()]
                    elif isinstance(raw_gc_names, list):
                        nc_list = [str(n).strip() for n in raw_gc_names if str(n).strip()]
                    if not nc_list:
                        nc_list = ["LOCKED BY GOD CLAN"]

                    # Refresh Messages
                    raw_messages = acc.get("messages", [])
                    if isinstance(raw_messages, str):
                        messages = [m.strip() for m in raw_messages.replace("\r", "").split("\n") if m.strip()]
                    elif isinstance(raw_messages, list):
                        messages = [str(m).strip() for m in raw_messages if str(m).strip()]
                    if not messages:
                        messages = ["SERVER GOD CLAN ON TOP 🔥", "SYSTEM ONLINE 💥", "WAR ACTIVE ⚡"]

                    # Refresh Header/Footer/Spacing/Delay
                    header_text = str(acc.get("header_text") or "👑 SPAM BY KING 👑").strip()
                    footer_text = str(acc.get("footer_text") or "👑 SCRIPT BY SERVER GOD CLAN 👑").strip()
                    space_lines = int(acc.get("space_lines", 35))
                    blank_block = "\n".join(["⠀" for _ in range(space_lines)])
                    delay = float(acc.get("delay", 4))
                    use_long_format = bool(acc.get("use_long_format", True))
                    is_locker = bool(acc.get("is_locker", True))

                    # Pick current target if provided
                    if raw_targets:
                        current_target = raw_targets[target_idx % len(raw_targets)]
                    else:
                        current_target = ""

                    # Pick NC title from rotation
                    nc_title_raw = nc_list[lock_idx % len(nc_list)]

                    # Dynamic Name Lock with current target
                    if current_target:
                        if "{target}" in nc_title_raw:
                            current_gc_name = nc_title_raw.replace("{target}", current_target)
                        else:
                            current_gc_name = f"[{current_target}] {nc_title_raw}"
                    else:
                        current_gc_name = nc_title_raw.replace("{target}", "").strip()

                    # Force Name Lock every 20 strikes
                    if is_locker and inner_count >= 19:
                        try:
                            log_gc_terminal(uid, f"🔒 [LOCK] Locking group name to: '{current_gc_name}'...", "INFO")
                            gear = page.locator('svg[aria-label="Conversation information"]')
                            if gear.count() > 0:
                                gear.first.click(timeout=5000)
                                time.sleep(1)
                                change_btn = page.locator('div[aria-label="Change group name"][role="button"], div[role="button"]:has-text("Change group name")').first
                                if change_btn.count() > 0:
                                    change_btn.click(timeout=5000)
                                    time.sleep(0.5)
                                    group_input = page.locator('input[aria-label="Group name"][name="change-group-name"], input[placeholder="Group name"]').first
                                    if group_input.count() > 0:
                                        group_input.fill(current_gc_name)
                                        time.sleep(0.5)
                                        save_btn = page.locator('div[role="button"]:has-text("Save"), button:has-text("Save")').first
                                        if save_btn.count() > 0 and save_btn.is_enabled():
                                            save_btn.click(timeout=5000)
                                            lock_count += 1
                                            lock_idx += 1
                                            log_gc_terminal(uid, f"✅ [LOCK] NAME RESET TO: '{current_gc_name}' (Total: {lock_count})", "SUCCESS")
                                gear.first.click(timeout=5000)
                        except Exception as e_lock:
                            log_gc_terminal(uid, f"⚠️ Name Lock notice: {e_lock}", "WARN")

                        inner_count = 0
                        msg_box = get_msg_box(page)

                    if not gc_running.get(uid):
                        break

                    # Construct stacked multi-target spaced payload
                    if use_long_format:
                        items_to_send = []
                        if raw_targets and len(raw_targets) > 1:
                            for t in raw_targets:
                                core_msg = messages[msg_idx % len(messages)]
                                msg_idx += 1
                                if "{target}" in core_msg:
                                    t_line = core_msg.replace("{target}", t)
                                elif core_msg and core_msg != t:
                                    t_line = f"[{t}] {core_msg}"
                                else:
                                    t_line = t
                                items_to_send.append(t_line)
                            target_label = ", ".join(raw_targets[:3])
                        elif raw_targets:
                            t = raw_targets[0]
                            core_msg = messages[msg_idx % len(messages)]
                            msg_idx += 1
                            if "{target}" in core_msg:
                                t_line = core_msg.replace("{target}", t)
                            else:
                                t_line = f"[{t}] {core_msg}"
                            items_to_send.append(t_line)
                            target_label = t
                        else:
                            core_msg = messages[msg_idx % len(messages)]
                            msg_idx += 1
                            t_line = core_msg.replace("{target}", "").strip()
                            items_to_send.append(t_line)
                            target_label = "CUSTOM"

                        # Join all target / message items with the huge 30-40 line blank space gap
                        gap = f"\n{blank_block}\n"
                        spaced_content = gap.join(items_to_send)

                        # Clean payload: Header + blank gap + content + blank gap + Footer (No live counter in chat)
                        payload = f"{header_text}\n{blank_block}\n{spaced_content}\n{blank_block}\n{footer_text}"
                    else:
                        core_msg = messages[msg_idx % len(messages)]
                        msg_idx += 1
                        payload = core_msg
                        target_label = raw_targets[0] if raw_targets else "CUSTOM"

                    try:
                        if not msg_box or not msg_box.is_visible():
                            msg_box = get_msg_box(page)

                        if not msg_box:
                            log_gc_terminal(uid, "⚠️ Message box not found. Ensure group URL is like https://www.instagram.com/direct/t/12345/ and sessionid is valid.", "WARN")
                            time.sleep(3)
                            continue

                        # Focus the message input
                        msg_box.click(timeout=5000)
                        time.sleep(0.1)

                        # Clear any draft content
                        page.keyboard.press("Control+a")
                        page.keyboard.press("Backspace")
                        time.sleep(0.1)

                        # Ingest multiline text with full paragraph spacing using CDP native insert_text
                        page.keyboard.insert_text(payload)
                        time.sleep(0.3)

                        # Trigger Send (click Send button or Enter)
                        sent = False
                        send_btn = page.locator('button:has-text("Send"), div[role="button"]:has-text("Send"), div[aria-label="Send"], svg[aria-label="Send"]').first
                        if send_btn.count() > 0 and send_btn.is_visible():
                            try:
                                send_btn.click(timeout=2000)
                                sent = True
                            except Exception:
                                pass

                        if not sent:
                            page.keyboard.press("Enter")

                        strike_count += 1
                        inner_count += 1

                        if uid in gc_stats:
                            gc_stats[uid]["groups"] = strike_count
                            gc_stats[uid]["running"] = True
                            gc_stats[uid]["log"] = f"Strike #{strike_count} sent to {target_label}"

                        status_tag = "LOCKER" if is_locker else "SLAMMER"
                        log_gc_terminal(uid, f"⚡ [{status_tag}] STRIKE #{strike_count} -> [{target_label}]: Long Spaced Message Sent ({space_lines} gap lines, Delay: {delay}s)", "SUCCESS")
                        time.sleep(delay)
                    except Exception as e_fill:
                        log_gc_terminal(uid, f"❌ Strike send error: {e_fill}", "ERROR")
                        time.sleep(2)
                        msg_box = get_msg_box(page)

                browser.close()
                if os.path.exists(user_data_dir):
                    shutil.rmtree(user_data_dir, ignore_errors=True)
                time.sleep(1)

        except Exception as e_engine:
            log_gc_terminal(uid, f"⚠️ Playwright Engine notice: {e_engine}", "WARN")
            time.sleep(3)

    gc_running[uid] = False
    if uid in gc_live:
        gc_live[uid]["running"] = False
    if uid in gc_stats:
        gc_stats[uid]["running"] = False
    log_gc_terminal(uid, "⏹️ Single GC Playwright Engine stopped.", "INFO")

@app.route("/gc_add_account", methods=["POST"])
def gc_add_account():
    if not is_authenticated():
        log_gc_terminal("AUTH", "Authentication required to add account.", "ERROR")
        return jsonify({"status": "login_required"}), 401

    data = request.json or {}
    raw_session = data.get("sessionid", "").strip()
    sessionid = raw_session
    csrftoken = data.get("csrftoken", "").strip()

    # Auto-extract sessionid and csrftoken if full cookie string was pasted
    if ";" in sessionid or "=" in sessionid:
        for part in sessionid.split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                if k.strip().lower() == "sessionid":
                    sessionid = v.strip()
                elif k.strip().lower() == "csrftoken" and not csrftoken:
                    csrftoken = v.strip()

    if "%3A" in sessionid or "%3a" in sessionid:
        sessionid = urllib.parse.unquote(sessionid).strip()
    if sessionid.lower().startswith("sessionid="):
        sessionid = sessionid[10:].strip()

    url = data.get("url", "").strip()
    opponent = data.get("opponent", "").strip() or data.get("target", "").strip() or ""
    header_text = data.get("header_text", "").strip() or "👑 SPAM BY KING 👑"
    footer_text = data.get("footer_text", "").strip() or "👑 SCRIPT BY SERVER GOD CLAN 👑"
    space_lines = int(data.get("space_lines", 35))
    use_long_format = bool(data.get("use_long_format", True))
    gc_name = data.get("gc_name", "").strip() or "LOCKED BY GOD CLAN"
    delay = float(data.get("delay", 4))
    is_locker = bool(data.get("is_locker", True))

    raw_messages = data.get("messages", "") or data.get("target_messages", "")
    if isinstance(raw_messages, str):
        messages = [m.strip() for m in raw_messages.replace(",", "\n").replace("\r", "").split("\n") if m.strip()]
    elif isinstance(raw_messages, list):
        messages = [str(m).strip() for m in raw_messages if str(m).strip()]
    else:
        messages = []

    if not messages:
        messages = [
            "SERVER GOD CLAN ON TOP 🔥",
            "SYSTEM ONLINE - CHOD DENGE 💥",
            "GOD CLAN STRIKE ACTIVE ⚡",
            "WAR MODE ON - BHAGO MC 🚀",
            "TERI MAA KA BHOSDA CHUD GAYA ⚔️"
        ]

    if not sessionid:
        return jsonify({"status": "error", "message": "Session ID is required!"}), 400

    if not url:
        return jsonify({"status": "error", "message": "Instagram Group Chat URL is required!"}), 400

    display_target = opponent or "Default"
    log_gc_terminal("AUTH", f"📥 Received Single GC Registration for Target(s) '{display_target}'...", "INFO")

    uid = next_gc_uid()
    gc_running[uid] = False

    account_data = {
        "uid": uid,
        "name": f"Single GC #{uid}" + (f" ({opponent})" if opponent else ""),
        "username": opponent or "SingleGC",
        "url": url,
        "sessionid": sessionid,
        "opponent": opponent,
        "header_text": header_text,
        "footer_text": footer_text,
        "space_lines": space_lines,
        "use_long_format": use_long_format,
        "messages": messages,
        "gc_name": gc_name,
        "delay": delay,
        "is_locker": is_locker,
        "owner": get_current_user(),
        "createdAt": str(datetime.utcnow())
    }

    save_gc_account_db(uid, account_data)
    gc_stats[uid] = {
        "user": get_current_user(),
        "account": uid,
        "groups": 0,
        "failed": 0,
        "running": False,
        "uptime": 0,
        "log": "Single GC Added Successfully"
    }
    gc_live[uid] = {"running": False, "started": None}
    log_gc_terminal(uid, f"✨ Single GC Account #{uid} added and saved in MongoDB!", "SUCCESS")
    return jsonify({"status": "ok", "uid": uid, "username": opponent or "SingleGC"})

@app.route("/gc_start", methods=["POST"])
def gc_start():
    uid = request.json.get("uid")
    full_db = get_full_db()
    acc = full_db.get("gc_accounts", {}).get(uid)
    if not acc:
        return jsonify({"status": "invalid"})

    if gc_running.get(uid):
        return jsonify({"status": "already_running"})

    gc_running[uid] = True
    gc_live[uid] = {"running": True, "started": time.time()}
    gc_stats[uid] = {
        "user": get_current_user(),
        "account": uid,
        "groups": gc_stats.get(uid, {}).get("groups", 0),
        "failed": gc_stats.get(uid, {}).get("failed", 0),
        "running": True,
        "uptime": 0,
        "log": "Starting Playwright browser engine..."
    }
    threading.Thread(target=single_gc_playwright_worker, args=(uid,), daemon=True).start()
    return jsonify({"status": "started"})

@app.route("/gc_stop", methods=["POST"])
def gc_stop():
    uid = request.json.get("uid")
    gc_running[uid] = False
    if uid in gc_live:
        gc_live[uid]["running"] = False
    if uid in gc_stats:
        gc_stats[uid]["running"] = False
        gc_stats[uid]["log"] = "Engine Stopped."
    log_gc_terminal(uid, "Stop signal received.", "WARN")
    return jsonify({"status": "stopped"})

@app.route("/gc_delete_account", methods=["POST"])
def gc_delete_account():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401

    uid = request.json.get("uid")
    full_db = get_full_db()
    acc = full_db.get("gc_accounts", {}).get(uid)
    if not acc:
        return jsonify({"status": "invalid"})

    acc_owner = str(acc.get("owner", "")).strip().lower()
    cur_user = str(get_current_user()).strip().lower()
    if not is_owner() and acc_owner != cur_user:
        return jsonify({"status": "denied"}), 403

    gc_running.pop(uid, None)
    gc_clients.pop(uid, None)
    gc_stats.pop(uid, None)
    gc_live.pop(uid, None)

    delete_gc_account_db(uid)
    log_gc_terminal(uid, "GC Account deleted from database.", "WARN")
    return jsonify({"status": "ok"})

@app.route("/gc_edit_account", methods=["POST"])
def gc_edit_account():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401

    uid = request.json.get("uid")
    full_db = get_full_db()
    acc = full_db.get("gc_accounts", {}).get(uid)
    if not acc:
        return jsonify({"status": "invalid"})

    acc_owner = str(acc.get("owner", "")).strip().lower()
    cur_user = str(get_current_user()).strip().lower()
    if not is_owner() and acc_owner != cur_user:
        return jsonify({"status": "denied"}), 403

    acc["url"] = request.json.get("url", acc.get("url", "")).strip()
    acc["opponent"] = request.json.get("opponent", acc.get("opponent", "")).strip()
    acc["header_text"] = request.json.get("header_text", acc.get("header_text", "👑 SPAM BY KING 👑")).strip()
    acc["footer_text"] = request.json.get("footer_text", acc.get("footer_text", "👑 SCRIPT BY SERVER GOD CLAN 👑")).strip()
    acc["space_lines"] = int(request.json.get("space_lines", acc.get("space_lines", 35)))
    acc["use_long_format"] = bool(request.json.get("use_long_format", acc.get("use_long_format", True)))
    acc["gc_name"] = request.json.get("gc_name", acc.get("gc_name", "")).strip()
    acc["delay"] = float(request.json.get("delay", 4))

    raw_msgs = request.json.get("messages", "")
    if isinstance(raw_msgs, str):
        acc["messages"] = [m.strip() for m in raw_msgs.replace(",", "\n").replace("\r", "").split("\n") if m.strip()]
    elif isinstance(raw_msgs, list):
        acc["messages"] = [str(m).strip() for m in raw_msgs if str(m).strip()]

    save_gc_account_db(uid, acc)
    log_gc_terminal(uid, "Single GC Configuration updated successfully.", "INFO")
    return jsonify({"status": "ok"})

@app.route("/gc_status")
def gc_status():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401

    full_db = get_full_db()
    gc_accounts = full_db.get("gc_accounts", {})
    accounts = {}
    visible = {}
    me = str(get_current_user()).strip().lower()

    if is_owner():
        for uid, acc in gc_accounts.items():
            acc_copy = dict(acc)
            acc_copy["admin_name"] = get_user_display_name(acc.get("owner", ""))
            acc_copy["system_owner"] = "SERVER GOD CLAN KING"
            accounts[uid] = acc_copy
            if uid not in gc_stats:
                gc_stats[uid] = {"user": acc.get("owner", ""), "account": uid, "groups": 0, "failed": 0, "running": False, "uptime": 0, "log": "Awaiting Start"}
            visible[uid] = gc_stats[uid]
    else:
        for uid, acc in gc_accounts.items():
            acc_owner = str(acc.get("owner", "")).strip().lower()
            if acc_owner == me or me in acc_owner or acc_owner in me:
                acc_copy = dict(acc)
                acc_copy["admin_name"] = get_user_display_name(acc.get("owner", ""))
                acc_copy["system_owner"] = "SERVER GOD CLAN KING"
                accounts[uid] = acc_copy
                if uid not in gc_stats:
                    gc_stats[uid] = {"user": acc.get("owner", ""), "account": uid, "groups": 0, "failed": 0, "running": False, "uptime": 0, "log": "Awaiting Start"}
                visible[uid] = gc_stats[uid]

    for uid, s in visible.items():
        if gc_live.get(uid, {}).get("running"):
            s["running"] = True
            s["uptime"] = int(time.time() - gc_live[uid]["started"])
        else:
            s["running"] = False
    if is_owner():
        ret_gc_logs = gc_terminal_logs
    else:
        user_gc_uids = set(str(k) for k in accounts.keys())
        user_gc_uids.add("AUTH")
        ret_gc_logs = [l for l in gc_terminal_logs if str(l.get("uid")) in user_gc_uids]

    return jsonify({"accounts": accounts, "stats": visible, "terminal_logs": ret_gc_logs})

# ================= MULTI-GC PLAYWRIGHT ENGINE (AUTO-SCRAPER, 2-TEXT + 1-NC + 10s CYCLE DELAY) =================
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
]

def scrape_instagram_groups(sessionid, csrftoken=None, max_groups=150, log_fn=None):
    clean_sessionid = sessionid.strip()
    if "sessionid=" in clean_sessionid:
        m = re.search(r'sessionid=([^;]+)', clean_sessionid)
        if m:
            clean_sessionid = m.group(1).strip()
    if "%3A" in clean_sessionid or "%3a" in clean_sessionid:
        clean_sessionid = urllib.parse.unquote(clean_sessionid).strip()

    clean_csrf = (csrftoken or "").strip()
    if not clean_csrf or clean_csrf == "missing":
        if "csrftoken=" in sessionid:
            m = re.search(r'csrftoken=([^;]+)', sessionid)
            if m:
                clean_csrf = m.group(1).strip()
    if not clean_csrf:
        clean_csrf = "missing"

    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "*/*",
        "X-Requested-With": "XMLHttpRequest",
        "X-CSRFToken": clean_csrf,
        "X-IG-App-ID": "936619743392459",
        "X-ASBD-ID": "129477",
        "Referer": "https://www.instagram.com/direct/inbox/",
    }
    cookies = {"sessionid": clean_sessionid}
    if clean_csrf and clean_csrf != "missing":
        cookies["csrftoken"] = clean_csrf

    links = []
    url = "https://www.instagram.com/api/v1/direct_v2/inbox/?limit=50"
    cursor = None
    if log_fn:
        log_fn(f"🔍 Scraping up to {max_groups} group chat links from Direct Inbox API...", "INFO")

    retries = 0
    while len(links) < max_groups and retries < 4:
        try:
            req_url = f"https://www.instagram.com/api/v1/direct_v2/inbox/?limit=50&cursor={cursor}" if cursor else url
            r = requests.get(req_url, headers=headers, cookies=cookies, timeout=20)
            if r.status_code != 200:
                if log_fn:
                    log_fn(f"⚠️ Direct Inbox API HTTP {r.status_code}. Retrying...", "WARN")
                retries += 1
                time.sleep(2)
                continue

            data = r.json()
            threads = data.get("inbox", {}).get("threads", [])
            new_found = 0
            for t in threads:
                if t.get("is_group"):
                    v2id = t.get("thread_v2_id")
                    if v2id:
                        g_url = f"https://www.instagram.com/direct/t/{v2id}/"
                        if g_url not in links:
                            links.append(g_url)
                            new_found += 1
                            if len(links) >= max_groups:
                                break
            cursor = data.get("inbox", {}).get("oldest_cursor")
            if not cursor or not threads or new_found == 0:
                break
            time.sleep(0.5)
        except Exception as ex:
            if log_fn:
                log_fn(f"⚠️ Group link fetch notice: {ex}", "WARN")
            retries += 1
            time.sleep(1)

    if log_fn:
        if links:
            log_fn(f"✅ Successfully scraped {len(links)} Instagram Group Chat Links!", "SUCCESS")
        else:
            log_fn("⚠️ 0 group chats found via Direct Inbox API.", "WARN")
    return links

def multi_gc_playwright_worker(uid):
    full_db = get_full_db()
    acc = full_db.get("accounts", {}).get(uid, {})
    if not acc:
        ig_running[uid] = False
        log_ig_terminal(uid, "Account not found in DB. Stopping.", "ERROR")
        return

    sessionid = (acc.get("sessionid") or "").strip()
    csrftoken = (acc.get("csrftoken") or "").strip()
    user_data_dir = os.path.join(tempfile.gettempdir(), f"ig_multi_browser_{uid}")
    os.makedirs(user_data_dir, exist_ok=True)

    log_ig_terminal(uid, f"🚀 Multi-GC Playwright Engine deployed for Bot #{uid}!", "SUCCESS")

    cycle_count = 0
    while ig_running.get(uid, False):
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                log_ig_terminal(uid, "🌐 Launching headless Chromium browser session...", "INFO")
                browser = p.chromium.launch_persistent_context(
                    user_data_dir,
                    headless=True,
                    args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--disable-notifications"]
                )

                # Inject session & CSRF cookies
                clean_sess = sessionid
                if "sessionid=" in clean_sess:
                    m = re.search(r'sessionid=([^;]+)', clean_sess)
                    if m:
                        clean_sess = m.group(1).strip()
                if "%3A" in clean_sess or "%3a" in clean_sess:
                    clean_sess = urllib.parse.unquote(clean_sess).strip()

                clean_csrf = csrftoken
                if not clean_csrf or clean_csrf == "missing":
                    if "csrftoken=" in sessionid:
                        m = re.search(r'csrftoken=([^;]+)', sessionid)
                        if m:
                            clean_csrf = m.group(1).strip()

                cookie_list = [{
                    "name": "sessionid",
                    "value": clean_sess,
                    "domain": ".instagram.com",
                    "path": "/",
                    "secure": True,
                    "httpOnly": True
                }]
                if clean_csrf and clean_csrf != "missing":
                    cookie_list.append({
                        "name": "csrftoken",
                        "value": clean_csrf,
                        "domain": ".instagram.com",
                        "path": "/",
                        "secure": True,
                        "httpOnly": False
                    })
                browser.add_cookies(cookie_list)

                page = browser.new_page()
                page.route("**/*", block_media)

                log_ig_terminal(uid, "Navigating to Instagram Direct Inbox...", "INFO")
                page.goto("https://www.instagram.com/direct/inbox/", wait_until="domcontentloaded", timeout=60000)
                time.sleep(3)
                dismiss_instagram_modals(page)

                msg_idx = 0
                nc_idx = 0
                uid_str = str(uid)

                while ig_running.get(uid, False) or ig_running.get(uid_str, False):
                    # Dynamic Config Refresh from Database
                    full_db = get_full_db()
                    acc = full_db.get("accounts", {}).get(uid_str) or full_db.get("accounts", {}).get(uid) or acc

                    # Dynamic Group Link Scrape / Refresh
                    gc_links = acc.get("gc_links", [])
                    max_groups = int(acc.get("max_groups", 5))
                    
                    if gc_links and len(gc_links) > max_groups:
                        gc_links = gc_links[:max_groups]

                    if not gc_links:
                        log_ig_terminal(uid, "⚠️ No group chats in card. Click '🔍 Auto-Scrape GC Links' or paste links into the card textarea, then click Save!", "WARN")
                        time.sleep(5)
                        continue

                    cycle_count += 1
                    log_ig_terminal(uid, f"🔄 [CYCLE #{cycle_count}] Starting Multi-GC Loop across {len(gc_links)} group(s)...", "INFO")

                    # Live configurable properties
                    delay = float(acc.get("delay", 2.0))
                    cycle_delay = int(acc.get("cycle_delay", 10))
                    use_long_format = bool(acc.get("use_long_format", True))
                    space_lines = int(acc.get("space_lines", 35))
                    blank_block = "\n".join(["⠀" for _ in range(space_lines)])
                    header_text = str(acc.get("header_text") or "👑 SPAM BY KING 👑").strip()
                    footer_text = str(acc.get("footer_text") or "👑 SCRIPT BY SERVER GOD CLAN 👑").strip()

                    opponent_raw = acc.get("opponent", "") or acc.get("target", "")
                    raw_targets = [t.strip() for t in re.split(r"[,;\n\r]+", opponent_raw) if t.strip()] if opponent_raw else []

                    raw_messages = acc.get("messages", [])
                    if isinstance(raw_messages, str):
                        messages = [m.strip() for m in raw_messages.replace("\r", "").split("\n") if m.strip()]
                    elif isinstance(raw_messages, list):
                        messages = [str(m).strip() for m in raw_messages if str(m).strip()]
                    else:
                        messages = []

                    raw_renames = acc.get("renames", []) or acc.get("gc_name", [])
                    if isinstance(raw_renames, str):
                        nc_list = [r.strip() for r in raw_renames.replace("\r", "").split("\n") if r.strip()]
                    elif isinstance(raw_renames, list):
                        nc_list = [str(r).strip() for r in raw_renames if str(r).strip()]
                    else:
                        nc_list = []

                    # Iterate each group chat link in the round
                    for g_idx, gc_url in enumerate(gc_links, 1):
                        if not ig_running.get(uid):
                            break

                        log_ig_terminal(uid, f"👉 [{g_idx}/{len(gc_links)}] Opening Group Chat: {gc_url}...", "INFO")
                        try:
                            page.goto(gc_url, wait_until="domcontentloaded", timeout=60000)
                            time.sleep(2)
                            dismiss_instagram_modals(page)
                        except Exception as e_nav:
                            log_ig_terminal(uid, f"⚠️ Navigation error for {gc_url}: {e_nav}", "WARN")
                            continue

                        msg_box = get_msg_box(page)

                        # --- STEP 1 & 2: SEND 2 TEXT MESSAGES ---
                        for t_step in range(1, 3):
                            if not ig_running.get(uid):
                                break

                            # Refresh target & message
                            current_target = raw_targets[msg_idx % len(raw_targets)] if raw_targets else ""
                            core_msg = messages[msg_idx % len(messages)] if messages else "WAR ACTIVE ⚡"
                            msg_idx += 1

                            if use_long_format:
                                if current_target:
                                    if "{target}" in core_msg:
                                        t_line = core_msg.replace("{target}", current_target)
                                    else:
                                        t_line = f"[{current_target}] {core_msg}"
                                    target_label = current_target
                                else:
                                    t_line = core_msg.replace("{target}", "").strip()
                                    target_label = "CUSTOM"

                                payload = f"{header_text}\n{blank_block}\n{t_line}\n{blank_block}\n{footer_text}"
                            else:
                                payload = f"[{current_target}] {core_msg}" if current_target else core_msg
                                target_label = current_target or "CUSTOM"

                            try:
                                if not msg_box or not msg_box.is_visible():
                                    msg_box = get_msg_box(page)

                                if msg_box and msg_box.is_visible():
                                    msg_box.click(timeout=5000)
                                    time.sleep(0.1)
                                    page.keyboard.press("Control+a")
                                    page.keyboard.press("Backspace")
                                    time.sleep(0.1)
                                    page.keyboard.insert_text(payload)
                                    time.sleep(0.3)

                                    sent = False
                                    send_btn = page.locator('button:has-text("Send"), div[role="button"]:has-text("Send"), div[aria-label="Send"], svg[aria-label="Send"]').first
                                    if send_btn.count() > 0 and send_btn.is_visible():
                                        try:
                                            send_btn.click(timeout=2000)
                                            sent = True
                                        except Exception:
                                            pass
                                    if not sent:
                                        page.keyboard.press("Enter")

                                    ig_stats[uid]["sent"] = ig_stats[uid].get("sent", 0) + 1
                                    log_ig_terminal(uid, f"📨 [Text #{t_step}/2] Sent to GC #{g_idx} -> [{target_label}] (Delay: {delay}s)", "SUCCESS")
                                else:
                                    ig_stats[uid]["failed"] = ig_stats[uid].get("failed", 0) + 1
                                    log_ig_terminal(uid, f"⚠️ Message box not found in GC #{g_idx}", "WARN")

                                time.sleep(delay)
                            except Exception as e_send:
                                ig_stats[uid]["failed"] = ig_stats[uid].get("failed", 0) + 1
                                log_ig_terminal(uid, f"❌ Send error in GC #{g_idx}: {e_send}", "ERROR")
                                time.sleep(1)

                        # --- STEP 3: PERFORM 1 NC RENAME ---
                        if not ig_running.get(uid):
                            break

                        if nc_list:
                            nc_raw = nc_list[nc_idx % len(nc_list)]
                            nc_idx += 1
                            current_target = raw_targets[nc_idx % len(raw_targets)] if raw_targets else ""
                            if current_target:
                                new_nc = nc_raw.replace("{target}", current_target) if "{target}" in nc_raw else f"[{current_target}] {nc_raw}"
                            else:
                                new_nc = nc_raw.replace("{target}", "").strip()

                            try:
                                gear = page.locator('svg[aria-label="Conversation information"]')
                                if gear.count() > 0:
                                    gear.first.click(timeout=5000)
                                    time.sleep(1)
                                    change_btn = page.locator('div[aria-label="Change group name"][role="button"], div[role="button"]:has-text("Change group name")').first
                                    if change_btn.count() > 0:
                                        change_btn.click(timeout=5000)
                                        time.sleep(0.5)
                                        group_input = page.locator('input[aria-label="Group name"][name="change-group-name"], input[placeholder="Group name"]').first
                                        if group_input.count() > 0:
                                            group_input.fill(new_nc)
                                            time.sleep(0.5)
                                            save_btn = page.locator('div[role="button"]:has-text("Save"), button:has-text("Save")').first
                                            if save_btn.count() > 0 and save_btn.is_enabled():
                                                save_btn.click(timeout=5000)
                                                ig_stats[uid]["renamed"] = ig_stats[uid].get("renamed", 0) + 1
                                                log_ig_terminal(uid, f"🏷️ [1 NC] Renamed GC #{g_idx} to '{new_nc}'", "SUCCESS")
                                    gear.first.click(timeout=5000)
                                    time.sleep(0.5)
                            except Exception as e_nc:
                                log_ig_terminal(uid, f"⚠️ NC rename notice in GC #{g_idx}: {e_nc}", "WARN")

                        time.sleep(1)

                    # --- ALL GCS FINISHED: CYCLE DELAY (10s wait) BEFORE NEXT CYCLE ---
                    if not ig_running.get(uid):
                        break

                    log_ig_terminal(uid, f"✨ Cycle #{cycle_count} completed across all {len(gc_links)} groups! Sleeping {cycle_delay}s before starting next loop...", "WARN")
                    for _ in range(cycle_delay):
                        if not ig_running.get(uid):
                            break
                        time.sleep(1)

                browser.close()
                if os.path.exists(user_data_dir):
                    shutil.rmtree(user_data_dir, ignore_errors=True)

        except Exception as e_engine:
            log_ig_terminal(uid, f"⚠️ Multi-GC Playwright notice: {e_engine}", "WARN")
            time.sleep(3)

    ig_running[uid] = False
    if uid in ig_live:
        ig_live[uid]["running"] = False
    if uid in ig_stats:
        ig_stats[uid]["running"] = False
    log_ig_terminal(uid, "⏹️ Multi-GC Playwright Engine stopped.", "INFO")

@app.route("/add_account", methods=["POST"])
def add_account():
    if not is_authenticated():
        log_ig_terminal("AUTH", "Login required to add account.", "ERROR")
        return jsonify({"status": "login_required"}), 401

    data = request.json or {}
    raw_session = data.get("sessionid", "").strip()
    sessionid = raw_session
    csrftoken = data.get("csrftoken", "").strip()

    # Auto-extract sessionid and csrftoken if full cookie string was pasted
    if ";" in sessionid or "=" in sessionid:
        for part in sessionid.split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                if k.strip().lower() == "sessionid":
                    sessionid = v.strip()
                elif k.strip().lower() == "csrftoken" and not csrftoken:
                    csrftoken = v.strip()

    if "%3A" in sessionid or "%3a" in sessionid:
        sessionid = urllib.parse.unquote(sessionid).strip()
    if sessionid.lower().startswith("sessionid="):
        sessionid = sessionid[10:].strip()

    opponent = data.get("opponent", "").strip() or data.get("target", "").strip() or ""
    header_text = data.get("header_text", "").strip() or "👑 SPAM BY KING 👑"
    footer_text = data.get("footer_text", "").strip() or "👑 SCRIPT BY SERVER GOD CLAN 👑"
    space_lines = int(data.get("space_lines", 35))
    use_long_format = bool(data.get("use_long_format", True))
    max_groups = int(data.get("max_groups", 5))
    delay = float(data.get("delay", 2.0))
    cycle_delay = int(data.get("cycle_delay", 10))

    if not sessionid:
        return jsonify({"status": "error", "message": "Session ID is required!"}), 400

    raw_messages = data.get("messages", "") or data.get("target_messages", "")
    if isinstance(raw_messages, str):
        messages = [m.strip() for m in raw_messages.replace(",", "\n").replace("\r", "").split("\n") if m.strip()]
    elif isinstance(raw_messages, list):
        messages = [str(m).strip() for m in raw_messages if str(m).strip()]
    else:
        messages = []

    raw_renames = data.get("renames", "") or data.get("target_renames", "") or data.get("gc_name", "")
    if isinstance(raw_renames, str):
        renames = [r.strip() for r in raw_renames.replace(",", "\n").replace("\r", "").split("\n") if r.strip()]
    elif isinstance(raw_renames, list):
        renames = [str(r).strip() for r in raw_renames if str(r).strip()]
    else:
        renames = []

    # Any manually provided links from add form
    raw_links = data.get("gc_links", "")
    if isinstance(raw_links, str):
        gc_links = [l.strip() for l in raw_links.replace("\r", "").split("\n") if l.strip().startswith("http")]
    elif isinstance(raw_links, list):
        gc_links = [str(l).strip() for l in raw_links if str(l).strip().startswith("http")]
    else:
        gc_links = []

    display_target = opponent or "Custom / Manual"
    log_ig_terminal("AUTH", f"📥 Received Multi-GC Registration for Target(s) '{display_target}'...", "INFO")

    uid = next_ig_uid()
    ig_running[uid] = False

    acc_data = {
        "uid": uid,
        "name": f"Multi-GC Bot #{uid}" + (f" ({opponent})" if opponent else ""),
        "username": opponent or f"MultiGC_{uid}",
        "sessionid": sessionid,
        "csrftoken": csrftoken,
        "opponent": opponent,
        "header_text": header_text,
        "footer_text": footer_text,
        "space_lines": space_lines,
        "use_long_format": use_long_format,
        "messages": messages,
        "renames": renames,
        "max_groups": max_groups,
        "delay": delay,
        "cycle_delay": cycle_delay,
        "gc_links": gc_links[:max_groups],
        "owner": get_current_user(),
        "admin_name": get_user_display_name(get_current_user()),
        "system_owner": "SERVER GOD CLAN KING",
        "createdAt": str(datetime.utcnow())
    }
    save_ig_account_db(uid, acc_data)

    ig_stats[uid] = {
        "user": get_current_user(),
        "account": uid,
        "sent": 0,
        "failed": 0,
        "renamed": 0,
        "rename_failed": 0,
        "running": False,
        "started": None
    }
    ig_live[uid] = {"running": False, "started": None}
    log_ig_terminal(uid, f"✨ Multi-GC Account #{uid} added and saved in MongoDB!", "SUCCESS")
    return jsonify({"status": "ok", "uid": uid, "username": opponent or f"MultiGC_{uid}", "gc_links": gc_links})

@app.route("/start", methods=["POST"])
def start_bot():
    uid = str(request.json.get("uid"))
    full_db = get_full_db()
    acc = full_db.get("accounts", {}).get(uid)
    if not acc:
        return jsonify({"status": "invalid", "message": "Account not found in database!"})

    if ig_running.get(uid):
        return jsonify({"status": "already_running"})

    ig_running[uid] = True
    start_time = time.time()
    ig_live[uid] = {"running": True, "started": start_time}
    if uid not in ig_stats:
        ig_stats[uid] = {"user": get_current_user(), "account": uid, "sent": 0, "failed": 0, "renamed": 0, "rename_failed": 0}
    ig_stats[uid]["running"] = True
    ig_stats[uid]["started"] = start_time

    threading.Thread(target=multi_gc_playwright_worker, args=(uid,), daemon=True).start()
    return jsonify({"status": "started"})

@app.route("/stop", methods=["POST"])
def stop_bot():
    uid = str(request.json.get("uid"))
    ig_running[uid] = False
    if uid in ig_live:
        ig_live[uid]["running"] = False
    if uid in ig_stats:
        ig_stats[uid]["running"] = False
    log_ig_terminal(uid, "Stop signal received.", "WARN")
    return jsonify({"status": "stopped"})

@app.route("/edit_account", methods=["POST"])
def edit_account():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401

    uid = str(request.json.get("uid"))
    full_db = get_full_db()
    acc = full_db.get("accounts", {}).get(uid)
    if not acc:
        return jsonify({"status": "invalid"})

    acc_owner = str(acc.get("owner", "")).strip().lower()
    cur_user = str(get_current_user()).strip().lower()
    if not is_owner() and acc_owner != cur_user:
        return jsonify({"status": "denied"}), 403

    acc["opponent"] = request.json.get("opponent", acc.get("opponent", "")).strip()
    acc["header_text"] = request.json.get("header_text", acc.get("header_text", "👑 SPAM BY KING 👑")).strip()
    acc["footer_text"] = request.json.get("footer_text", acc.get("footer_text", "👑 SCRIPT BY SERVER GOD CLAN 👑")).strip()
    acc["space_lines"] = int(request.json.get("space_lines", acc.get("space_lines", 35)))
    acc["use_long_format"] = bool(request.json.get("use_long_format", acc.get("use_long_format", True)))
    acc["max_groups"] = int(request.json.get("max_groups", acc.get("max_groups", 5)))
    acc["delay"] = float(request.json.get("delay", acc.get("delay", 2.0)))
    acc["cycle_delay"] = int(request.json.get("cycle_delay", acc.get("cycle_delay", 10)))

    raw_messages = request.json.get("messages", "")
    if isinstance(raw_messages, str):
        acc["messages"] = [m.strip() for m in raw_messages.replace(",", "\n").replace("\r", "").split("\n") if m.strip()]
    elif isinstance(raw_messages, list):
        acc["messages"] = [str(m).strip() for m in raw_messages if str(m).strip()]

    raw_renames = request.json.get("renames", "") or request.json.get("gc_name", "")
    if isinstance(raw_renames, str):
        acc["renames"] = [r.strip() for r in raw_renames.replace(",", "\n").replace("\r", "").split("\n") if r.strip()]
    elif isinstance(raw_renames, list):
        acc["renames"] = [str(r).strip() for r in raw_renames if str(r).strip()]

    # If user provided custom GC links manually in edit
    raw_links = request.json.get("gc_links", "")
    if raw_links is not None:
        if isinstance(raw_links, str):
            acc["gc_links"] = [l.strip() for l in raw_links.replace("\r", "").split("\n") if l.strip().startswith("http")][:acc["max_groups"]]
        elif isinstance(raw_links, list):
            acc["gc_links"] = [str(l).strip() for l in raw_links if str(l).strip().startswith("http")][:acc["max_groups"]]

    save_ig_account_db(uid, acc)
    log_ig_terminal(uid, "Multi-GC Account Configuration updated successfully.", "INFO")
    return jsonify({"status": "ok"})

@app.route("/delete_account", methods=["POST"])
def delete_account():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401

    uid = request.json.get("uid")
    full_db = get_full_db()
    acc = full_db.get("accounts", {}).get(uid)
    if not acc:
        return jsonify({"status": "invalid"})

    acc_owner = str(acc.get("owner", "")).strip().lower()
    cur_user = str(get_current_user()).strip().lower()
    if not is_owner() and acc_owner != cur_user:
        return jsonify({"status": "denied"}), 403

    ig_running.pop(uid, None)
    ig_clients.pop(uid, None)
    ig_stats.pop(uid, None)
    ig_live.pop(uid, None)

    delete_ig_account_db(uid)
    log_ig_terminal(uid, "Account deleted from database.", "WARN")
    return jsonify({"status": "ok"})

@app.route("/api/ig/clear_terminal", methods=["POST"])
def clear_ig_terminal():
    global ig_terminal_logs
    ig_terminal_logs.clear()
    return jsonify({"status": "ok"})

@app.route("/scrape_links", methods=["POST"])
@app.route("/ig_scrape_links", methods=["POST"])
def ig_scrape_links():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401
    
    uid = str(request.json.get("uid", "")).strip()
    sessionid = request.json.get("sessionid", "").strip()
    csrftoken = request.json.get("csrftoken", "").strip()
    max_groups = int(request.json.get("max_groups") or 5)

    full_db = get_full_db()
    acc = full_db.get("accounts", {}).get(uid, {}) if uid else {}
    if acc:
        if not sessionid:
            sessionid = acc.get("sessionid", "")
        if not csrftoken:
            csrftoken = acc.get("csrftoken", "")
        if "max_groups" in request.json and request.json["max_groups"]:
            max_groups = int(request.json["max_groups"])
        elif acc.get("max_groups"):
            max_groups = int(acc.get("max_groups"))

    if not sessionid:
        return jsonify({"status": "error", "message": "Session ID is required to scrape links!"}), 400

    links = scrape_instagram_groups(sessionid, csrftoken, max_groups=max_groups, log_fn=lambda m, l: log_ig_terminal(uid or "AUTH", m, l))
    links = links[:max_groups]

    if acc and uid:
        acc["gc_links"] = links
        acc["max_groups"] = max_groups
        save_ig_account_db(uid, acc)

    return jsonify({"status": "ok", "links": links, "count": len(links)})

@app.route("/api/ig/chatinfo", methods=["POST"])
def ig_chatinfo_api():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401
    
    uid = str(request.json.get("uid", "")).strip()
    target_link = str(request.json.get("link", "")).strip()
    full_db = get_full_db()
    acc = full_db.get("accounts", {}).get(uid, {}) if uid else {}
    
    sessionid = acc.get("sessionid", "")
    csrftoken = acc.get("csrftoken", "")
    if not sessionid:
        return jsonify({"status": "error", "message": "Valid Instagram sessionid required"}), 400

    client = InstaUnifiedClient(sessionid=sessionid, csrftoken=csrftoken)
    thread_id = None
    if "direct/t/" in target_link:
        thread_id = target_link.split("direct/t/")[1].split("/")[0].split("?")[0].strip()
    elif target_link.isdigit():
        thread_id = target_link

    if not thread_id:
        return jsonify({"status": "error", "message": "Invalid thread ID or link"}), 400

    info = client.get_thread_info(thread_id)
    if info:
        return jsonify({"status": "ok", "thread_id": thread_id, "title": info.get("title", "Instagram Group"), "users_count": len(info.get("users", []))})
    return jsonify({"status": "ok", "thread_id": thread_id, "title": "Instagram Direct Thread", "users_count": 0})

@app.route("/api/ig/join", methods=["POST"])
def ig_join_api():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401
    
    uid = str(request.json.get("uid", "")).strip()
    invite_link = str(request.json.get("link", "")).strip()
    full_db = get_full_db()
    acc = full_db.get("accounts", {}).get(uid, {}) if uid else {}
    
    if not acc:
        return jsonify({"status": "error", "message": "Account not found"}), 404

    current_links = acc.get("gc_links", [])
    if invite_link and invite_link not in current_links:
        current_links.append(invite_link)
        acc["gc_links"] = current_links
        save_ig_account_db(uid, acc)
        return jsonify({"status": "ok", "message": "Instagram group link added successfully!", "total_links": len(current_links)})
    return jsonify({"status": "ok", "message": "Link already present", "total_links": len(current_links)})

@app.route("/status")
def status():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401

    full_db = get_full_db()
    accounts = {}
    visible_stats = {}
    me = str(get_current_user()).strip().lower()

    if is_owner():
        for uid, acc in full_db.get("accounts", {}).items():
            acc_copy = dict(acc)
            acc_copy["admin_name"] = get_user_display_name(acc.get("owner", ""))
            acc_copy["system_owner"] = "SERVER GOD CLAN KING"
            accounts[uid] = acc_copy
        visible_stats = ig_stats
        users = full_db.get("users", {})
    else:
        for uid, acc in full_db.get("accounts", {}).items():
            acc_owner = str(acc.get("owner", "")).strip().lower()
            if acc_owner == me or me in acc_owner or acc_owner in me:
                acc_copy = dict(acc)
                acc_copy["admin_name"] = get_user_display_name(acc.get("owner", ""))
                acc_copy["system_owner"] = "SERVER GOD CLAN KING"
                accounts[uid] = acc_copy
                if uid in ig_stats:
                    visible_stats[uid] = ig_stats[uid]
        users = {}

    for uid, s in visible_stats.items():
        if uid in ig_live and ig_live[uid].get("running"):
            s["running"] = True
            s["uptime"] = int(time.time() - ig_live[uid]["started"])
        else:
            s["running"] = False
    if is_owner():
        ret_terminal_logs = ig_terminal_logs
    else:
        user_uids = set(str(k) for k in accounts.keys())
        user_uids.add("AUTH")
        ret_terminal_logs = [l for l in ig_terminal_logs if str(l.get("uid")) in user_uids]

    return jsonify({
        "role": session.get("role"),
        "name": session.get("name"),
        "users": users,
        "members": full_db.get("members", []),
        "accounts": accounts,
        "stats": visible_stats,
        "terminal_logs": ret_terminal_logs
    })

# ================= TELEGRAM MASTER =================
def tg_worker(uid):
    while tg_running.get(uid, False):
        try:
            full_db = get_full_db()
            cfg = full_db.get("tg_accounts", {}).get(uid)
            if not cfg:
                tg_running[uid] = False
                break

            bot_token = cfg.get("bot_token", "").strip()
            chat_ids = cfg.get("chat_ids", [])
            prefix = cfg.get("prefix", "").strip()
            delay = int(cfg.get("delay", 5))

            messages = load_messages()
            if not bot_token or not chat_ids or not messages:
                time.sleep(5)
                continue

            for chat_id in chat_ids:
                if not tg_running.get(uid):
                    break
                for msg in messages:
                    if not tg_running.get(uid):
                        break
                    try:
                        text = f"{prefix} {msg}".strip()
                        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                        resp = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
                        if resp.status_code == 200:
                            tg_stats[uid]["sent"] = tg_stats[uid].get("sent", 0) + 1
                            tg_stats[uid]["log"] = f"Sent to {chat_id}"
                        else:
                            tg_stats[uid]["failed"] = tg_stats[uid].get("failed", 0) + 1
                            tg_stats[uid]["log"] = f"Error: {resp.text[:40]}"
                        time.sleep(delay)
                    except Exception as err:
                        tg_stats[uid]["failed"] = tg_stats[uid].get("failed", 0) + 1
                        time.sleep(2)
            time.sleep(delay)
        except Exception:
            time.sleep(5)

    tg_running[uid] = False
    if uid in tg_live:
        tg_live[uid]["running"] = False
    if uid in tg_stats:
        tg_stats[uid]["running"] = False

@app.route("/tg_add_account", methods=["POST"])
def tg_add_account():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401

    data = request.json or {}
    bot_token = data.get("bot_token", "").strip()
    raw_chats = data.get("chat_ids", "")
    prefix = data.get("prefix", "").strip()
    delay = int(data.get("delay", 5))

    chat_ids = [x.strip() for x in str(raw_chats).replace(",", "\n").split("\n") if x.strip()]
    if not bot_token:
        return jsonify({"status": "error", "message": "Bot Token is required!"}), 400

    uid = next_tg_uid()
    acc_data = {
        "bot_token": bot_token,
        "chat_ids": chat_ids,
        "prefix": prefix,
        "delay": delay,
        "owner": get_current_user()
    }

    save_tg_account_db(uid, acc_data)
    tg_stats[uid] = {"user": get_current_user(), "account": uid, "sent": 0, "failed": 0, "running": False, "uptime": 0, "log": "Ready"}
    tg_live[uid] = {"running": False, "started": None}
    return jsonify({"status": "ok", "uid": uid})

@app.route("/tg_start", methods=["POST"])
def tg_start():
    uid = request.json.get("uid")
    if tg_running.get(uid):
        return jsonify({"status": "already_running"})

    tg_running[uid] = True
    start_time = time.time()
    tg_live[uid] = {"running": True, "started": start_time}
    if uid not in tg_stats:
        tg_stats[uid] = {"user": get_current_user(), "account": uid, "sent": 0, "failed": 0}
    tg_stats[uid]["running"] = True
    tg_stats[uid]["log"] = "Broadcaster Started"

    threading.Thread(target=tg_worker, args=(uid,), daemon=True).start()
    return jsonify({"status": "started"})

@app.route("/tg_stop", methods=["POST"])
def tg_stop():
    uid = request.json.get("uid")
    tg_running[uid] = False
    if uid in tg_live:
        tg_live[uid]["running"] = False
    if uid in tg_stats:
        tg_stats[uid]["running"] = False
        tg_stats[uid]["log"] = "Bot Stopped."
    return jsonify({"status": "stopped"})

@app.route("/tg_delete_account", methods=["POST"])
def tg_delete_account():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401

    uid = request.json.get("uid")
    full_db = get_full_db()
    acc = full_db.get("tg_accounts", {}).get(uid)
    if not acc:
        return jsonify({"status": "invalid"})

    if not is_owner() and acc.get("owner") != get_current_user():
        return jsonify({"status": "denied"}), 403

    tg_running.pop(uid, None)
    tg_stats.pop(uid, None)
    tg_live.pop(uid, None)
    delete_tg_account_db(uid)
    return jsonify({"status": "ok"})

# --- TELEGRAM USERBOT & MULTI-BOT MASTER REST ROUTES ---
@app.route("/tg_userbot_send_code", methods=["POST"])
def tg_userbot_send_code():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401
    ensure_tg_service()
    data = request.json or {}
    data["owner"] = get_current_user()
    try:
        r = requests.post(f"{TG_SERVICE_URL}/userbot/send_code", json=data, timeout=20)
        return jsonify(r.json()), r.status_code
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/tg_userbot_verify_code", methods=["POST"])
def tg_userbot_verify_code():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401
    ensure_tg_service()
    data = request.json or {}
    data["owner"] = get_current_user()
    try:
        r = requests.post(f"{TG_SERVICE_URL}/userbot/verify_code", json=data, timeout=20)
        return jsonify(r.json()), r.status_code
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/tg_userbot_verify_2fa", methods=["POST"])
def tg_userbot_verify_2fa():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401
    ensure_tg_service()
    data = request.json or {}
    data["owner"] = get_current_user()
    try:
        r = requests.post(f"{TG_SERVICE_URL}/userbot/verify_2fa", json=data, timeout=20)
        return jsonify(r.json()), r.status_code
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/tg_userbot_qr_gen", methods=["POST"])
def tg_userbot_qr_gen():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401
    ensure_tg_service()
    data = request.json or {}
    data["owner"] = get_current_user()
    try:
        r = requests.post(f"{TG_SERVICE_URL}/userbot/qr_generate", json=data, timeout=15)
        return jsonify(r.json()), r.status_code
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/tg_userbot_qr_check", methods=["POST"])
def tg_userbot_qr_check():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401
    ensure_tg_service()
    data = request.json or {}
    try:
        r = requests.post(f"{TG_SERVICE_URL}/userbot/qr_check", json=data, timeout=10)
        return jsonify(r.json()), r.status_code
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/tg_userbot_disconnect", methods=["POST"])
def tg_userbot_disconnect():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401
    ensure_tg_service()
    data = request.json or {}
    try:
        r = requests.post(f"{TG_SERVICE_URL}/userbot/disconnect", json=data, timeout=10)
        return jsonify(r.json()), r.status_code
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/tg_userbot_set_admin", methods=["POST"])
def tg_userbot_set_admin():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401
    ensure_tg_service()
    data = request.json or {}
    try:
        r = requests.post(f"{TG_SERVICE_URL}/userbot/set_admin", json=data, timeout=10)
        return jsonify(r.json()), r.status_code
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/tg_swarm_save", methods=["POST"])
def tg_swarm_save():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401
    ensure_tg_service()
    data = request.json or {}
    data["owner"] = get_current_user()
    try:
        r = requests.post(f"{TG_SERVICE_URL}/swarm/save", json=data, timeout=25)
        return jsonify(r.json()), r.status_code
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/tg_swarm_start", methods=["POST"])
def tg_swarm_start():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401
    ensure_tg_service()
    data = request.json or {}
    try:
        r = requests.post(f"{TG_SERVICE_URL}/swarm/start", json=data, timeout=15)
        return jsonify(r.json()), r.status_code
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/tg_swarm_stop", methods=["POST"])
def tg_swarm_stop():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401
    ensure_tg_service()
    data = request.json or {}
    try:
        r = requests.post(f"{TG_SERVICE_URL}/swarm/stop", json=data, timeout=10)
        return jsonify(r.json()), r.status_code
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/tg_swarm_delete", methods=["POST"])
def tg_swarm_delete():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401
    ensure_tg_service()
    data = request.json or {}
    try:
        r = requests.post(f"{TG_SERVICE_URL}/swarm/delete", json=data, timeout=10)
        return jsonify(r.json()), r.status_code
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/tg_master_status")
def tg_master_status():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401
    ensure_tg_service()
    try:
        r = requests.get(f"{TG_SERVICE_URL}/status", timeout=5)
        if r.status_code == 200:
            d = r.json()
            userbots = d.get("userbots", {})
            swarms = d.get("swarms", {})
            logs = d.get("logs", [])

            if not is_owner():
                me = str(get_current_user()).strip().lower()
                userbots = {k: v for k, v in userbots.items() if str(v.get("owner", "")).strip().lower() == me}
                swarms = {k: v for k, v in swarms.items() if str(v.get("owner", "")).strip().lower() == me}

                # Filter logs to only show user's own bot events
                user_identifiers = set(userbots.keys())
                for ub in userbots.values():
                    if ub.get("phone"):
                        clean_p = str(ub.get("phone")).replace("+", "").strip()
                        if clean_p: user_identifiers.add(clean_p)
                    if ub.get("name"):
                        clean_n = str(ub.get("name")).strip()
                        if clean_n: user_identifiers.add(clean_n)

                filtered_logs = []
                for l in logs:
                    if any(ident in l for ident in user_identifiers if ident):
                        filtered_logs.append(l)
                logs = filtered_logs

            # Inject clean display names & brand owner
            for k, ub in userbots.items():
                ub["admin_name"] = get_user_display_name(ub.get("owner", ""))
                ub["system_owner"] = "SERVER GOD CLAN KING"
            for k, sw in swarms.items():
                sw["admin_name"] = get_user_display_name(sw.get("owner", ""))
                sw["system_owner"] = "SERVER GOD CLAN KING"

            return jsonify({
                "userbots": userbots,
                "swarms": swarms,
                "logs": logs
            })
    except Exception as e:
        pass
    return jsonify({"userbots": {}, "swarms": {}, "logs": []})

@app.route("/tg_status")
def tg_status():
    return tg_master_status()

# ================= WHATSAPP BAILEYS MASTER =================
@app.route("/wp_add_account", methods=["POST"])
def wp_add_account():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401

    curr_user = get_current_user()
    data = request.json or {}
    custom_name = data.get("name", "").strip().replace(" ", "_")
    owner_jid = data.get("owner_jid", "").strip()

    # User-scoped clean UID
    user_tag = curr_user.split("@")[0].replace(".", "_") if "@" in curr_user else curr_user
    user_tag = "".join(c for c in user_tag if c.isalnum() or c == "_")[:12] or "usr"

    if custom_name:
        clean_n = "".join(c for c in custom_name if c.isalnum() or c == "_")
        if is_owner():
            uid = f"wp_{clean_n}" if not clean_n.startswith("wp_") else clean_n
        else:
            uid = f"wp_{user_tag}_{clean_n}"
    else:
        user_nodes = [k for k, v in cache_db.get("wp_accounts", {}).items() if v.get("owner") == curr_user]
        node_num = len(user_nodes) + 1
        uid = f"wp_{user_tag}_bot{node_num}"

    display_name = custom_name or uid.replace(f"wp_{user_tag}_", "")

    acc_data = {
        "uid": uid,
        "name": display_name,
        "owner_jid": owner_jid,
        "owner": curr_user,
        "admin_name": get_user_display_name(curr_user),
        "system_owner": "SERVER GOD CLAN KING",
        "prefix": "+",
        "delay": 5,
        "target_numbers": [],
        "createdAt": str(datetime.utcnow())
    }

    save_wp_account_db(uid, acc_data)
    ensure_baileys_service()
    try:
        requests.post(f"{BAILEYS_SERVICE_URL}/session/init", json={
            "uid": uid,
            "owner_jid": owner_jid
        }, timeout=5)
    except Exception as e:
        print(f"[WP ADD ACC ERROR]: {e}")

    return jsonify({"status": "ok", "uid": uid, "name": display_name})

@app.route("/wp_pair_code", methods=["POST"])
def wp_pair_code():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401

    data = request.json or {}
    uid = data.get("uid")
    phone = data.get("phone", "").strip()

    if not uid or not phone:
        return jsonify({"status": "error", "message": "UID and phone number are required!"}), 400

    full_db = get_full_db()
    acc = full_db.get("wp_accounts", {}).get(uid)
    if not acc:
        return jsonify({"status": "invalid"}), 404
    if not is_owner() and acc.get("owner") != get_current_user():
        return jsonify({"status": "denied"}), 403

    ensure_baileys_service()
    try:
        r = requests.post(f"{BAILEYS_SERVICE_URL}/session/{uid}/pair", json={"phone": phone}, timeout=25)
        res_data = r.json()
        if res_data.get("success"):
            return jsonify({
                "status": "ok",
                "pairingCode": res_data.get("pairingCode"),
                "rawCode": res_data.get("rawCode"),
                "phone": res_data.get("phone"),
                "expiresIn": res_data.get("expiresIn", 900)
            })
        else:
            return jsonify({"status": "error", "message": res_data.get("message", "Failed to generate pairing code")}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": f"Baileys pairing error: {e}"}), 500

@app.route("/wp_qr", methods=["GET"])
def wp_qr():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401
    uid = request.args.get("uid")
    if not uid:
        return jsonify({"status": "error", "message": "UID is required"}), 400

    refresh = request.args.get("refresh", "0") == "1"

    ensure_baileys_service()
    try:
        if refresh:
            requests.post(f"{BAILEYS_SERVICE_URL}/session/{uid}/refresh_qr", timeout=8)
            time.sleep(1)

        r = requests.get(f"{BAILEYS_SERVICE_URL}/session/{uid}/status", timeout=8)
        res_data = r.json()
        return jsonify({
            "status": "ok",
            "qr": res_data.get("qr", ""),
            "pairingCode": res_data.get("pairingCode", ""),
            "session_status": res_data.get("status", "UNKNOWN"),
            "connectedNumber": res_data.get("connectedNumber", ""),
            "isOnline": res_data.get("isOnline", False)
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/wp_set_owner", methods=["POST"])
def wp_set_owner():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401

    data = request.json or {}
    uid = data.get("uid")
    owner_jid = data.get("owner_jid", "").strip()

    full_db = get_full_db()
    acc = full_db.get("wp_accounts", {}).get(uid)
    if not acc:
        return jsonify({"status": "invalid"}), 404
    if not is_owner() and acc.get("owner") != get_current_user():
        return jsonify({"status": "denied"}), 403

    acc["owner_jid"] = owner_jid
    save_wp_account_db(uid, acc)

    ensure_baileys_service()
    try:
        requests.post(f"{BAILEYS_SERVICE_URL}/session/{uid}/set_owner", json={"owner_jid": owner_jid}, timeout=5)
    except Exception:
        pass

    return jsonify({"status": "ok", "owner_jid": owner_jid})

@app.route("/wp_start", methods=["POST"])
def wp_start():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401
    uid = request.json.get("uid")
    full_db = get_full_db()
    acc = full_db.get("wp_accounts", {}).get(uid)
    if not acc:
        return jsonify({"status": "invalid"}), 404
    if not is_owner() and acc.get("owner") != get_current_user():
        return jsonify({"status": "denied"}), 403

    ensure_baileys_service()
    try:
        r = requests.post(f"{BAILEYS_SERVICE_URL}/session/{uid}/start_worker", json={
            "targets": acc.get("target_numbers", []),
            "delay": int(acc.get("delay", 5)),
            "prefix": acc.get("prefix", ""),
            "messages": load_messages()
        }, timeout=5)
        return jsonify(r.json() if r.status_code == 200 else {"status": "started"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/wp_stop", methods=["POST"])
def wp_stop():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401
    uid = request.json.get("uid")
    full_db = get_full_db()
    acc = full_db.get("wp_accounts", {}).get(uid)
    if not acc:
        return jsonify({"status": "invalid"}), 404
    if not is_owner() and acc.get("owner") != get_current_user():
        return jsonify({"status": "denied"}), 403

    ensure_baileys_service()
    try:
        r = requests.post(f"{BAILEYS_SERVICE_URL}/session/{uid}/stop_worker", timeout=5)
        return jsonify(r.json() if r.status_code == 200 else {"status": "stopped"})
    except Exception:
        pass
    return jsonify({"status": "stopped"})

@app.route("/wp_disconnect", methods=["POST"])
def wp_disconnect():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401
    uid = request.json.get("uid")
    full_db = get_full_db()
    acc = full_db.get("wp_accounts", {}).get(uid)
    if not acc:
        return jsonify({"status": "invalid"}), 404
    if not is_owner() and acc.get("owner") != get_current_user():
        return jsonify({"status": "denied"}), 403

    ensure_baileys_service()
    try:
        r = requests.post(f"{BAILEYS_SERVICE_URL}/session/{uid}/disconnect", timeout=5)
        return jsonify(r.json() if r.status_code == 200 else {"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/wp_delete_account", methods=["POST"])
def wp_delete_account():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401

    uid = request.json.get("uid")
    full_db = get_full_db()
    acc = full_db.get("wp_accounts", {}).get(uid)
    if not acc:
        return jsonify({"status": "invalid"}), 404

    if not is_owner() and acc.get("owner") != get_current_user():
        return jsonify({"status": "denied"}), 403

    ensure_baileys_service()
    try:
        requests.post(f"{BAILEYS_SERVICE_URL}/session/{uid}/delete", timeout=5)
    except Exception:
        pass

    delete_wp_account_db(uid)
    return jsonify({"status": "ok"})

@app.route("/wp_status")
@app.route("/wp_accounts")
def wp_status():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401

    ensure_baileys_service()
    full_db = get_full_db()
    wp_accounts = full_db.get("wp_accounts", {})
    accounts = {}
    visible_stats = {}

    baileys_live = {}
    global_logs = []
    try:
        r = requests.get(f"{BAILEYS_SERVICE_URL}/sessions/all", timeout=3)
        if r.status_code == 200:
            b_data = r.json()
            baileys_live = b_data.get("sessions", {})
            global_logs = b_data.get("globalLogs", [])
    except Exception:
        pass

    is_adm = is_owner()
    curr_user = str(get_current_user()).strip().lower()

    for uid, acc in wp_accounts.items():
        acc_owner = str(acc.get("owner", "")).strip().lower()
        is_my_acc = is_adm or (acc_owner == curr_user)

        if is_my_acc:
            acc_copy = dict(acc)
            acc_copy["admin_name"] = get_user_display_name(acc.get("owner", ""))
            acc_copy["system_owner"] = "SERVER GOD CLAN KING"
            accounts[uid] = acc_copy
            b_sess = baileys_live.get(uid, {})
            visible_stats[uid] = {
                "user": acc.get("owner", curr_user),
                "admin_name": acc_copy["admin_name"],
                "account": uid,
                "status": b_sess.get("status") or ("ONLINE" if b_sess.get("isOnline") else "READY_TO_CONNECT"),
                "isOnline": b_sess.get("isOnline", False),
                "connectedNumber": b_sess.get("connectedNumber", ""),
                "ownerJid": b_sess.get("ownerJid", acc.get("owner_jid", "")),
                "running": b_sess.get("isWorkerRunning", False) or b_sess.get("isOnline", False),
                "sent": b_sess.get("sentCount", 0),
                "failed": b_sess.get("failedCount", 0),
                "uptime": b_sess.get("uptime", 0),
                "hasQr": b_sess.get("hasQr", False),
                "hasPairingCode": b_sess.get("hasPairingCode", False)
            }

    # Also include any live Baileys sessions for the user or owner
    for uid, b_sess in baileys_live.items():
        if uid not in accounts:
            acc_info = wp_accounts.get(uid, {})
            acc_owner = str(acc_info.get("owner", "")).strip().lower()
            is_my_acc = is_adm or (acc_owner and acc_owner == curr_user)
            if is_my_acc:
                accounts[uid] = {
                    "uid": uid,
                    "name": acc_info.get("name") or uid.replace("wp_", ""),
                    "owner": acc_info.get("owner", curr_user),
                    "admin_name": acc_info.get("admin_name", get_user_display_name(curr_user)),
                    "system_owner": "SERVER GOD CLAN KING",
                    "owner_jid": b_sess.get("ownerJid", acc_info.get("owner_jid", ""))
                }
                visible_stats[uid] = {
                    "user": acc_info.get("owner", curr_user),
                    "admin_name": acc_info.get("admin_name", get_user_display_name(curr_user)),
                    "account": uid,
                    "status": b_sess.get("status") or ("ONLINE" if b_sess.get("isOnline") else "READY_TO_CONNECT"),
                    "isOnline": b_sess.get("isOnline", False),
                    "connectedNumber": b_sess.get("connectedNumber", ""),
                    "ownerJid": b_sess.get("ownerJid", ""),
                    "running": b_sess.get("isOnline", False) or b_sess.get("isWorkerRunning", False),
                    "sent": b_sess.get("sentCount", 0),
                    "failed": b_sess.get("failedCount", 0),
                    "uptime": b_sess.get("uptime", 0),
                    "hasQr": b_sess.get("hasQr", False),
                    "hasPairingCode": b_sess.get("hasPairingCode", False)
                }

    # Filter logs: Admin gets all, user only gets logs for their account UIDs
    user_uids = {str(u) for u in accounts.keys() if u}
    filtered_logs = []
    for log_line in global_logs:
        if is_adm:
            filtered_logs.append(log_line)
        else:
            if any(f"[{u}]" in log_line for u in user_uids if u):
                filtered_logs.append(log_line)

    return jsonify({
        "accounts": accounts,
        "stats": visible_stats,
        "globalLogs": filtered_logs[:100]
    })

# ================= OWNER CONTROLS =================
@app.route("/api/owner/users/add", methods=["POST"])
def owner_add_user():
    if not is_authenticated() or not is_owner():
        return jsonify({"status": "denied"}), 403

    data = request.json or {}
    name = data.get("name", "").strip()
    email = data.get("email", "").lower().strip()
    phone = data.get("phone", "").strip()
    password = data.get("password", "").strip()

    if not name or not email or not password:
        return jsonify({"status": "error", "message": "Name, Email and Password are required!"}), 400

    user_data = {
        "name": name,
        "email": email,
        "phone": phone or "+91 9507325677",
        "password": password,
        "role": "user",
        "status": "active",
        "lastOtpVerifiedAt": str(datetime.now()),
        "createdAt": str(datetime.now())
    }
    save_or_update_user(user_data)
    return jsonify({"status": "ok", "message": f"User '{name}' saved to MongoDB!"})

@app.route("/api/owner/users/delete", methods=["POST"])
def owner_delete_user():
    if not is_authenticated() or not is_owner():
        return jsonify({"status": "denied"}), 403

    email_or_name = request.json.get("user", "").strip()
    if not email_or_name:
        return jsonify({"status": "error", "message": "User identifier required!"}), 400

    delete_user_db(email_or_name)
    return jsonify({"status": "ok", "message": f"User '{email_or_name}' deleted permanently!"})

@app.route("/api/owner/users/toggle_status", methods=["POST"])
def owner_toggle_user_status():
    if not is_authenticated() or not is_owner():
        return jsonify({"status": "denied"}), 403

    email = request.json.get("email", "").lower().strip()
    new_status = request.json.get("status", "active")
    user = find_user_by_email(email)
    if not user:
        return jsonify({"status": "error", "message": "User not found!"}), 400

    user["status"] = new_status
    save_or_update_user(user)
    return jsonify({"status": "ok", "message": f"Status updated to '{new_status}'!"})

@app.route("/api/owner/users/change_password", methods=["POST"])
def owner_change_user_password():
    if not is_authenticated() or not is_owner():
        return jsonify({"status": "denied"}), 403

    data = request.json or {}
    email = data.get("email", "").lower().strip()
    new_pass = data.get("password", "").strip()
    if not email or not new_pass:
        return jsonify({"status": "error", "message": "Email and new password are required!"}), 400

    user = find_user_by_email(email)
    if not user:
        return jsonify({"status": "error", "message": "User not found in MongoDB!"}), 404

    user["password"] = new_pass
    save_or_update_user(user)
    return jsonify({"status": "ok", "message": f"Password for '{email}' updated successfully!"})

@app.route("/api/owner/change_credentials", methods=["POST"])
def owner_change_credentials():
    if not is_authenticated() or not is_owner():
        return jsonify({"status": "denied"}), 403

    data = request.json or {}
    new_user = str(data.get("username", "")).strip()
    new_pass = str(data.get("password", "")).strip()
    new_name = str(data.get("name", "")).strip() or "PLATFORM OWNER"
    new_email = str(data.get("email", "")).strip()

    if not new_user or not new_pass:
        return jsonify({"status": "error", "message": "Owner Username and Password are required!"}), 400

    creds = {
        "username": new_user,
        "password": new_pass,
        "name": new_name,
        "email": new_email
    }
    save_owner_creds(creds)
    session["user"] = new_user
    session["name"] = new_name
    return jsonify({"status": "ok", "message": "Owner Username & Passcode updated successfully in MongoDB Atlas!"})

@app.route("/api/owner/users/edit", methods=["POST"])
def owner_edit_user():
    if not is_authenticated() or not is_owner():
        return jsonify({"status": "denied"}), 403

    data = request.json or {}
    old_email = str(data.get("old_email", "")).lower().strip()
    new_name = str(data.get("name", "")).strip()
    new_email = str(data.get("email", "")).lower().strip()
    new_phone = str(data.get("phone", "")).strip()
    new_password = str(data.get("password", "")).strip()
    new_status = str(data.get("status", "active")).strip()

    if not old_email:
        return jsonify({"status": "error", "message": "Target user email is required!"}), 400

    user = find_user_by_email(old_email)
    if not user:
        return jsonify({"status": "error", "message": f"User '{old_email}' not found in MongoDB!"}), 404

    # Update fields
    if new_name: user["name"] = new_name
    if new_phone: user["phone"] = new_phone
    if new_password: user["password"] = new_password
    if new_status: user["status"] = new_status

    # If email changed, migrate database keys and bot ownership
    if new_email and new_email != old_email:
        if new_email in cache_db["users"] and new_email != old_email:
            return jsonify({"status": "error", "message": f"Email '{new_email}' is already in use by another user!"}), 400

        user["email"] = new_email
        cache_db["users"].pop(old_email, None)
        cache_db["users"][new_email] = user

        # Migrate bot ownership in cache and MongoDB
        for k, acc in cache_db.get("accounts", {}).items():
            if str(acc.get("owner", "")).lower().strip() == old_email:
                acc["owner"] = new_email
                acc["admin_name"] = new_name or acc.get("admin_name")
                save_ig_account_db(k, acc)
        for k, acc in cache_db.get("gc_accounts", {}).items():
            if str(acc.get("owner", "")).lower().strip() == old_email:
                acc["owner"] = new_email
                acc["admin_name"] = new_name or acc.get("admin_name")
                save_gc_account_db(k, acc)
        for k, acc in cache_db.get("tg_accounts", {}).items():
            if str(acc.get("owner", "")).lower().strip() == old_email:
                acc["owner"] = new_email
                save_tg_account_db(k, acc)
        for k, acc in cache_db.get("wp_accounts", {}).items():
            if str(acc.get("owner", "")).lower().strip() == old_email:
                acc["owner"] = new_email
                acc["admin_name"] = new_name or acc.get("admin_name")
                save_wp_account_db(k, acc)

        if mongo_connected and mongo_db is not None:
            try:
                mongo_db["users"].delete_one({"email": old_email})
                mongo_db["users"].update_one({"email": new_email}, {"$set": user}, upsert=True)
                mongo_db["ig_accounts"].update_many({"owner": old_email}, {"$set": {"owner": new_email}})
                mongo_db["ig_gc_accounts"].update_many({"owner": old_email}, {"$set": {"owner": new_email}})
                mongo_db["tg_accounts"].update_many({"owner": old_email}, {"$set": {"owner": new_email}})
                mongo_db["wp_accounts"].update_many({"owner": old_email}, {"$set": {"owner": new_email}})
            except Exception as ex:
                print(f"[MONGODB USER MIGRATE ERROR]: {ex}")
    else:
        save_or_update_user(user)

    return jsonify({"status": "ok", "message": "User details updated successfully in MongoDB Atlas!"})

@app.route("/api/user/profile/update", methods=["POST"])
def user_profile_update():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401

    if is_owner():
        data = request.json or {}
        new_name = str(data.get("name", "")).strip()
        new_pass = str(data.get("password", "")).strip()
        creds = get_owner_creds()
        if new_name: creds["name"] = new_name
        if new_pass: creds["password"] = new_pass
        save_owner_creds(creds)
        session["name"] = creds["name"]
        return jsonify({"status": "ok", "message": "Owner profile updated successfully!"})

    current_email = str(get_current_user()).lower().strip()
    user = find_user_by_email(current_email)
    if not user:
        return jsonify({"status": "error", "message": "User session expired or not found!"}), 404

    data = request.json or {}
    new_name = str(data.get("name", "")).strip()
    new_email = str(data.get("email", "")).lower().strip()
    new_phone = str(data.get("phone", "")).strip()
    new_password = str(data.get("password", "")).strip()

    if new_name:
        user["name"] = new_name
        session["name"] = new_name
    if new_phone:
        user["phone"] = new_phone
    if new_password:
        user["password"] = new_password

    if new_email and new_email != current_email:
        if new_email in cache_db["users"] and new_email != current_email:
            return jsonify({"status": "error", "message": f"Email '{new_email}' is already registered by another user!"}), 400

        user["email"] = new_email
        cache_db["users"].pop(current_email, None)
        cache_db["users"][new_email] = user
        session["user"] = new_email

        # Update bot ownership
        for k, acc in cache_db.get("accounts", {}).items():
            if str(acc.get("owner", "")).lower().strip() == current_email:
                acc["owner"] = new_email
                acc["admin_name"] = new_name or acc.get("admin_name")
                save_ig_account_db(k, acc)
        for k, acc in cache_db.get("gc_accounts", {}).items():
            if str(acc.get("owner", "")).lower().strip() == current_email:
                acc["owner"] = new_email
                acc["admin_name"] = new_name or acc.get("admin_name")
                save_gc_account_db(k, acc)
        for k, acc in cache_db.get("tg_accounts", {}).items():
            if str(acc.get("owner", "")).lower().strip() == current_email:
                acc["owner"] = new_email
                save_tg_account_db(k, acc)
        for k, acc in cache_db.get("wp_accounts", {}).items():
            if str(acc.get("owner", "")).lower().strip() == current_email:
                acc["owner"] = new_email
                acc["admin_name"] = new_name or acc.get("admin_name")
                save_wp_account_db(k, acc)

        if mongo_connected and mongo_db is not None:
            try:
                mongo_db["users"].delete_one({"email": current_email})
                mongo_db["users"].update_one({"email": new_email}, {"$set": user}, upsert=True)
                mongo_db["ig_accounts"].update_many({"owner": current_email}, {"$set": {"owner": new_email}})
                mongo_db["ig_gc_accounts"].update_many({"owner": current_email}, {"$set": {"owner": new_email}})
                mongo_db["tg_accounts"].update_many({"owner": current_email}, {"$set": {"owner": new_email}})
                mongo_db["wp_accounts"].update_many({"owner": current_email}, {"$set": {"owner": new_email}})
            except Exception:
                pass
    else:
        save_or_update_user(user)

    return jsonify({"status": "ok", "message": "Profile and credentials updated successfully!"})

@app.route("/api/user/profile", methods=["GET"])
def get_user_profile():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401

    if is_owner():
        creds = get_owner_creds()
        return jsonify({
            "status": "ok",
            "role": "owner",
            "name": creds.get("name", session.get("name", "PLATFORM OWNER")),
            "username": creds.get("username", "OWNER"),
            "email": creds.get("email", "spamkingxl400@gmail.com"),
            "phone": "+91 9507325677"
        })

    user = find_user_by_email(get_current_user())
    if not user:
        return jsonify({
            "status": "ok",
            "role": "user",
            "name": session.get("name", "User"),
            "email": session.get("user", ""),
            "phone": ""
        })

    return jsonify({
        "status": "ok",
        "role": "user",
        "name": user.get("name", session.get("name")),
        "email": user.get("email", session.get("user")),
        "phone": user.get("phone", ""),
        "status": user.get("status", "active")
    })

@app.route("/api/owner/members/update", methods=["POST"])
def owner_update_members():
    if not is_authenticated() or not is_owner():
        return jsonify({"status": "denied"}), 403

    members = request.json.get("members", [])
    save_members_db(members)
    return jsonify({"status": "ok", "message": "Clan members updated in MongoDB!"})

@app.route("/add_user", methods=["POST"])
def legacy_add_user():
    return owner_add_user()

@app.route("/delete_user", methods=["POST"])
def legacy_delete_user():
    return owner_delete_user()

@app.route("/update_members", methods=["POST"])
def legacy_update_members():
    return owner_update_members()

# ================= RUNNER =================
if __name__ == "__main__":
    port = int(os.getenv("PORT", 20822))
    print(f"[SERVER GOD CLAN] Running on http://0.0.0.0:{port}")
    try:
        ensure_baileys_service()
    except Exception as _e:
        print(f"[BAILEYS STARTUP WARNING] {_e}")
    try:
        ensure_tg_service()
    except Exception as _e:
        print(f"[TG MASTER STARTUP WARNING] {_e}")
    app.run(host="0.0.0.0", port=port, debug=False)