#!/usr/bin/env python3
"""Fetch relevant images from Unsplash for tweet posts."""
import os, sys, json, urllib.request, urllib.parse, re, random

sys.path.insert(0, '/root/x-bot')
os.chdir('/root/x-bot')
from dotenv import load_dotenv
load_dotenv('/root/x-bot/.env')

UNSPLASH_KEY = os.getenv('UNSPLASH_API_KEY', '')
IMG_DIR = '/root/x-bot/images'

KEYWORD_MAP = {
    'iran': 'iran flag middle east', 'israel': 'israel flag jerusalem',
    'china': 'china beijing skyline', 'russia': 'russia moscow kremlin',
    'ukraine': 'ukraine flag', 'usa': 'united states capitol',
    'trump': 'white house washington', 'bitcoin': 'bitcoin cryptocurrency',
    'crypto': 'cryptocurrency blockchain', 'oil': 'oil refinery petroleum',
    'gold': 'gold bars investment', 'fed': 'federal reserve building',
    'inflation': 'economy money', 'war': 'military conflict',
    'sanctions': 'economy sanctions', 'brics': 'brics summit diplomacy',
    'nato': 'nato alliance military', 'gaza': 'gaza middle east',
    'qatar': 'qatar doha skyline', 'lng': 'natural gas energy',
    'nuclear': 'nuclear energy', 'bank': 'central bank finance',
    'market': 'stock market trading', 'dollar': 'us dollar currency',
    'sec': 'wall street finance', 'lebanon': 'lebanon beirut',
}

def extract_keywords(text):
    text_lower = text.lower()
    for keyword, search_term in KEYWORD_MAP.items():
        if keyword in text_lower:
            return search_term
    words = re.sub(r'[^\w\s]', '', text_lower).split()
    stop = {'the','a','an','is','are','was','in','on','to','for','of','with','by',
            'from','as','that','this','will','has','have','not','says','said','after'}
    meaningful = [w for w in words if w not in stop and len(w) > 2]
    return ' '.join(meaningful[:3]) if meaningful else 'world news'

def fetch_image(headline_text, output_name='tweet_image.jpg'):
    if not UNSPLASH_KEY:
        print('No UNSPLASH_API_KEY in .env')
        return None
    os.makedirs(IMG_DIR, exist_ok=True)
    query = extract_keywords(headline_text)
    encoded = urllib.parse.quote(query)
    url = f'https://api.unsplash.com/search/photos?query={encoded}&per_page=5&orientation=landscape'
    req = urllib.request.Request(url, headers={'Authorization': 'Client-ID ' + UNSPLASH_KEY})
    try:
        res = urllib.request.urlopen(req, timeout=15)
        data = json.loads(res.read())
    except Exception as e:
        print(f'Unsplash API error: {e}')
        return None
    results = data.get('results', [])
    if not results:
        return None
    photo = random.choice(results)
    img_url = photo['urls']['regular']
    photographer = photo['user']['name']
    output_path = os.path.join(IMG_DIR, output_name)
    try:
        urllib.request.urlretrieve(img_url, output_path)
    except Exception as e:
        print(f'Download error: {e}')
        return None
    # Trigger download endpoint (Unsplash requirement)
    dl = photo.get('links', {}).get('download_location', '')
    if dl:
        try:
            urllib.request.urlopen(urllib.request.Request(dl, headers={'Authorization': 'Client-ID ' + UNSPLASH_KEY}), timeout=5)
        except Exception as e: print(f"[WARN] Unsplash tracking failed: {e}")
    print(f'Image: {output_path} ({os.path.getsize(output_path)} bytes) by {photographer}')
    return output_path

if __name__ == '__main__':
    headline = ' '.join(sys.argv[1:]) if len(sys.argv) > 1 else 'Iran attacks Qatar LNG'
    path = fetch_image(headline)
    print(f'Result: {path}' if path else 'Failed')
