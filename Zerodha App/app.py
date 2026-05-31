from flask import Flask, render_template, request, redirect, jsonify
from markupsafe import Markup
import threading

from services.High_Momentum_Stocks import run_momentum_scanner
from services.Upper_Lower_Circuit_Stocks import run_circuit_scanner
from services.position_monitor import run_position_monitor
from services.nifty_screener import run_nifty_screener
from services.nifty500_most_active_momentum_stocks import run_universe_selector
from services.kite_auth_service import get_login_url, generate_token, get_token_status

app = Flask(__name__)


# ================================================================
# JINJA2 CUSTOM FILTERS  (badge HTML for trend & category values)
# ================================================================

TREND_BADGE_MAP = {
    "Strong Bullish": ("badge--strong-bull", "●", "STRONG BULL"),
    "Bullish":        ("badge--bull",         "●", "BULL"),
    "Sideways":       ("badge--sideways",     "●", "SIDEWAYS"),
    "Sideways (Rangebound)": ("badge--sideways", "●", "SIDEWAYS"),
    "Bullish Sideways":  ("badge--bull",      "●", "BULL SIDE"),
    "Bearish Sideways":  ("badge--bear",      "●", "BEAR SIDE"),
    "Strong Bearish":  ("badge--strong-bear", "●", "STRONG BEAR"),
    "Bearish":         ("badge--bear",        "●", "BEAR"),
    "STRONG_BULL":     ("badge--strong-bull", "●", "STRONG BULL"),
    "BULL":            ("badge--bull",        "●", "BULL"),
    "SIDEWAYS":        ("badge--sideways",    "●", "SIDEWAYS"),
    "BEAR":            ("badge--bear",        "●", "BEAR"),
    "STRONG_BEAR":     ("badge--strong-bear", "●", "STRONG BEAR"),
    "Low Data":        ("badge--low-data",    "○", "LOW DATA"),
}

CATEGORY_BADGE_MAP = {
    "FULLY_ALIGNED":   ("badge--fully-aligned",   "FULLY ALIGNED"),
    "PARTIAL_ALIGNED": ("badge--partial-aligned",  "PARTIAL"),
    "CONFLICT":        ("badge--conflict",         "CONFLICT"),
    "OPPOSITE":        ("badge--opposite",         "OPPOSITE"),
}


@app.template_filter("trend_badge")
def trend_badge_filter(value):
    """Render a colour-coded badge for trend strings."""
    val = str(value).strip()
    cfg = TREND_BADGE_MAP.get(val)
    if cfg:
        css, dot, label = cfg
        html = f'<span class="badge {css}"><span class="badge-dot" style="background:currentColor"></span>{label}</span>'
    else:
        html = f'<span class="badge badge--low-data">{val}</span>'
    return Markup(html)


@app.template_filter("category_badge")
def category_badge_filter(value):
    """Render a colour-coded badge for position category strings."""
    val = str(value).strip()
    cfg = CATEGORY_BADGE_MAP.get(val)
    if cfg:
        css, label = cfg
        html = f'<span class="badge {css}">{label}</span>'
    else:
        html = f'<span class="badge badge--low-data">{val}</span>'
    return Markup(html)


# ================================================================
# ROUTES
# ================================================================

@app.route("/")
def home():
    token_status = get_token_status()
    return render_template("index.html", token_status=token_status)


@app.route("/run_positions")
def run_positions():
    try:
        data = run_position_monitor()
    except Exception as e:
        data = []
        print(f"[position_monitor] ERROR: {e}")
    token_status = get_token_status()
    return render_template("index.html", position_data=data, token_status=token_status)


@app.route("/run_nifty")
def run_nifty():
    try:
        data = run_nifty_screener()
    except Exception as e:
        data = {"error": str(e)}
        print(f"[nifty_screener] ERROR: {e}")
    token_status = get_token_status()
    return render_template("index.html", nifty_data=data, token_status=token_status)


@app.route("/run_universe", methods=["POST"])
def run_universe():
    def background_task():
        try:
            run_universe_selector()
        except Exception as e:
            print(f"[universe_selector] ERROR: {e}")

    thread = threading.Thread(target=background_task, daemon=True)
    thread.start()
    return {"status": "started"}


@app.route("/run_circuit")
def run_circuit():
    try:
        data = run_circuit_scanner()
    except Exception as e:
        data = {"stocks": [], "file_path": None, "message": f"Error: {e}"}
        print(f"[circuit_scanner] ERROR: {e}")
    token_status = get_token_status()
    return render_template("index.html", circuit_data=data, token_status=token_status)


@app.route("/run_momentum")
def run_momentum():
    try:
        data = run_momentum_scanner()
    except Exception as e:
        data = {"buyers": [], "sellers": [], "message": f"Error: {e}"}
        print(f"[momentum_scanner] ERROR: {e}")
    token_status = get_token_status()
    return render_template("index.html", momentum_data=data, token_status=token_status)


# ================================================================
# AUTH ROUTES
# ================================================================

@app.route("/auth/login")
def auth_login():
    """Redirect user to Zerodha login page."""
    url = get_login_url()
    return redirect(url)


@app.route("/auth/callback")
def auth_callback():
    """
    Zerodha redirects back here after login with ?request_token=xxx&status=success
    Automatically exchanges the token and redirects home.
    """
    req_token = request.args.get("request_token", "").strip()
    status    = request.args.get("status", "")

    if not req_token or status != "success":
        token_status = get_token_status()
        return render_template(
            "index.html",
            token_status=token_status,
            auth_message="Login cancelled or failed. Please try again.",
            auth_success=False,
        )

    result = generate_token(req_token)
    token_status = get_token_status()
    return render_template(
        "index.html",
        token_status=token_status,
        auth_message=result["message"],
        auth_success=result["success"],
    )


@app.route("/auth/token", methods=["POST"])
def auth_token():
    """
    AJAX/manual fallback: accepts JSON body {"request_token": "..."} 
    or form field request_token, generates session, returns JSON.
    """
    data = request.get_json(silent=True) or {}
    req_token = data.get("request_token") or request.form.get("request_token", "")
    req_token = req_token.strip()

    if not req_token:
        return jsonify({"success": False, "message": "No request_token provided."}), 400

    result = generate_token(req_token)
    return jsonify(result), 200 if result["success"] else 500


@app.route("/auth/status")
def auth_status():
    """Return current token status as JSON (for polling/AJAX)."""
    return jsonify(get_token_status())


# ================================================================

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5000)