from dotenv import load_dotenv
load_dotenv()

from fetcher import get_latest_headlines
from generator import generate_tweet
from poster import post_tweet
import random

def run():
    headlines = get_latest_headlines(n=5)
    if not headlines:
        print("No headlines found")
        return

    headline = random.choice(headlines)
    print(f"Noticia seleccionada: {headline['title']}")

    tweet = generate_tweet(headline)
    print(f"\nTweet generado:\n{tweet}\n")

    tweet_id = post_tweet(tweet)
    print(f"Publicado: https://x.com/i/web/status/{tweet_id}")

if __name__ == "__main__":
    run()
