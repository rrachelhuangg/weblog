import hashlib
import hmac
import os
import secrets

from flask import Flask, abort, jsonify, make_response, render_template, request
from upstash_redis import Redis

app = Flask(__name__)

# Upstash Redis credentials. Vercel's Upstash integration sets the KV_* names;
# the UPSTASH_* names are what you get when creating a database on upstash.com.
REDIS_URL = os.environ.get("KV_REST_API_URL") or os.environ.get("UPSTASH_REDIS_REST_URL")
REDIS_TOKEN = os.environ.get("KV_REST_API_TOKEN") or os.environ.get("UPSTASH_REDIS_REST_TOKEN")
STATS_KEY = os.environ.get("STATS_KEY")

redis = Redis(url=REDIS_URL, token=REDIS_TOKEN) if REDIS_URL and REDIS_TOKEN else None

VISITORS_KEY = "unique_visitors"
LIKERS_KEY = "liked_devices"
DEVICE_COOKIE = "device_id"
DEVICE_COOKIE_MAX_AGE = 60 * 60 * 24 * 365 * 2  # 2 years


def client_ip():
    # Vercel puts the real client IP first in X-Forwarded-For
    forwarded = request.headers.get("X-Forwarded-For", "")
    return forwarded.split(",")[0].strip() or request.remote_addr or ""


def client_id():
    # A hash of the IP identifies a unique user without storing the raw address
    ip = client_ip()
    return hashlib.sha256(ip.encode()).hexdigest() if ip else None


def track_visitor():
    if redis is None:
        return
    user = client_id()
    if not user:
        return
    try:
        redis.sadd(VISITORS_KEY, user)
    except Exception:
        # Never let tracking break the page
        app.logger.exception("Failed to record visitor")


def device_id():
    """Random ID stored in a cookie so each browser/device is identified separately."""
    return request.cookies.get(DEVICE_COOKIE)


def like_state(device):
    """Return (like count, whether this device has liked)."""
    if redis is None:
        return 0, False
    try:
        count = redis.scard(LIKERS_KEY)
        liked = bool(device) and bool(redis.sismember(LIKERS_KEY, device))
        return count, liked
    except Exception:
        app.logger.exception("Failed to load likes")
        return 0, False


@app.route("/")
def blog():
    track_visitor()
    device = device_id()
    like_count, liked = like_state(device)
    response = make_response(render_template(
        "index.html",
        blog_title="rookie nova swe",
        title="my first 2 months as a full-time software engineer",
        description="october 2026",
        like_count=like_count,
        liked=liked,
    ))
    if not device:
        response.set_cookie(
            DEVICE_COOKIE,
            secrets.token_hex(16),
            max_age=DEVICE_COOKIE_MAX_AGE,
            httponly=True,
            samesite="Lax",
            secure=request.headers.get("X-Forwarded-Proto", request.scheme) == "https",
        )
    return response


@app.route("/like", methods=["POST"])
def like():
    if redis is None:
        return jsonify(error="Likes aren't configured"), 503
    device = device_id()
    if not device:
        return jsonify(error="Couldn't identify device"), 400
    # Each device is stored once in the set, so repeat likes don't add to the count
    redis.sadd(LIKERS_KEY, device)
    return jsonify(count=redis.scard(LIKERS_KEY), liked=True)


@app.route("/stats")
def stats():
    key = request.args.get("key", "")
    if not STATS_KEY or not hmac.compare_digest(key, STATS_KEY):
        abort(404)
    if redis is None:
        return "Visitor tracking isn't configured (Redis env vars missing).", 503
    count = redis.scard(VISITORS_KEY)
    return f"Unique visitors: {count}"


if __name__ == "__main__":
    app.run(debug=True)
