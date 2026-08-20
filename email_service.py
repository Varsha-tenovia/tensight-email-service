import os
import base64
import requests


def send_email(
    recipients,
    subject,
    body,
    attachment_paths
):
    resend_api_key = os.getenv(
        "RESEND_API_KEY"
    )

    from_email = os.getenv(
        "REPORT_FROM_EMAIL"
    )

    # ============================================
    # VALIDATION
    # ============================================

    if not resend_api_key:
        raise Exception(
            "RESEND_API_KEY is not configured"
        )

    if not from_email:
        raise Exception(
            "REPORT_FROM_EMAIL is not configured"
        )

    if not recipients:
        raise Exception(
            "No email recipients configured"
        )

    if not attachment_paths:
        raise Exception(
            "No attachments configured"
        )

    # ============================================
    # PREPARE EMAIL BODY
    # ============================================

    body = f"""{body}

Regards,
Tensight Reports
"""

    # ============================================
    # PREPARE ATTACHMENTS
    # ============================================

    attachments = []

    for attachment_path in attachment_paths:

        if not os.path.exists(attachment_path):
            raise Exception(
                f"Attachment not found: {attachment_path}"
            )

        with open(
            attachment_path,
            "rb"
        ) as file:

            attachment_data = (
                base64.b64encode(
                    file.read()
                ).decode()
            )

        filename = os.path.basename(
            attachment_path
        )

        attachments.append({
            "filename": filename,
            "content": attachment_data
        })

    # ============================================
    # SEND EMAIL
    # ============================================

    payload = {
        "from": f"Tensight Reports <{from_email}>",
        "to": recipients,
        "subject": subject,
        "text": body,
        "attachments": attachments
    }

    response = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {resend_api_key}",
            "Content-Type": "application/json"
        },
        json=payload,
        timeout=60
    )

    # ============================================
    # HANDLE RESPONSE
    # ============================================

    if not response.ok:
        raise Exception(
            f"Email failed: "
            f"{response.status_code} "
            f"{response.text}"
        )

    print(
        f"Email sent successfully to: "
        f"{recipients}"
    )

    

    return response.json()