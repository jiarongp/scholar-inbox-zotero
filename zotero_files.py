#!/usr/bin/env python3
"""Finish Scholar Inbox papers on the Mac so they match a Zotero connector + ZotMoov save.

Usage:
  zotero_files.py [--item KEY ...] [--dry-run]

For every top-level item in the "Scholar Inbox" collection (plus any --item keys) that has an
arXiv ID, add whatever is missing:
  - arXiv category tags (automatic tags) and the primary category in the first Extra line
  - the arXiv "Comment:" note
  - the PDF, downloaded into Zotero's linked attachment base directory (the folder ZotMoov
    moves files to) as "Author et al. - Year - Title.pdf" and linked as attachments:<name>
  - a Snapshot of the arXiv page, uploaded to Zotero storage
and remove the placeholder "arXiv PDF" link the cloud routine adds. Items that are complete
are left alone, so the script is safe to run repeatedly (launchd runs it hourly).

Needs the Zotero API key in the macOS Keychain (service "zotero-api-key") and the base
directory set in Zotero (Settings → Files and Folders → Linked Attachment Base Directory).
"""
import glob
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import zotero_add as z

ARXIV_NS = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom"}
USER_AGENT = "scholar-zotero/1.0 (personal Zotero helper)"
# The names the Zotero arXiv translator gives categories, used as automatic tags.
ARXIV_CATEGORY_NAMES = {
    "cs.AI": "Computer Science - Artificial Intelligence",
    "cs.CE": "Computer Science - Computational Engineering, Finance, and Science",
    "cs.CL": "Computer Science - Computation and Language",
    "cs.CV": "Computer Science - Computer Vision and Pattern Recognition",
    "cs.DS": "Computer Science - Data Structures and Algorithms",
    "cs.IT": "Computer Science - Information Theory",
    "cs.LG": "Computer Science - Machine Learning",
    "cs.MA": "Computer Science - Multiagent Systems",
    "cs.NE": "Computer Science - Neural and Evolutionary Computing",
    "cs.RO": "Computer Science - Robotics",
    "cs.SY": "Computer Science - Systems and Control",
    "eess.SY": "Electrical Engineering and Systems Science - Systems and Control",
    "math.NA": "Mathematics - Numerical Analysis",
    "math.OC": "Mathematics - Optimization and Control",
    "math.PR": "Mathematics - Probability",
    "math.ST": "Mathematics - Statistics Theory",
    "physics.comp-ph": "Physics - Computational Physics",
    "q-bio.QM": "Quantitative Biology - Quantitative Methods",
    "stat.AP": "Statistics - Applications",
    "stat.CO": "Statistics - Computation",
    "stat.ME": "Statistics - Methodology",
    "stat.ML": "Statistics - Machine Learning",
    "stat.TH": "Statistics - Statistics Theory",
}


def base_directory():
    for prefs in glob.glob(os.path.expanduser("~/Library/Application Support/Zotero/Profiles/*/prefs.js")):
        m = re.search(r'user_pref\("extensions\.zotero\.baseAttachmentPath", "(.*)"\);', Path(prefs).read_text())
        if m:
            return Path(m.group(1).encode().decode("unicode_escape"))
    return None


def download(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def arxiv_metadata(ids):
    """{arxiv_id: {"primary", "categories", "comment"}} from the arXiv API."""
    out = {}
    for i in range(0, len(ids), 50):
        if i:
            time.sleep(3)  # arXiv asks for at most one API call every 3 seconds
        batch = ids[i:i + 50]
        xml = download("https://export.arxiv.org/api/query?max_results=100&id_list=" + ",".join(batch))
        for e in ET.fromstring(xml).findall("a:entry", ARXIV_NS):
            aid = re.sub(r"v\d+$", "", e.find("a:id", ARXIV_NS).text.rsplit("/", 1)[-1])
            comment = e.find("x:comment", ARXIV_NS)
            out[aid] = {
                "primary": e.find("x:primary_category", ARXIV_NS).get("term"),
                "categories": [c.get("term") for c in e.findall("a:category", ARXIV_NS)],
                "comment": " ".join(comment.text.split()) if comment is not None else None,
            }
    return out


def zotero_file_base(data):
    """The name Zotero's default rename format gives an attachment of this item:
    {{ firstCreator suffix=" - " }}{{ year suffix=" - " }}{{ title truncate="100" }}"""
    authors = [c for c in data.get("creators", []) if c.get("creatorType") == "author"]
    last = lambda c: c.get("lastName") or c.get("name", "")
    if len(authors) == 1:
        first_creator = last(authors[0])
    elif len(authors) == 2:
        first_creator = f"{last(authors[0])} and {last(authors[1])}"
    elif authors:
        first_creator = f"{last(authors[0])} et al."
    else:
        first_creator = ""
    year = (re.search(r"\d{4}", data.get("date", "")) or [""])[0]
    title = data.get("title", "")[:100].strip()
    name = " - ".join(part for part in (first_creator, year, title) if part)
    name = re.sub(r'[/\\?*:|"<>]', "", name)
    name = re.sub(r"[\r\n\t]+", " ", name)
    return unicodedata.normalize("NFC", name).strip()


def upload_snapshot(uid, parent_key, data, aid, dry_run):
    html = download(f"https://arxiv.org/abs/{aid}")
    filename = zotero_file_base(data) + ".html"
    if dry_run:
        return f"would upload Snapshot {filename} ({len(html)} bytes)"
    res = z.request("POST", f"/users/{uid}/items", [{
        "itemType": "attachment", "parentItem": parent_key, "linkMode": "imported_url",
        "title": "Snapshot", "url": f"https://arxiv.org/abs/{aid}",
        "accessDate": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "contentType": "text/html", "charset": "utf-8", "filename": filename, "tags": [],
    }])
    att_key = res["successful"]["0"]["key"]
    auth = z.request("POST", f"/users/{uid}/items/{att_key}/file", headers={"If-None-Match": "*"}, form={
        "md5": hashlib.md5(html).hexdigest(), "filename": filename,
        "filesize": len(html), "mtime": int(time.time() * 1000),
    })
    if not auth.get("exists"):
        body = auth["prefix"].encode() + html + auth["suffix"].encode()
        req = urllib.request.Request(auth["url"], data=body, method="POST",
                                     headers={"Content-Type": auth["contentType"]})
        urllib.request.urlopen(req, timeout=120).read()
        z.request("POST", f"/users/{uid}/items/{att_key}/file", headers={"If-None-Match": "*"},
                  form={"upload": auth["uploadKey"]})
    return f"uploaded Snapshot {filename}"


def link_pdf(uid, parent_key, data, aid, base, dry_run):
    pdf = download(f"https://arxiv.org/pdf/{aid}")
    if not pdf.startswith(b"%PDF"):
        raise RuntimeError(f"arXiv did not return a PDF for {aid}")
    # Like ZotMoov: a name taken by another file gets " 1", " 2", ... appended. The same
    # file (left by an interrupted run) is linked as is.
    stem, n = zotero_file_base(data), 0
    while True:
        name = f"{stem} {n}.pdf" if n else f"{stem}.pdf"
        target = base / name
        if not target.exists() or target.read_bytes() == pdf:
            break
        n += 1
    if dry_run:
        return f"would {'link existing' if target.exists() else 'save'} {name} ({len(pdf)} bytes)"
    if not target.exists():
        target.write_bytes(pdf)
    z.request("POST", f"/users/{uid}/items", [{
        "itemType": "attachment", "parentItem": parent_key, "linkMode": "linked_file",
        "title": name, "path": f"attachments:{name}", "contentType": "application/pdf", "tags": [],
    }])
    return f"linked {name}"


def finish_item(uid, item, meta, base, dry_run):
    key, data = item["key"], item["data"]
    aid = z.ARXIV_ID.search(data.get("archiveID", "") + " " + data.get("url", "")).group(0)
    children = z.request("GET", f"/users/{uid}/items/{key}/children", params={"limit": 100})
    atts = [c["data"] for c in children if c["data"]["itemType"] == "attachment"]
    notes = [c["data"] for c in children if c["data"]["itemType"] == "note"]
    done = []

    # Tags and Extra, in one PATCH of the parent.
    tags = data.get("tags", [])
    names = {t["tag"] for t in tags}
    new_tags = [{"tag": ARXIV_CATEGORY_NAMES[c], "type": 1} for c in meta.get("categories", [])
                if c in ARXIV_CATEGORY_NAMES and ARXIV_CATEGORY_NAMES[c] not in names]
    # The routine's own tags are manual tags, as on papers saved by hand.
    fixed_tags = [{"tag": t["tag"]} if t["tag"].startswith("si:") else t for t in tags]
    extra_lines = (data.get("extra") or "").split("\n")
    extra = data.get("extra") or ""
    if meta.get("primary") and not extra_lines[0].startswith(f"arXiv:{aid} ["):
        rest = [l for l in extra_lines if l and not l.startswith("arXiv:")]
        extra = "\n".join([f"arXiv:{aid} [{meta['primary']}]"] + rest)
    changes = [label for label, changed in (
        (f"+{len(new_tags)} arXiv category tags", new_tags),
        ("si: tags made manual", fixed_tags != tags),
        ("primary category added to Extra", extra != (data.get("extra") or ""))) if changed]
    if changes:
        if not dry_run:
            z.request("PATCH", f"/users/{uid}/items/{key}", {"tags": fixed_tags + new_tags, "extra": extra},
                      headers={"If-Unmodified-Since-Version": str(item["version"])})
        done += changes

    if meta.get("comment") and not any(re.sub("<[^>]+>", "", n["note"]).startswith("Comment:") for n in notes):
        if not dry_run:
            z.request("POST", f"/users/{uid}/items", [{
                "itemType": "note", "parentItem": key, "tags": [],
                "note": f'<div class="zotero-note znv1">Comment: {meta["comment"]}</div>'}])
        done.append("Comment note")

    has_pdf = any(a.get("contentType") == "application/pdf" and a.get("linkMode") != "linked_url" for a in atts)
    if not has_pdf:
        done.append(link_pdf(uid, key, data, aid, base, dry_run))
    if not any(a.get("contentType") == "text/html" and a.get("linkMode") == "imported_url" for a in atts):
        done.append(upload_snapshot(uid, key, data, aid, dry_run))

    for a in atts:
        if a.get("linkMode") == "linked_url" and a.get("title") == "arXiv PDF" and (has_pdf or not dry_run):
            if not dry_run:
                z.request("DELETE", f"/users/{uid}/items/{a['key']}",
                          headers={"If-Unmodified-Since-Version": str(a["version"])})
            done.append("removed arXiv PDF link")
    return done


def main():
    dry_run = "--dry-run" in sys.argv
    extra_keys = [a for a in sys.argv[1:] if not a.startswith("--")]
    z.KEY = z.api_key()
    if not z.KEY:
        sys.exit("No Zotero API key in the Keychain (service 'zotero-api-key').")
    base = base_directory()
    if not base or not base.is_dir():
        sys.exit(f"Linked attachment base directory not available: {base}")
    uid = z.user_id()
    inbox = z.ensure_collection(uid)
    items, start = [], 0
    while True:
        page = z.request("GET", f"/users/{uid}/collections/{inbox}/items/top",
                         params={"limit": 100, "start": start})
        items += page
        if len(page) < 100:
            break
        start += 100
    seen = {i["key"] for i in items}
    items += [z.request("GET", f"/users/{uid}/items/{k}") for k in extra_keys if k not in seen]

    def arxiv_id(i):
        m = z.ARXIV_ID.search(i["data"].get("archiveID", "") + " " + i["data"].get("url", ""))
        return m.group(0) if m else None

    items = [i for i in items if i["data"].get("itemType") != "note" and arxiv_id(i)]
    meta = arxiv_metadata(sorted({arxiv_id(i) for i in items})) if items else {}
    report = {}
    for i in items:
        try:
            done = finish_item(uid, i, meta.get(arxiv_id(i), {}), base, dry_run)
        except (Exception, SystemExit) as e:  # keep going; the next run retries
            done = [f"error: {e}"]
        if done:
            report[i["data"]["title"][:70]] = done
    print(json.dumps({"checked": len(items), "changed": report}, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
