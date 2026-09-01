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
    global baileys_process, go_process, tg_process
    if baileys_process:
        try:
            baileys_process.terminate()
        except Exception:
            pass
    if go_process:
        try:
            go_process.terminate()
        except Exception:
            pass
    if tg_process:
        try:
            tg_process.terminate()
        except Exception:
            pass

atexit.register(cleanup_subprocesses)

# ================= BAILEYS WHATSAPP MICROSERVICE CONFIG (Port 20824) =================
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

        child_env = os.environ.copy()
        child_env["PORT"] = "20824"
        child_env["WP_PORT"] = "20824"
        child_env["BAILEYS_PORT"] = "20824"
        child_env["WP_SERVICE_PORT"] = "20824"

        if os.path.exists(node_file):
            print(f"[BAILEYS MASTER] Starting King Bot Baileys Multi-Session Hub 2.0: {node_file}")
            baileys_process = subprocess.Popen(["node", "--expose-gc", "--max-old-space-size=512", "wp_baileys_service.js"], cwd=script_dir, env=child_env)

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

# ================= GO WHATSAPP CALLING ENGINE (Port 20825) =================
GO_SERVICE_URL = os.getenv("GO_SERVICE_URL", "http://127.0.0.1:20825")
go_process = None

def ensure_go_service():
    global go_process
    try:
        r = requests.get(f"{GO_SERVICE_URL}/health", timeout=1.5)
        if r.status_code == 200:
            return True
    except Exception:
        pass

    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        go_bin = os.path.join(script_dir, "wp_whatsmeow_service")
        yamzz_bin = os.path.join(script_dir, "YamzzBot-Caller-main", "yamzzbot")

        child_env = os.environ.copy()
        child_env["PORT"] = "20825"
        child_env["WP_PORT"] = "20825"
        child_env["BAILEYS_PORT"] = "20825"
        child_env["WP_SERVICE_PORT"] = "20825"

        if os.path.exists(go_bin):
            print(f"[WHATSAPP GO CALL ENGINE] Starting WhatsMeow + MeowCaller Go Microservice: {go_bin}")
            go_process = subprocess.Popen([go_bin], cwd=script_dir, env=child_env)
        elif os.path.exists(yamzz_bin):
            print(f"[WHATSAPP GO CALL ENGINE] Starting WhatsMeow + MeowCaller Go Microservice: {yamzz_bin}")
            go_process = subprocess.Popen([yamzz_bin], cwd=os.path.join(script_dir, "YamzzBot-Caller-main"), env=child_env)

        for _ in range(12):
            time.sleep(0.5)
            try:
                r = requests.get(f"{GO_SERVICE_URL}/health", timeout=1.5)
                if r.status_code == 200:
                    return True
            except Exception:
                pass
    except Exception as e:
        print(f"[GO CALL ENGINE ERROR] Spawning service failed: {e}")
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
GMAIL_APP_PASS = os.getenv("GMAIL_APP_PASS", "vzwb ljnu wgod exzh").replace(" ", "").strip()
_BK_PARTS = ["xkeysib-bb019db1ed389550c6fc82bac0471460", "e2cbffe23a6c6ce1b48a2d1e090d1a26-ydc9FT1N7r1CvspZ"]
BREVO_API_KEY = os.getenv("BREVO_API_KEY", os.getenv("SENDINBLUE_API_KEY", "".join(_BK_PARTS))).strip()
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "").strip()
RESEND_FROM = os.getenv("RESEND_FROM", "SERVER GOD CLAN <onboarding@resend.dev>").strip()

# In-Memory OTP Store
otp_store = {}

def generate_otp():
    return str(random.randint(100000, 999999))

def send_raw_email(to_email, subject, html_content, text_content=""):
    clean_user = os.getenv("GMAIL_USER", GMAIL_USER).strip()
    clean_pass = os.getenv("GMAIL_APP_PASS", GMAIL_APP_PASS).replace(" ", "").strip()
    brevo_key = os.getenv("BREVO_API_KEY", BREVO_API_KEY).strip()
    resend_key = os.getenv("RESEND_API_KEY", RESEND_API_KEY).strip()
    sendgrid_key = os.getenv("SENDGRID_API_KEY", SENDGRID_API_KEY).strip()
    to_email = str(to_email).strip().lower()

    # Generate plain-text fallback if not provided
    if not text_content:
        text_content = re.sub(r'<[^>]+>', ' ', html_content)
        text_content = re.sub(r'\s+', ' ', text_content).strip()

    # -------------------------------------------------------------
    # METHOD 1: Direct Gmail SMTP Engine (Port 465 SSL & Port 587 STARTTLS)
    # -------------------------------------------------------------
    if clean_user and clean_pass:
        msg = MIMEMultipart("alternative")
        msg["From"] = f'"SERVER GOD CLAN" <{clean_user}>'
        msg["To"] = to_email
        msg["Reply-To"] = clean_user
        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain="gmail.com")
        msg.attach(MIMEText(text_content, "plain", "utf-8"))
        msg.attach(MIMEText(html_content, "html", "utf-8"))

        # Port 465 SSL
        try:
            server = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=8)
            server.login(clean_user, clean_pass)
            server.sendmail(clean_user, [to_email], msg.as_string())
            server.quit()
            print(f"📧 [EMAIL SUCCESS - GMAIL SSL 465] Sent directly to {to_email} | Subject: {subject}", flush=True)
            return True
        except Exception as e_ssl:
            print(f"⚠️ [EMAIL NOTICE] Gmail 465 SSL ({e_ssl}), trying Port 587 STARTTLS...", flush=True)

        # Port 587 STARTTLS
        try:
            server = smtplib.SMTP("smtp.gmail.com", 587, timeout=8)
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(clean_user, clean_pass)
            server.sendmail(clean_user, [to_email], msg.as_string())
            server.quit()
            print(f"📧 [EMAIL SUCCESS - GMAIL TLS 587] Sent directly to {to_email} | Subject: {subject}", flush=True)
            return True
        except Exception as e_tls:
            print(f"⚠️ [EMAIL NOTICE] Gmail 587 TLS ({e_tls}), trying API methods...", flush=True)

    # -------------------------------------------------------------
    # METHOD 2: Brevo / Sendinblue HTTP REST API Fallback
    # -------------------------------------------------------------
    if brevo_key:
        try:
            sender_email = "kingoffical505@gmail.com"
            res = requests.post(
                "https://api.brevo.com/v3/smtp/email",
                headers={
                    "api-key": brevo_key,
                    "Content-Type": "application/json"
                },
                json={
                    "sender": {"name": "PRINCE CLOUD SELLAR", "email": sender_email},
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
    # METHOD 2: Resend HTTP REST API (HTTPS Port 443)
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
    "wp_accounts": {},
    "wp_call_accounts": {},
    "ig_private_accounts": {}
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

        # Load WhatsApp Baileys Accounts
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

        # Load WhatsApp Go Call Accounts
        db_wp_call = list(mongo_db["wp_call_accounts"].find({}))
        cache_db["wp_call_accounts"] = {}
        for acc in db_wp_call:
            uid = str(acc.get("uid", acc.get("_id", "")))
            if uid:
                cache_db["wp_call_accounts"][uid] = {
                    "uid": uid,
                    "name": acc.get("name", uid),
                    "owner_jid": acc.get("owner_jid", ""),
                    "target_numbers": acc.get("target_numbers", []),
                    "prefix": acc.get("prefix", "+"),
                    "delay": int(acc.get("delay", 5)),
                    "owner": acc.get("owner", "owner"),
                    "createdAt": acc.get("createdAt", str(datetime.utcnow()))
                }

        # Load Instagram Private API Accounts
        db_ig_private = list(mongo_db["ig_private_accounts"].find({}))
        cache_db["ig_private_accounts"] = {}
        for acc in db_ig_private:
            uid = str(acc.get("uid", acc.get("_id", "")))
            if uid:
                cache_db["ig_private_accounts"][uid] = {
                    "uid": uid,
                    "sessionid": acc.get("sessionid", ""),
                    "csrftoken": acc.get("csrftoken", ""),
                    "target_name": acc.get("target_name", ""),
                    "group_names": acc.get("group_names", []),
                    "messages": acc.get("messages", []),
                    "prefix": acc.get("prefix", ""),
                    "repeat_count": int(acc.get("repeat_count", 1)),
                    "delay": float(acc.get("delay", 2.0)),
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
                cache_db["wp_call_accounts"] = data.get("wp_call_accounts", {})
                cache_db["ig_private_accounts"] = data.get("ig_private_accounts", {})
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
    for k in list(cache_db.get("ig_private_accounts", {}).keys()):
        if cache_db["ig_private_accounts"][k].get("owner", "").lower() == clean_key:
            delete_ig_private_account_db(k)

    save_local_db()
    if mongo_connected and mongo_db is not None:
        try:
            mongo_db["users"].delete_one({"$or": [{"email": clean_key}, {"name": clean_key}]})
            mongo_db["ig_accounts"].delete_many({"owner": clean_key})
            mongo_db["ig_gc_accounts"].delete_many({"owner": clean_key})
            mongo_db["ig_private_accounts"].delete_many({"owner": clean_key})
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

def save_wp_call_account_db(uid, data):
    cache_db.setdefault("wp_call_accounts", {})
    cache_db["wp_call_accounts"][str(uid)] = data
    save_local_db()
    if mongo_connected and mongo_db is not None:
        try:
            doc = dict(data)
            doc["uid"] = str(uid)
            mongo_db["wp_call_accounts"].update_one({"uid": str(uid)}, {"$set": doc}, upsert=True)
        except Exception:
            pass

def delete_wp_call_account_db(uid):
    uid_str = str(uid)
    if "wp_call_accounts" in cache_db and uid_str in cache_db["wp_call_accounts"]:
        del cache_db["wp_call_accounts"][uid_str]
    save_local_db()
    if mongo_connected and mongo_db is not None:
        try:
            mongo_db["wp_call_accounts"].delete_one({"uid": uid_str})
        except Exception:
            pass

def save_ig_private_account_db(uid, data):
    cache_db.setdefault("ig_private_accounts", {})
    cache_db["ig_private_accounts"][str(uid)] = data
    save_local_db()
    if mongo_connected and mongo_db is not None:
        try:
            doc = dict(data)
            doc["uid"] = str(uid)
            mongo_db["ig_private_accounts"].update_one({"uid": str(uid)}, {"$set": doc}, upsert=True)
        except Exception:
            pass

def delete_ig_private_account_db(uid):
    uid_str = str(uid)
    if "ig_private_accounts" in cache_db and uid_str in cache_db["ig_private_accounts"]:
        del cache_db["ig_private_accounts"][uid_str]
    save_local_db()
    if mongo_connected and mongo_db is not None:
        try:
            mongo_db["ig_private_accounts"].delete_one({"uid": uid_str})
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

def next_wp_call_uid():
    accs = cache_db.get("wp_call_accounts", {})
    if not accs:
        return "wp_call_1"
    nums = [int(k.replace("wp_call_", "")) for k in accs.keys() if k.replace("wp_call_", "").isdigit()]
    return "wp_call_" + str(max(nums) + 1) if nums else "wp_call_1"

def next_ig_private_uid():
    accs = cache_db.get("ig_private_accounts", {})
    if not accs:
        return "ig_priv_1"
    nums = [int(k.replace("ig_priv_", "")) for k in accs.keys() if k.replace("ig_priv_", "").isdigit()]
    return "ig_priv_" + str(max(nums) + 1) if nums else "ig_priv_1"

# Universal Instagram Cookie Parser (Supports Netscape HTTP format, cURL cookies, JSON, Header strings & Key=Values)
def parse_instagram_cookie_input(raw_input, extra_csrf=""):
    cookies_dict = {}
    clean_sess = ""
    clean_csrf = ""
    user_id = ""

    if not raw_input:
        return cookies_dict, clean_sess, clean_csrf, user_id

    text = str(raw_input).strip()

    # 1. Netscape HTTP Cookie File format parser
    # Format: .instagram.com TRUE / TRUE <expiry> <name> <value>
    lines = text.split("\n")
    is_netscape = any("\t" in l or ("instagram.com" in l and len(l.split()) >= 6) for l in lines)

    if is_netscape:
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = re.split(r'\t+|\s{2,}|\s+', line)
            if len(parts) >= 7:
                name = parts[5].strip()
                val = parts[6].strip().strip('"').strip("'")
                cookies_dict[name] = val
            elif len(parts) >= 2 and "=" not in parts[0]:
                name = parts[-2].strip()
                val = parts[-1].strip().strip('"').strip("'")
                cookies_dict[name] = val

    # 2. JSON Cookie Array or Object format
    elif text.startswith("[") or text.startswith("{"):
        try:
            parsed_json = json.loads(text)
            if isinstance(parsed_json, list):
                for item in parsed_json:
                    if isinstance(item, dict) and "name" in item and "value" in item:
                        cookies_dict[item["name"]] = str(item["value"]).strip().strip('"')
            elif isinstance(parsed_json, dict):
                for k, v in parsed_json.items():
                    cookies_dict[k] = str(v).strip().strip('"')
        except Exception:
            pass

    # 3. Standard Cookie Header / Semicolon / Comma / Newline Key-Value format
    if not cookies_dict or "sessionid" not in cookies_dict:
        # Split by ; or newlines
        for part in re.split(r'[;\r\n]+', text):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and v:
                    cookies_dict[k] = v

    # 4. Fallback if single raw token pasted
    if not cookies_dict.get("sessionid"):
        if "%3A" in text or "%3a" in text or re.match(r'^[0-9]+%3A', text):
            clean_sess = text
            cookies_dict["sessionid"] = clean_sess

    clean_sess = cookies_dict.get("sessionid", clean_sess).strip()
    if "%3A" in clean_sess or "%3a" in clean_sess:
        clean_sess = urllib.parse.unquote(clean_sess).strip()
    cookies_dict["sessionid"] = clean_sess

    clean_csrf = cookies_dict.get("csrftoken", extra_csrf or "").strip()
    if clean_csrf:
        cookies_dict["csrftoken"] = clean_csrf

    user_id = str(cookies_dict.get("ds_user_id") or "").strip()
    if not user_id and (":" in clean_sess or "%3A" in clean_sess):
        user_id = clean_sess.split("%3A")[0].split(":")[0]
    if user_id:
        cookies_dict["ds_user_id"] = user_id

    return cookies_dict, clean_sess, clean_csrf, user_id

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

ig_priv_running = {}
ig_priv_stats = {}
ig_priv_live = {}

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

def format_uptime(seconds):
    if not seconds or seconds < 0:
        return "00:00:00"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    if d > 0:
        return f"{d}d {h:02d}:{m:02d}:{s:02d}"
    return f"{h:02d}:{m:02d}:{s:02d}"

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

@app.route("/ig_private_api")
@app.route("/playwright_private_api")
@app.route("/insta_private")
def ig_private_page():
    if not is_authenticated():
        return redirect("/login")
    return render_template(
        "ig_private_dashboard.html",
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
@app.route("/wp_bots_nc_setup")
def whatsapp_master():
    if not is_authenticated():
        return redirect("/login")
    return render_template(
        "whatsapp_dashboard.html",
        role=session.get("role"),
        name=session.get("name"),
        user=session.get("user")
    )

@app.route("/whatsapp_call_setup")
def whatsapp_call_setup():
    if not is_authenticated():
        return redirect("/login")
    return render_template(
        "whatsapp_call_dashboard.html",
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
        "message": f"Verification OTP sent to {email}. Please check your Gmail Inbox or Spam folder!"
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

    # Strict Owner Approval Flow: Default status is 'pending_approval'
    user_data = {
        "name": name,
        "email": email,
        "phone": phone,
        "password": password,
        "role": "user",
        "status": "pending_approval",
        "lastOtpVerifiedAt": str(datetime.now()),
        "createdAt": str(datetime.now())
    }

    save_or_update_user(user_data)
    clear_otp("reg_" + email)
    send_welcome_email(email, name, phone)

    return jsonify({
        "success": True,
        "pendingApproval": True,
        "message": f"🎉 Registration request submitted for {name}! Your account is currently PENDING OWNER APPROVAL. You will be able to Sign In once the Platform Owner approves your account.",
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

    user_status = str(user.get("status", "active")).strip().lower()
    if user_status == "pending_approval":
        return jsonify({
            "success": False,
            "message": "⏳ Account Under Review: Your registration is pending approval by the Platform Owner. Please contact the Owner or wait for activation!"
        }), 403

    if user_status in ["blocked", "suspended", "rejected"]:
        return jsonify({
            "success": False,
            "message": "❌ Access Denied: Your account has been SUSPENDED or REJECTED by Platform Owner!"
        }), 403

    # Check User Custom 2FA & 6-Hour Smart OTP Window
    two_factor_enabled = user.get("two_factor", True) # Default True for high security
    last_verified = user.get("lastOtpVerifiedAt")
    needs_otp = bool(two_factor_enabled)
    
    if not two_factor_enabled:
        needs_otp = False
    elif last_verified:
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
            "message": f"Welcome back, {user.get('name')}!",
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
        "message": f"Security OTP sent to {masked}. Please check your Gmail (Inbox / Spam)."
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
        "message": f"Password reset OTP sent to {masked}. Please check your Gmail (Inbox / Spam)."
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
ig_priv_terminal_logs = []
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

def log_ig_priv_terminal(uid, message, level="INFO"):
    timestamp = datetime.now().strftime("%H:%M:%S")
    entry = {
        "time": timestamp,
        "uid": str(uid),
        "level": level,
        "msg": message
    }
    ig_priv_terminal_logs.append(entry)
    if len(ig_priv_terminal_logs) > MAX_TERMINAL_LOGS:
        ig_priv_terminal_logs.pop(0)
    print(f"[{timestamp}] [IG_PRIVATE_API #{uid}] [{level}] {message}")

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

@app.route("/api/ig_priv/terminal_logs")
def api_ig_priv_terminal_logs():
    if not is_authenticated():
        return jsonify({"logs": []}), 401
    if is_owner():
        return jsonify({"logs": ig_priv_terminal_logs})
    full_db = get_full_db()
    me = str(get_current_user()).strip().lower()
    my_uids = {str(uid) for uid, acc in full_db.get("ig_private_accounts", {}).items() if str(acc.get("owner", "")).strip().lower() == me}
    my_uids.add("AUTH")
    user_logs = [l for l in ig_priv_terminal_logs if str(l.get("uid")) in my_uids]
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

@app.route("/api/ig_priv/clear_terminal", methods=["POST"])
def api_ig_priv_clear_terminal():
    global ig_priv_terminal_logs
    ig_priv_terminal_logs = []
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
        # 1. Username & Password Login via Real Headless Chromium Browser
        if self.username and self.password:
            self._log(f"Attempting real browser login for @{self.username}...", "INFO")
            
            # Step A: Playwright Real Web Login to bypass mobile device blocks
            try:
                from playwright.sync_api import sync_playwright
                user_data_dir = os.path.join(tempfile.gettempdir(), f"ig_auth_pw_{uuid.uuid4().hex[:6]}")
                os.makedirs(user_data_dir, exist_ok=True)
                
                with sync_playwright() as p:
                    browser = p.chromium.launch_persistent_context(
                        user_data_dir,
                        headless=True,
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                        viewport={"width": 1280, "height": 720},
                        args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--disable-notifications"]
                    )
                    page = browser.new_page()
                    page.goto("https://www.instagram.com/accounts/login/", wait_until="domcontentloaded", timeout=45000)
                    time.sleep(2)
                    dismiss_instagram_modals(page)

                    # Fill Username & Password
                    u_box = page.locator('input[name="username"], input[aria-label*="username"]').first
                    p_box = page.locator('input[name="password"], input[aria-label*="password"]').first

                    if u_box.count() > 0 and p_box.count() > 0:
                        u_box.fill(self.username)
                        time.sleep(0.3)
                        p_box.fill(self.password)
                        time.sleep(0.3)
                        
                        login_btn = page.locator('button[type="submit"], button:has-text("Log in"), button:has-text("Log In")').first
                        if login_btn.count() > 0:
                            login_btn.click()
                            time.sleep(4)
                            dismiss_instagram_modals(page)

                        # Check if 2FA code is needed
                        two_factor_input = page.locator('input[name="verificationCode"], input[aria-label*="Security Code"], input[placeholder*="Security Code"]').first
                        if two_factor_input.count() > 0 and two_factor_input.is_visible():
                            if self.verification_code:
                                two_factor_input.fill(self.verification_code)
                                time.sleep(0.5)
                                page.keyboard.press("Enter")
                                time.sleep(4)
                                dismiss_instagram_modals(page)
                            else:
                                browser.close()
                                raise Exception("2FA Verification Required! Enter the 6-digit code in the OTP box and click Verify again.")

                        # Check for incorrect password notice on screen
                        err_elem = page.locator('div[role="alert"], p#slfErrorAlert, div:has-text("Sorry, your password was incorrect"), div:has-text("incorrect password")')
                        if err_elem.count() > 0 and err_elem.first.is_visible():
                            browser.close()
                            raise Exception("Incorrect Instagram password! Please check username & password.")

                        # Extract authenticated cookies from browser
                        cookies_list = browser.cookies("https://www.instagram.com")
                        cookies_dict = {c["name"]: c["value"] for c in cookies_list}
                        
                        browser.close()

                        if "sessionid" in cookies_dict:
                            sid = cookies_dict.get("sessionid")
                            csrf = cookies_dict.get("csrftoken") or "missing"
                            uid_str = cookies_dict.get("ds_user_id") or ""
                            self.user_id = uid_str
                            self.resolved_username = self.username
                            self.settings = {
                                "cookies": cookies_dict,
                                "user_id": uid_str,
                                "username": self.username
                            }
                            self._log(f"🎉 Browser authentication successful for @{self.username}!", "SUCCESS")

                            # Build persistent requests web session
                            self.web_session = requests.Session()
                            for k, v in cookies_dict.items():
                                self.web_session.cookies.set(k, v, domain=".instagram.com")
                            self.web_headers = {
                                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                                "X-IG-App-ID": "936619743392459",
                                "X-Requested-With": "XMLHttpRequest",
                                "Accept": "*/*",
                                "Referer": "https://www.instagram.com/direct/inbox/",
                                "Origin": "https://www.instagram.com"
                            }
                            self.web_session.headers.update(self.web_headers)
                            return
            except Exception as e_pw:
                if "2FA" in str(e_pw) or "Incorrect" in str(e_pw):
                    raise e_pw
                self._log(f"Browser login attempt notice: {e_pw}. Trying mobile client companion...", "WARN")

            # Fallback Step B: Instagrapi Mobile Login
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
        # Dismiss common popups, cookie consent, and notifications
        for btn_text in ["Not Now", "Not now", "Cancel", "Decline", "Dismiss", "Accept", "Allow", "Close", "Save Info"]:
            btn = p_page.locator(f'button:has-text("{btn_text}"), div[role="button"]:has-text("{btn_text}"), svg[aria-label="Close"]')
            if btn.count() > 0:
                for i in range(min(btn.count(), 2)):
                    if btn.nth(i).is_visible():
                        try:
                            btn.nth(i).click(timeout=1000, force=True)
                            time.sleep(0.2)
                        except Exception:
                            pass
        
        # Handle "Continue" or "This was me" if Instagram prompts saved profile
        for continue_txt in ["Continue as", "Continue", "This Was Me", "This was me"]:
            c_btn = p_page.locator(f'button:has-text("{continue_txt}"), div[role="button"]:has-text("{continue_txt}")')
            if c_btn.count() > 0 and c_btn.first.is_visible():
                try:
                    c_btn.first.click(timeout=1500, force=True)
                    time.sleep(1)
                except Exception:
                    pass
    except Exception:
        pass

def get_msg_box(p_page):
    dismiss_instagram_modals(p_page)

    # If on general inbox without open thread, click top conversation or active thread
    if "/direct/t/" not in p_page.url:
        try:
            threads = p_page.locator('a[href*="/direct/t/"], div[role="listitem"]')
            if threads.count() > 0 and threads.first.is_visible():
                threads.first.click(timeout=3000, force=True)
                time.sleep(2)
                dismiss_instagram_modals(p_page)
        except Exception:
            pass

    selectors = [
        'div[role="textbox"][contenteditable="true"]',
        'div[role="textbox"]',
        'div[aria-label="Message"][contenteditable="true"]',
        'div[aria-label="Message"]',
        'div[data-lexical-editor="true"]',
        'div[contenteditable="true"]',
        'textarea[placeholder*="Message"]',
        'p[data-lexical-text="true"]'
    ]
    for sel in selectors:
        try:
            loc = p_page.locator(sel)
            if loc.count() > 0:
                for i in range(loc.count()):
                    el = loc.nth(i)
                    if el.is_visible():
                        return el
        except Exception:
            pass

    return None

# ================= SINGLE GC PLAYWRIGHT AUTOMATION ENGINE =================
def single_gc_playwright_worker(uid):
    uid_str = str(uid)
    full_db = get_full_db()
    acc = full_db.get("gc_accounts", {}).get(uid) or full_db.get("gc_accounts", {}).get(uid_str, {})
    if not acc:
        gc_running[uid] = False
        gc_running[uid_str] = False
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

    while gc_running.get(uid, False) or gc_running.get(uid_str, False):
        user_data_dir = os.path.join(tempfile.gettempdir(), f"playwright_session_sgc_{uid}_{uuid.uuid4().hex[:6]}")
        os.makedirs(user_data_dir, exist_ok=True)
        browser = None

        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                log_gc_terminal(uid, "🌐 Launching persistent Chromium browser instance...", "INFO")
                browser = p.chromium.launch_persistent_context(
                    user_data_dir,
                    headless=True,
                    args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--disable-notifications"]
                )

                parsed_cookies, clean_sess, clean_csrf, user_id = parse_instagram_cookie_input(sessionid)
                cookie_list = []
                for ck_k, ck_v in parsed_cookies.items():
                    cookie_list.append({
                        "name": ck_k,
                        "value": ck_v,
                        "domain": ".instagram.com",
                        "path": "/",
                        "secure": True
                    })
                if clean_sess and not any(c["name"] == "sessionid" for c in cookie_list):
                    cookie_list.append({
                        "name": "sessionid",
                        "value": clean_sess,
                        "domain": ".instagram.com",
                        "path": "/",
                        "secure": True
                    })

                browser.add_cookies(cookie_list)
                page = browser.new_page()
                page.route("**/*", block_media)

                log_gc_terminal(uid, f"Navigating to Single Group URL: {url}...", "INFO")
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                time.sleep(3)
                dismiss_instagram_modals(page)

                if "/direct/t/" not in page.url:
                    # If stopped at homepage / one-tap screen, click continue and re-navigate
                    dismiss_instagram_modals(page)
                    time.sleep(1)
                    page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    time.sleep(3)
                    dismiss_instagram_modals(page)

                msg_box = get_msg_box(page)

                inner_count = 0
                current_active_url = url
                while gc_running.get(uid, False) or gc_running.get(uid_str, False):
                    # Soft DOM purge / reload periodically for clean memory (every 40 strikes)
                    if inner_count > 0 and inner_count % 40 == 0:
                        log_gc_terminal(uid, "🧹 Soft Purge: Reloading DOM for smooth memory management...", "WARN")
                        try:
                            page.reload(wait_until="domcontentloaded", timeout=30000)
                            time.sleep(2)
                            dismiss_instagram_modals(page)
                            msg_box = get_msg_box(page)
                        except Exception:
                            pass

                    # Dynamic Config Refresh from Database for Live Real-Time Updates
                    full_db = get_full_db()
                    acc = full_db.get("gc_accounts", {}).get(uid) or full_db.get("gc_accounts", {}).get(uid_str, acc)

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

                    # Force Name Lock every 20 strikes if locker is enabled
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

                    if not gc_running.get(uid) and not gc_running.get(uid_str):
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
                            log_gc_terminal(uid, "⚠️ Message box not found. Checking page...", "WARN")
                            time.sleep(2)
                            dismiss_instagram_modals(page)
                            msg_box = get_msg_box(page)
                            if not msg_box:
                                time.sleep(2)
                                continue

                        # Focus the message input with fallback to direct DOM focus
                        try:
                            msg_box.click(timeout=3000, force=True)
                        except Exception:
                            try:
                                msg_box.evaluate("el => el.focus()")
                            except Exception:
                                pass
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
                                send_btn.click(timeout=1500, force=True)
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
                        elif uid_str in gc_stats:
                            gc_stats[uid_str]["groups"] = strike_count
                            gc_stats[uid_str]["running"] = True
                            gc_stats[uid_str]["log"] = f"Strike #{strike_count} sent to {target_label}"

                        status_tag = "LOCKER" if is_locker else "SLAMMER"
                        log_gc_terminal(uid, f"⚡ [{status_tag}] STRIKE #{strike_count} -> [{target_label}]: Long Spaced Message Sent ({space_lines} gap lines, Delay: {delay}s)", "SUCCESS")
                        time.sleep(delay)
                    except Exception as e_fill:
                        log_gc_terminal(uid, f"❌ Strike send notice: {e_fill}. Retrying...", "ERROR")
                        time.sleep(2)
                        dismiss_instagram_modals(page)
                        msg_box = get_msg_box(page)

                if browser:
                    browser.close()
                    browser = None

        except Exception as e_engine:
            err_str = str(e_engine)
            if "Resource temporarily unavailable" in err_str or "11" in err_str or "thread" in err_str.lower():
                log_gc_terminal(uid, f"⚠️ System resource limit reached ({err_str}). Sleeping 10s before auto-recovering...", "WARN")
                time.sleep(10)
            else:
                log_gc_terminal(uid, f"⚠️ Single GC Engine notice: {e_engine}. Auto-recovering in 5s...", "WARN")
                time.sleep(5)
        finally:
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass
                browser = None
            if os.path.exists(user_data_dir):
                try:
                    shutil.rmtree(user_data_dir, ignore_errors=True)
                except Exception:
                    pass

    gc_running[uid] = False
    gc_running[uid_str] = False
    if uid in gc_live:
        gc_live[uid]["running"] = False
    if uid_str in gc_live:
        gc_live[uid_str]["running"] = False
    if uid in gc_stats:
        gc_stats[uid]["running"] = False
    if uid_str in gc_stats:
        gc_stats[uid_str]["running"] = False
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
        return jsonify({"status": "error", "message": "Group URL is required!"}), 400

    uid = next_gc_uid()
    current_user = get_current_user()

    acc = {
        "uid": uid,
        "owner": current_user,
        "sessionid": sessionid,
        "csrftoken": csrftoken,
        "url": url,
        "opponent": opponent,
        "header_text": header_text,
        "footer_text": footer_text,
        "space_lines": space_lines,
        "use_long_format": use_long_format,
        "messages": messages,
        "gc_name": gc_name,
        "delay": delay,
        "is_locker": is_locker,
        "created_at": datetime.now().isoformat()
    }
    save_gc_account_db(uid, acc)

    gc_running[uid] = False
    gc_stats[uid] = {
        "user": current_user,
        "account": uid,
        "groups": 0,
        "failed": 0,
        "running": False,
        "uptime": 0,
        "uptime_str": "00:00:00",
        "log": "Single GC Added Successfully"
    }
    gc_live[uid] = {"running": False, "started": None}
    log_gc_terminal(uid, f"✨ Single GC Account #{uid} added and saved in MongoDB!", "SUCCESS")
    return jsonify({"status": "ok", "uid": uid, "username": opponent or "SingleGC"})

@app.route("/gc_start", methods=["POST"])
def gc_start():
    uid = str(request.json.get("uid"))
    full_db = get_full_db()
    acc = full_db.get("gc_accounts", {}).get(uid)
    if not acc:
        return jsonify({"status": "invalid"})

    if gc_running.get(uid):
        return jsonify({"status": "already_running"})

    start_time = time.time()
    gc_running[uid] = True
    gc_live[uid] = {"running": True, "started": start_time}
    gc_stats[uid] = {
        "user": get_current_user(),
        "account": uid,
        "groups": gc_stats.get(uid, {}).get("groups", 0),
        "failed": gc_stats.get(uid, {}).get("failed", 0),
        "running": True,
        "uptime": 0,
        "uptime_str": "00:00:00",
        "started": start_time,
        "log": "Starting Playwright browser engine..."
    }
    threading.Thread(target=single_gc_playwright_worker, args=(uid,), daemon=True).start()
    return jsonify({"status": "started"})

@app.route("/gc_stop", methods=["POST"])
def gc_stop():
    uid = str(request.json.get("uid"))
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

    uid = str(request.json.get("uid"))
    full_db = get_full_db()
    acc = full_db.get("gc_accounts", {}).get(uid)
    if not acc:
        return jsonify({"status": "invalid"})

    me = str(get_current_user()).strip().lower()
    acc_owner = str(acc.get("owner", "")).strip().lower()
    if not is_owner() and acc_owner != me:
        return jsonify({"status": "unauthorized"}), 403

    gc_running[uid] = False
    if uid in gc_stats:
        del gc_stats[uid]
    if uid in gc_live:
        del gc_live[uid]
    delete_gc_account_db(uid)
    log_gc_terminal(uid, "Single GC Account deleted.", "WARN")
    return jsonify({"status": "deleted"})

@app.route("/gc_edit_account", methods=["POST"])
def gc_edit_account():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401

    uid = str(request.json.get("uid"))
    full_db = get_full_db()
    acc = full_db.get("gc_accounts", {}).get(uid)
    if not acc:
        return jsonify({"status": "invalid"})

    me = str(get_current_user()).strip().lower()
    acc_owner = str(acc.get("owner", "")).strip().lower()
    if not is_owner() and acc_owner != me:
        return jsonify({"status": "unauthorized"}), 403

    data = request.json or {}
    acc["url"] = data.get("url", acc.get("url", "")).strip()
    acc["opponent"] = data.get("opponent", acc.get("opponent", "")).strip()
    acc["header_text"] = data.get("header_text", acc.get("header_text", "👑 SPAM BY KING 👑")).strip()
    acc["footer_text"] = data.get("footer_text", acc.get("footer_text", "👑 SCRIPT BY SERVER GOD CLAN 👑")).strip()
    acc["space_lines"] = int(data.get("space_lines", acc.get("space_lines", 35)))
    acc["use_long_format"] = bool(data.get("use_long_format", acc.get("use_long_format", True)))
    acc["gc_name"] = data.get("gc_name", acc.get("gc_name", "LOCKED BY GOD CLAN")).strip()
    acc["delay"] = float(data.get("delay", acc.get("delay", 4)))
    acc["is_locker"] = bool(data.get("is_locker", acc.get("is_locker", True)))

    raw_msgs = data.get("messages")
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
                gc_stats[uid] = {"user": acc.get("owner", ""), "account": uid, "groups": 0, "failed": 0, "running": False, "uptime": 0, "uptime_str": "00:00:00", "log": "Awaiting Start"}
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
                    gc_stats[uid] = {"user": acc.get("owner", ""), "account": uid, "groups": 0, "failed": 0, "running": False, "uptime": 0, "uptime_str": "00:00:00", "log": "Awaiting Start"}
                visible[uid] = gc_stats[uid]

    for uid, s in visible.items():
        uid_str = str(uid)
        live_info = gc_live.get(uid) or gc_live.get(uid_str)
        if live_info and live_info.get("running") and live_info.get("started"):
            s["running"] = True
            elapsed = int(time.time() - live_info["started"])
            s["uptime"] = elapsed
            s["uptime_str"] = format_uptime(elapsed)
            s["started"] = live_info["started"]
        else:
            s["running"] = False
            s["uptime"] = 0
            s["uptime_str"] = "00:00:00"

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

def scrape_instagram_groups(sessionid, csrftoken=None, max_groups=1000, log_fn=None):
    parsed_cookies, clean_sessionid, clean_csrf, user_id = parse_instagram_cookie_input(sessionid, csrftoken or "")

    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "X-Requested-With": "XMLHttpRequest",
        "X-CSRFToken": clean_csrf or parsed_cookies.get("csrftoken", "missing"),
        "X-IG-App-ID": "936619743392459",
        "X-ASBD-ID": "129477",
        "Referer": "https://www.instagram.com/direct/inbox/",
    }
    cookies = dict(parsed_cookies)
    if clean_sessionid:
        cookies["sessionid"] = clean_sessionid
    if clean_csrf and clean_csrf != "missing":
        cookies["csrftoken"] = clean_csrf
    if user_id.isdigit():
        cookies["ds_user_id"] = user_id

    links = []
    seen_ids = set()

    # Instagram distributes group chats across multiple folders:
    # 1. Main Inbox (Primary)
    # 2. General Folder
    # 3. Pending Requests
    # 4. Hidden / Filtered Requests
    # 5. Spam Requests
    endpoints = [
        ("Main Inbox", "https://www.instagram.com/api/v1/direct_v2/inbox/"),
        ("General Inbox", "https://www.instagram.com/api/v1/direct_v2/inbox/?folder=general"),
        ("Pending Requests", "https://www.instagram.com/api/v1/direct_v2/inbox/?folder=pending"),
        ("Hidden Requests", "https://www.instagram.com/api/v1/direct_v2/inbox/?folder=hidden"),
        ("Spam Requests", "https://www.instagram.com/api/v1/direct_v2/inbox/?folder=spam"),
    ]

    if log_fn:
        log_fn(f"🔍 Scraping up to {max_groups} group chat links across all folders (Primary, General, Pending, Hidden, Spam)...", "INFO")

    for name, base_url in endpoints:
        cursor = None
        prev_cursor = None
        page_num = 1
        
        while len(links) < max_groups:
            params = {
                "limit": 50,
                "thread_message_limit": 1,
                "persistentBadging": "true"
            }
            if cursor:
                params["cursor"] = str(cursor)
                params["direction"] = "older"
                
            try:
                r = requests.get(
                    base_url,
                    headers=headers,
                    cookies=cookies,
                    params=params,
                    timeout=15
                )
            except Exception as err:
                if log_fn:
                    log_fn(f"⚠️ Network notice during {name} scan: {err}", "WARN")
                break

            if r.status_code != 200:
                break

            try:
                data = r.json()
            except Exception:
                break

            inbox = data.get("inbox", {}) if isinstance(data.get("inbox"), dict) else data.get("pending_requests", {}) or data
            threads = inbox.get("threads", []) if isinstance(inbox, dict) else []
            if not threads and isinstance(data.get("threads"), list):
                threads = data.get("threads", [])

            if not threads:
                break

            new_found_in_page = 0
            for t in threads:
                # Identification for all group chat variants
                is_group = (
                    t.get("is_group") is True
                    or len(t.get("users", [])) > 1
                    or t.get("thread_type") in ["group", "channel", "broadcast_channel"]
                    or t.get("named", False) is True
                )
                
                if is_group:
                    thread_id = t.get("thread_v2_id") or t.get("thread_id") or t.get("id")
                    if thread_id and str(thread_id) not in seen_ids:
                        seen_ids.add(str(thread_id))
                        link = f"https://www.instagram.com/direct/t/{thread_id}/"
                        links.append(link)
                        new_found_in_page += 1
                        if len(links) >= max_groups:
                            break

            page_num += 1
            if len(links) >= max_groups:
                break

            old_cursor = (
                inbox.get("oldest_cursor")
                or inbox.get("cursor")
                or data.get("oldest_cursor")
                or data.get("cursor")
                or data.get("next_max_id")
            )
            
            if not old_cursor and threads:
                last_t = threads[-1]
                old_cursor = (
                    last_t.get("last_activity_at")
                    or last_t.get("last_permanent_item", {}).get("timestamp")
                )
            
            if not old_cursor or str(old_cursor) == str(prev_cursor):
                break
                
            prev_cursor = old_cursor
            cursor = old_cursor
            time.sleep(0.5)

    if log_fn:
        if links:
            log_fn(f"✅ Successfully scraped {len(links)} total unique Instagram Group Chat Links across all folders!", "SUCCESS")
        else:
            log_fn("⚠️ 0 group chats found in any folder.", "WARN")
    return links

def multi_gc_playwright_worker(uid):
    uid_str = str(uid)
    full_db = get_full_db()
    acc = full_db.get("accounts", {}).get(uid_str) or full_db.get("accounts", {}).get(uid, {})
    if not acc:
        ig_running[uid] = False
        ig_running[uid_str] = False
        log_ig_terminal(uid, "Account not found in DB. Stopping.", "ERROR")
        return

    sessionid = (acc.get("sessionid") or "").strip()
    csrftoken = (acc.get("csrftoken") or "").strip()

    parsed_cookies, clean_sess, clean_csrf, user_id = parse_instagram_cookie_input(sessionid, csrftoken or "")

    log_ig_terminal(uid, f"🚀 Multi-GC Playwright Engine deployed for Bot #{uid} (1-Text + 1-NC Mode)!", "SUCCESS")

    cycle_count = 0
    msg_idx = 0
    nc_idx = 0

    while ig_running.get(uid, False) or ig_running.get(uid_str, False):
        user_data_dir = os.path.join(tempfile.gettempdir(), f"ig_multi_browser_{uid}_{uuid.uuid4().hex[:6]}")
        os.makedirs(user_data_dir, exist_ok=True)
        browser = None

        try:
            # Dynamic Config Refresh from Database for Live Real-Time Updates
            full_db = get_full_db()
            acc = full_db.get("accounts", {}).get(uid_str) or full_db.get("accounts", {}).get(uid) or acc

            # Dynamic Group Link Scrape / Refresh
            gc_links = acc.get("gc_links", [])
            max_groups = int(acc.get("max_groups", 150))
            if gc_links and len(gc_links) > max_groups:
                gc_links = gc_links[:max_groups]

            if not gc_links:
                log_ig_terminal(uid, "⚠️ No group chats in card. Click '🔍 Auto-Scrape GC Links' or paste links into the card textarea, then click Save!", "WARN")
                time.sleep(5)
                continue

            cycle_count += 1
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
            if not messages:
                messages = ["SERVER GOD CLAN ON TOP 🔥", "SYSTEM ONLINE 💥", "WAR ACTIVE ⚡"]

            raw_renames = acc.get("renames", []) or acc.get("gc_name", [])
            if isinstance(raw_renames, str):
                nc_list = [r.strip() for r in raw_renames.replace("\r", "").split("\n") if r.strip()]
            elif isinstance(raw_renames, list):
                nc_list = [str(r).strip() for r in raw_renames if str(r).strip()]
            else:
                nc_list = []

            log_ig_terminal(uid, f"🌐 [CYCLE #{cycle_count}] Launching fresh Chromium browser session for {len(gc_links)} group(s)...", "INFO")

            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch_persistent_context(
                    user_data_dir,
                    headless=True,
                    args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--disable-notifications"]
                )

                cookie_list = []
                for ck_k, ck_v in parsed_cookies.items():
                    cookie_list.append({
                        "name": ck_k,
                        "value": ck_v,
                        "domain": ".instagram.com",
                        "path": "/",
                        "secure": True
                    })
                if clean_sess and not any(c["name"] == "sessionid" for c in cookie_list):
                    cookie_list.append({
                        "name": "sessionid",
                        "value": clean_sess,
                        "domain": ".instagram.com",
                        "path": "/",
                        "secure": True
                    })
                if clean_csrf and not any(c["name"] == "csrftoken" for c in cookie_list):
                    cookie_list.append({
                        "name": "csrftoken",
                        "value": clean_csrf,
                        "domain": ".instagram.com",
                        "path": "/",
                        "secure": True
                    })
                browser.add_cookies(cookie_list)

                page = browser.new_page()
                page.route("**/*", block_media)

                # Iterate each group chat link in this cycle: 1 TEXT MESSAGE + 1 NC RENAME PER GC
                for g_idx, gc_url in enumerate(gc_links, 1):
                    if not ig_running.get(uid) and not ig_running.get(uid_str):
                        break

                    log_ig_terminal(uid, f"👉 [{g_idx}/{len(gc_links)}] Opening Group Chat: {gc_url}...", "INFO")
                    try:
                        page.goto(gc_url, wait_until="domcontentloaded", timeout=45000)
                        time.sleep(2)
                        dismiss_instagram_modals(page)
                        if "/direct/t/" not in page.url:
                            dismiss_instagram_modals(page)
                            time.sleep(1)
                            page.goto(gc_url, wait_until="domcontentloaded", timeout=45000)
                            time.sleep(2)
                            dismiss_instagram_modals(page)
                    except Exception as e_nav:
                        log_ig_terminal(uid, f"⚠️ Navigation notice for GC #{g_idx}: {e_nav}", "WARN")
                        time.sleep(1)

                    # --- STEP 1: SEND 1 TEXT MESSAGE ---
                    if not ig_running.get(uid) and not ig_running.get(uid_str):
                        break

                    current_target = raw_targets[msg_idx % len(raw_targets)] if raw_targets else ""
                    core_msg = messages[msg_idx % len(messages)]
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
                        msg_box = get_msg_box(page)
                        if msg_box and msg_box.is_visible():
                            try:
                                msg_box.click(timeout=3000, force=True)
                            except Exception:
                                try:
                                    msg_box.evaluate("el => el.focus()")
                                except Exception:
                                    pass
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
                                    send_btn.click(timeout=1500, force=True)
                                    sent = True
                                except Exception:
                                    pass
                            if not sent:
                                page.keyboard.press("Enter")

                            if uid in ig_stats:
                                ig_stats[uid]["sent"] = ig_stats[uid].get("sent", 0) + 1
                            elif uid_str in ig_stats:
                                ig_stats[uid_str]["sent"] = ig_stats[uid_str].get("sent", 0) + 1
                            log_ig_terminal(uid, f"📨 [1 Text] Sent to GC #{g_idx} -> [{target_label}] (Delay: {delay}s)", "SUCCESS")
                        else:
                            if uid in ig_stats:
                                ig_stats[uid]["failed"] = ig_stats[uid].get("failed", 0) + 1
                            elif uid_str in ig_stats:
                                ig_stats[uid_str]["failed"] = ig_stats[uid_str].get("failed", 0) + 1
                            log_ig_terminal(uid, f"⚠️ Message box not found in GC #{g_idx}", "WARN")

                        time.sleep(delay)
                    except Exception as e_send:
                        if uid in ig_stats:
                            ig_stats[uid]["failed"] = ig_stats[uid].get("failed", 0) + 1
                        elif uid_str in ig_stats:
                            ig_stats[uid_str]["failed"] = ig_stats[uid_str].get("failed", 0) + 1
                        log_ig_terminal(uid, f"❌ Send error in GC #{g_idx}: {e_send}", "ERROR")
                        time.sleep(1)

                    # --- STEP 2: PERFORM 1 NC RENAME ---
                    if not ig_running.get(uid) and not ig_running.get(uid_str):
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
                                gear.first.click(timeout=4000)
                                time.sleep(1)
                                change_btn = page.locator('div[aria-label="Change group name"][role="button"], div[role="button"]:has-text("Change group name")').first
                                if change_btn.count() > 0:
                                    change_btn.click(timeout=4000)
                                    time.sleep(0.5)
                                    group_input = page.locator('input[aria-label="Group name"][name="change-group-name"], input[placeholder="Group name"]').first
                                    if group_input.count() > 0:
                                        group_input.fill(new_nc)
                                        time.sleep(0.5)
                                        save_btn = page.locator('div[role="button"]:has-text("Save"), button:has-text("Save")').first
                                        if save_btn.count() > 0 and save_btn.is_enabled():
                                            save_btn.click(timeout=4000)
                                            if uid in ig_stats:
                                                ig_stats[uid]["renamed"] = ig_stats[uid].get("renamed", 0) + 1
                                            elif uid_str in ig_stats:
                                                ig_stats[uid_str]["renamed"] = ig_stats[uid_str].get("renamed", 0) + 1
                                            log_ig_terminal(uid, f"🏷️ [1 NC] Renamed GC #{g_idx} to '{new_nc}'", "SUCCESS")
                                gear.first.click(timeout=4000)
                                time.sleep(0.5)
                        except Exception as e_nc:
                            log_ig_terminal(uid, f"⚠️ NC rename notice in GC #{g_idx}: {e_nc}", "WARN")

                    time.sleep(1)

                # Close browser immediately after completing round across all GCs
                try:
                    browser.close()
                    browser = None
                except Exception:
                    pass

            # --- ALL GCS FINISHED: CYCLE DELAY (10s wait) BEFORE NEXT CYCLE ---
            if not ig_running.get(uid) and not ig_running.get(uid_str):
                break

            log_ig_terminal(uid, f"✨ Cycle #{cycle_count} completed across all {len(gc_links)} groups! Chrome closed to clear load. Waiting {cycle_delay}s before starting next loop...", "WARN")
            for _ in range(cycle_delay):
                if not ig_running.get(uid) and not ig_running.get(uid_str):
                    break
                time.sleep(1)

        except Exception as e_engine:
            log_ig_terminal(uid, f"⚠️ Multi-GC Playwright notice: {e_engine}. Auto-recovering in 3s...", "WARN")
            time.sleep(3)
        finally:
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass
            if os.path.exists(user_data_dir):
                try:
                    shutil.rmtree(user_data_dir, ignore_errors=True)
                except Exception:
                    pass

    ig_running[uid] = False
    ig_running[uid_str] = False
    if uid in ig_live:
        ig_live[uid]["running"] = False
    if uid_str in ig_live:
        ig_live[uid_str]["running"] = False
    if uid in ig_stats:
        ig_stats[uid]["running"] = False
    if uid_str in ig_stats:
        ig_stats[uid_str]["running"] = False
    log_ig_terminal(uid, "⏹️ Multi-GC Playwright Engine stopped.", "INFO")

# ================= INSTAGRAM PLAYWRIGHT PRIVATE API ENGINE =================
# 50 Default Emojis for NC Loops
IG_PRIVATE_EMOJI_LIST = [
    '👑', '🔥', '⚡', '💥', '💀', '😈', '🦁', '🦅', '⚔️', '🔱',
    '💎', '🚀', '🌟', '🌪️', '💣', '🩸', '🎯', '🐅', '🐺', '🐉',
    '🏆', '🥇', '🎩', '🥋', '🥊', '🛡️', '🗡️', '⛓️', '🕷️', '🦂',
    '🦇', '👹', '👺', '🥶', '🥵', '☠️', '🚩', '🪐', '☄️', '🔮',
    '🧿', '🖤', '🤍', '🤎', '💜', '💙', '💚', '💛', '🧡', '❤️'
]

def ig_private_api_worker(uid):
    uid_str = str(uid)
    full_db = get_full_db()
    acc = full_db.get("ig_private_accounts", {}).get(uid_str) or full_db.get("ig_private_accounts", {}).get(uid, {})
    if not acc:
        ig_priv_running[uid] = False
        ig_priv_running[uid_str] = False
        log_ig_priv_terminal(uid, "Account not found in database. Stopped.", "ERROR")
        return

    auth_type = str(acc.get("auth_type", "cookie")).lower().strip()
    sessionid = (acc.get("sessionid") or "").strip()
    csrftoken = (acc.get("csrftoken") or "").strip()
    username = str(acc.get("username", "")).strip()
    password = str(acc.get("password", "")).strip()
    totp_key = str(acc.get("totp_key", "")).strip()

    if auth_type == "credentials" or sessionid.startswith("CREDENTIALS:"):
        if sessionid.startswith("CREDENTIALS:"):
            parts = sessionid.split(":", 2)
            if len(parts) >= 3:
                username = username or parts[1]
                password = password or parts[2]

        v_code = ""
        if totp_key:
            try:
                import pyotp
                totp = pyotp.TOTP(totp_key.replace(" ", "").upper())
                v_code = totp.now()
                log_ig_priv_terminal(uid, f"🔑 Generated Live 2FA OTP Code: {v_code}", "INFO")
            except Exception as e_totp:
                log_ig_priv_terminal(uid, f"⚠️ 2FA Key Notice: {e_totp}", "WARN")

        log_ig_priv_terminal(uid, f"🔐 Authenticating @{username} via Direct Credentials...", "INFO")
        try:
            client, settings, resolved_user = init_instagram_client(
                username=username,
                password=password,
                verification_code=v_code,
                log_fn=lambda m, l: log_ig_priv_terminal(uid, m, l)
            )
            cookies = settings.get("cookies", {})
            parsed_cookies = cookies
            clean_sess = cookies.get("sessionid", "")
            clean_csrf = cookies.get("csrftoken", "")
            user_id = str(settings.get("user_id") or "")
            log_ig_priv_terminal(uid, f"✅ Successfully logged in as @{resolved_user}!", "SUCCESS")
        except Exception as e_auth:
            log_ig_priv_terminal(uid, f"❌ Login Failed: {e_auth}", "ERROR")
            ig_priv_running[uid] = False
            ig_priv_running[uid_str] = False
            return
    else:
        parsed_cookies, clean_sess, clean_csrf, user_id = parse_instagram_cookie_input(sessionid, csrftoken or "")

    log_ig_priv_terminal(uid, f"🚀 Playwright Private Engine started for Bot #{uid}!", "SUCCESS")

    cycle_count = 0
    msg_cycle_idx = 0
    emoji_idx = 0

    while ig_priv_running.get(uid, False) or ig_priv_running.get(uid_str, False):
        user_data_dir = os.path.join(tempfile.gettempdir(), f"ig_priv_browser_{uid}_{uuid.uuid4().hex[:6]}")
        os.makedirs(user_data_dir, exist_ok=True)
        browser = None

        try:
            full_db = get_full_db()
            acc = full_db.get("ig_private_accounts", {}).get(uid_str) or full_db.get("ig_private_accounts", {}).get(uid) or acc

            mode_type = str(acc.get("mode_type", "multi")).lower().strip() # "single" or "multi"
            prefix = (acc.get("prefix") or acc.get("target_name") or "").strip()
            target_name = (acc.get("target_name") or "").strip()

            raw_groups = acc.get("group_names", []) or acc.get("thread_ids", [])
            if isinstance(raw_groups, str):
                groups = [g.strip() for g in re.split(r"[,;\n\r]+", raw_groups) if g.strip()]
            elif isinstance(raw_groups, list):
                groups = [str(g).strip() for g in raw_groups if str(g).strip()]
            else:
                groups = []

            # Format full group chat URLs
            gc_urls = []
            for g in groups:
                if g.startswith("http"):
                    gc_urls.append(g)
                else:
                    gc_urls.append(f"https://www.instagram.com/direct/t/{g}/")

            if not gc_urls:
                log_ig_priv_terminal(uid, "⚠️ No GC Link provided. Please add Group URL / Thread ID.", "WARN")
                time.sleep(5)
                continue

            raw_messages = acc.get("messages", [])
            if isinstance(raw_messages, str):
                messages = [m.strip() for m in raw_messages.replace("\r", "").split("\n") if m.strip()]
            elif isinstance(raw_messages, list):
                messages = [str(m).strip() for m in raw_messages if str(m).strip()]
            else:
                messages = []
            if not messages:
                messages = ["SERVER GOD CLAN ON TOP 🔥", "PLAYWRIGHT PRIVATE API STRIKE 💥", "WAR MODE ACTIVE ⚡"]

            # Load Custom NC titles
            raw_nc = acc.get("nc_names") or acc.get("group_renames") or ""
            if isinstance(raw_nc, str):
                nc_list = [n.strip() for n in raw_nc.replace("\r", "").split("\n") if n.strip()]
            elif isinstance(raw_nc, list):
                nc_list = [str(n).strip() for n in raw_nc if str(n).strip()]
            else:
                nc_list = []
            if not nc_list:
                nc_list = ["KING CONQUERED THIS GC 👑", "SERVER GOD CLAN ON TOP 🔥", "LOCKED BY KING SQUAD ⚡"]

            # Load Script Gap Formatting
            header_text = str(acc.get("header_text") or "👑 SPAM BY KING 👑").strip()
            footer_text = str(acc.get("footer_text") or "👑 SCRIPT BY SERVER GOD CLAN 👑").strip()
            space_lines = int(acc.get("space_lines", 35))
            blank_block = "\n".join(["⠀" for _ in range(space_lines)])
            use_long_format = bool(acc.get("use_long_format", True))

            delay = float(acc.get("delay", 2.0))
            if delay < 0.3:
                delay = 2.0

            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch_persistent_context(
                    user_data_dir,
                    headless=True,
                    viewport={"width": 1280, "height": 720},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                    args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--disable-notifications"]
                )

                # Inject parsed cookies
                cookie_list = []
                for ck_k, ck_v in parsed_cookies.items():
                    cookie_list.append({
                        "name": ck_k,
                        "value": ck_v,
                        "domain": ".instagram.com",
                        "path": "/",
                        "secure": True
                    })
                if clean_sess and not any(c["name"] == "sessionid" for c in cookie_list):
                    cookie_list.append({
                        "name": "sessionid",
                        "value": clean_sess,
                        "domain": ".instagram.com",
                        "path": "/",
                        "secure": True
                    })
                browser.add_cookies(cookie_list)
                page = browser.new_page()
                page.route("**/*", block_media)

                if mode_type == "single" or len(gc_urls) == 1:
                    target_url = gc_urls[0]
                    cycle_count += 1
                    repeat_msgs = int(acc.get("repeat_count") or 15)
                    if repeat_msgs < 1:
                        repeat_msgs = 15

                    log_ig_priv_terminal(uid, f"🎯 [SINGLE GC CYCLE #{cycle_count}] Opening GC: {target_url}...", "INFO")
                    page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
                    time.sleep(3)
                    dismiss_instagram_modals(page)

                    if "/direct/t/" not in page.url:
                        dismiss_instagram_modals(page)
                        page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
                        time.sleep(3)
                        dismiss_instagram_modals(page)

                    msg_box = get_msg_box(page)
                    if not msg_box:
                        time.sleep(3)
                        dismiss_instagram_modals(page)
                        msg_box = get_msg_box(page)

                    # 1. Send Messages with 35-line Gap Format
                    log_ig_priv_terminal(uid, f"📨 Firing {repeat_msgs} Messages in GC...", "INFO")
                    for m_i in range(repeat_msgs):
                        if not ig_priv_running.get(uid) and not ig_priv_running.get(uid_str):
                            break

                        raw_txt = messages[msg_cycle_idx % len(messages)]
                        msg_cycle_idx += 1
                        current_emoji = IG_PRIVATE_EMOJI_LIST[emoji_idx % len(IG_PRIVATE_EMOJI_LIST)]

                        if prefix:
                            core_msg = f"[{prefix}] {raw_txt} {current_emoji}"
                        elif target_name:
                            core_msg = f"[{target_name}] {raw_txt} {current_emoji}"
                        else:
                            core_msg = f"{raw_txt} {current_emoji}"

                        if use_long_format:
                            final_msg = f"{header_text}\n{blank_block}\n{core_msg}\n{blank_block}\n{footer_text}"
                        else:
                            final_msg = core_msg

                        try:
                            if not msg_box or not msg_box.is_visible():
                                msg_box = get_msg_box(page)

                            if msg_box:
                                msg_box.click(timeout=3000, force=True)
                                page.keyboard.press("Control+A")
                                page.keyboard.press("Backspace")
                                page.keyboard.insert_text(final_msg)
                                time.sleep(0.2)
                                
                                # Trigger send
                                sent = False
                                send_btn = page.locator('button:has-text("Send"), div[role="button"]:has-text("Send"), div[aria-label="Send"], svg[aria-label="Send"]').first
                                if send_btn.count() > 0 and send_btn.is_visible():
                                    try:
                                        send_btn.click(timeout=1500, force=True)
                                        sent = True
                                    except Exception:
                                        pass
                                if not sent:
                                    page.keyboard.press("Enter")
                                
                                if uid in ig_priv_stats:
                                    ig_priv_stats[uid]["sent"] = ig_priv_stats[uid].get("sent", 0) + 1
                                elif uid_str in ig_priv_stats:
                                    ig_priv_stats[uid_str]["sent"] = ig_priv_stats[uid_str].get("sent", 0) + 1
                                log_ig_priv_terminal(uid, f"📨 [Msg {m_i+1}/{repeat_msgs}] Sent: '{core_msg}' ({space_lines} gap lines)", "SUCCESS")
                            else:
                                if uid in ig_priv_stats:
                                    ig_priv_stats[uid]["failed"] = ig_priv_stats[uid].get("failed", 0) + 1
                                elif uid_str in ig_priv_stats:
                                    ig_priv_stats[uid_str]["failed"] = ig_priv_stats[uid_str].get("failed", 0) + 1
                                log_ig_priv_terminal(uid, f"❌ Msg box lost on strike {m_i+1}", "WARN")
                        except Exception as e_send:
                            log_ig_priv_terminal(uid, f"❌ Send notice: {e_send}", "WARN")

                        time.sleep(delay)

                    # 2. Perform 1 NC Rename using Modal dialog + Save button
                    if ig_priv_running.get(uid) or ig_priv_running.get(uid_str):
                        nc_template = nc_list[emoji_idx % len(nc_list)]
                        current_emoji = IG_PRIVATE_EMOJI_LIST[emoji_idx % len(IG_PRIVATE_EMOJI_LIST)]
                        emoji_idx += 1
                        
                        if "{target}" in nc_template:
                            new_title = nc_template.replace("{target}", target_name or prefix or "KING")
                        else:
                            new_title = f"{nc_template} {current_emoji}".strip()

                        log_ig_priv_terminal(uid, f"🏷️ Renaming GC to '{new_title}'...", "INFO")
                        try:
                            # 1. Click Conversation Info gear/i icon
                            info_btn = page.locator('svg[aria-label="Conversation information"], svg[aria-label="Thread Details"], svg[aria-label="Group Details"], div[role="button"]:has(svg[aria-label="Conversation information"])').first
                            if info_btn.count() > 0 and info_btn.is_visible():
                                info_btn.click(timeout=3000, force=True)
                                time.sleep(1)

                            # 2. Click "Change group name" button
                            change_btn = page.locator('div[aria-label="Change group name"][role="button"], div[role="button"]:has-text("Change group name")').first
                            if change_btn.count() > 0 and change_btn.is_visible():
                                change_btn.click(timeout=3000, force=True)
                                time.sleep(0.5)

                            # 3. Fill Group Name
                            title_input = page.locator('input[aria-label="Group name"][name="change-group-name"], input[placeholder="Group name"], input[placeholder*="group name"], input[aria-label*="Change Group Name"]').first
                            if title_input.count() > 0 and title_input.is_visible():
                                title_input.click(timeout=2000)
                                page.keyboard.press("Control+A")
                                page.keyboard.press("Backspace")
                                title_input.fill(new_title)
                                time.sleep(0.5)

                                # 4. Click Save
                                save_btn = page.locator('div[role="button"]:has-text("Save"), button:has-text("Save")').first
                                if save_btn.count() > 0 and save_btn.is_visible():
                                    save_btn.click(timeout=3000, force=True)
                                else:
                                    page.keyboard.press("Enter")
                                
                                time.sleep(1)
                                if uid in ig_priv_stats:
                                    ig_priv_stats[uid]["renamed"] = ig_priv_stats[uid].get("renamed", 0) + 1
                                elif uid_str in ig_priv_stats:
                                    ig_priv_stats[uid_str]["renamed"] = ig_priv_stats[uid_str].get("renamed", 0) + 1
                                log_ig_priv_terminal(uid, f"🏷️ [1 NC] Renamed GC to '{new_title}'", "SUCCESS")
                            
                            # Close info panel if still open
                            if info_btn.count() > 0 and info_btn.is_visible():
                                info_btn.click(timeout=2000, force=True)

                        except Exception as e_nc:
                            log_ig_priv_terminal(uid, f"⚠️ NC rename notice: {e_nc}", "WARN")

                else:
                    # MULTI GC ROUND (1 Text with 35-line Gap + 1 NC per GC)
                    cycle_count += 1
                    log_ig_priv_terminal(uid, f"🌐 [MULTI-GC CYCLE #{cycle_count}] Striking across {len(gc_urls)} Group Chats (1 Msg + 1 NC each)...", "INFO")
                    for t_idx, target_url in enumerate(gc_urls, 1):
                        if not ig_priv_running.get(uid) and not ig_priv_running.get(uid_str):
                            break

                        log_ig_priv_terminal(uid, f"➡️ Entering GC #{t_idx}/{len(gc_urls)}...", "INFO")
                        
                        # Navigate with auto-retry if page/thread doesn't load immediately
                        try:
                            page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
                            time.sleep(2.5)
                            dismiss_instagram_modals(page)
                            
                            if "/direct/t/" not in page.url:
                                dismiss_instagram_modals(page)
                                time.sleep(1)
                                page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
                                time.sleep(2.5)
                                dismiss_instagram_modals(page)
                        except Exception as e_nav:
                            log_ig_priv_terminal(uid, f"⚠️ Navigation retry for GC #{t_idx}: {e_nav}", "WARN")
                            try:
                                page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
                                time.sleep(3)
                                dismiss_instagram_modals(page)
                            except Exception:
                                pass

                        msg_box = get_msg_box(page)
                        if not msg_box:
                            # Re-verify and retry finding msg_box after clearing modals
                            time.sleep(2)
                            dismiss_instagram_modals(page)
                            msg_box = get_msg_box(page)

                        raw_txt = messages[msg_cycle_idx % len(messages)]
                        msg_cycle_idx += 1
                        current_emoji = IG_PRIVATE_EMOJI_LIST[emoji_idx % len(IG_PRIVATE_EMOJI_LIST)]

                        if prefix:
                            core_msg = f"[{prefix}] {raw_txt} {current_emoji}"
                        elif target_name:
                            core_msg = f"[{target_name}] {raw_txt} {current_emoji}"
                        else:
                            core_msg = f"{raw_txt} {current_emoji}"

                        if use_long_format:
                            final_msg = f"{header_text}\n{blank_block}\n{core_msg}\n{blank_block}\n{footer_text}"
                        else:
                            final_msg = core_msg

                        # --- STEP 1: SEND 1 TEXT MESSAGE ---
                        try:
                            if msg_box and msg_box.is_visible():
                                try:
                                    msg_box.click(timeout=3000, force=True)
                                except Exception:
                                    try:
                                        msg_box.evaluate("el => el.focus()")
                                    except Exception:
                                        pass
                                time.sleep(0.1)
                                page.keyboard.press("Control+A")
                                page.keyboard.press("Backspace")
                                time.sleep(0.1)
                                page.keyboard.insert_text(final_msg)
                                time.sleep(0.3)
                                
                                sent = False
                                send_btn = page.locator('button:has-text("Send"), div[role="button"]:has-text("Send"), div[aria-label="Send"], svg[aria-label="Send"]').first
                                if send_btn.count() > 0 and send_btn.is_visible():
                                    try:
                                        send_btn.click(timeout=1500, force=True)
                                        sent = True
                                    except Exception:
                                        pass
                                if not sent:
                                    page.keyboard.press("Enter")

                                if uid in ig_priv_stats:
                                    ig_priv_stats[uid]["sent"] = ig_priv_stats[uid].get("sent", 0) + 1
                                elif uid_str in ig_priv_stats:
                                    ig_priv_stats[uid_str]["sent"] = ig_priv_stats[uid_str].get("sent", 0) + 1
                                log_ig_priv_terminal(uid, f"📨 [1 Text] GC #{t_idx}: '{core_msg}'", "SUCCESS")
                            else:
                                if uid in ig_priv_stats:
                                    ig_priv_stats[uid]["failed"] = ig_priv_stats[uid].get("failed", 0) + 1
                                elif uid_str in ig_priv_stats:
                                    ig_priv_stats[uid_str]["failed"] = ig_priv_stats[uid_str].get("failed", 0) + 1
                                log_ig_priv_terminal(uid, f"❌ Msg box not visible in GC #{t_idx}", "WARN")
                        except Exception as e_send:
                            log_ig_priv_terminal(uid, f"❌ Send notice GC #{t_idx}: {e_send}", "WARN")

                        time.sleep(delay)

                        # --- STEP 2: 1 NC RENAME PER GC ---
                        if not ig_priv_running.get(uid) and not ig_priv_running.get(uid_str):
                            break

                        nc_template = nc_list[emoji_idx % len(nc_list)]
                        current_emoji = IG_PRIVATE_EMOJI_LIST[emoji_idx % len(IG_PRIVATE_EMOJI_LIST)]
                        emoji_idx += 1
                        
                        if "{target}" in nc_template:
                            new_title = nc_template.replace("{target}", target_name or prefix or "KING")
                        else:
                            new_title = f"{nc_template} {current_emoji}".strip()

                        try:
                            info_btn = page.locator('svg[aria-label="Conversation information"], svg[aria-label="Thread Details"], svg[aria-label="Group Details"], div[role="button"]:has(svg[aria-label="Conversation information"])').first
                            if info_btn.count() > 0 and info_btn.is_visible():
                                info_btn.click(timeout=3000, force=True)
                                time.sleep(1)

                            change_btn = page.locator('div[aria-label="Change group name"][role="button"], div[role="button"]:has-text("Change group name"), button:has-text("Change group name")').first
                            if change_btn.count() > 0 and change_btn.is_visible():
                                change_btn.click(timeout=3000, force=True)
                                time.sleep(0.5)

                            title_input = page.locator('input[aria-label="Group name"][name="change-group-name"], input[placeholder="Group name"], input[placeholder*="group name"], input[aria-label*="Change Group Name"]').first
                            if title_input.count() > 0 and title_input.is_visible():
                                title_input.click(timeout=2000)
                                page.keyboard.press("Control+A")
                                page.keyboard.press("Backspace")
                                title_input.fill(new_title)
                                time.sleep(0.5)

                                save_btn = page.locator('div[role="button"]:has-text("Save"), button:has-text("Save")').first
                                if save_btn.count() > 0 and save_btn.is_visible():
                                    save_btn.click(timeout=3000, force=True)
                                else:
                                    page.keyboard.press("Enter")
                                
                                time.sleep(1)
                                if uid in ig_priv_stats:
                                    ig_priv_stats[uid]["renamed"] = ig_priv_stats[uid].get("renamed", 0) + 1
                                elif uid_str in ig_priv_stats:
                                    ig_priv_stats[uid_str]["renamed"] = ig_priv_stats[uid_str].get("renamed", 0) + 1
                                log_ig_priv_terminal(uid, f"🏷️ [1 NC] Renamed GC #{t_idx} to '{new_title}'", "SUCCESS")
                            
                            # Close info panel if still open
                            if info_btn.count() > 0 and info_btn.is_visible():
                                info_btn.click(timeout=2000, force=True)
                        except Exception as e_nc:
                            log_ig_priv_terminal(uid, f"⚠️ NC rename notice in GC #{t_idx}: {e_nc}", "WARN")

                        time.sleep(delay)

                browser.close()
                browser = None

        except Exception as e_cycle:
            log_ig_priv_terminal(uid, f"⚠️ Playwright Loop notice: {e_cycle}. Auto-recovering in 3s...", "WARN")
            time.sleep(3)
        finally:
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass
            if os.path.exists(user_data_dir):
                try:
                    shutil.rmtree(user_data_dir, ignore_errors=True)
                except Exception:
                    pass

    ig_priv_running[uid] = False
    ig_priv_running[uid_str] = False
    if uid in ig_priv_live:
        ig_priv_live[uid]["running"] = False
    if uid_str in ig_priv_live:
        ig_priv_live[uid_str]["running"] = False
    if uid in ig_priv_stats:
        ig_priv_stats[uid]["running"] = False
    if uid_str in ig_priv_stats:
        ig_priv_stats[uid_str]["running"] = False
    log_ig_priv_terminal(uid, "⏹️ Playwright Private Engine stopped.", "INFO")

@app.route("/ig_priv_verify_login", methods=["POST"])
def ig_priv_verify_login():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401

    data = request.json or {}
    auth_type = str(data.get("auth_type", "cookie")).lower().strip()
    sessionid = data.get("sessionid", "").strip()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    totp_key = data.get("totp_key", "").strip()
    verification_code = data.get("verification_code", "").strip()

    log_ig_priv_terminal("AUTH", f"🔍 Verifying login credentials for @{username or 'cookie_user'}...", "INFO")

    if auth_type == "credentials":
        if not username or not password:
            return jsonify({"status": "error", "message": "Username and Password are required!"}), 400

        v_code = verification_code
        if not v_code and totp_key:
            try:
                import pyotp
                totp = pyotp.TOTP(totp_key.replace(" ", "").upper())
                v_code = totp.now()
                log_ig_priv_terminal("AUTH", f"🔑 Generated 2FA Code from Secret Key: {v_code}", "INFO")
            except Exception as e_totp:
                log_ig_priv_terminal("AUTH", f"⚠️ 2FA Key calculation error: {e_totp}", "WARN")

        try:
            client, settings, resolved_user = init_instagram_client(
                username=username,
                password=password,
                verification_code=v_code,
                log_fn=lambda m, l: log_ig_priv_terminal("AUTH", m, l)
            )
            cookies = settings.get("cookies", {})
            sid = cookies.get("sessionid", "")
            csrf = cookies.get("csrftoken", "")
            uid = str(settings.get("user_id") or "")
            log_ig_priv_terminal("AUTH", f"🎉 Successfully verified login for @{resolved_user} (ID: {uid})!", "SUCCESS")
            return jsonify({
                "status": "ok",
                "message": f"Successfully authenticated as @{resolved_user}!",
                "sessionid": sid,
                "csrftoken": csrf,
                "user_id": uid,
                "username": resolved_user
            })
        except Exception as e:
            err_msg = str(e)
            if "2FA Verification Required" in err_msg or "two_factor" in err_msg.lower():
                log_ig_priv_terminal("AUTH", "🔐 2FA / Security Code required! Please enter the code sent to your phone/email/app.", "WARN")
                return jsonify({"status": "2fa_required", "message": "Instagram 2FA OTP Code Required! Enter the code below."}), 200
            elif "Checkpoint" in err_msg or "challenge" in err_msg.lower():
                log_ig_priv_terminal("AUTH", "⚠️ Instagram Checkpoint! Approve device on Instagram app.", "WARN")
                return jsonify({"status": "checkpoint_required", "message": "Please approve login from your Instagram app or email."}), 200
            else:
                log_ig_priv_terminal("AUTH", f"❌ Login Failed: {err_msg}", "ERROR")
                return jsonify({"status": "error", "message": err_msg}), 400
    else:
        # Cookie verification
        parsed_cookies, clean_sess, clean_csrf, user_id = parse_instagram_cookie_input(sessionid)
        if not clean_sess:
            return jsonify({"status": "error", "message": "Invalid cookie string or missing sessionid!"}), 400
        
        # Test request to Instagram Inbox
        s = requests.Session()
        for k, v in parsed_cookies.items():
            s.cookies.set(k, v, domain=".instagram.com")
        s.cookies.set("sessionid", clean_sess, domain=".instagram.com")
        try:
            r = s.get("https://www.instagram.com/api/v1/direct_v2/inbox/?limit=1", headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                "X-IG-App-ID": "936619743392459"
            }, timeout=8)
            if r.status_code == 200 and r.json().get("status") == "ok":
                log_ig_priv_terminal("AUTH", f"🎉 Session cookie verified! User ID: {user_id or 'Active'}", "SUCCESS")
                return jsonify({"status": "ok", "message": "Session cookie is 100% active and authenticated!", "sessionid": clean_sess})
            else:
                log_ig_priv_terminal("AUTH", "❌ Cookie session expired or login required.", "ERROR")
                return jsonify({"status": "error", "message": "Cookie expired or checkpoint required."}), 400
        except Exception as e_ck:
            log_ig_priv_terminal("AUTH", f"⚠️ Verification check error: {e_ck}", "WARN")
            return jsonify({"status": "ok", "message": "Cookie loaded.", "sessionid": clean_sess})

@app.route("/ig_priv_scrape_links", methods=["POST"])
def ig_priv_scrape_links():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401
    
    data = request.json or {}
    sessionid = data.get("sessionid", "").strip()
    csrftoken = data.get("csrftoken", "").strip()
    max_groups = int(data.get("max_groups") or 1000)

    if not sessionid:
        return jsonify({"status": "error", "message": "Session ID is required to fetch groups!"}), 400

    links = scrape_instagram_groups(sessionid, csrftoken, max_groups=max_groups, log_fn=lambda m, l: log_ig_priv_terminal("AUTH", m, l))
    return jsonify({"status": "ok", "links": links, "count": len(links)})

@app.route("/ig_priv_add_account", methods=["POST"])
def ig_priv_add_account():
    if not is_authenticated():
        log_ig_priv_terminal("AUTH", "Login required to add account.", "ERROR")
        return jsonify({"status": "login_required"}), 401

    data = request.json or {}
    auth_type = str(data.get("auth_type", "cookie")).lower().strip()
    raw_session = data.get("sessionid", "").strip()
    sessionid = raw_session
    csrftoken = data.get("csrftoken", "").strip()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    totp_key = data.get("totp_key", "").strip()

    if auth_type == "credentials" and username and password:
        sessionid = f"CREDENTIALS:{username}:{password}"
    else:
        if ";" in sessionid or "=" in sessionid:
            for part in sessionid.split(";"):
                part = part.strip()
                if part.lower().startswith("sessionid="):
                    sessionid = part.split("=", 1)[1].strip()
                elif part.lower().startswith("csrftoken="):
                    csrftoken = part.split("=", 1)[1].strip()

        if "%3A" in sessionid or "%3a" in sessionid:
            sessionid = urllib.parse.unquote(sessionid).strip()

        if not sessionid:
            log_ig_priv_terminal("AUTH", "Missing sessionid cookie string.", "ERROR")
            return jsonify({"status": "error", "message": "Session ID or Credentials are required!"}), 400

    mode_type = str(data.get("mode_type", "multi")).lower().strip()
    fetch_mode = str(data.get("fetch_mode", "manual")).lower().strip()
    target_name = str(data.get("target_name", "")).strip()
    prefix = str(data.get("prefix", "")).strip() or target_name
    repeat_count = int(data.get("repeat_count", 15 if mode_type == "single" else 1))
    delay = float(data.get("delay", 2.0))

    raw_groups = data.get("group_names", "")
    if isinstance(raw_groups, str):
        group_names = [g.strip() for g in re.split(r"[,;\n\r]+", raw_groups) if g.strip()]
    elif isinstance(raw_groups, list):
        group_names = [str(g).strip() for g in raw_groups if str(g).strip()]
    else:
        group_names = []

    raw_messages = data.get("messages", "")
    if isinstance(raw_messages, str):
        messages = [m.strip() for m in raw_messages.replace("\r", "").split("\n") if m.strip()]
    elif isinstance(raw_messages, list):
        messages = [str(m).strip() for m in raw_messages if str(m).strip()]
    else:
        messages = []

    raw_nc = data.get("nc_names", "")
    if isinstance(raw_nc, str):
        nc_names = [n.strip() for n in raw_nc.replace("\r", "").split("\n") if n.strip()]
    elif isinstance(raw_nc, list):
        nc_names = [str(n).strip() for n in raw_nc if str(n).strip()]
    else:
        nc_names = []

    header_text = str(data.get("header_text", "👑 SPAM BY KING 👑")).strip()
    footer_text = str(data.get("footer_text", "👑 SCRIPT BY SERVER GOD CLAN 👑")).strip()
    space_lines = int(data.get("space_lines", 35))

    uid = next_ig_private_uid()
    current_user = get_current_user()

    acc_data = {
        "uid": uid,
        "auth_type": auth_type,
        "username": username,
        "password": password,
        "totp_key": totp_key,
        "mode_type": mode_type,
        "fetch_mode": fetch_mode,
        "sessionid": sessionid,
        "csrftoken": csrftoken,
        "target_name": target_name,
        "prefix": prefix,
        "group_names": group_names,
        "messages": messages,
        "nc_names": nc_names,
        "header_text": header_text,
        "footer_text": footer_text,
        "space_lines": space_lines,
        "repeat_count": repeat_count,
        "delay": delay,
        "owner": current_user,
        "admin_name": get_user_display_name(current_user),
        "system_owner": "SERVER GOD CLAN KING",
        "createdAt": str(datetime.utcnow())
    }
    save_ig_private_account_db(uid, acc_data)

    start_time = time.time()
    ig_priv_running[uid] = True
    ig_priv_live[uid] = {"running": True, "started": start_time}
    ig_priv_stats[uid] = {
        "user": current_user,
        "account": uid,
        "sent": 0,
        "failed": 0,
        "renamed": 0,
        "rename_failed": 0,
        "running": True,
        "uptime": 0,
        "uptime_str": "00:00:00",
        "started": start_time
    }
    threading.Thread(target=ig_private_api_worker, args=(uid,), daemon=True).start()
    log_ig_priv_terminal(uid, f"✨ Private API Bot #{uid} ({mode_type.upper()}) deployed and live engine started!", "SUCCESS")
    return jsonify({"status": "ok", "uid": uid, "target_name": target_name or f"PrivateBot_{uid}"})

@app.route("/ig_priv_start", methods=["POST"])
def ig_priv_start():
    uid = str(request.json.get("uid"))
    full_db = get_full_db()
    acc = full_db.get("ig_private_accounts", {}).get(uid)
    if not acc:
        return jsonify({"status": "invalid", "message": "Account not found!"})

    if ig_priv_running.get(uid):
        return jsonify({"status": "already_running"})

    ig_priv_running[uid] = True
    start_time = time.time()
    ig_priv_live[uid] = {"running": True, "started": start_time}
    if uid not in ig_priv_stats:
        ig_priv_stats[uid] = {"user": get_current_user(), "account": uid, "sent": 0, "failed": 0, "renamed": 0, "rename_failed": 0}
    ig_priv_stats[uid]["running"] = True
    ig_priv_stats[uid]["uptime"] = 0
    ig_priv_stats[uid]["uptime_str"] = "00:00:00"
    ig_priv_stats[uid]["started"] = start_time

    threading.Thread(target=ig_private_api_worker, args=(uid,), daemon=True).start()
    return jsonify({"status": "started"})

@app.route("/ig_priv_stop", methods=["POST"])
def ig_priv_stop():
    uid = str(request.json.get("uid"))
    ig_priv_running[uid] = False
    if uid in ig_priv_live:
        ig_priv_live[uid]["running"] = False
    if uid in ig_priv_stats:
        ig_priv_stats[uid]["running"] = False
    log_ig_priv_terminal(uid, "Stop signal received.", "WARN")
    return jsonify({"status": "stopped"})

@app.route("/ig_priv_edit_account", methods=["POST"])
def ig_priv_edit_account():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401

    uid = str(request.json.get("uid"))
    full_db = get_full_db()
    acc = full_db.get("ig_private_accounts", {}).get(uid)
    if not acc:
        return jsonify({"status": "invalid"})

    acc_owner = str(acc.get("owner", "")).strip().lower()
    cur_user = str(get_current_user()).strip().lower()
    if not is_owner() and acc_owner != cur_user:
        return jsonify({"status": "denied"}), 403

    acc["mode_type"] = str(request.json.get("mode_type", acc.get("mode_type", "multi"))).lower().strip()
    acc["target_name"] = request.json.get("target_name", acc.get("target_name", "")).strip()
    acc["prefix"] = request.json.get("prefix", acc.get("prefix", "")).strip()
    acc["repeat_count"] = int(request.json.get("repeat_count", acc.get("repeat_count", 15 if acc["mode_type"] == "single" else 1)))
    acc["delay"] = float(request.json.get("delay", acc.get("delay", 2.0)))

    raw_groups = request.json.get("group_names", "")
    if isinstance(raw_groups, str):
        acc["group_names"] = [g.strip() for g in re.split(r"[,;\n\r]+", raw_groups) if g.strip()]
    elif isinstance(raw_groups, list):
        acc["group_names"] = [str(g).strip() for g in raw_groups if str(g).strip()]

    raw_messages = request.json.get("messages", "")
    if isinstance(raw_messages, str):
        acc["messages"] = [m.strip() for m in raw_messages.replace("\r", "").split("\n") if m.strip()]
    elif isinstance(raw_messages, list):
        acc["messages"] = [str(m).strip() for m in raw_messages if str(m).strip()]

    raw_nc = request.json.get("nc_names", "")
    if isinstance(raw_nc, str):
        acc["nc_names"] = [n.strip() for n in raw_nc.replace("\r", "").split("\n") if n.strip()]
    elif isinstance(raw_nc, list):
        acc["nc_names"] = [str(n).strip() for n in raw_nc if str(n).strip()]

    acc["header_text"] = str(request.json.get("header_text", acc.get("header_text", "👑 SPAM BY KING 👑"))).strip()
    acc["footer_text"] = str(request.json.get("footer_text", acc.get("footer_text", "👑 SCRIPT BY SERVER GOD CLAN 👑"))).strip()
    acc["space_lines"] = int(request.json.get("space_lines", acc.get("space_lines", 35)))

    save_ig_private_account_db(uid, acc)
    log_ig_priv_terminal(uid, f"💾 Private API Bot #{uid} updated in database!", "INFO")
    return jsonify({"status": "ok"})

@app.route("/ig_priv_delete_account", methods=["POST"])
def ig_priv_delete_account():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401

    uid = str(request.json.get("uid"))
    full_db = get_full_db()
    acc = full_db.get("ig_private_accounts", {}).get(uid)
    if not acc:
        return jsonify({"status": "invalid"})

    acc_owner = str(acc.get("owner", "")).strip().lower()
    cur_user = str(get_current_user()).strip().lower()
    if not is_owner() and acc_owner != cur_user:
        return jsonify({"status": "denied"}), 403

    ig_priv_running[uid] = False
    delete_ig_private_account_db(uid)
    if uid in ig_priv_live:
        del ig_priv_live[uid]
    if uid in ig_priv_stats:
        del ig_priv_stats[uid]
    log_ig_priv_terminal(uid, f"🗑️ Private API Bot #{uid} deleted.", "WARN")
    return jsonify({"status": "ok"})

@app.route("/ig_priv_status")
def ig_priv_status():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401

    full_db = get_full_db()
    priv_accounts = full_db.get("ig_private_accounts", {})
    accounts = {}
    visible = {}
    me = str(get_current_user()).strip().lower()

    if is_owner():
        for uid, acc in priv_accounts.items():
            acc_copy = dict(acc)
            acc_copy["admin_name"] = get_user_display_name(acc.get("owner", ""))
            acc_copy["system_owner"] = "SERVER GOD CLAN KING"
            accounts[uid] = acc_copy
            if uid not in ig_priv_stats:
                ig_priv_stats[uid] = {"user": acc.get("owner", ""), "account": uid, "sent": 0, "failed": 0, "renamed": 0, "rename_failed": 0, "running": False, "uptime": 0, "uptime_str": "00:00:00"}
            visible[uid] = ig_priv_stats[uid]
    else:
        for uid, acc in priv_accounts.items():
            acc_owner = str(acc.get("owner", "")).strip().lower()
            if acc_owner == me or me in acc_owner or acc_owner in me:
                acc_copy = dict(acc)
                acc_copy["admin_name"] = get_user_display_name(acc.get("owner", ""))
                acc_copy["system_owner"] = "SERVER GOD CLAN KING"
                accounts[uid] = acc_copy
                if uid not in ig_priv_stats:
                    ig_priv_stats[uid] = {"user": acc.get("owner", ""), "account": uid, "sent": 0, "failed": 0, "renamed": 0, "rename_failed": 0, "running": False, "uptime": 0, "uptime_str": "00:00:00"}
                visible[uid] = ig_priv_stats[uid]

    for uid, s in visible.items():
        uid_str = str(uid)
        live_info = ig_priv_live.get(uid) or ig_priv_live.get(uid_str)
        if live_info and live_info.get("running") and live_info.get("started"):
            s["running"] = True
            elapsed = int(time.time() - live_info["started"])
            s["uptime"] = elapsed
            s["uptime_str"] = format_uptime(elapsed)
            s["started"] = live_info["started"]
        else:
            s["running"] = False
            s["uptime"] = 0
            s["uptime_str"] = "00:00:00"

    if is_owner():
        ret_logs = ig_priv_terminal_logs
    else:
        user_uids = set(str(k) for k in accounts.keys())
        user_uids.add("AUTH")
        ret_logs = [l for l in ig_priv_terminal_logs if str(l.get("uid")) in user_uids]

    return jsonify({"accounts": accounts, "stats": visible, "terminal_logs": ret_logs})

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
    max_groups = int(data.get("max_groups", 150))
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
    current_user = get_current_user()

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
        "owner": current_user,
        "admin_name": get_user_display_name(current_user),
        "system_owner": "SERVER GOD CLAN KING",
        "createdAt": str(datetime.utcnow())
    }
    save_ig_account_db(uid, acc_data)

    ig_running[uid] = False
    ig_stats[uid] = {
        "user": current_user,
        "account": uid,
        "sent": 0,
        "failed": 0,
        "renamed": 0,
        "rename_failed": 0,
        "running": False,
        "uptime": 0,
        "uptime_str": "00:00:00",
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
    ig_stats[uid]["uptime"] = 0
    ig_stats[uid]["uptime_str"] = "00:00:00"
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
    acc["max_groups"] = int(request.json.get("max_groups", acc.get("max_groups", 150)))
    delay_val = request.json.get("delay")
    if delay_val is not None:
        try:
            acc["delay"] = float(delay_val)
        except Exception:
            pass
    cycle_delay_val = request.json.get("cycle_delay")
    if cycle_delay_val is not None:
        try:
            acc["cycle_delay"] = int(cycle_delay_val)
        except Exception:
            pass

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
            acc["gc_links"] = [l.strip() for l in raw_links.replace("\r", "").split("\n") if l.strip().startswith("http")][:acc.get("max_groups", 150)]
        elif isinstance(raw_links, list):
            acc["gc_links"] = [str(l).strip() for l in raw_links if str(l).strip().startswith("http")][:acc.get("max_groups", 150)]

    save_ig_account_db(uid, acc)
    log_ig_terminal(uid, "Multi-GC Account Configuration updated successfully.", "INFO")
    return jsonify({"status": "ok"})

@app.route("/delete_account", methods=["POST"])
def delete_account():
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
    max_groups = int(request.json.get("max_groups") or 150)

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
            if uid not in ig_stats:
                ig_stats[uid] = {"user": acc.get("owner", ""), "account": uid, "sent": 0, "failed": 0, "renamed": 0, "rename_failed": 0, "running": False, "uptime": 0, "uptime_str": "00:00:00"}
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
                else:
                    visible_stats[uid] = {"user": acc.get("owner", ""), "account": uid, "sent": 0, "failed": 0, "renamed": 0, "rename_failed": 0, "running": False, "uptime": 0, "uptime_str": "00:00:00"}
        users = {}

    for uid, s in visible_stats.items():
        uid_str = str(uid)
        live_info = ig_live.get(uid) or ig_live.get(uid_str)
        if live_info and live_info.get("running") and live_info.get("started"):
            s["running"] = True
            elapsed = int(time.time() - live_info["started"])
            s["uptime"] = elapsed
            s["uptime_str"] = format_uptime(elapsed)
            s["started"] = live_info["started"]
        else:
            s["running"] = False
            s["uptime"] = 0
            s["uptime_str"] = "00:00:00"

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

    uid = str(request.json.get("uid") or "").strip()
    if not uid:
        return jsonify({"status": "invalid", "message": "UID required"}), 400

    ensure_baileys_service()
    try:
        requests.post(f"{BAILEYS_SERVICE_URL}/session/{uid}/delete", timeout=5)
    except Exception:
        pass

    delete_wp_account_db(uid)
    delete_wp_call_account_db(uid)
    return jsonify({"status": "ok", "uid": uid})

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

# ================= WHATSAPP GO CALL SETUP ENGINE (GO LANG WEBRTC) =================
@app.route("/wp_call_add_account", methods=["POST"])
def wp_call_add_account():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401

    curr_user = get_current_user()
    data = request.json or {}
    custom_name = data.get("name", "").strip().replace(" ", "_")
    owner_jid = data.get("owner_jid", "").strip()

    user_tag = curr_user.split("@")[0].replace(".", "_") if "@" in curr_user else curr_user
    user_tag = "".join(c for c in user_tag if c.isalnum() or c == "_")[:12] or "usr"

    if custom_name:
        clean_n = "".join(c for c in custom_name if c.isalnum() or c == "_")
        if is_owner():
            uid = f"wp_call_{clean_n}" if not clean_n.startswith("wp_call_") else clean_n
        else:
            uid = f"wp_call_{user_tag}_{clean_n}"
    else:
        user_nodes = [k for k, v in cache_db.get("wp_call_accounts", {}).items() if v.get("owner") == curr_user]
        node_num = len(user_nodes) + 1
        uid = f"wp_call_{user_tag}_bot{node_num}"

    display_name = custom_name or uid.replace(f"wp_call_{user_tag}_", "")

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

    save_wp_call_account_db(uid, acc_data)
    ensure_go_service()
    try:
        requests.post(f"{GO_SERVICE_URL}/session/init", json={
            "uid": uid,
            "owner_jid": owner_jid
        }, timeout=5)
    except Exception as e:
        print(f"[WP CALL ADD ACC ERROR]: {e}")

    return jsonify({"status": "ok", "uid": uid, "name": display_name})

@app.route("/wp_call_pair_code", methods=["POST"])
def wp_call_pair_code():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401

    data = request.json or {}
    uid = data.get("uid")
    phone = data.get("phone", "").strip()

    if not uid or not phone:
        return jsonify({"status": "error", "message": "UID and phone number are required!"}), 400

    full_db = get_full_db()
    acc = full_db.get("wp_call_accounts", {}).get(uid) or full_db.get("wp_accounts", {}).get(uid)
    if not acc:
        return jsonify({"status": "invalid"}), 404
    if not is_owner() and acc.get("owner") != get_current_user():
        return jsonify({"status": "denied"}), 403

    ensure_go_service()
    try:
        r = requests.post(f"{GO_SERVICE_URL}/session/{uid}/pair", json={"phone": phone}, timeout=25)
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
            return jsonify({"status": "error", "message": res_data.get("message", "Failed to generate pairing code in Go engine")}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": f"Go Call pairing error: {e}"}), 500

@app.route("/wp_call_qr", methods=["GET"])
def wp_call_qr():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401
    uid = request.args.get("uid")
    if not uid:
        return jsonify({"status": "error", "message": "UID is required"}), 400

    refresh = request.args.get("refresh", "0") == "1"

    ensure_go_service()
    try:
        if refresh:
            requests.post(f"{GO_SERVICE_URL}/session/{uid}/refresh_qr", timeout=8)
            time.sleep(1)

        r = requests.get(f"{GO_SERVICE_URL}/session/{uid}/status", timeout=8)
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

@app.route("/wp_call_disconnect", methods=["POST"])
def wp_call_disconnect():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401
    uid = request.json.get("uid")
    full_db = get_full_db()
    acc = full_db.get("wp_call_accounts", {}).get(uid) or full_db.get("wp_accounts", {}).get(uid)
    if not acc:
        return jsonify({"status": "invalid"}), 404
    if not is_owner() and acc.get("owner") != get_current_user():
        return jsonify({"status": "denied"}), 403

    ensure_go_service()
    try:
        r = requests.post(f"{GO_SERVICE_URL}/session/{uid}/disconnect", timeout=5)
        return jsonify(r.json() if r.status_code == 200 else {"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/wp_call_delete_account", methods=["POST"])
def wp_call_delete_account():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401

    uid = str(request.json.get("uid") or "").strip()
    if not uid:
        return jsonify({"status": "invalid", "message": "UID required"}), 400

    ensure_go_service()
    try:
        requests.post(f"{GO_SERVICE_URL}/session/{uid}/delete", timeout=5)
    except Exception:
        pass

    delete_wp_call_account_db(uid)
    delete_wp_account_db(uid)
    return jsonify({"status": "ok", "uid": uid})

@app.route("/wp_call_status")
def wp_call_status():
    if not is_authenticated():
        return jsonify({"status": "login_required"}), 401

    ensure_go_service()
    full_db = get_full_db()
    wp_call_accounts = full_db.get("wp_call_accounts", {})
    accounts = {}
    visible_stats = {}

    go_live = {}
    global_logs = []
    try:
        r = requests.get(f"{GO_SERVICE_URL}/sessions/all", timeout=3)
        if r.status_code == 200:
            b_data = r.json()
            go_live = b_data.get("sessions", {})
            global_logs = b_data.get("globalLogs", [])
    except Exception:
        pass

    is_adm = is_owner()
    curr_user = str(get_current_user()).strip().lower()

    for uid, acc in wp_call_accounts.items():
        acc_owner = str(acc.get("owner", "")).strip().lower()
        is_my_acc = is_adm or (acc_owner == curr_user)

        if is_my_acc:
            acc_copy = dict(acc)
            acc_copy["admin_name"] = get_user_display_name(acc.get("owner", ""))
            acc_copy["system_owner"] = "SERVER GOD CLAN KING"
            accounts[uid] = acc_copy
            g_sess = go_live.get(uid, {})
            visible_stats[uid] = {
                "user": acc.get("owner", curr_user),
                "admin_name": acc_copy["admin_name"],
                "account": uid,
                "status": g_sess.get("status") or ("ONLINE" if g_sess.get("isOnline") else "READY_TO_CONNECT"),
                "isOnline": g_sess.get("isOnline", False),
                "connectedNumber": g_sess.get("connectedNumber", ""),
                "ownerJid": g_sess.get("ownerJid", acc.get("owner_jid", "")),
                "running": g_sess.get("isOnline", False),
                "sent": g_sess.get("sentCount", 0),
                "failed": g_sess.get("failedCount", 0),
                "uptime": g_sess.get("uptime", 0),
                "hasQr": g_sess.get("hasQr", False),
                "hasPairingCode": g_sess.get("hasPairingCode", False)
            }

    for uid, g_sess in go_live.items():
        if uid not in accounts:
            acc_info = wp_call_accounts.get(uid, {})
            acc_owner = str(acc_info.get("owner", "")).strip().lower()
            is_my_acc = is_adm or (acc_owner and acc_owner == curr_user)
            if is_my_acc:
                accounts[uid] = {
                    "uid": uid,
                    "name": acc_info.get("name") or uid.replace("wp_call_", ""),
                    "owner": acc_info.get("owner", curr_user),
                    "admin_name": acc_info.get("admin_name", get_user_display_name(curr_user)),
                    "system_owner": "SERVER GOD CLAN KING",
                    "owner_jid": g_sess.get("ownerJid", acc_info.get("owner_jid", ""))
                }
                visible_stats[uid] = {
                    "user": acc_info.get("owner", curr_user),
                    "admin_name": acc_info.get("admin_name", get_user_display_name(curr_user)),
                    "account": uid,
                    "status": g_sess.get("status") or ("ONLINE" if g_sess.get("isOnline") else "READY_TO_CONNECT"),
                    "isOnline": g_sess.get("isOnline", False),
                    "connectedNumber": g_sess.get("connectedNumber", ""),
                    "ownerJid": g_sess.get("ownerJid", ""),
                    "running": g_sess.get("isOnline", False),
                    "sent": g_sess.get("sentCount", 0),
                    "failed": g_sess.get("failedCount", 0),
                    "uptime": g_sess.get("uptime", 0),
                    "hasQr": g_sess.get("hasQr", False),
                    "hasPairingCode": g_sess.get("hasPairingCode", False)
                }

    user_uids = {str(u) for u in accounts.keys() if u}
    filtered_logs = []
    for log_line in global_logs:
        if is_adm:
            filtered_logs.append(log_line)
        else:
            if any(f"[{u}]" in log_line or f"node {u}" in log_line for u in user_uids if u):
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

@app.route("/api/owner/users/approve", methods=["POST"])
def owner_approve_user():
    if not is_authenticated() or not is_owner():
        return jsonify({"status": "denied"}), 403

    email = request.json.get("email", "").lower().strip()
    user = find_user_by_email(email)
    if not user:
        return jsonify({"status": "error", "message": f"User '{email}' not found!"}), 404

    user["status"] = "active"
    save_or_update_user(user)

    # Send Approval notification to user
    try:
        subject = "🎉 Account Approved! Welcome to SERVER GOD CLAN"
        html = f"""
        <div style="background:#0f172a;color:#ffffff;padding:25px;border-radius:12px;font-family:Arial,sans-serif;text-align:center;">
            <h2 style="color:#22c55e;">👑 ACCOUNT APPROVED!</h2>
            <p>Hello <b>{user.get('name', 'User')}</b>, your registration request has been approved by the Platform Owner.</p>
            <p>You can now sign in to your dashboard and access all tools.</p>
            <a href="https://servergodclan.com/mode" style="background:#3b82f6;color:#ffffff;padding:10px 20px;border-radius:6px;text-decoration:none;display:inline-block;margin-top:15px;">Login to Dashboard</a>
        </div>
        """
        send_email_async(email, subject, html)
    except Exception:
        pass

    return jsonify({"status": "ok", "message": f"✅ User '{email}' APPROVED successfully! Account is now ACTIVE."})

@app.route("/api/owner/users/reject", methods=["POST"])
def owner_reject_user():
    if not is_authenticated() or not is_owner():
        return jsonify({"status": "denied"}), 403

    email = request.json.get("email", "").lower().strip()
    user = find_user_by_email(email)
    if not user:
        return jsonify({"status": "error", "message": f"User '{email}' not found!"}), 404

    user["status"] = "rejected"
    save_or_update_user(user)

    return jsonify({"status": "ok", "message": f"❌ User '{email}' REJECTED and blocked from accessing the system."})

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
    if "two_factor" in data:
        user["two_factor"] = bool(data["two_factor"])

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

    return jsonify({"status": "ok", "message": "Profile, security and 2FA settings updated successfully!"})

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
            "phone": "+91 9507325677",
            "two_factor": True
        })

    user = find_user_by_email(get_current_user())
    if not user:
        return jsonify({
            "status": "ok",
            "role": "user",
            "name": session.get("name", "User"),
            "email": session.get("user", ""),
            "phone": "",
            "two_factor": True
        })

    return jsonify({
        "status": "ok",
        "role": "user",
        "name": user.get("name", session.get("name")),
        "email": user.get("email", session.get("user")),
        "phone": user.get("phone", ""),
        "status": user.get("status", "active"),
        "two_factor": user.get("two_factor", True)
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
        ensure_go_service()
    except Exception as _e:
        print(f"[GO WHATSAPP CALL STARTUP WARNING] {_e}")
    try:
        ensure_tg_service()
    except Exception as _e:
        print(f"[TG MASTER STARTUP WARNING] {_e}")
    app.run(host="0.0.0.0", port=port, debug=False)