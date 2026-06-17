"""
app.py — Flask web server.

Routes:
  GET  /          → sales landing page (pay $97 via Stripe)
  GET  /order     → client intake form (shown after Stripe redirect)
  POST /generate  → validates form, starts pipeline in background thread,
                    redirects to /success
  GET  /success   → confirmation page
  GET  /health    → simple uptime check
"""

import logging
import os
import threading
from flask import Flask, render_template, request, redirect, url_for, jsonify
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
                               client_email=client_email)

    # Fire and forget — the pipeline can take several minutes
    thread = threading.Thread(
        target=pipeline.run,
        kwargs=dict(
            product_name=product_name,
            target_audience=target_audience,
            tone=tone or "professional, cinematic, compelling",
            client_email=client_email,
        ),
        daemon=True,
    )
    thread.start()
    logger.info("Pipeline thread started for '%s' → %s", product_name, client_email)

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
