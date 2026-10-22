#!/usr/bin/env python3
"""Add Scholar Inbox papers to Zotero via the Zotero Web API.

Usage:
  zotero_add.py check                 verify API key, ensure the collection exists
  zotero_add.py known ARXIV_ID...     print the IDs already in the library or trash
  zotero_add.py collections           print every collection as {key, path}
  zotero_add.py add PAPERS.json [--dry-run]

PAPERS.json is a list of objects:
  {arxiv_id, title, authors, abstract, url, publication_date, ranking_score (null if none),
   source: "scholar-inbox" | "alphaxiv", category: "relevance" | "discovery",
   verdict: "must-read" | "skim", topic_collection (a key from `collections`), reason, note_html}
Papers with any other category or verdict (e.g. "skip") are refused. Each paper goes into
the "Scholar Inbox" collection and its topic collection. The PDF, Snapshot, arXiv category
tags and Comment note are added later on the Mac by zotero_files.py.

The API key is read from $ZOTERO_API_KEY, falling back to the macOS Keychain
(service "zotero-api-key"). In a Claude Code cloud routine neither exists: the key is a
network secret that the proxy attaches as the Zotero-API-Key header. Papers already in the library or its trash are skipped,
so deleting a paper (without emptying the trash) keeps it from being re-added.
"""
import json
import os
import re
import secrets
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.zotero.org"
COLLECTION = "Scholar Inbox"


def api_key():
    if os.environ.get("ZOTERO_API_KEY"):
        return os.environ["ZOTERO_API_KEY"]
    try:
        return subprocess.run(
            ["security", "find-generic-password", "-s", "zotero-api-key", "-w"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None  # cloud: injected by the network-secret proxy


KEY = None


def request(method, path, body=None, params=None, headers=None, form=None):
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    all_headers = {"Zotero-API-Version": "3", **(headers or {})}
    if KEY:
        all_headers["Zotero-API-Key"] = KEY
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        all_headers["Content-Type"] = "application/json"
        if method == "POST":
            all_headers["Zotero-Write-Token"] = secrets.token_hex(16)
    elif form is not None:
        data = urllib.parse.urlencode(form).encode()
        all_headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, headers=all_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as e:
        sys.exit(f"Zotero API {e.code} on {method} {path}: {e.read().decode()[:300]}")


def norm(title):
    return re.sub(r"[^a-z0-9]", "", title.lower())


def user_id():
    return request("GET", "/keys/current")["userID"]


def all_collections(uid):
    """Every collection as {key, path}, e.g. "Bayesian Optimization / High-dimensional BO"."""
    cols, start = [], 0
    while True:
        page = request("GET", f"/users/{uid}/collections", params={"limit": 100, "start": start})
        cols += page
        if len(page) < 100:
            break
        start += 100
    by_key = {c["key"]: c["data"] for c in cols}

    def path(key):
        data = by_key[key]
        parent = data.get("parentCollection")
        return f"{path(parent)} / {data['name']}" if parent else data["name"]

    return sorted(({"key": k, "path": path(k)} for k in by_key), key=lambda c: c["path"])


def ensure_collection(uid):
    start = 0
    while True:
        cols = request("GET", f"/users/{uid}/collections", params={"limit": 100, "start": start})
        for c in cols:
            if c["data"]["name"] == COLLECTION and not c["data"].get("parentCollection"):
                return c["key"]
        if len(cols) < 100:
            break
        start += 100
    res = request("POST", f"/users/{uid}/collections", [{"name": COLLECTION}])
    return res["successful"]["0"]["key"]


ARXIV_ID = re.compile(r"\d{4}\.\d{4,5}")
_index = None


def library_index(uid):
    """arXiv IDs and normalized titles of every item in the library and its trash.

    Built by listing the items rather than with Zotero's quick search, which
    doesn't reliably match arXiv IDs.
    """
    global _index
    if _index is None:
        _index = {"ids": set(), "titles": set()}
        for path in ("/items", "/items/trash"):
            start = 0
            while True:
                page = request("GET", f"/users/{uid}{path}",
                               params={"itemType": "-attachment", "limit": 100, "start": start})
                for item in page:
                    remember(item["data"])
                if len(page) < 100:
                    break
                start += 100
    return _index


def remember(data):
    if data.get("itemType") == "note":
        return
    if data.get("title"):
        _index["titles"].add(norm(data["title"]))
    for field in ("url", "archiveID", "DOI", "extra"):
        value = data.get(field) or ""
        if "arxiv" in value.lower():
            _index["ids"].update(ARXIV_ID.findall(value))


def in_library(uid, title):
    return norm(title) in library_index(uid)["titles"]


def known(uid, arxiv_ids):
    return [aid for aid in arxiv_ids if aid in library_index(uid)["ids"]]


def creators(authors):
    out = []
    for name in re.split(r",\s*|\s+and\s+", authors or ""):
        name = name.strip()
        if not name:
            continue
        first, _, last = name.rpartition(" ")
        out.append({"creatorType": "author", "firstName": first, "lastName": last or name})
    return out


CATEGORIES = {"relevance", "discovery"}
VERDICTS = {"must-read", "skim"}


def build_item(p, coll_keys):
    tags = ["si:to-review", f"si:{p['category']}", f"si:{p['verdict']}"]
    source = ("Found via alphaXiv search" if p.get("ranking_score") is None
              else f"Scholar Inbox score: {p['ranking_score']}")
    item = {
        "itemType": "preprint",
        "title": p["title"],
        "creators": creators(p.get("authors")),
        "abstractNote": p.get("abstract", ""),
        "date": (p.get("publication_date") or "")[:10],
        "url": p.get("url", ""),
        "libraryCatalog": "arXiv.org",
        "extra": source,
        "collections": coll_keys,
        "tags": [{"tag": t} for t in tags],
    }
    aid = p.get("arxiv_id")
    if aid:
        # Same fields as a Zotero connector save from arXiv; zotero_files.py later adds
        # the primary category to the first Extra line.
        item.update({
            "repository": "arXiv",
            "archiveID": f"arXiv:{aid}",
            "DOI": f"10.48550/arXiv.{aid}",
            "url": f"http://arxiv.org/abs/{aid}",
            "extra": f"arXiv:{aid}\n{source}",
        })
    return item


def add(path, dry_run):
    papers = json.loads(Path(path).read_text())
    uid = user_id()
    coll_key = ensure_collection(uid)
    topics = {c["key"] for c in all_collections(uid)} - {coll_key}
    results = []
    for p in papers:
        aid, title = p.get("arxiv_id"), p["title"]
        if p.get("category") not in CATEGORIES or p.get("verdict") not in VERDICTS:
            results.append({"title": title, "status":
                            f"refused: category={p.get('category')!r} verdict={p.get('verdict')!r}"})
            continue
        if in_library(uid, title) or (aid and known(uid, [aid])):
            results.append({"title": title, "status": "skipped: already in library or trash"})
            continue
        if dry_run:
            results.append({"title": title, "status": "would add"})
            continue
        coll_keys = [coll_key]
        if p.get("topic_collection") in topics:
            coll_keys.append(p["topic_collection"])
        res = request("POST", f"/users/{uid}/items", [build_item(p, coll_keys)])
        if not res["successful"]:
            results.append({"title": title, "status": f"failed: {res['failed']}"})
            continue
        key = res["successful"]["0"]["key"]
        remember(build_item(p, coll_keys))
        children =[{"itemType": "note", "parentItem": key, "note": p.get("note_html", ""), "tags": []}]
        if aid:
            children.append({
                "itemType": "attachment", "parentItem": key, "linkMode": "linked_url",
                "title": "arXiv PDF", "url": f"https://arxiv.org/pdf/{aid}",
                "contentType": "application/pdf", "tags": [],
            })
        request("POST", f"/users/{uid}/items", children)
        results.append({
            "title": title, "status": "added", "key": key,
            "topic_collection": coll_keys[1] if len(coll_keys) > 1 else "missing or unknown key",
            "zotero_link": f"zotero://select/library/items/{key}",
            "web_link": f"https://www.zotero.org/users/{uid}/items/{key}",
        })
    print(json.dumps(results, indent=1))


def main():
    global KEY
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd = sys.argv[1]
    KEY = api_key()
    if cmd == "known":
        print(json.dumps(known(user_id(), sys.argv[2:])))
    elif cmd == "collections":
        print(json.dumps(all_collections(user_id()), indent=1))
    elif cmd == "check":
        uid = user_id()
        print(json.dumps({"userID": uid, "collection_key": ensure_collection(uid)}))
    elif cmd == "add":
        add(sys.argv[2], "--dry-run" in sys.argv)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
