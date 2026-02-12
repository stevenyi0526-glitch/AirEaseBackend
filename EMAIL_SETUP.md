# AirEase Email Configuration Guide

This guide explains how to set up email functionality for AirEase, including:
1. **Email Verification** for user registration
2. **Feedback Notifications** sent to admin

## Quick Setup (Gmail)

### Step 1: Enable 2-Factor Authentication
1. Go to [Google Account Security](https://myaccount.google.com/security)
2. Enable "2-Step Verification"

### Step 2: Generate App Password
1. Go to [Google App Passwords](https://myaccount.google.com/apppasswords)
2. Select "Mail" and your device
3. Click "Generate"
4. Copy the 16-character password (format: `xxxx xxxx xxxx xxxx`)

### Step 3: Configure .env File

Create or update your `.env` file in the backend directory:

```env
# Email Configuration for Gmail
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=xxxx xxxx xxxx xxxx
ADMIN_EMAIL=stevenyi0526@gmail.com
FROM_EMAIL=your-email@gmail.com
```

**⚠️ Important**: Use the App Password from Step 2, NOT your regular Gmail password!

## Other Email Providers

### Outlook/Office 365
```env
SMTP_HOST=smtp.office365.com
SMTP_PORT=587
SMTP_USER=your-email@outlook.com
SMTP_PASSWORD=your-app-password
ADMIN_EMAIL=stevenyi0526@gmail.com
FROM_EMAIL=your-email@outlook.com
```

### Yahoo Mail
```env
SMTP_HOST=smtp.mail.yahoo.com
SMTP_PORT=587
SMTP_USER=your-email@yahoo.com
SMTP_PASSWORD=your-app-password
ADMIN_EMAIL=stevenyi0526@gmail.com
FROM_EMAIL=your-email@yahoo.com
```

### Custom SMTP Server
```env
SMTP_HOST=mail.your-domain.com
SMTP_PORT=587
SMTP_USER=noreply@your-domain.com
SMTP_PASSWORD=your-password
ADMIN_EMAIL=stevenyi0526@gmail.com
FROM_EMAIL=noreply@your-domain.com
```

## Email Features

### 1. Registration Email Verification

**Flow:**
1. User calls `POST /api/v1/auth/register` with email, username, password
2. System sends 6-digit verification code to email
3. User calls `POST /api/v1/auth/verify-email` with email and code
4. Account is created and JWT token is returned

**Endpoints:**
- `POST /api/v1/auth/register` - Initiate registration, sends verification code
- `POST /api/v1/auth/verify-email` - Complete registration with code
- `POST /api/v1/auth/resend-verification` - Resend verification code

**Code Expiry:** 10 minutes

### 2. Feedback Notifications

When users submit feedback via `POST /api/reports/`, an email notification is sent to `stevenyi0526@gmail.com` (configured in `admin_email`).

**Categories:**
- `aircraft_mismatch` - Aircraft type mismatch
- `missing_facilities` - Missing facilities
- `price_error` - Price error
- `flight_info_error` - Flight info error
- `time_inaccurate` - Incorrect time
- `other` - Other

## Development Mode

If SMTP is not configured, the system will:
1. Print verification codes to console (for development/testing)
2. Skip sending notification emails
3. Continue to function normally

This allows development without email setup.

## Testing Email Configuration

Run the backend and check startup logs:

```bash
cd backend
python3 -m uvicorn app.main:app --reload
```

You should see:
```
🛫 AirEase Backend starting...
   Email Notifications: ✓ configured → stevenyi0526@gmail.com
```

If not configured:
```
   Email Notifications: ✗ not configured
```

## Troubleshooting

### "Authentication failed" Error
- Make sure you're using an App Password, not your regular password
- Ensure 2-Factor Authentication is enabled
- Check that SMTP_USER matches your email exactly

### "Connection refused" Error
- Verify SMTP_HOST and SMTP_PORT are correct
- Check if your network/firewall blocks SMTP connections
- Try port 465 with SSL if 587 doesn't work

### Emails Not Received
- Check spam/junk folder
- Verify ADMIN_EMAIL is correct
- Ensure FROM_EMAIL is a valid address

## Security Notes

1. **Never commit `.env` file** to version control
2. **Use App Passwords** instead of regular passwords
3. **Rotate passwords** periodically
4. Consider using a dedicated email service (SendGrid, AWS SES) for production
