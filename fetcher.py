import feedparser

FEEDS = [
    "https://feeds.bloomberg.com/markets/news.rss",
    "https://cointelegraph.com/rss",
    "https://feeds.reuters.com/reuters/businessNews",
    "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
]

def get_latest_headlines(n=5):
    items = []
    for url in FEEDS:
        feed = feedparser.parse(url)
        for entry in feed.entries[:2]:
            items.append({
                "title": entry.title,
                "summary": getattr(entry, "summary", ""),
                "source": feed.feed.title
            })
    return items[:n]
