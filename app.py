"""
app.py — Flask web server.

Routes:
  GET  /               -> sales landing page (pay $14.99 via Stripe)
  GET  /order?token=X  -> client intake form (requires valid single-use token)
  GET  /paid?session_id -> post-checkout form, gated on a verified Stripe payment
  POST /generate       -> validates form + token, starts pipeline, redirects to /status
  GET  /status/<job>   -> live progress page, with the download button when ready
  GET  /api/status/<job> -> JSON the status page polls
  GET  /success        -> legacy confirmation page
  GET  /download/<job>  -> serve a finished video (link sent in the delivery email)
  GET  /health         -> simple uptime check
  GET  /admin/tokens?key=ADMIN_KEY  -> view all tokens + generate new ones
  POST /admin/generate?key=ADMIN_KEY -> generate N new tokens
"""

import glob
import json
import logging
import os
import re
import threading
import uuid
from flask import (
    Flask, render_template, request, redirect, url_for, jsonify, send_file, abort
)
import config
import moderation
import payments
import pipeline
import tiers
import tokens as token_store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("app")

app = Flask(__name__)

# Initialize token DB on startup
token_store.init_db()

# Admin key — set ADMIN_KEY in Railway environment variables
ADMIN_KEY = os.environ.get("ADMIN_KEY", "changeme")


def _check_admin(req):
    """Return True if the request carries the correct admin key."""
    return req.args.get("key") == ADMIN_KEY or req.form.get("key") == ADMIN_KEY


# ─────────────────────────────────────────────────────────────────────────────
# Public routes
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    return render_template("landing.html")


@app.route("/order", methods=["GET"])
def order():
    token = request.args.get("token", "").strip()
    status = token_store.validate_token(token)

    if status == "valid":
        tier = token_store.tier_for_token(token) or tiers.BUSINESS
        return render_template(
            "form.html", token=token, tier=tier,
            default_type=tiers.default_type(tier),
            tier_price=tiers.price_display(tier),
            tier_label=tiers.label(tier),
        )
    elif status == "used":
        return render_template("token_error.html",
                               message="This link has already been used.",
                               detail="Each free link works for one video only. "
                                      "Purchase a video to create more.")
    else:
        return render_template("token_error.html",
                               message="This link is not valid.",
                               detail="Please make sure you copied the full link, "
                                      "or purchase a video below.")


@app.route("/paid", methods=["GET"])
def paid():
    """Post-checkout form. Open only to a Stripe session that was really paid.

    This route used to render the form for anyone who typed the URL, which
    meant unlimited free videos to anyone who knew the path. It now asks
    Stripe whether the session was paid, and derives the tier from the amount
    so it cannot be forged.
    """
    session_id = request.args.get("session_id", "").strip()
    try:
        info = payments.verify_session(session_id)
    except payments.PaymentError as exc:
        logger.warning("Blocked /paid (%s): %s", session_id[:24] or "no session", exc)
        return render_template(
            "token_error.html",
            message="We couldn't verify that payment.",
            detail=f"{exc} If you were charged, reply to your Stripe receipt "
                   "and we'll get your video sorted.",
        ), 402

    tier = tiers.tier_for_amount(info["amount_total"])
    token, state = token_store.token_for_session(info["session_id"], tier)

    if state == "used":
        return render_template(
            "token_error.html",
            message="This purchase has already been used.",
            detail="Each purchase produces one video. Grab another to make a new one.",
        ), 409

    logger.info(
        "Checkout verified: tier=%s (%s), state=%s, session=%s",
        tier, tiers.price_display(tier), state, info["session_id"][:24],
    )
    return render_template(
        "form.html",
        token=token,
        tier=tier,
        default_type=tiers.default_type(tier),
        tier_price=tiers.price_display(tier),
        tier_label=tiers.label(tier),
        client_email=info.get("email", ""),
    )


@app.route("/generate", methods=["POST"])
def generate():
    token            = request.form.get("token", "").strip()
    product_name     = request.form.get("product_name", "").strip()
    target_audience  = request.form.get("target_audience", "").strip()
    tone             = request.form.get("tone", "").strip()
    client_email     = request.form.get("client_email", "").strip()
    key_benefits     = request.form.get("key_benefits", "").strip()
    business_type    = request.form.get("business_type", "product").strip() or "product"
    generate_logo    = request.form.get("generate_logo") == "1"
    business_address = request.form.get("business_address", "").strip()
    business_phone   = request.form.get("business_phone", "").strip()
    business_website     = request.form.get("business_website", "").strip()
    cultural_preference  = request.form.get("cultural_preference", "standard").strip()

    # Re-validate the token before doing any work. There is no bypass value:
    # the old "PAID" magic string let anyone skip this entirely.
    token_status = token_store.validate_token(token)
    if token_status != "valid":
        return render_template("token_error.html",
                               message="This link has already been used or is invalid.",
                               detail="Purchase a video to create more."), 403

    # Tier is read from the token, never from the form. Tokens issued by the
    # admin page predate tiers and carry NULL -- treat those as full access.
    tier = token_store.tier_for_token(token) or tiers.BUSINESS
    if not tiers.allows(tier, business_type):
        logger.warning("Tier %s attempted business_type=%s", tier, business_type)
        return render_template(
            "token_error.html",
            message="That category needs the Business plan.",
            detail="Your Personal & Creative purchase covers fun, school and college "
                   "videos. Commercials for a business are $39.99.",
        ), 403

    errors = []
    if not product_name:
        errors.append("Business/product name is required.")
    if not target_audience:
        errors.append("Target audience is required.")
    if not client_email or "@" not in client_email:
        errors.append("A valid email address is required.")

    if errors:
        return render_template("form.html", errors=errors, token=token,
                               tier=tier,
                               default_type=tiers.default_type(tier),
                               tier_price=tiers.price_display(tier),
                               tier_label=tiers.label(tier),
                               product_name=product_name,
                               target_audience=target_audience,
                               tone=tone,
                               client_email=client_email,
                               business_type=business_type,
                               business_address=business_address,
                               business_phone=business_phone,
                               business_website=business_website)

    # Screen the brief before anything is spent on it. This sits ahead of the
    # logo upload and the token consumption on purpose: a refusal costs the
    # customer nothing, so a false positive can be corrected and resubmitted
    # against the same purchase.
    verdict = moderation.screen_brief(
        product_name=product_name,
        target_audience=target_audience,
        key_benefits=key_benefits,
        business_type=business_type,
        tone=tone,
    )
    if not verdict.allowed:
        headline, detail = verdict.customer_message()
        logger.warning(
            "Refused order from %s: category=%s layer=%s product=%r",
            client_email, verdict.category, verdict.layer, product_name[:60],
        )
        return render_template("token_error.html",
                               message=headline, detail=detail), 422

    # Handle optional logo upload
    logo_path = None
    logo_file = request.files.get("logo")
    if logo_file and logo_file.filename:
        ext = os.path.splitext(logo_file.filename)[1].lower() or ".png"
        safe_ext = ext if ext in (".png", ".jpg", ".jpeg", ".webp") else ".png"
        tmp_name = f"upload_logo_{uuid.uuid4().hex[:8]}{safe_ext}"
        logo_path = os.path.join(config.BASE_OUTPUT_DIR, tmp_name)
        logo_file.save(logo_path)
        logger.info("Logo uploaded -> %s", logo_path)
        generate_logo = False

    # Consume the token atomically -- prevents double-submission and makes the
    # Stripe session single-use.
    if not token_store.consume_token(token, client_email):
        return render_template("token_error.html",
                               message="This link was just used.",
                               detail="Each purchase produces one video."), 409

    # Create the job directory up front so the status page exists the moment
    # the client lands on it.
    job_id, job_dir = pipeline.new_job(product_name)

    thread = threading.Thread(
        target=pipeline.run,
        kwargs=dict(
            job_id=job_id,
            job_dir=job_dir,
            product_name=product_name,
            target_audience=target_audience,
            tone=tone or "professional, cinematic, compelling",
            client_email=client_email,
            key_benefits=key_benefits,
            logo_path=logo_path,
            generate_logo=generate_logo,
            business_type=business_type,
            business_address=business_address,
            business_phone=business_phone,
            business_website=business_website,
            cultural_preference=cultural_preference,
        ),
        daemon=True,
    )
    thread.start()
    logger.info("Pipeline thread started for '%s' -> %s (job %s, token: %s)",
                product_name, client_email, job_id, token)

    return redirect(url_for("status_page", job_id=job_id, email=client_email))


@app.route("/success", methods=["GET"])
def success():
    email   = request.args.get("email", "your inbox")
    product = request.args.get("product", "your product")
    return render_template("success.html", email=email, product=product)


# Job directories are built by pipeline._make_job_dir: slug + timestamp + random
# hex. Anything outside this character set is not one of ours, so reject it
# rather than letting it near the filesystem.
_JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,120}$")


def _read_status(job_id):
    """Assemble the current state of a job from disk. Returns None if unknown."""
    job_dir = os.path.join(config.BASE_OUTPUT_DIR, job_id)
    if not os.path.isdir(job_dir):
        return None

    status = {"state": "queued", "message": "Your brief is in the queue."}
    try:
        with open(os.path.join(job_dir, pipeline.STATUS_FILE)) as f:
            status.update(json.load(f))
    except (OSError, ValueError):
        pass   # job dir exists but status not written yet - "queued" is right

    # Clip progress is just a file count, so no plumbing through the worker.
    status["clips_done"] = len(glob.glob(os.path.join(job_dir, "shot_*", "clip.mp4")))
    status.setdefault("total_shots", 7)

    # Trust the filesystem over the status file: if the MP4 is there, it's done.
    if glob.glob(os.path.join(job_dir, "*_final.mp4")) and status["state"] != "done":
        status["state"] = "done"
        status["message"] = "Your video is ready."
        status.setdefault("download_url", f"{config.PUBLIC_BASE_URL}/download/{job_id}")

    status["job_id"] = job_id
    status["step_index"] = (
        pipeline.STEPS.index(status["state"]) if status["state"] in pipeline.STEPS
        else (len(pipeline.STEPS) if status["state"] == "done" else -1)
    )
    status["total_steps"] = len(pipeline.STEPS)
    return status


@app.route("/api/status/<job_id>", methods=["GET"])
def api_status(job_id):
    """JSON polled by the status page."""
    if not _JOB_ID_RE.match(job_id):
        abort(404)
    status = _read_status(job_id)
    if status is None:
        return jsonify({"state": "unknown",
                        "message": "We can't find that video."}), 404
    return jsonify(status)


@app.route("/status/<job_id>", methods=["GET"])
def status_page(job_id):
    """Live progress page - the client's copy of the delivery link."""
    if not _JOB_ID_RE.match(job_id):
        abort(404)
    status = _read_status(job_id)
    if status is None:
        return render_template(
            "token_error.html",
            message="We can't find that video.",
            detail="Double-check the link, or reply to your confirmation email.",
        ), 404
    return render_template("status.html", status=status,
                           email=request.args.get("email", ""))


@app.route("/download/<job_id>", methods=["GET"])
def download(job_id):
    """Serve the finished MP4 for a job. This is the link emailed to clients."""
    if not _JOB_ID_RE.match(job_id):
        abort(404)

    job_dir = os.path.join(config.BASE_OUTPUT_DIR, job_id)
    matches = sorted(glob.glob(os.path.join(job_dir, "*_final.mp4")))
    if not matches:
        logger.warning("Download miss for job '%s' (looked in %s)", job_id, job_dir)
        return render_template(
            "token_error.html",
            message="This video is no longer available.",
            detail="Download links expire when a video is cleaned up. "
                   "Reply to your delivery email and we'll re-send it.",
        ), 404

    video = matches[0]
    logger.info("Serving download: %s (%.1f MB)",
                video, os.path.getsize(video) / (1024 * 1024))
    return send_file(
        video,
        mimetype="video/mp4",
        as_attachment=True,
        download_name=os.path.basename(video),
    )


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


# ─────────────────────────────────────────────────────────────────────────────
# Admin routes (protected by ADMIN_KEY)
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/admin/tokens", methods=["GET"])
def admin_tokens():
    if not _check_admin(request):
        return "Unauthorized", 403
    all_tokens = token_store.list_tokens()
    base_url = request.host_url.rstrip("/")
    return render_template("admin_tokens.html",
                           tokens=all_tokens,
                           base_url=base_url,
                           admin_key=ADMIN_KEY)


@app.route("/admin/generate", methods=["POST"])
def admin_generate():
    if not _check_admin(request):
        return "Unauthorized", 403
    count = min(int(request.form.get("count", 10)), 100)
    new_tokens = token_store.generate_tokens(count)
    base_url = request.host_url.rstrip("/")
    all_tokens = token_store.list_tokens()
    return render_template("admin_tokens.html",
                           tokens=all_tokens,
                           new_tokens=new_tokens,
                           base_url=base_url,
                           admin_key=ADMIN_KEY)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
