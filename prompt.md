You are running unattended as a daily paper-digest job in a cloud session. Your working directory is the `scholar-inbox-zotero` repo. Get today's date and weekday with `TZ=Europe/Amsterdam date '+%F %A'` (call them DATE and WEEKDAY). Write scratch files to `/tmp/digest/`. The routine prompt gives values for the placeholders `RECIPIENT_EMAIL` and `NOTION_PARENT_PAGE_ID`. If either is missing, stop and report it.

**First read `screening.md` in full.** It defines my research interests, the two tracks, the per-paper overview format, and the writing rules. Every judgment below follows it.

## Steps

1. **Scholar Inbox.** Call the Scholar Inbox `get_digest` tool (MCP server `scholar_inbox`, from the repo's `.mcp.json`) with no dates and `top_k: 60`. It returns the whole daily digest, usually 9–20 papers. If it returns no papers (typically weekends), stop and do nothing else. If the tool is unavailable or returns an auth error, skip to step 9 and email the error. The likely cause is that the `mcp.scholar-inbox.com` network secret is missing or the token expired.

2. **alphaXiv searches.** Make exactly two calls to the alphaXiv `discover_papers` tool, both with `prioritize: "recency"`, `difficulty: 5`, and `published_after` set to the previous weekday (DATE − 1 day; on Monday, DATE − 3 days).
   - **Fixed search, every day:** question "New methods for sampling, search or exploration in high-dimensional spaces from MCMC, active learning, experimental design, high-dimensional statistics or optimization", keywords `["MCMC", "active learning", "experimental design", "high-dimensional", "sparse perturbations", "effective dimensionality"]`.
   - **Rotating search, by WEEKDAY:**
     | WEEKDAY | question | keywords |
     |---|---|---|
     | Monday | New MCMC and sampling methods for high-dimensional distributions | `["MCMC", "sampling", "high-dimensional"]` |
     | Tuesday | New active learning and experimental design methods | `["active learning", "experimental design", "acquisition"]` |
     | Wednesday | New results in high-dimensional statistics on sparsity and effective dimensionality | `["high-dimensional statistics", "sparsity", "effective dimensionality"]` |
     | Thursday | New derivative-free, evolutionary and trust-region optimization methods | `["derivative-free optimization", "evolutionary", "trust region"]` |
     | Friday, Saturday, Sunday | New machine learning methods for search and exploration in large spaces | `["exploration", "search", "machine learning"]` |
   If a search fails, continue with what you have and mention it in the summary.

3. **Merge and drop known papers.** Combine the digest and the search results into one candidate list, merging duplicates by arXiv ID. Keep the Scholar Inbox score where there is one; alphaXiv-only papers have no score. Run `python3 zotero_add.py known <arxiv_id> <arxiv_id> ...` with all candidate arXiv IDs, and drop the IDs it prints: they're already in my library or trash.

4. **Shortlist two tracks** from titles and abstracts (snippets, for alphaXiv results). Each paper goes in at most one track, and candidates from either source can go in either track:
   - **Relevance** (category `"relevance"`, up to 5): Relevance Direct, per `screening.md`.
   - **Discovery** (category `"discovery"`, up to 5): Relevance Potential, each with a specific mechanism that could transfer.
   These are limits, not quotas. If nothing qualifies for a track, leave it empty. The Scholar Inbox score is one signal, not the selection rule.

5. **Read the full text** of every shortlisted paper with the alphaXiv `get_paper_content` tool, using `https://arxiv.org/abs/<arxiv_id>`. The result is often too large to show and is saved to a file. In that case, read the file's introduction, contribution list and experiments/results sections, so the overview can quote real numbers. For alphaXiv-only papers, also take the exact title, the author names and the full abstract from the paper text. If it fails, use what you have and say "Based on abstract only."

6. **Write the overviews and the skipped list.** Write each shortlisted paper's overview in the format of `screening.md` (TL;DR, Problem, Method, Key results, Relevance, Read it?, reason). After the full-text read, a paper may fall to **Skip**. Skip papers don't go to Zotero. The "Considered but skipped" list contains digest papers with `ranking_score >= 75` that weren't selected, plus any shortlisted papers downgraded to Skip. Give each one line saying why it was passed over.

7. **Add to Zotero.** First run `python3 zotero_add.py collections` to see my collections as `{key, path}`. Choose a `topic_collection` for each selected paper: the subcollection where I'd file it myself. For example:
   - trust-region or other high-dimensional BO → `Bayesian Optimization / High-dimensional BO`
   - constraints → `… / Constrained BO`; multiple objectives → `… / Multi-objective BO`; batches → `… / Parallel BO`
   - tuning or pre-training BO across tasks → `… / Meta-learning BO`; BO with LLMs → `… / LLMs`
   - MCMC or approximate inference → `… / Probabilistic Inference`
   If nothing fits, use the `Bayesian Optimization` root. Never choose `Scholar Inbox` or anything under `TODOs`.
   Write the selected papers (verdict Must-read or Skim) to `/tmp/digest/papers.json` as a JSON list with fields
   `arxiv_id, title, authors, abstract, url, publication_date, ranking_score, source, category, verdict, topic_collection, reason, note_html`.
   - `topic_collection` is the chosen collection's key.
   - `source` is `"scholar-inbox"` or `"alphaxiv"`. Use `ranking_score: null` for alphaXiv-only papers.
   - `category` is `"relevance"` or `"discovery"`; `verdict` is `"must-read"` or `"skim"`.
   - `abstract` is the full, unshortened abstract. Build the file with a short Python script that loads the data rather than retyping it where you can.
   - `note_html` is the overview as simple HTML (`<h2>`, `<p>`, `<ul><li>`, `<b>`), starting with `<h2>Overview (Claude, DATE)</h2>`.
   Then run `python3 zotero_add.py add /tmp/digest/papers.json`. It prints one result per paper, with a `web_link` and the `topic_collection` used for each one added. Don't fetch PDFs, snapshots or arXiv categories yourself: a helper on my Mac adds them. If the script exits with a Zotero API error, go to step 9 and email the error. If no papers were selected and the skipped list is empty, stop.

8. **Notion.** Create a page with the Notion `notion-create-pages` tool, parent `{"type":"page_id","page_id":"<NOTION_PARENT_PAGE_ID>"}`, `allow_async: false`, title `Papers — DATE`. It has three sections, in this order: **Relevance**, **Discovery**, **Considered but skipped**. Within each track, rank by expected research value (Must-reads first). Each selected paper gets a `###` heading with its title, a line with `Must-read`/`Skim` · authors · score (or "via alphaXiv") · Zotero collection (the last part of its path) · [arXiv](abs link) · [Zotero](web_link), and the full overview as Markdown bullets. Skipped papers get one bullet each: title linked to arXiv, score, and the one-line reason. Use plain Markdown only (headings, bullets, bold, links).

9. **Email.** Send one email with the Gmail `send_message` tool to `RECIPIENT_EMAIL`, subject `Paper digest DATE: N must-read, M skim`, using `htmlBody`. Use the same three sections as the Notion page, with compact overviews for the selected papers (TL;DR + Relevance + Read it?). Each paper links to arXiv and shows its score or "via alphaXiv". Put a link to the Notion page at the top. Add a footer: "Selected papers are in Zotero → Scholar Inbox, tagged si:to-review plus their track and verdict. Delete the ones you don't want; they won't be re-added unless you empty the trash."

10. Don't commit or push anything to the repo. Finish with a one-paragraph summary of what you did, including which searches ran and any failures.
