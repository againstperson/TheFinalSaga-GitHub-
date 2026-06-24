# name=real_drama/script_generator.py
import random
import html
from typing import List

from .drama_fetchers import FetchResult

def sanitize_text(s):
    if not s:
        return ""
    return html.unescape(s).strip().replace("\n", " ").strip()

def make_debate_script(items: List[FetchResult], max_lines=12):
    """
    Construct a short, fast-paced debate-style script from FetchResult items.
    We avoid inventing claims — every line references the source title/snippet and includes a URL line.
    """
    if not items:
        return "No recent drama found from configured sources."

    # normalize
    entries = []
    for it in items:
        title = sanitize_text(it.title) or sanitize_text(it.snippet) or "Untitled post"
        snippet = sanitize_text(it.snippet)
        entries.append({"title": title, "snippet": snippet, "url": it.url, "source": it.source})

    # pick top N and shuffle for variety
    random.shuffle(entries)
    lines = []
    roles = ["Host", "Pro", "Con", "Analyst"]
    role_index = 0

    # Compose quick alternating lines: 2 lines per entry (claim + rebuttal), plus source link lines
    count = 0
    for e in entries:
        if count >= max_lines:
            break
        role = roles[role_index % len(roles)]
        line = f"{role}: \"{e['title']}\""
        if e["snippet"]:
            line += f" — {e['snippet'][:140]}..."
        lines.append(line)
        count += 1
        if count >= max_lines:
            break
        role_index += 1
        role = roles[role_index % len(roles)]
        lines.append(f"{role}: Reaction to {e['source'].upper()} post — see {e['url']}")
        count += 1
        role_index += 1

    # ensure fast pace: keep short lines, remove long filler
    trimmed = []
    for l in lines:
        if len(l) > 260:
            l = l[:250] + "..."
        trimmed.append(l)

    # join with blank lines to simulate short beats
    script = "\n\n".join(trimmed)
    return script
