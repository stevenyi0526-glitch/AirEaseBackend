"""
AirEase Backend - Email Verification Service
Handles email verification codes for user registration
"""

import os
import random
import string
import logging
import traceback
import asyncio
import sys
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from app.config import settings

logger = logging.getLogger(__name__)

# ── Dedicated file logger for verification events ──
_VERIFICATION_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs")
os.makedirs(_VERIFICATION_LOG_DIR, exist_ok=True)
_VERIFICATION_LOG_PATH = os.path.join(_VERIFICATION_LOG_DIR, "verification.log")

_vlog = logging.getLogger("verification_audit")
_vlog.setLevel(logging.INFO)
_vlog.propagate = False  # don't bubble up to root logger
if not _vlog.handlers:
    _fh = logging.FileHandler(_VERIFICATION_LOG_PATH, encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(message)s"))
    _vlog.addHandler(_fh)


class VerificationService:
    """
    Email verification service for user registration.
    
    Manages verification codes:
    - Generate and store codes with expiry
    - Send verification emails
    - Verify submitted codes
    """
    
    # In-memory storage for verification codes
    # Format: { email: (code, expiry_datetime) }
    # NOTE: For production, use Redis or database storage
    _pending_verifications: Dict[str, Tuple[str, datetime, dict]] = {}
    
    # Code settings
    CODE_LENGTH = 6
    CODE_EXPIRY_MINUTES = 10
    
    def __init__(self):
        self.smtp_host = settings.smtp_host
        self.smtp_port = settings.smtp_port
        self.smtp_user = settings.smtp_user
        self.smtp_password = settings.smtp_password
        self.from_email = settings.from_email or self.smtp_user
    
    def is_configured(self) -> bool:
        """Check if email service is properly configured."""
        return all([
            self.smtp_host,
            self.smtp_port,
            self.smtp_user,
            self.smtp_password
        ])
    
    def generate_code(self) -> str:
        """Generate a random 6-digit verification code."""
        return ''.join(random.choices(string.digits, k=self.CODE_LENGTH))
    
    def store_pending_registration(
        self,
        email: str,
        code: str,
        user_data: dict
    ) -> None:
        """
        Store pending registration with verification code.
        
        Args:
            email: User's email address
            code: Verification code
            user_data: User registration data to save after verification
        """
        expiry = datetime.utcnow() + timedelta(minutes=self.CODE_EXPIRY_MINUTES)
        self._pending_verifications[email.lower()] = (code, expiry, user_data)
    
    def get_pending_registration(self, email: str) -> Optional[Tuple[str, dict]]:
        """
        Get pending registration data if code is valid.
        
        Returns:
            Tuple of (code, user_data) if exists and not expired, None otherwise
        """
        email_lower = email.lower()
        if email_lower not in self._pending_verifications:
            return None
        
        code, expiry, user_data = self._pending_verifications[email_lower]
        
        # Check if expired
        if datetime.utcnow() > expiry:
            del self._pending_verifications[email_lower]
            return None
        
        return (code, user_data)
    
    def verify_code(self, email: str, submitted_code: str) -> Optional[dict]:
        """
        Verify the submitted code and return user data if valid.
        
        Args:
            email: User's email address
            submitted_code: Code submitted by user
        
        Returns:
            User registration data if code is correct, None otherwise
        """
        pending = self.get_pending_registration(email)
        if not pending:
            return None
        
        stored_code, user_data = pending
        
        if submitted_code == stored_code:
            # Remove from pending after successful verification
            del self._pending_verifications[email.lower()]
            return user_data
        
        return None
    
    def verify_code_detailed(self, email: str, submitted_code: str) -> dict:
        """
        Verify the submitted code with detailed status for better error messages.
        
        Returns a dict with:
          - status: "success" | "no_pending" | "expired" | "wrong_code"
          - user_data: dict (only if status == "success")
          - stored_code: the code that was stored (for logging)
        """
        email_lower = email.lower()
        
        if email_lower not in self._pending_verifications:
            return {"status": "no_pending", "stored_code": "N/A"}
        
        stored_code, expiry, user_data = self._pending_verifications[email_lower]
        
        # Check if expired
        if datetime.utcnow() > expiry:
            del self._pending_verifications[email_lower]
            return {"status": "expired", "stored_code": stored_code}
        
        # Check if code matches
        if submitted_code != stored_code:
            return {"status": "wrong_code", "stored_code": stored_code}
        
        # Success – remove from pending
        del self._pending_verifications[email_lower]
        return {"status": "success", "user_data": user_data, "stored_code": stored_code}
    
    def log_verification_event(
        self,
        username: str,
        email: str,
        code_sent: str,
        event_type: str = "SEND",
        user_code_input: str = "",
        result: str = ""
    ) -> None:
        """
        Write a structured log entry to the verification log file.
        
        Format:
        ────────────────────────
        [SEND] / [VERIFY] / [RESEND]
        账号：testin01
        邮箱：xzzhanga@gmail.com
        验证码_send：009616
        user_code_input：xxxxxx
        result：success / wrong_code / expired / no_pending
        时间：20260305 16:56
        ────────────────────────
        """
        now = datetime.utcnow().strftime("%Y%m%d %H:%M:%S")
        lines = [
            "────────────────────────",
            f"[{event_type}]",
            f"账号：{username}",
            f"邮箱：{email}",
            f"验证码_send：{code_sent}",
        ]
        if user_code_input:
            lines.append(f"user_code_input：{user_code_input}")
        if result:
            lines.append(f"result：{result}")
        lines.append(f"时间：{now}")
        lines.append("────────────────────────")
        
        msg = "\n".join(lines)
        _vlog.info(msg)
        # Also print to stdout for real-time visibility
        print(f"📋 Verification [{event_type}] — {email} — code_sent={code_sent}"
              + (f" — user_input={user_code_input}" if user_code_input else "")
              + (f" — result={result}" if result else ""),
              flush=True)
    
    def clear_pending(self, email: str) -> None:
        """Remove pending registration for an email."""
        email_lower = email.lower()
        if email_lower in self._pending_verifications:
            del self._pending_verifications[email_lower]
    
    async def send_verification_email(
        self,
        email: str,
        code: str,
        username: str,
        subject: str = None
    ) -> bool:
        """
        Send verification code email to user.
        
        Args:
            email: Recipient email address
            code: Verification code
            username: User's display name
            subject: Optional custom email subject
        
        Returns:
            True if email sent successfully, False otherwise
        """
        if not self.is_configured():
            logger.warning(f"⚠️ Email service not configured. Verification code: {code}")
            # In development, return True so registration can proceed
            return True
        
        try:
            # Build email content
            if not subject:
                subject = f"[AirEase] Your Verification Code: {code}"
            
            html_body = self._build_verification_email_html(code, username)
            text_body = self._build_verification_email_text(code, username)
            
            # Create message
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = '"AirEase" <noreply@airease.ai>'
            msg["To"] = email
            
            # Attach both text and HTML versions
            msg.attach(MIMEText(text_body, "plain", "utf-8"))
            msg.attach(MIMEText(html_body, "html", "utf-8"))
            
            # Run synchronous SMTP in a thread to avoid blocking the async event loop
            smtp_host = self.smtp_host
            smtp_port = self.smtp_port
            smtp_user = self.smtp_user
            smtp_password = self.smtp_password
            msg_string = msg.as_string()
            
            def _send():
                with smtplib.SMTP(smtp_host, smtp_port) as server:
                    server.starttls()
                    server.login(smtp_user, smtp_password)
                    server.sendmail(smtp_user, email, msg_string)
            
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _send)
            
            print(f"✅ Verification email sent to {email}", flush=True)
            return True
            
        except Exception as e:
            print(f"❌ Failed to send verification email: {e}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
            return False
    
    def _build_verification_email_html(self, code: str, username: str) -> str:
        """Build HTML email body for verification code."""
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #f5f5f5;">
            <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; border-radius: 12px 12px 0 0; text-align: center;">
                <h1 style="color: white; margin: 0; font-size: 28px;">🛫 AirEase</h1>
                <p style="color: rgba(255,255,255,0.9); margin-top: 8px;">Smart Flight Experience Platform</p>
            </div>
            
            <div style="background: #ffffff; padding: 30px; border-radius: 0 0 12px 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
                <h2 style="color: #333; margin-top: 0;">Hi {username}! 👋</h2>
                
                <p style="color: #666; font-size: 16px; line-height: 1.6;">
                    Welcome to AirEase! To complete your registration, please enter the verification code below:
                </p>
                
                <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; border-radius: 12px; text-align: center; margin: 25px 0;">
                    <p style="color: rgba(255,255,255,0.8); margin: 0 0 8px 0; font-size: 14px;">Your Verification Code</p>
                    <p style="color: white; font-size: 36px; font-weight: bold; letter-spacing: 8px; margin: 0; font-family: 'Courier New', monospace;">{code}</p>
                </div>
                
                <p style="color: #999; font-size: 14px; text-align: center;">
                    ⏰ This code expires in <strong>10 minutes</strong>
                </p>
                
                <hr style="border: none; border-top: 1px solid #eee; margin: 25px 0;">
                
                <p style="color: #999; font-size: 12px; text-align: center;">
                    If you didn't request this code, please ignore this email.<br>
                    Someone may have entered your email by mistake.
                </p>
                
                <p style="color: #999; font-size: 12px; text-align: center; margin-top: 20px;">
                    AirEase - 智能航班舒适度评估平台<br>
                    Making every journey comfortable ✈️
                </p>
            </div>
        </body>
        </html>
        """
    
    def _build_verification_email_text(self, code: str, username: str) -> str:
        """Build plain text email body for verification code."""
        return f"""
AirEase - Email Verification
=============================

Hi {username}!

Welcome to AirEase! To complete your registration, please enter the verification code below:

Your Verification Code: {code}

⏰ This code expires in 10 minutes.

---

If you didn't request this code, please ignore this email.
Someone may have entered your email by mistake.

AirEase - Smart Flight Experience Platform
Making every journey comfortable ✈️
"""


# Singleton instance
verification_service = VerificationService()
