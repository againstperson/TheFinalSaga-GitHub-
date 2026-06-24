# name=tests/test_generator.py
from real_drama.script_generator import make_debate_script
from real_drama.drama_fetchers import FetchResult

def test_script_references_source():
    items = [
        FetchResult("Title A", "Snippet A", "https://reddit.com/a", "reddit"),
        FetchResult("Title B", "Snippet B", "https://x.com/b", "x"),
    ]
    script = make_debate_script(items, max_lines=6)
    assert "reddit" in script.lower() or "reddit" in script
    assert "https://reddit.com/a" in script or "https://x.com/b" in script
