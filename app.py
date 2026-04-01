"""
Newsreel Feed Analyzer Backend
Fetches following lists from X/Twitter and Instagram.
Deploy on Render with env vars:
  X_AUTH_TOKEN, X_CT0 (from browser cookies)
  IG_USERNAME, IG_PASSWORD
"""

import os
import json
import asyncio
import logging
import traceback
from curl_cffi import requests as cffi_requests
from flask import Flask, jsonify, request
from flask_cors import CORS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app, origins=["https://newsreel.co", "http://localhost:*"])

# ── X/Twitter via direct GraphQL API ──

BEARER_TOKEN = "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"

GRAPHQL_FOLLOWING = "https://x.com/i/api/graphql/UCFedrkjMz7PeEAWCWhqFw/Following"
GRAPHQL_USER_BY_SCREEN_NAME = "https://x.com/i/api/graphql/IGgvgiOx4QZndDHuD3x9TQ/UserByScreenName"


def get_x_headers():
    ct0 = os.environ.get('X_CT0', '')
    return {
        'authorization': f'Bearer {BEARER_TOKEN}',
        'x-csrf-token': ct0,
        'x-twitter-auth-type': 'OAuth2Session',
        'x-twitter-active-user': 'yes',
        'x-twitter-client-language': 'en',
        'content-type': 'application/json',
        'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'referer': 'https://x.com/',
        'origin': 'https://x.com',
    }


def get_x_cookies():
    auth_token = os.environ.get('X_AUTH_TOKEN', '')
    ct0 = os.environ.get('X_CT0', '')
    kdt = os.environ.get('X_KDT', '')
    twid = os.environ.get('X_TWID', '')
    cookies = {'auth_token': auth_token, 'ct0': ct0}
    if kdt:
        cookies['kdt'] = kdt
    if twid:
        cookies['twid'] = twid
    return cookies


def fetch_x_user_id(handle):
    """Get user ID from screen name using X's GraphQL API with Chrome TLS impersonation."""
    handle = handle.lstrip('@')

    cookie_str = "; ".join(f"{k}={v}" for k, v in get_x_cookies().items() if v)
    headers = get_x_headers()
    headers['cookie'] = cookie_str

    variables = json.dumps({"screen_name": handle, "withSafetyModeUserFields": True})
    features = json.dumps({
        "hidden_profile_subscriptions_enabled": True,
        "rweb_tipjar_consumption_enabled": True,
        "responsive_web_graphql_exclude_directive_enabled": True,
        "verified_phone_label_enabled": False,
        "subscriptions_verification_info_is_identity_verified_enabled": True,
        "subscriptions_verification_info_verified_since_enabled": True,
        "highlights_tweets_tab_ui_enabled": True,
        "responsive_web_twitter_article_notes_tab_enabled": True,
        "subscriptions_feature_can_gift_premium": True,
        "creator_subscriptions_tweet_preview_api_enabled": True,
        "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
        "responsive_web_graphql_timeline_navigation_enabled": True,
    })

    resp = cffi_requests.get(
        GRAPHQL_USER_BY_SCREEN_NAME,
        params={'variables': variables, 'features': features},
        headers=headers,
        impersonate="chrome",
        timeout=30,
    )
    logger.info(f"UserByScreenName status: {resp.status_code}")

    if resp.status_code != 200:
        logger.error(f"UserByScreenName error (status {resp.status_code}): {resp.text[:1000]}")
        raise Exception(f'User @{handle} not found (status {resp.status_code})')

    data = resp.json()
    user_result = data.get('data', {}).get('user', {}).get('result', {})
    rest_id = user_result.get('rest_id', '')
    legacy = user_result.get('legacy', {})
    name = legacy.get('name', handle)
    friends_count = legacy.get('friends_count', 0)

    if not rest_id:
        logger.error(f"No rest_id in response: {json.dumps(data)[:500]}")
        raise Exception(f'User @{handle} not found')

    logger.info(f"Found user @{handle} (id={rest_id}, following={friends_count})")
    return rest_id, name, friends_count


def fetch_x_following(handle):
    """Fetch following list using X's GraphQL API with Chrome TLS impersonation."""
    user_id, name, friends_count = fetch_x_user_id(handle)

    following = []
    cursor = None
    cookie_str = "; ".join(f"{k}={v}" for k, v in get_x_cookies().items() if v)
    headers = get_x_headers()
    headers['cookie'] = cookie_str

    for page in range(50):  # max 5000 follows
        variables = {
            "userId": user_id,
            "count": 20,
            "includePromotedContent": False,
            "withGrokTranslatedBio": False,
        }
        if cursor:
            variables["cursor"] = cursor

        features = {
            "rweb_video_screen_enabled": False,
            "profile_label_improvements_pcf_label_in_post_enabled": True,
            "responsive_web_profile_redirect_enabled": False,
            "rweb_tipjar_consumption_enabled": False,
            "verified_phone_label_enabled": False,
            "creator_subscriptions_tweet_preview_api_enabled": True,
            "responsive_web_graphql_timeline_navigation_enabled": True,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
            "premium_content_api_read_enabled": False,
            "communities_web_enable_tweet_community_results_fetch": True,
            "c9s_tweet_anatomy_moderator_badge_enabled": True,
            "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
            "responsive_web_grok_analyze_post_followups_enabled": True,
            "responsive_web_jetfuel_frame": True,
            "responsive_web_grok_share_attachment_enabled": True,
            "responsive_web_grok_annotations_enabled": True,
            "articles_preview_enabled": True,
            "responsive_web_edit_tweet_api_enabled": True,
            "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
            "view_counts_everywhere_api_enabled": True,
            "longform_notetweets_consumption_enabled": True,
            "responsive_web_twitter_article_tweet_consumption_enabled": True,
            "content_disclosure_indicator_enabled": True,
            "content_disclosure_ai_generated_indicator_enabled": True,
            "responsive_web_grok_show_grok_translated_post": True,
            "responsive_web_grok_analysis_button_from_backend": True,
            "post_ctas_fetch_enabled": True,
            "freedom_of_speech_not_reach_fetch_enabled": True,
            "standardized_nudges_misinfo": True,
            "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
            "longform_notetweets_rich_text_read_enabled": True,
            "longform_notetweets_inline_media_enabled": False,
            "responsive_web_grok_image_annotation_enabled": True,
            "responsive_web_grok_imagine_annotation_enabled": True,
            "responsive_web_grok_community_note_auto_translation_is_enabled": False,
            "responsive_web_enhance_cards_enabled": False,
        }

        resp = cffi_requests.get(
            GRAPHQL_FOLLOWING,
            params={
                'variables': json.dumps(variables),
                'features': json.dumps(features),
            },
            headers=headers,
            impersonate="chrome",
            timeout=30,
        )

        logger.info(f"Following page {page}: status {resp.status_code}")

        if resp.status_code != 200:
            logger.error(f"Following error: {resp.text[:500]}")
            break

        data = resp.json()

        # Parse the timeline entries
        instructions = (
            data.get('data', {})
            .get('user', {})
            .get('result', {})
            .get('timeline', {})
            .get('timeline', {})
            .get('instructions', [])
        )

        entries = []
        next_cursor = None

        for instruction in instructions:
            if instruction.get('type') == 'TimelineAddEntries' or 'entries' in instruction:
                entries = instruction.get('entries', [])
            elif instruction.get('type') == 'TimelineAddToModule':
                entries.extend(instruction.get('moduleItems', []))

        if page == 0:
            logger.info(f"Found {len(entries)} entries, instructions types: {[i.get('type','NO_TYPE') for i in instructions]}")
            if entries:
                logger.info(f"First entry keys: {list(entries[0].keys())}")

        for entry in entries:
            entry_id = entry.get('entryId', '')

            # Cursor entries
            if entry_id.startswith('cursor-bottom'):
                next_cursor = entry.get('content', {}).get('value')
                continue

            # User entries
            content = entry.get('content', {})
            item_content = content.get('itemContent', {})
            user_results = item_content.get('user_results', {}).get('result', {})

            if not user_results:
                continue

            legacy = user_results.get('legacy', {})
            screen_name = legacy.get('screen_name', '')
            display_name = legacy.get('name', screen_name)

            if screen_name:
                following.append({
                    'handle': screen_name,
                    'name': display_name,
                })

        if not next_cursor or len(entries) <= 2:  # only cursor entries left
            break
        cursor = next_cursor

    logger.info(f"Fetched {len(following)} following for @{handle}")
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
            following = fetch_x_following(handle)
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
        if 'not found' in error_msg.lower():
            return jsonify({'error': 'Handle not found. Check spelling and try again.'}), 404
        return jsonify({'error': f'Something went wrong: {error_msg}'}), 500


@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'ok',
        'x_configured': bool(os.environ.get('X_AUTH_TOKEN')),
        'ig_configured': bool(os.environ.get('IG_USERNAME')),
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
