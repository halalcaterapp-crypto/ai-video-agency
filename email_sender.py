"""
email_sender.py - Deliver the finished MP4 to the client via Resend.

Delivery is a download link, not an attachment. Attaching the MP4 meant a
25 MB ceiling, a base64 payload roughly a third larger than the file itself,
and - when a send failed - a finished video stranded on an ephemeral
container with no way to reach it. A link sidesteps all three: the email is
tiny, any file size works, and a failed send can be retried or the link
handed over manually because the file is still on the volume.
"""

import logging

import resend

import config

logger = logging.getLogger(__name__)

_BRAND_HEADER = """
  <div style="background: linear-gradient(135deg, #0f0f0f 0%, #1a1a2e 100%);
              padding: 40px; border-radius: 12px 12px 0 0; text-align: center;">
    <h1 style="color: #ffffff; font-size: 28px; margin: 0;">{heading}</h1>
    <p style="color: #aaaaaa; font-size: 14px; margin-top: 8px;">SwiftAI Videos</p>
  </div>
"""


def _configured() -> bool:
    if not config.RESEND_API_KEY:
        logger.error(
            "RESEND_API_KEY is not set - cannot deliver email. "
            "Add it in Railway > Variables."
        )
        return False
    return True


def _send(to_email: str, subject: str, html: str, what: str) -> bool:
    """Send one email through Resend. Returns True on success."""
    if not _configured():
        return False
    try:
        resend.api_key = config.RESEND_API_KEY
        result = resend.Emails.send({
            "from": f"{config.FROM_NAME} <{config.FROM_EMAIL}>",
            "to": [to_email],
            "subject": subject,
            "html": html,
        })
        email_id = (result or {}).get("id", "?")
        logger.info("%s sent to %s (resend id=%s)", what, to_email, email_id)
        return True
    except Exception as exc:
        logger.error("Resend error sending %s to %s: %s", what, to_email, exc)
        return False


def send_video_to_client(
    to_email: str,
    product_name: str,
    project_title: str,
    video_path: str,
    download_url: str = "",
    size_mb: float = 0.0,
) -> bool:
    """
    Email the client a link to their finished video.

    Args:
        to_email:      Client's email address.
        product_name:  Used in the subject line.
        project_title: Video title from the storyboard.
        video_path:    Local path to the assembled MP4 (logged, not attached).
        download_url:  Public URL the client downloads from.
        size_mb:       File size, shown so they know what they're fetching.

    Returns:
        True on success, False on failure.
    """
    if not download_url:
        logger.error("No download_url given - client would receive a dead email.")
        return False

    size_line = f" ({size_mb:.1f} MB)" if size_mb else ""
    logger.info("Emailing download link for %s -> %s", video_path, download_url)

    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; color: #1a1a1a; max-width: 600px; margin: 0 auto;">
      {_BRAND_HEADER.format(heading="&#127916; Your Video is Ready")}
      <div style="background: #f9f9f9; padding: 36px; border-radius: 0 0 12px 12px;">
        <h2 style="color: #0f0f0f; font-size: 22px; margin-top: 0;">{project_title}</h2>
        <p style="color: #444; line-height: 1.7;">
          Hi there! Your custom video for <strong>{product_name}</strong> has
          finished production and is ready to download.
        </p>
        <p style="text-align: center; margin: 32px 0;">
          <a href="{download_url}"
             style="background: #1a1a2e; color: #ffffff; text-decoration: none;
                    padding: 16px 40px; border-radius: 8px; font-size: 17px;
                    font-weight: bold; display: inline-block;">
            Download your video{size_line}
          </a>
        </p>
        <p style="color: #888; font-size: 13px; text-align: center;">
          Or paste this into your browser:<br>
          <a href="{download_url}" style="color: #5a5ad8; word-break: break-all;">{download_url}</a>
        </p>
        <p style="color: #444; line-height: 1.7; margin-top: 28px;">Your video includes:</p>
        <ul style="color: #444; line-height: 2;">
          <li>AI-generated cinematic B-roll (Higgsfield AI)</li>
          <li>Professional voiceover narration</li>
          <li>Background music matched to your tone</li>
          <li>Ready-to-publish MP4 @ 24fps</li>
        </ul>
        <p style="color: #888; font-size: 13px; margin-top: 32px;">
          Save the file somewhere safe once you've downloaded it. Questions or
          revisions? Just reply to this email.
        </p>
        <p style="color: #0f0f0f; font-weight: bold;">- SwiftAI Videos Team</p>
      </div>
      <p style="color: #bbb; font-size: 11px; text-align: center; margin-top: 20px;">
        You're receiving this because you submitted a video brief through our platform.
      </p>
    </body>
    </html>
    """
    return _send(to_email, f"Your AI Video is Ready: {product_name}", html, "video link")


def send_failure_notice(to_email: str, product_name: str) -> bool:
    """Send an apology email when the pipeline fails."""
    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; color: #1a1a1a; max-width: 600px; margin: 0 auto;">
      {_BRAND_HEADER.format(heading="&#9888;&#65039; Production Delay")}
      <div style="background: #f9f9f9; padding: 36px; border-radius: 0 0 12px 12px;">
        <p style="color: #444; line-height: 1.7;">
          Hi there! We ran into a technical issue while producing your video for
          <strong>{product_name}</strong>. Our team has been notified and will
          reprocess your order and deliver it to you within 24 hours.
        </p>
        <p style="color: #444; line-height: 1.7;">
          We apologize for the inconvenience. No action is needed from you.
        </p>
        <p style="color: #0f0f0f; font-weight: bold;">- SwiftAI Videos Team</p>
      </div>
    </body>
    </html>
    """
    return _send(
        to_email, f"Your video for {product_name} - we're on it", html, "failure notice"
    )
