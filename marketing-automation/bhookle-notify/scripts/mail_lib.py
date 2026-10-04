#!/usr/bin/env python3
"""Tiny Gmail SMTP sender shared by the notify scripts (same creds as other Bhookle skills)."""
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


def send_email(subject, html, to=None):
    user = os.environ["GMAIL_USER"]
    pwd = os.environ["GMAIL_APP_PASSWORD"]
    to = to or os.environ.get("EMAIL_RECIPIENT", "owner@example.com")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Bhookle Bot <{user}>"
    msg["To"] = to
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(user, pwd)
        s.sendmail(user, [to], msg.as_string())
    print(f"email sent -> {to} :: {subject}")
