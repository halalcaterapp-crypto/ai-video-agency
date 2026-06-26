"""
app.py — Flask web server.

Routes:
  GET  /          -> sales landing page (pay $19.99 via Stripe)
  GET  /order     -> client intake form (shown after Stripe redirect)
  POST /generate  -> validates form, starts pipeline in background thread,
                     redirects to /success
  GET  /success   -> confirmation page
  GET  /health    -> simple uptime check
"""

import logging
import os
import threading
import uuid
from flask import Flask, render_template, request, redirect, url_for, jsonify
import config
import pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("app")

app = Flask(__name__)


@app.route("/", methods=["GET"])
def index():
    return render_template("landing.html")


@app.route("/order", methods=["GET"])
def order():
    return render_template("form.html")


@app.route("/generate", methods=["POST"])
def generate():
    product_name    = request.form.get("product_name", "").strip()
    target_audience = request.form.get("target_audience", "").strip()
    tone            = request.form.get("tone", "").strip()
    client_email    = request.form.get("client_email", "").strip()
    key_benefits    = request.form.get("key_benefits", "").strip()
    business_type   = request.form.get("business_type", "product").strip() or "product"
    generate_logo   = request.form.get("generate_logo") == "1"

    errors = []
    if not product_name:
        errors.append("Product name is required.")
    if not target_audience:
        errors.append("Target audience is required.")
    if not client_email or "@" not in client_email:
        errors.append("A valid email address is required.")

    if errors:
        return render_template("form.html", errors=errors,
                               product_name=product_name,
                               target_audience=target_audience,
                               tone=tone,
                               client_email=client_email,
                               business_type=business_type)

    # Handle optional logo upload
    logo_path = None
    logo_file = request.files.get("logo")
    if logo_file and logo_file.filename:
        # Save to a temp location so the pipeline thread can access it
        ext = os.path.splitext(logo_file.filename)[1].lower() or ".png"
        safe_ext = ext if ext in (".png", ".jpg", ".jpeg", ".webp") else ".png"
        tmp_name = f"upload_logo_{uuid.uuid4().hex[:8]}{safe_ext}"
        logo_path = os.path.join(config.BASE_OUTPUT_DIR, tmp_name)
        logo_file.save(logo_path)
        logger.info("Logo uploaded -> %s", logo_path)
        generate_logo = False  # uploaded logo takes priority over generation

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
    logger.info("Pipeline thread started for '%s' -> %s (logo: %s)",
                product_name, client_email, logo_path or ("generate" if generate_logo else "none"))

    return redirect(url_for("success", email=client_email, product=product_name))


@app.route("/success", methods=["GET"])
def success():
    email   = request.args.get("email", "your inbox")
    product = request.args.get("product", "your product")
    return render_template("success.html", email=email, product=product)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
