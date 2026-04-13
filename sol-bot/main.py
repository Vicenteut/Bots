from dotenv import load_dotenv
load_dotenv()

from fetcher import get_latest_headlines
from generator import generate_tweet
import random
import subprocess
from pathlib import Path

def run():
    headlines = get_latest_headlines(n=5)
    if not headlines:
        print("No headlines found")
        return

    headline = random.choice(headlines)
    print(f"Noticia seleccionada: {headline['title']}")

    post_text = generate_tweet(headline)
    print(f"\nPost generado:\n{post_text}\n")

    result = subprocess.run(
        ["python3", "threads_publisher.py", post_text],
        capture_output=True,
        text=True,
        check=False,
        cwd=Path(__file__).resolve().parent,
    )
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)
        raise SystemExit(result.returncode)

if __name__ == "__main__":
    run()
