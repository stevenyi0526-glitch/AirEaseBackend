"""
AirEase Backend - Email Notification Service
Sends email notifications for user feedback reports
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from datetime import datetime

from app.config import settings


class EmailService:
    """
    Email notification service for feedback reports.
    Uses SMTP to send emails to admin when users submit reports.
    """
    
    # Category labels for email formatting
    CATEGORY_LABELS = {
        "aircraft_mismatch": ("机型不符", "Aircraft Type Mismatch"),
        "missing_facilities": ("设施缺失", "Missing Facilities"),
        "price_error": ("价格错误", "Price Error"),
        "flight_info_error": ("航班信息错误", "Flight Info Error"),
        "time_inaccurate": ("时间不准确", "Incorrect Time"),
        "other": ("其他", "Other"),
    }
    
    STATUS_LABELS = {
        "pending": ("待处理", "Pending"),
        "reviewed": ("已审核", "Reviewed"),
        "resolved": ("已解决", "Resolved"),
        "dismissed": ("已驳回", "Dismissed"),
    }
    
    def __init__(self):
        self.smtp_host = settings.smtp_host
        self.smtp_port = settings.smtp_port
        self.smtp_user = settings.smtp_user
        self.smtp_password = settings.smtp_password
        self.admin_email = settings.admin_email
        self.from_email = settings.from_email or self.smtp_user
    
    def is_configured(self) -> bool:
        """Check if email service is properly configured."""
        return all([
            self.smtp_host,
            self.smtp_port,
            self.smtp_user,
            self.smtp_password,
            self.admin_email
        ])
    
    async def send_report_notification(
        self,
        report_id: int,
        user_email: str,
        category: str,
        content: str,
        flight_id: Optional[str] = None,
        flight_info: Optional[dict] = None,
    ) -> bool:
        """
        Send email notification to admin when a new report is submitted.
        
        Args:
            report_id: Database ID of the report
            user_email: Email of the user who submitted the report
            category: Report category
            content: Report content/description
            flight_id: Optional flight ID related to the report
            flight_info: Optional flight details (airline, route, etc.)
        
        Returns:
            True if email sent successfully, False otherwise
        """
        if not self.is_configured():
            print("⚠️ Email service not configured. Skipping notification.")
            return False
        
        try:
            # Get category labels
            cat_cn, cat_en = self.CATEGORY_LABELS.get(category, ("未知", "Unknown"))
            
            # Build email subject
            subject = f"[AirEase 反馈] 新报告 #{report_id}: {cat_cn}"
            
            # Build email body
            html_body = self._build_report_email_html(
                report_id=report_id,
                user_email=user_email,
                category=category,
                category_label=cat_cn,
                content=content,
                flight_id=flight_id,
                flight_info=flight_info,
            )
            
            text_body = self._build_report_email_text(
                report_id=report_id,
                user_email=user_email,
                category=category,
                category_label=cat_cn,
                content=content,
                flight_id=flight_id,
                flight_info=flight_info,
            )
            
            # Create message
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.from_email
            msg["To"] = self.admin_email
            msg["Reply-To"] = user_email
            
            # Attach both text and HTML versions
            msg.attach(MIMEText(text_body, "plain", "utf-8"))
            msg.attach(MIMEText(html_body, "html", "utf-8"))
            
            # Send email
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.sendmail(self.from_email, self.admin_email, msg.as_string())
            
            print(f"✅ Email notification sent for report #{report_id}")
            return True
            
        except Exception as e:
            print(f"❌ Failed to send email notification: {e}")
            return False
    
    def _build_report_email_html(
        self,
        report_id: int,
        user_email: str,
        category: str,
        category_label: str,
        content: str,
        flight_id: Optional[str] = None,
        flight_info: Optional[dict] = None,
    ) -> str:
        """Build HTML email body for report notification."""
        
        flight_section = ""
        if flight_id or flight_info:
            flight_details = []
            if flight_id:
                flight_details.append(f"<strong>航班ID:</strong> {flight_id}")
            if flight_info:
                if flight_info.get("airline"):
                    flight_details.append(f"<strong>航空公司:</strong> {flight_info['airline']}")
                if flight_info.get("flightNumber"):
                    flight_details.append(f"<strong>航班号:</strong> {flight_info['flightNumber']}")
                if flight_info.get("route"):
                    flight_details.append(f"<strong>航线:</strong> {flight_info['route']}")
                if flight_info.get("date"):
                    flight_details.append(f"<strong>日期:</strong> {flight_info['date']}")
            
            flight_section = f"""
            <div style="background: #f0f9ff; padding: 15px; border-radius: 8px; margin: 15px 0;">
                <h3 style="margin: 0 0 10px 0; color: #0369a1;">相关航班信息</h3>
                {'<br>'.join(flight_details)}
            </div>
            """
        
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
        </head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; border-radius: 12px 12px 0 0;">
                <h1 style="color: white; margin: 0;">🛫 AirEase 用户反馈</h1>
            </div>
            
            <div style="background: #ffffff; padding: 20px; border: 1px solid #e5e7eb; border-top: none; border-radius: 0 0 12px 12px;">
                <div style="background: #fef3c7; padding: 15px; border-radius: 8px; margin-bottom: 15px;">
                    <strong>📋 报告编号:</strong> #{report_id}<br>
                    <strong>📂 类别:</strong> {category_label}<br>
                    <strong>📧 用户邮箱:</strong> <a href="mailto:{user_email}">{user_email}</a><br>
                    <strong>🕐 提交时间:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
                </div>
                
                {flight_section}
                
                <div style="background: #f9fafb; padding: 15px; border-radius: 8px; border-left: 4px solid #667eea;">
                    <h3 style="margin: 0 0 10px 0;">反馈内容:</h3>
                    <p style="margin: 0; white-space: pre-wrap;">{content}</p>
                </div>
                
                <div style="margin-top: 20px; padding-top: 20px; border-top: 1px solid #e5e7eb; text-align: center; color: #6b7280;">
                    <p>请直接回复此邮件与用户联系</p>
                    <p style="font-size: 12px;">AirEase - 智能航班舒适度评估平台</p>
                </div>
            </div>
        </body>
        </html>
        """
    
    def _build_report_email_text(
        self,
        report_id: int,
        user_email: str,
        category: str,
        category_label: str,
        content: str,
        flight_id: Optional[str] = None,
        flight_info: Optional[dict] = None,
    ) -> str:
        """Build plain text email body for report notification."""
        
        flight_section = ""
        if flight_id or flight_info:
            flight_details = []
            if flight_id:
                flight_details.append(f"航班ID: {flight_id}")
            if flight_info:
                if flight_info.get("airline"):
                    flight_details.append(f"航空公司: {flight_info['airline']}")
                if flight_info.get("flightNumber"):
                    flight_details.append(f"航班号: {flight_info['flightNumber']}")
                if flight_info.get("route"):
                    flight_details.append(f"航线: {flight_info['route']}")
                if flight_info.get("date"):
                    flight_details.append(f"日期: {flight_info['date']}")
            
            flight_section = f"""
相关航班信息:
{chr(10).join(flight_details)}
"""
        
        return f"""
AirEase 用户反馈通知
====================

报告编号: #{report_id}
类别: {category_label}
用户邮箱: {user_email}
提交时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
{flight_section}
反馈内容:
{content}

---
请直接回复此邮件与用户联系
AirEase - 智能航班舒适度评估平台
"""


# Singleton instance
email_service = EmailService()
