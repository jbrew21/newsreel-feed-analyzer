"""
Newsreel Feed Analyzer Backend
Fetches following lists from X/Twitter and Instagram.
Deploy on Render with env vars:
  X_USERNAME, X_EMAIL, X_PASSWORD
  IG_USERNAME, IG_PASSWORD
"""

import os
import json
import asyncio
import logging
import traceback
from flask import Flask, jsonify, request
from flask_cors import CORS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app, origins=["https://newsreel.co", "http://localhost:*"])

# ── X/Twitter via twikit ──

_x_client = None
_x_lock = asyncio.Lock()


async def get_x_client():
    global _x_client
    if _x_client is not None:
        return _x_client

    from twikit import Client
    client = Client('en-US', timeout=60)

    # Try loading saved cookies first
    cookie_path = '/tmp/x_cookies.json'
    if os.path.exists(cookie_path):
        try:
            client.load_cookies(cookie_path)
            _x_client = client
            return client
        except Exception:
            pass

    # Login with credentials
    username = os.environ.get('X_USERNAME')
    email = os.environ.get('X_EMAIL')
    password = os.environ.get('X_PASSWORD')

    if not all([username, email, password]):
        raise Exception('X credentials not configured')

    await client.login(
        auth_info_1=username,
        auth_info_2=email,
        password=password
    )
    client.save_cookies(cookie_path)
    _x_client = client
    return client


async def fetch_x_following(handle):
    client = await get_x_client()

    # Get user
    handle = handle.lstrip('@')
    user = await client.get_user_by_screen_name(handle)

    # Fetch following (paginated)
    following = []
    result = await user.get_following()

    for _ in range(50):  # max 5000
        for u in result:
            following.append({
                'handle': u.screen_name,
                'name': u.name or u.screen_name,
            })
        # Check for next page
        try:
            result = await result.next()
            if not result:
                break
        except Exception:
            break

    return following


# ── Instagram via instagrapi ──

_ig_client = None


def get_ig_client():
    global _ig_client
    if _ig_client is not None:
        return _ig_client

    from instagrapi import Client
    client = Client()

    # Try loading saved session
    session_path = '/tmp/ig_session.json'
    if os.path.exists(session_path):
        try:
            client.load_settings(session_path)
            client.login(
                os.environ.get('IG_USERNAME', ''),
                os.environ.get('IG_PASSWORD', '')
            )
            _ig_client = client
            return client
        except Exception:
            pass

    username = os.environ.get('IG_USERNAME')
    password = os.environ.get('IG_PASSWORD')

    if not all([username, password]):
        raise Exception('Instagram credentials not configured')

    client.login(username, password)
    client.dump_settings(session_path)
    _ig_client = client
    return client


def fetch_ig_following(handle):
    client = get_ig_client()
    handle = handle.lstrip('@')

    # Get user ID
    user_id = client.user_id_from_username(handle)
    info = client.user_info(user_id)

    # Fetch following (instagrapi handles pagination internally)
    following_list = client.user_following(user_id, amount=0)  # 0 = all

    following = []
    for uid, user in following_list.items():
        following.append({
            'handle': user.username,
            'name': user.full_name or user.username,
        })

    return following


# ── Routes ──

@app.route('/api/following', methods=['GET'])
def get_following():
    platform = request.args.get('platform', '').lower()
    handle = request.args.get('handle', '').strip()

    if not platform or not handle:
        return jsonify({'error': 'Missing platform or handle'}), 400

    try:
        if platform == 'twitter' or platform == 'x':
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            following = loop.run_until_complete(fetch_x_following(handle))
            loop.close()
            return jsonify({'following': following, 'count': len(following)})

        elif platform == 'instagram':
            following = fetch_ig_following(handle)
            return jsonify({'following': following, 'count': len(following)})

        else:
            return jsonify({'error': f'Unsupported platform: {platform}'}), 400

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error fetching {platform} following for {handle}: {error_msg}")
        logger.error(traceback.format_exc())
        if 'not configured' in error_msg:
            return jsonify({'error': 'Platform not yet available. Coming soon.'}), 503
        if 'not found' in error_msg.lower() or 'user' in error_msg.lower():
            return jsonify({'error': 'Handle not found. Check spelling and try again.'}), 404
        return jsonify({'error': f'Something went wrong: {error_msg}'}), 500


@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'ok',
        'x_configured': bool(os.environ.get('X_USERNAME')),
        'ig_configured': bool(os.environ.get('IG_USERNAME')),
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
