# Mac Disk Cleanup

A local dashboard that finds what is eating your Mac's disk, explains whether each item is safe to remove, and lets you clean it up — reversibly — from a web page. Built for developer Macs: it knows about Xcode build data, simulators, device symbols, editor caches, package managers, and the private build copies left behind by AI coding agents.

Everything runs on your machine at `127.0.0.1`. No dependencies beyond Python 3.9+ — the copy that ships with macOS is enough.

## Run it

```bash
bin/cleanup
```

(`bin/cleanup` finds the newest Python 3.9+ on the Mac and runs `cleanup.py` with it — so it keeps working when Homebrew upgrades Python. `python3 cleanup.py` works too.)

That starts the server on port 7777 and opens the dashboard in your browser. Press **Scan**.

Other commands:

```bash
bin/cleanup scan            # print the findings as a table instead
bin/cleanup scan --deep     # also measure every top-level folder for the overview map
bin/cleanup auto --dry-run  # show what the scheduled cleanup would do
bin/cleanup schedule status
```

### Install it as a Mac app

```bash
bin/cleanup install-app
```

This creates **Disk Cleanup.app** in `/Applications` (with its own icon). Double-click it — or find it in Spotlight / Launchpad — and the dashboard opens in your default browser. The app is a thin launcher that runs the code from this folder, so pulling new changes updates the app too; re-run `install-app` only if you move the folder. The server it starts quits on its own 15 minutes after the last dashboard tab is closed. If a dashboard is already running, launching again just opens it.

Optional: add an alias so it is one word away in the terminal.

```bash
echo 'alias cleanup="\"$HOME/DEVELOPMENT DRIVE/GITHUB Projects/mac-disk-cleanup/bin/cleanup\""' >> ~/.zshrc
```

## How it decides what is safe

Every finding lands in one of four tiers:

| Tier | Meaning | In the UI |
|---|---|---|
| **Safe to reclaim** | Caches and build output the owning tool regenerates on its own | Preselected; one click to clean |
| **Needs a decision** | Reclaimable but loses state (a settings DB, a simulator), can't go through the Trash, or needs an app quit first | Selectable, with the condition spelled out |
| **Your files** | Looks like content you made (Downloads folders, documents) | Shown for awareness only — cannot be selected |
| **App data** | Real application data, not junk | Listed so you know it was seen |

The scanner checks which apps are running. An item whose app is open (Xcode mid-build, Cursor with its database open) is shown but locked until you quit the app and rescan.

## Cleaning

- **Move to Trash** (default) — a Finder move, so everything is recoverable until you empty the Trash. Disk space is reclaimed when the Trash is emptied; the dashboard reminds you.
- **Delete permanently** — skips the Trash. Separate red button, typed confirmation.
- A few actions have no Trash equivalent (deleting a simulator, Homebrew's cleanup, compacting a database). They are labelled *Skips Trash*.

The server only acts on item IDs from its own most recent scan. The page never sends paths, and every path is checked against an allow-list (your home folder and Claude's temp space) before anything is touched.

## Auto cleanup

The **Auto cleanup** panel installs a `launchd` agent (`~/Library/LaunchAgents/com.sandeepgs.mac-disk-cleanup.plist`) that runs `cleanup.py auto` daily or weekly at the hour you pick. It only ever:

- touches the **safe** tier,
- in the categories you ticked,
- by moving to the **Trash**,

and posts a macOS notification saying what it moved. Every run is logged in the panel. Turn the switch off to remove the agent.

## What it looks for

- **Xcode** — DerivedData (default or custom location, per project, with orphan detection), iOS/watchOS/tvOS DeviceSupport symbols, XCTestDevices clones, old Archives, the CoreDevice connection cache
- **Simulators** — size per device, booted vs idle vs unavailable, and the `containermanagerd/Dead` folder of stale app installs inside each device
- **Editors & AI tools** — Cursor / VS Code / Kiro `state.vscdb` bloat (compacted with `VACUUM`, never deleted), stacked Cursor agent CLI versions, Electron caches
- **Claude Code** — private DerivedData copies under `/private/tmp/claude-*`, with live-session and orphaned-process detection
- **Caches** — `~/Library/Caches/*`, npm, npx, pip, uv, Gradle, CocoaPods, Homebrew, Puppeteer/Playwright browsers, LM Studio models
- **Downloads** — installer images older than a week; everything else is listed as yours
- **Trash** — size when readable; otherwise a reminder (macOS hides it without Full Disk Access)

## Layout

```
cleanup.py              CLI entry point
diskcleanup/
  model.py              Finding / Action / tiers / categories
  sysinfo.py            du, df, running-app detection
  scanner.py            runs detectors in parallel, streams progress
  detectors/            one module per area (xcode, simulators, caches, apps, claude_tmp, downloads)
  actions.py            trash / delete / simctl / brew / vacuum, with path checks
  store.py              ~/.disk-cleanup/{settings,last-scan,history,runs}.json
  schedule.py           launchd agent install/remove
  auto.py               headless scheduled run + notification
  server.py             http.server API + static files
static/                 the dashboard (vanilla HTML/CSS/JS, no build step)
```

## Testing the clean flow safely

Set `DISK_CLEANUP_FIXTURE_DIR` to a folder of throwaway files; its children appear as safe items so you can exercise Trash/Delete without touching real caches.
