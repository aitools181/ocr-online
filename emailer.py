"""
emailer.py — SMVS OCR email utility (Gmail SMTP via App Password).

Config (config.yaml):
  email:
    from_address: smvs.ocr@gmail.com
    app_password: xxxx xxxx xxxx xxxx   # Gmail Settings > Security > App Passwords
    from_name: SMVS OCR System          # optional
    admin_email: admin@smvs.org         # feedback/alerts jaay tyaare
"""
import logging
import smtplib
import threading
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

log = logging.getLogger("smvs.emailer")
_CFG = {}
_lock = threading.Lock()


def configure(cfg):
    global _CFG
    _CFG = cfg or {}


def is_enabled():
    return bool(_CFG.get("from_address") and _CFG.get("app_password"))


def _send(to, subject, html_body, text_body=None):
    if not is_enabled():
        log.warning("Email not configured — skipping send to %s", to)
        return False
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{_CFG.get('from_name', 'SMVS OCR')} <{_CFG['from_address']}>"
    msg["To"] = to
    if text_body:
        msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
            srv.login(_CFG["from_address"], _CFG["app_password"])
            srv.sendmail(_CFG["from_address"], to, msg.as_string())
        return True
    except Exception as e:
        log.error("Email send failed to %s: %s", to, e)
        return False


def send_async(to, subject, html_body, text_body=None):
    """Background thread thi send kare — request block na thay."""
    t = threading.Thread(target=_send, args=(to, subject, html_body, text_body), daemon=True)
    t.start()


# ---------------------------------------------------------------- TEMPLATES

_BASE = """
<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f5f0e8;font-family:Inter,Arial,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:32px 16px">
<table width="520" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:16px;
  overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,.08)">
<tr><td style="background:linear-gradient(135deg,#c97e1a,#e8a020);padding:28px 32px">
  <div style="font-family:Sora,Arial,sans-serif;font-size:22px;font-weight:700;color:#fff">
    SMVS OCR System</div>
</td></tr>
<tr><td style="padding:32px">__BODY__</td></tr>
<tr><td style="background:#faf7f1;padding:16px 32px;font-size:12px;color:#999;text-align:center;
  border-top:1px solid #f0e8d5">
  This is an automated message from SMVS OCR System. Please do not reply.
</td></tr>
</table></td></tr></table></body></html>
"""


def _wrap(body):
    return _BASE.replace("__BODY__", body)


def send_signup_verification(to, first_name, username, verify_link):
    body = f"""
<h2 style="margin:0 0 8px;font-size:20px;color:#2c2c4a">Welcome, {first_name}! 🙏</h2>
<p style="color:#555;margin:0 0 20px">Thank you for signing up to <b>SMVS OCR</b>.
Your account has been created and is <b>pending approval</b> from the administrator.</p>
<div style="background:#faf7f1;border-radius:10px;padding:14px 18px;margin-bottom:20px">
  <div style="font-size:13px;color:#888">Username</div>
  <div style="font-size:16px;font-weight:600;color:#2c2c4a">{username}</div>
</div>
<p style="color:#555;margin:0 0 20px">You will receive another email once the administrator
approves your account.</p>
<p style="font-size:12px;color:#aaa;margin:0">If you did not create this account, please ignore this email.</p>
"""
    send_async(to, "SMVS OCR — Account Signup Received", _wrap(body))


def send_admin_approval_request(admin_email, first_name, last_name, username, email, approve_link):
    body = f"""
<h2 style="margin:0 0 8px;font-size:20px;color:#2c2c4a">New User Signup Request</h2>
<p style="color:#555;margin:0 0 20px">A new user has registered and is awaiting your approval.</p>
<div style="background:#faf7f1;border-radius:10px;padding:14px 18px;margin-bottom:20px">
  <table style="font-size:14px;color:#444;width:100%">
    <tr><td style="padding:4px 0;color:#888;width:120px">Full Name</td><td><b>{first_name} {last_name}</b></td></tr>
    <tr><td style="padding:4px 0;color:#888">Username</td><td><b>{username}</b></td></tr>
    <tr><td style="padding:4px 0;color:#888">Email</td><td>{email}</td></tr>
  </table>
</div>
<a href="{approve_link}" style="display:inline-block;background:linear-gradient(135deg,#c97e1a,#e8a020);
  color:#fff;text-decoration:none;padding:14px 28px;border-radius:10px;font-weight:700;font-size:15px">
  ✅ Approve User
</a>
<p style="font-size:12px;color:#aaa;margin-top:16px">Or log in to Admin → User Management to approve manually.</p>
"""
    send_async(admin_email, f"SMVS OCR — New Signup: {username}", _wrap(body))


def send_approval_notification(to, first_name, username):
    body = f"""
<h2 style="margin:0 0 8px;font-size:20px;color:#2c2c4a">Your Account is Approved! 🎉</h2>
<p style="color:#555;margin:0 0 20px">Great news, <b>{first_name}</b>! Your SMVS OCR account
has been approved by the administrator.</p>
<div style="background:#e3f6ea;border-radius:10px;padding:14px 18px;margin-bottom:20px">
  <div style="font-size:13px;color:#888">Username</div>
  <div style="font-size:16px;font-weight:600;color:#1e8449">{username}</div>
</div>
<a href="/login" style="display:inline-block;background:linear-gradient(135deg,#1e8449,#27ae60);
  color:#fff;text-decoration:none;padding:14px 28px;border-radius:10px;font-weight:700;font-size:15px">
  🚀 Login Now
</a>
"""
    send_async(to, "SMVS OCR — Account Approved!", _wrap(body))


def send_password_reset(to, first_name, reset_link):
    body = _password_reset_body(first_name, reset_link)
    send_async(to, "SMVS OCR — Password Reset Link", _wrap(body))


def send_password_reset_sync(to, first_name, reset_link):
    """Synchronous — returns True/False so caller knows if it actually sent."""
    body = _password_reset_body(first_name, reset_link)
    return _send(to, "SMVS OCR — Password Reset Link", _wrap(body))


def _password_reset_body(first_name, reset_link):
    return f"""
<h2 style="margin:0 0 8px;font-size:20px;color:#2c2c4a">Password Reset Request 🔑</h2>
<p style="color:#555;margin:0 0 20px">Hello <b>{first_name}</b>, we received a request to
reset your SMVS OCR password.</p>
<a href="{reset_link}" style="display:inline-block;background:linear-gradient(135deg,#c97e1a,#e8a020);
  color:#fff;text-decoration:none;padding:14px 28px;border-radius:10px;font-weight:700;font-size:15px">
  🔓 Reset My Password
</a>
<p style="color:#888;font-size:13px;margin-top:16px">This link expires in <b>15 minutes</b>.</p>
<p style="font-size:12px;color:#aaa;margin:0">If you did not request a reset, please ignore this email.</p>
"""


def send_feedback_notification(admin_email, fb_name, fb_email, fb_type, fb_message, fb_id):
    body = f"""
<h2 style="margin:0 0 8px;font-size:20px;color:#2c2c4a">New Feedback Received 💬</h2>
<div style="background:#faf7f1;border-radius:10px;padding:14px 18px;margin-bottom:20px">
  <table style="font-size:14px;color:#444;width:100%">
    <tr><td style="padding:4px 0;color:#888;width:100px">From</td><td><b>{fb_name}</b> ({fb_email})</td></tr>
    <tr><td style="padding:4px 0;color:#888">Type</td><td><span style="background:#fdecc8;
      color:#9a6a12;border-radius:6px;padding:1px 8px">{fb_type}</span></td></tr>
    <tr><td style="padding:4px 0;color:#888">Message</td><td></td></tr>
  </table>
  <div style="background:#fff;border-radius:8px;padding:12px;margin-top:8px;font-size:14px;
    color:#333;border-left:3px solid #e8a020">{fb_message}</div>
</div>
<p style="font-size:12px;color:#aaa">Feedback ID: {fb_id} — View in Admin → Feedback tab.</p>
"""
    send_async(admin_email, f"SMVS OCR — New {fb_type} Feedback", _wrap(body))
