# Blind regressions: protocol

**Purpose:** the planted regressions were designed by the author, so they test the gate on changes its author anticipated. Five releases written by someone else, sealed before the run, test it on changes the author did not design. This is PREREG §6, item 1.

**Who:** anyone other than the author who can read a config file. They need no ML background. Their job is to write five plausible changes, some harmful and some not, without saying which.

**Steps:**
1. **The author sends them** `configs/blind_regressions.template.toml`. The five example releases in it are only examples; they replace all of them.
2. **They write five releases** and save the file as `blind_regressions.toml`.
3. **They seal it:**
   ```
   shasum -a 256 blind_regressions.toml
   ```
   They send the author **only the hash**. The author records it in `docs/PREREG.md` before any measuring run.
4. **The author runs the gate without seeing the file.** The measuring run takes the file only as an encrypted or separately held input. See the note below.
5. **They release the file after the gate has decided.** The author checks that its SHA-256 equals the recorded hash, then reports each release: true effect, gate decision, caught or missed.

**Running without seeing it:** the simplest honest way is for the rater to upload the file to Kaggle themselves:
- as a private dataset shared with the author's account;
- or by giving the author the file in a password-protected zip whose password comes after the run.

`scripts/kaggle/run_measure.py` runs every release in `configs/blind_regressions.toml` if the file is in the bundle. It names each release `blind_<name>` and reports it beside the planted ones.
