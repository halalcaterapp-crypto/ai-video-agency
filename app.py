"""
app.py — Flask web server.

Routes:
  GET  /               -> sales landing page (pay $14.99 via Stripe)
  GET  /order?token=X  -> client intake form (requires valid single-use token)
  POST /generate       -> validates form + token, starts pipeline, redirects to /success
  GET  /success        -> confirmation page
  GET  /health         -> simple uptime check
  GET  /admin/tokens?key=ADMIN_KEY  -> view all tokens + generate new ones
  POST /admin/generate?key=ADMIN_KEY -> generate N new tokens
"""

import logging
import os
import threading
import uuid
from flask import Flask, render_template, request, redirect, url_for, jsonify
import config
import pipeline
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
        return render_template("form.html", token=token)
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


@app.route("/generate", methods=["POST"])
def generate():
    token         = request.form.get("token", "").strip()
    product_name  = request.form.get("product_name", "").strip()
    target_audience = request.form.get("target_audience", "").strip()
    tone          = request.form.get("tone", "").strip()
    client_email  = request.form.get("client_email", "").strip()
    key_benefits  = request.form.get("key_benefits", "").strip()
    business_type = request.form.get("business_type", "product").strip() or "product"
    generate_logo = request.form.get("generate_logo") == "1"

    # Re-validate token before doing any work
    token_status = token_store.validate_token(token)
    if token_status != "valid":
        return render_template("token_error.html",
                               message="This link has already been used or is invalid.",
                               detail="Purchase a video to create more.")

    errors = []
    if not product_name:
        errors.append("Business/product name is required.")
    if not target_audience:
        errors.append("Target audience is required.")
    if not client_email or "@" not in client_email:
        errors.append("A valid email address is required.")

    if errors:
        return render_template("form.html", errors=errors, token=token,
                               product_name=product_name,
                               target_audience=target_audience,
                               tone=tone,
                               client_email=client_email,
                               business_type=business_type)

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

    # Consume token atomically — prevents double-submission
    consumed = token_store.consume_token(token, client_email)
    if not consumed:
        return render_template("token_error.html",
                               message="This link was just used by someone else.",
                               detail="Purchase a video to create more.")

    thread = threading.Thread(
        target=pipeline.run,
        kwargs=dict(
            product_name=product_name,
            target_audience=target_audience,
            tone=tone or "professional, cinematic, compelling",
            client_email=client_email,
            key_benefits=key_benefits,
            logo_path=logo_path,
            generate_logo=generate_logo,
            business_type=business_type,
        ),
        daemon=True,
    )
    thread.start()
    logger.info("Pipeline thread started for '%s' -> %s (token: %s)",
                product_name, client_email, token)

    return redirect(url_for("success", email=client_email, product=product_name))


@app.route("/success", methods=["GET"])
def success():
    email   = request.args.get("email", "your inbox")
    product = request.args.get("product", "your product")
    return render_template("success.html", email=email, product=product)


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
