# scholar-inbox-zotero

A daily Claude Code routine. Each morning it screens the Scholar Inbox digest, plus two alphaXiv searches of adjacent fields, on two tracks (**Relevance**: papers directly about your research, as described in `screening.md`; **Discovery**: ideas from adjacent fields with a mechanism that could transfer), adds the papers worth reading to Zotero with an overview note, and posts the overviews to Notion and Gmail. The screening runs in the cloud, so your Mac can be off. A small helper on the Mac then finishes each paper the way a Zotero connector + ZotMoov save would: PDF in the Drive folder, Snapshot, arXiv tags and Comment note.

- Routine: "Scholar Inbox → Zotero digest" at https://claude.ai/code/routines
- Schedule: `0 7 * * *` (07:00 UTC, which is 08:00 Amsterdam in winter and 09:00 in summer)
- Model: Opus 5.5

## Make it yours

The repo ships with the author's setup (high-dimensional Bayesian optimization) as a worked example. To adapt it:

1. **`screening.md`:** replace the parts marked `EDIT` with your field and research interests.
2. **`prompt.md` step 2:** change the two alphaXiv searches (the fixed query and the weekday rotation) to your adjacent fields.
3. **`prompt.md` step 7:** change the examples that map topics to your own Zotero collections, and the fallback root collection.
4. Change `TZ=Europe/Amsterdam` at the top of `prompt.md` to your timezone.
5. Follow [Setup](#setup-to-rebuild-from-scratch) below to create the cloud environment, connectors and routine.

## Architecture

```
 claude.ai routine (cron 0 7 * * * UTC)
        │  starts a fresh cloud sandbox, environment "Scholar-Zotero"
        ▼
 clone this repo ──► Claude reads prompt.md and follows it
        │
        ├─ Scholar Inbox MCP   (.mcp.json; token added by the network-secret proxy)
        ├─ alphaXiv connector  (2 cross-field searches; full text of every shortlisted paper)
        ├─ zotero_add.py ───► api.zotero.org (key added by the network-secret proxy)
        ├─ Notion connector    (daily page)
        └─ Gmail connector     (daily email)

 on the Mac: launchd (login, wake, hourly) ──► zotero_files.py
        ├─ export.arxiv.org    (categories, Comment)
        ├─ arxiv.org           (PDF ──► linked attachment base directory, i.e. the ZotMoov folder)
        └─ api.zotero.org      (tags, notes, linked PDF, uploaded Snapshot; key from the Keychain)
```

| File | Purpose |
|---|---|
| `screening.md` | **What** to look for and how to judge it: research interests, the two tracks, the overview format, the Relevance and Read it? scales, writing rules. Edit this when your interests change. |
| `prompt.md` | **How** the run works: sources and search queries, track limits, full-text reading, Zotero, Notion and email layout, error handling. |
| `zotero_add.py` | Zotero Web API helper used by the routine, standard library only. `check` verifies access and creates the collection if needed, `known` finds arXiv IDs already in the library or trash, `collections` lists collection paths and keys, `add` creates the items. |
| `zotero_files.py` | Mac helper. Finishes papers in the Scholar Inbox collection: arXiv category tags, Comment note, PDF and Snapshot. It only adds what's missing, so it's safe to run repeatedly. |
| `install_mac_helper.sh` | Installs the launchd job that runs `zotero_files.py` at login, after wake and hourly (`./install_mac_helper.sh remove` uninstalls it). |
| `.mcp.json` | Points the session at `https://mcp.scholar-inbox.com/mcp`. It contains no token. |
| `.claude/settings.json` | Enables the `scholar_inbox` server from `.mcp.json`. |

The routine can use only these tools: Bash, Read, Write, Glob, Grep, `scholar_inbox` `get_digest`, alphaXiv `discover_papers` and `get_paper_content`, Notion `notion-create-pages` and Gmail `send_message`. Anything else is refused. For example, it can't read, delete or label email, and it can't edit existing Notion pages.

## What happens each run

1. **Get the digest:** Scholar Inbox returns its whole daily digest (usually 9–20 papers), each with an arXiv ID, abstract and a 0–100 score. An empty digest (typically weekends) ends the run.
2. **Search alphaXiv**, because the digest stays close to your known interests. alphaXiv allows 2 searches per run, limited to papers published since the previous weekday:
   - **Fixed, every day:** sampling, search and exploration in high-dimensional spaces, across MCMC, active learning, experimental design, high-dim statistics and optimization
   - **Rotating by weekday:** Mon MCMC and sampling · Tue active learning and experimental design · Wed high-dimensional statistics · Thu derivative-free, evolutionary and trust-region optimization · Fri–Sun ML for search and exploration
3. **Merge and drop papers already handled:** candidates are merged by arXiv ID, and `zotero_add.py known <ids>` drops any already in the library **or its trash**. It reads the whole library once and matches arXiv IDs from URL, archive ID, DOI and Extra.
4. **Shortlist two tracks**, following `screening.md`. Each paper is in one track only, candidates from either source can land in either track, and the limits aren't quotas:
   - **Relevance (0–5):** Relevance *Direct*, meaning it bears on your research questions or methods
   - **Discovery (0–5):** Relevance *Potential*, meaning another field's idea with a specific mechanism that could transfer
   The Scholar Inbox score is one signal, not the selection rule.
5. **Read the full text** of every shortlisted paper from alphaXiv (contributions and results sections). For papers found through alphaXiv, this also supplies the exact title, the authors and the full abstract. If alphaXiv lacks the paper, the overview says "Based on abstract only."
6. **Write the overviews** (100–150 words): TL;DR, problem, method, key results, Relevance (Direct / Potential / Low), Read it? (Must-read / Skim / Skip, the overall research value, novelty included), and a one-line reason. A paper that turns out weak after the full-text read becomes **Skip**.
7. **Build the "Considered but skipped" list:** digest papers scoring 75 or more that weren't selected, plus shortlisted papers that fell to Skip, each with a one-line reason. They aren't added to Zotero.
8. **Add to Zotero** (Must-read and Skim only). The run lists your collections and picks a **topic collection** for each paper: the subcollection you'd file it in yourself, e.g. *High-dimensional BO* or *Constrained BO*. If nothing fits, it uses the *Bayesian Optimization* root, and it never picks *TODOs*. `zotero_add.py add /tmp/digest/papers.json` then checks again for duplicates (title and arXiv ID) and creates for each paper:
   - a **Preprint** item with the fields a connector save from arXiv has (catalog *arXiv.org*, `http://arxiv.org/abs/<id>`, arXiv DOI, archive ID), plus the score (or "Found via alphaXiv search") in *Extra*
   - placement in **Scholar Inbox** *and* the topic collection
   - manual tags `si:to-review`, the track (`si:relevance` or `si:discovery`) and the verdict (`si:must-read` or `si:skim`)
   - a child **note** with the overview
   - a placeholder link to the arXiv PDF, which the Mac helper replaces with the real file
   `zotero_add.py` refuses any paper whose verdict is Skip or whose track is unknown.
9. **Notion:** a page titled "Papers — YYYY-MM-DD" under the page given by `NOTION_PARENT_PAGE_ID`, with three sections: Relevance, Discovery, Considered but skipped. Within each track, Must-reads come first. Each paper links to arXiv and Zotero, and shows its score or "via alphaXiv".
10. **Email:** one email to `RECIPIENT_EMAIL`, subject "Paper digest YYYY-MM-DD: N must-read, M skim", with the same three sections, a short version of each overview, and a link to the Notion page.
11. **Finish:** a summary in the run log. It never commits or pushes to this repo.

A normal run takes a few minutes; reading up to 10 full texts with Opus takes longer than the old setup.

## On the Mac: finishing each paper

`zotero_files.py` runs at login, after the Mac wakes, and every hour. For each paper in *Scholar Inbox* with an arXiv ID, it adds whatever is missing:

- **arXiv category tags**, as automatic tags (e.g. *Computer Science - Machine Learning*), and the primary category in Extra (`arXiv:<id> [cs.LG]`)
- the arXiv **"Comment:" note**, when arXiv has one
- the **PDF**, saved in Zotero's *linked attachment base directory* (the folder ZotMoov moves files to). It's named like Zotero's renaming, `Author et al. - Year - Title.pdf`, with ` 1`, ` 2`, … appended if a different file already has that name, and linked as `attachments:<name>`, which is exactly what ZotMoov produces
- a **Snapshot** of the arXiv page, uploaded to Zotero storage (about 40 KB each)

It then removes the placeholder PDF link. It never touches papers outside *Scholar Inbox* unless you pass their keys (`python3 zotero_files.py ITEMKEY --dry-run`). Its log is at `~/Library/Logs/scholar-zotero-files.log`.

## What to expect

| Situation | What happens |
|---|---|
| Normal day | Zotero items, a Notion page and an email, a few minutes after 07:00 UTC; the Mac helper adds the PDFs within the hour |
| The Mac is off or asleep | Items, notes and tags arrive as usual; PDFs, Snapshots and arXiv tags follow when the Mac is next awake |
| The Drive folder is unavailable | The helper does nothing and retries next hour |
| Empty digest (likely on weekends) | Nothing: no email, no page, no alphaXiv searches |
| An alphaXiv search fails | The run continues with the other sources and says so in its summary |
| Every digest paper is already in Zotero | Nothing to report, so no email or page |
| Nothing qualifies for a track | That track is empty that day. If both are empty, the email still lists the papers considered but skipped. |
| A high-score paper isn't selected | It appears under "Considered but skipped" with a reason. To keep it, add it to Zotero yourself. |
| A shortlisted paper is weak after the full-text read | It's rated Skip, moved to the skipped list, and not added to Zotero |
| A paper is deleted in Zotero | It stays in the trash and isn't added again |
| The Zotero trash is emptied | A paper could be added again if Scholar Inbox lists it again, which is rare |
| A paper is kept | Remove `si:to-review` and file it anywhere. The routine never modifies existing items; the Mac helper only adds missing pieces to papers still in *Scholar Inbox*. |
| Scholar Inbox token expired or wrong | No Zotero changes; an email describes the error |
| Zotero key revoked or wrong | An email describes the Zotero API error |
| alphaXiv lacks the paper | The overview is written from the abstract and says so |
| Notion or Gmail fails | Not handled by `prompt.md`. The run log will show it, and papers already added stay in Zotero. |
| `screening.md` or `prompt.md` is edited | The next run follows the new version |

## Daily use

1. Read the email, or the Notion page for the full overviews.
2. In Zotero → *Scholar Inbox*, filter by `si:to-review` (and `si:must-read` to start with the essentials). Each paper is also already in its topic collection. Keep what you want (remove `si:to-review`, and remove it from *Scholar Inbox* if you like) and delete the rest.
3. To debug, open the routine at https://claude.ai/code/routines and look at the run history.

## Configuration

Personal values are kept out of this repo. They live in the routine's prompt on claude.ai, which `prompt.md` refers to by placeholder:

| Placeholder | Meaning |
|---|---|
| `RECIPIENT_EMAIL` | Where the daily email goes |
| `NOTION_PARENT_PAGE_ID` | The Notion page that the daily pages are created under |

To change either value, edit the routine's prompt, not this repo.

## Setup (to rebuild from scratch)

All of these are configured on claude.ai, not in this repo:

1. **Cloud environment** (claude.ai/code → environment selector → ⚙). This one is named `Scholar-Zotero`.
   - Network access: **Custom**, allowing `api.zotero.org` and `mcp.scholar-inbox.com`, with the default package-manager list included.
   - Network secrets (both of type Bearer token):
     - host `api.zotero.org`, value = a Zotero API key with library **and** write access (https://www.zotero.org/settings/keys)
     - host `mcp.scholar-inbox.com`, value = the Scholar Inbox MCP token
2. **Connectors** on claude.ai: alphaXiv, Notion, Gmail. Scholar Inbox is **not** a claude.ai connector: its OAuth registration fails, so the session reaches it through `.mcp.json` instead.
3. **GitHub:** the Claude GitHub App installed on your copy of this repo, so the cloud can clone it.
4. **Routine:** created through the Claude Code `/schedule` command (RemoteTrigger), using this repo, the environment above, the three connectors, and the tool allowlist listed earlier. The routine prompt is *"Read prompt.md in this repository and follow its steps exactly…"*, followed by the configuration values above.

On the Mac:

5. **Zotero API key in the Keychain**, entered without echoing: `security add-generic-password -U -s zotero-api-key -a zotero -w`
6. **Linked attachment base directory** set in Zotero (Settings → Files and Folders), the same folder ZotMoov moves files to.
7. **The helper job:** `./install_mac_helper.sh`

## Running locally

Both scripts read the key from `$ZOTERO_API_KEY` or the macOS Keychain (service `zotero-api-key`):

```sh
python3 zotero_add.py check                    # verify access, create the collection
python3 zotero_add.py known 2610.28136         # is this paper already in the library?
python3 zotero_add.py collections              # collection paths and keys
python3 zotero_add.py add papers.json --dry-run
python3 zotero_files.py --dry-run              # what the Mac helper would add
```

## Caveats

- **Daylight saving time:** cron runs in UTC, so the local run time moves by an hour twice a year.
- **Usage:** each run counts toward the Claude plan's usage. Opus and the full-text reads make each run noticeably heavier than the original Sonnet setup.
- **Secrets:** they're attached by the proxy to any request to their host. A misbehaving run could misuse them only against that host (Zotero or Scholar Inbox), and the Zotero key's write access is limited to your library.

## License

MIT, see `LICENSE`.
