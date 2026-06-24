# name=real_drama/drama_fetchers.py
import time
import requests
from bs4 import BeautifulSoup

class FetchResult:
    def __init__(self, title, snippet, url, source):
        self.title = title
        self.snippet = snippet
        self.url = url
        self.source = source

class BaseFetcher:
    def fetch(self, limit=5, query=None):
        raise NotImplementedError

class RedditFetcher(BaseFetcher):
    # Uses Pushshift API as a no-key fallback; supports subreddit lists
    def __init__(self, session=None):
        self.session = session or requests.Session()

    def fetch_from_subreddit(self, subreddit, limit=5):
        url = f"https://api.pushshift.io/reddit/search/submission/?subreddit={subreddit}&sort=desc&size={limit}"
        try:
            r = self.session.get(url, timeout=10)
            r.raise_for_status()
            data = r.json().get("data", [])
            results = []
            for item in data:
                title = item.get("title") or ""
                selftext = item.get("selftext") or ""
                permalink = item.get("permalink")
                fullurl = f"https://reddit.com{permalink}" if permalink else item.get("url")
                snippet = (selftext[:200] + "...") if selftext else ""
                results.append(FetchResult(title, snippet, fullurl, "reddit"))
            return results
        except Exception:
            return []

    def fetch(self, subreddits=None, limit=5):
        subreddits = subreddits or []
        out = []
        per_sub = max(1, limit)
        for s in subreddits:
            out.extend(self.fetch_from_subreddit(s, per_sub))
            time.sleep(0.5)
        return out[:limit]

class YouTubeFetcher(BaseFetcher):
    # Uses youtube-search-python package (no API key) if available; otherwise no-op
    def __init__(self):
        try:
            from youtubesearchpython import VideosSearch
            self.VideosSearch = VideosSearch
        except Exception:
            self.VideosSearch = None

    def fetch(self, queries=None, limit=5, api_key=""):
        queries = queries or []
        if self.VideosSearch is None:
            return []
        out = []
        for q in queries:
            try:
                vs = self.VideosSearch(q, limit)
                r = vs.result()
                for v in r.get("result", [])[:limit]:
                    title = v.get("title", "")
                    url = v.get("link", "")
                    snippet = v.get("descriptionSnippet", "")
                    if isinstance(snippet, list):
                        snippet = " ".join([s.get("text","") for s in snippet])
                    out.append(FetchResult(title, snippet[:200], url, "youtube"))
            except Exception:
                continue
        return out[:limit]

class XFetcher(BaseFetcher):
    # Best-effort using nitter instance to search tweets or user timelines (HTML scrape)
    def __init__(self, nitter_instance="https://nitter.net"):
        self.nitter = nitter_instance.rstrip("/")
        self.session = requests.Session()

    def fetch_from_search(self, query, limit=5):
        # search page: /search?q=<query>&f=tweets
        try:
            url = f"{self.nitter}/search?q={requests.utils.requote_uri(query)}&f=tweets"
            r = self.session.get(url, timeout=10)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            tweets = soup.select(".timeline-item")[:limit]
            out = []
            for t in tweets:
                content_el = t.select_one(".tweet-content")
                content = content_el.get_text(" ", strip=True) if content_el else ""
                a = t.select_one("a:not(.tweet-avatar)")
                href = a["href"] if a and a.has_attr("href") else None
                link = f"{self.nitter}{href}" if href else url
                out.append(FetchResult(content[:200], "", link, "x"))
            return out
        except Exception:
            return []

    def fetch(self, queries=None, limit=5):
        queries = queries or []
        out = []
        for q in queries:
            out.extend(self.fetch_from_search(q, limit=limit))
            time.sleep(0.5)
        return out[:limit]

class ThreadsFetcher(BaseFetcher):
    # Best-effort scraping of threads via public web pages — fragile, best-effort
    def __init__(self):
        self.session = requests.Session()

    def fetch_from_profile(self, username, limit=5):
        try:
            url = f"https://www.threads.net/@{username}"
            r = self.session.get(url, timeout=10)
            r.raise_for_status()
            # Threads page contains JSON embedded. We'll extract first N post snippets via naive parsing.
            soup = BeautifulSoup(r.text, "html.parser")
            metas = soup.find_all("meta", {"property": "og:description"})
            if metas:
                text = metas[0].get("content", "")
                return [FetchResult(text[:200], "", url, "threads")]
            return []
        except Exception:
            return []

    def fetch(self, queries=None, limit=5):
        out = []
        for q in queries:
            if q.startswith("username:"):
                username = q.split(":", 1)[1]
                out.extend(self.fetch_from_profile(username, limit))
            else:
                # fallback: simple search via threads.net is not public — skip
                continue
            time.sleep(0.5)
        return out[:limit]
