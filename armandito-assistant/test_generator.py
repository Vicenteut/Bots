from config import load_environment
load_environment()
from fetcher import get_latest_headlines
from generator import generate_tweet, generate_tweet_variants

headlines = get_latest_headlines(3)
print("=== %d NOTICIAS REALES ===" % len(headlines))
print()

for i, h in enumerate(headlines):
    title = h.get("title", "???")
    source = h.get("source", "???")
    print("NOTICIA %d: %s" % (i+1, title[:100]))
    print("Fuente: %s" % source)
    print()

    tweet = generate_tweet(h)
    print("TWEET:")
    print(tweet)
    print("[%d chars]" % len(tweet))
    print()

    v = generate_tweet_variants(h)
    print("VARIANTES A/B:")
    print("MAIN: %s" % v["main"][:250])
    for j, alt in enumerate(v.get("alt_hooks", [])):
        if alt:
            print("ALT %d: %s" % (j+1, alt))
    print()
    print("=" * 60)
    print()
