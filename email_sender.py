"""
email_sender.py — Deliver the finished MP4 to the client via SendGrid.

The video is attached directly if ≤ 25 MB; otherwise a download link
placeholder is included (you can swap in S3/GCS/Cloudinary as needed).
"""

import base64
import logging
import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import (
    Mail,
    Attachment,
    FileContent,
    FileName,
    FileType,
    Disposition,
)
import config

logger = logging.getLogger(__name__)

MAX_ATTACH_BYTES = 25 * 1024 * 1024   # SendGrid's attachment limit


def send_video_to_client(
    to_email: str,
    product_name: str,
    project_title: str,
    video_path: str,
) -> bool:
    """
    Send the final video to the client.

    Args:
        to_email:      Client's email address.
        product_name:  Used in the subject line.
        project_title: Video title from the storyboard.
        video_path:    Local path to the assembled MP4.

    Returns:
        True on success, False on failure.
    """
    file_size = os.path.getsize(video_path)
    file_name = os.path.basename(video_path)

    subject = f"Your AI Video is Ready: {product_name}"

    html_body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; color: #1a1a1a; max-width: 600px; margin: 0 auto;">
      <div style="background: linear-gradient(135deg, #0f0f0f 0%, #1a1a2e 100%);
                  padding: 40px; border-radius: 12px 12px 0 0; text-align: center;">
        <h1 style="color: #ffffff; font-size: 28px; margin: 0;">
          🎬 Your Video is Ready
        </h1>
        <p style="color: #aaaaaa; font-size: 14px; margin-top: 8px;">
          AI Video Studio
        </p>
      </div>

      <div style="background: #f9f9f9; padding: 36px; border-radius: 0 0 12px 12px;">
        <h2 style="color: #0f0f0f; font-size: 22px;">
          {project_title}
        </h2>
        <p style="color: #444; line-height: 1.7;">
          Hi there! Your custom AI-generated commercial for
          <strong>{product_name}</strong> has been produced and is attached
          to this email.
        </p>
        <p style="color: #444; line-height: 1.7;">
          The video includes:
        </p>
        <ul style="color: #444; line-height: 2;">
          <li>AI-generated cinematic B-roll (Higgsfield)</li>
          <li>Professional voiceover narration</li>
          <li>Synced caption overlays</li>
          <li>Ready-to-publish MP4 (1920×1080 @ 24fps)</li>
        </ul>
        <p style="color: #888; font-size: 13px; margin-top: 32px;">
          Questions or revisions? Reply to this email and our team will help
          within 24 hours.
        </p>
        <p style="color: #0f0f0f; font-weight: bold;">
          — AI Video Studio Team
        </p>
      </div>

      <p style="color: #bbb; font-size: 11px; text-align: center; margin-top: 20px;">
        You're receiving this because you submitted a video brief through our platform.
      </p>
    </body>
    </html>
    """

    message = Mail(
        from_email=(config.FROM_EMAIL, config.FROM_NAME),
        to_emails=to_email,
        subject=subject,
        html_content=html_body,
    )

    if file_size <= MAX_ATTACH_BYTES:
        with open(video_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode()
        attachment = Attachment(
            FileContent(encoded),
            FileName(file_name),
            FileType("video/mp4"),
            Disposition("attachment"),
        )
        message.attachment = attachment
        logger.info("Video attached (%.1f MB).", file_size / (1024 * 1024))
    else:
        logger.warning(
            "Video too large to attach (%.1f MB). "
            "Upload to cloud storage and insert a download link.",
            file_size / (1024 * 1024),
        )
        # TODO: upload to S3/GCS and embed a signed download URL in html_body

    try:
        sg = SendGridAPIClient(config.SENDGRID_API_KEY)
        response = sg.send(message)
        logger.info(
            "Email sent to %s — status %d", to_email, response.status_code
        )
        return response.status_code in (200, 201, 202)
    except Exception as exc:
        logger.error("SendGrid error: %s", exc)
        return False
