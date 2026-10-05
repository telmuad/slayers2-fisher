# Slayers 2 Auto-Fisher

A Windows desktop app that fishes for you in the Roblox game **Slayers 2**. It watches your screen, plays the fishing minigame, and collects the catch:

1. **Cast:** clicks the water spot you picked.
2. **Wait:** watches for the fishing bar to appear. If no bite comes within 20 s, it casts again.
3. **Minigame:** holds and releases left-click to keep the white box inside the yellow zone.
4. **Collect:** if the "T / Collect" prompt appears, holds **T** until it goes away. Many fish go straight into your inventory with no prompt. That's normal, and the bot just casts again.
5. Waits a random 0.3–0.8 s and starts again.

> **Safety:** the rod shop next to the fishing spot shows an identical "T" prompt that says **Purchase**. The bot only presses T after it has found the word **Collect**, so it never buys the rod.

> **Use at your own risk.** This is a fan-made tool, not affiliated with Roblox or the Slayers 2 developers. Automating gameplay may be against Roblox's or a game's rules, so check that you're allowed to before using it.

It only sends input while Roblox is the focused window. The only key it ever presses is **T**. It never presses movement keys (W/A/S/D, the arrow keys or space), so it doesn't walk your character; everything else it does uses the mouse.

---

## 1. Install

### Option A: download the app (easiest)
1. Go to the [latest release](https://github.com/telmuad/slayers2-fisher/releases/latest) and download **`Slayers2Fisher-<version>-windows.zip`**.
2. **Extract the whole folder** somewhere you keep programs, such as Documents. Don't run it from inside the zip, or your settings will be lost.
3. Double-click **`Slayers 2 Fisher.exe`**.

The app isn't code-signed, so Windows may show *"Windows protected your PC"* the first time. Click **More info**, then **Run anyway**. Your settings, calibration and logs are saved in the same folder as the app.

### Option B: run from the source code
1. Install **Python 3.11 or newer** from <https://www.python.org/downloads/>. On the installer's first screen, **tick "Add python.exe to PATH"**.
2. Download this repository and double-click **`setup.bat`**. It creates a private Python environment in `.venv` and installs the requirements into it, so nothing else on your PC changes. It also puts a **Slayers 2 Fisher** shortcut on your Desktop and in this folder.
3. Start the app with that shortcut. To watch the log live in a console instead, use `run.bat`.

Run `setup.bat` again if you move the folder. To build the `.exe` yourself, run `build.bat`, which creates it in `dist/`.

---

## 2. The app

The small window stays on top and shows:
- the current state: Casting / Waiting / Minigame / Collecting / Paused
- **Minigames:** fish hooked and played
- **Collected:** catches that showed a Collect prompt and were collected with T
- **No prompt:** minigames with no Collect prompt afterwards. Usually the fish went straight into your inventory; sometimes it escaped.
- **Recasts:** casts with no bite within 20 s
- the detection fps

Its buttons:
- **Start / Pause:** the same as the start and pause hotkeys. After clicking Start, click into Roblox; the bot only acts while Roblox is focused. On first use this button says **Calibrate** instead.
- **Settings:** every setting, in tabs (General, Fishing, Minigame, Quests, Notifications, Detection). Each one has a short explanation, and wrong values are refused with a message. **Reset this tab to defaults** undoes your changes on that tab. The bot is paused while Settings is open and uses the new values as soon as you click Save.
- **Fishing / Quests:** what the bot does (see *Quest mode* below).
- **Setup:** calibration, saving the camera view, preview, the simulator, and the log and debug image folders.

| Hotkey (default) | Action |
|---|---|
| **F6** | Start / resume |
| **F7** | Pause (releases everything) |
| **F8** | Quit immediately (releases everything) |
| **Mouse to top-left corner** | Emergency stop (same as F8) |

You can change the hotkeys under **Settings → General**: click a key's button, then press the new key. F1–F24, Insert, Delete, Home, End, Page Up/Down, Pause, Scroll Lock and Num Lock can be used. The window always shows the keys in use; this README says F6 / F7 / F8.

---

## 3. Roblox settings (important!)

The bot finds things by their **position on screen**, so keep these the same between calibrating and fishing:

- **Windowed or borderless fullscreen.** Avoid exclusive fullscreen, where the bot's windows can't appear on top.
- **Don't move or resize the Roblox window** after calibrating.
- **Keep the same in-game UI scale and screen resolution.** Windows display scaling (100% / 125% / 150%) must stay the same too. If the screen changes, the app notices and asks you to calibrate again.
- **Stand in the same fishing spot.** When you press F6, the bot puts the camera back where you saved it (see *Camera keeping* below). A click only casts if it lands on water; if the cast spot ever ends up on the dock, the bot moves the click to the nearest water by itself.
- **Shift-lock off**, so the mouse cursor is free.
- **Equip your fishing rod** before starting.
- Keep the app window, and any other window that floats on top, such as a chat overlay, away from the fishing bar and the collect prompt.

---

## 4. Calibrate

Click **Calibrate** (or **Setup → Calibrate everything**). A console window opens with the instructions. While it's open, the bot is off, so pressing F6 only takes snapshots. Close the console with Ctrl+C to cancel.

**Step 1: the fishing bar**
1. In Roblox, cast your rod and wait for a bite so the fishing bar is on screen.
2. Press **F6**. A snapshot of your screen opens in a calibration window. Click on it if it's behind Roblox.
3. **Drag a box around the whole fishing bar.** Include a little water on the left and right. Press **Enter**.
4. The next screen shows what the bot detected. The bar is outlined in magenta, the target zone in yellow and the white box in green. Press **Enter** to accept or **R** to select again.
5. **Click the spot on the water where you want to cast**, then press **Enter**.

**Step 2: the collect prompt**
1. Go back to Roblox and catch a fish by hand. When the **T / Collect** prompt shows, don't press T yet. Press **F6** instead.
2. **Drag a generous box** around where the prompt can appear. The caught item can drift around and its prompt moves with it, so be generous. Press **Enter**, or press **Esc** to use the default, which is most of the screen.
3. The area is shown zoomed in. **Drag a tight box around only the white circle with the "T"** and press **Enter**.
4. **Drag a tight box around only the word "Collect"** (the small gray word under the item name) and press **Enter**. The bot won't press T without it, so it can never trigger a different prompt like the rod shop's "Purchase".
5. Check it says "Collect prompt FOUND" and press **Enter**.

You can press **F7** to skip step 2, but then the bot won't press T at all (unless the optional OCR below is set up). To do or redo only this step later, use **Setup → Redo the collect prompt**.

**Step 3: the camera view**
Set the camera the way you want the bot to keep it, with open water in front of you where the cast spot is. Then press **F6** and **don't touch the mouse for about 10 seconds.** The bot zooms fully out, looks straight down, turns a little, then comes back to your view, measuring each move as it goes.

When the console says it's done, press Enter to close it. The app picks up the new calibration by itself.

---

## 5. Fish

1. Open the app.
2. Click into Roblox and make sure the rod is equipped.
3. Press **F6** (or click Start, then click into Roblox).

After each minigame the log says how much of the time the box was in the zone, e.g. "box in the zone 97% of the time". It's the easiest way to see how well it's playing. Open it with **Setup → Open the log folder**.

If you alt-tab away, the bot pauses by itself and resumes when Roblox is focused again. Clicking the app window also takes focus away from Roblox, so avoid that while fishing.

---

## Quest mode: Angler Runo's crate quest

Instead of fishing, the bot can do Angler Runo's crate quest over and over with the fish you've caught:

1. Holds T on **Angler Runo / Chat** and clicks through his lines. For the Lv 60 quest it picks **Anything bigger?** first.
2. Accepts the quest you chose: **Ill fill your crates (Lv 45)** or **Ill land the good catch (Lv 60)**.
3. Holds T on **Fish Crate / Load** to put your fish in.
4. Talks to him again, clicks **The crate is loaded**, and clicks through his lines.
5. Waits out the 10 s quest cooldown and starts over.

**To use it:**
- Stand between Angler Runo and his crate, close enough that both his Chat prompt and the crate's Load prompt can show up. The bot never moves your character.
- Keep the quest list on the left of the screen visible. That's how the bot sees which fish are still missing.
- Switch the main window from **Fishing** to **Quests** (the button next to Setup), then press **F6** in Roblox.
- Choose the quest under **Settings → Quests**. Lv 60 is the default.

When the crate can't be filled because you're **out of fish**, it sends a Discord alert listing what's still missing (e.g. "Clown Fish: 0/1") and pauses. Every finished quest also sends a Discord message if notifications are set up (see below).

Quest mode reads the dialogue and prompts with the text recognition built into Windows 10/11, so it needs no calibration and works at any screen size. It only presses T when the prompt says **Chat** under Angler Runo's name or **Load** under the crate's name. It only clicks dialogue that is on screen. If Windows says text recognition isn't available, add English under *Windows Settings → Time & language → Language*.

---

## Discord notifications: check on it while you're away

The app can post to a Discord channel, so you can see on your phone that it's still fishing.

1. In Discord, pick a channel (a private server just for you works well). Open the channel's settings, choose **Integrations → Webhooks → New Webhook**, then **Copy Webhook URL**.
2. In the app, open **Settings → Notifications**, paste the URL and click **Test**. A test message should appear in the channel.
3. Optional: to be **@mentioned on alerts**, so your phone buzzes, paste your Discord user ID. To find it, turn on Developer Mode under Discord's *Settings → Advanced*, then right-click your name and choose *Copy User ID*.
4. Click **Save**. The app window shows "Discord on".

What it sends (each can be switched off):

| Message | Default |
|---|---|
| **Every catch**, with a close-up of the item and its prompt, and how well it played the minigame | on |
| Started / paused / stopped, with the reason (e.g. the emergency stop) | on |
| **Status update** with counts, fish hooked per hour, run time and a screenshot | every 30 min |
| Minigames without a Collect prompt | off |

**Alerts** (with the @mention) when something looks wrong:
- nothing hooked for **10 minutes** while running
- Roblox not the focused window for **5 minutes**, for example if it crashed or disconnected
- **5 casts in a row** without a bite: the cast may be missing the water, or your character moved
- the bot hit an error (always on)

Each alert is sent once until things recover, with a screenshot so you can see what's wrong. Messages are sent in the background and never slow the bot down.

> **Keep your webhook URL private.** Anyone who has it can post in that channel. It's saved only in `config.json` on your PC, which is never uploaded or included in builds. If it leaks, delete the webhook in Discord and make a new one. Screenshots show the screen Roblox is on, so they go wherever that channel's messages go.

---

## Camera keeping

Each time you press **F6** (to start, or to resume after F7), the bot checks the camera once, before its first cast. It doesn't touch the camera between catches after that. The check compares the screen with the camera view you saved (in about 0.1 s). If the view has moved, the bot resets it, which takes about 4 s:
1. Zoom fully out, and tilt to look straight down. These are the camera's limits, so they are always the same.
2. Turn until the ground below matches the saved top-down snapshot. From straight above, turning just rotates the picture, which is easy to measure.
3. Tilt back up and zoom back in by the amounts measured when you saved the view.

The bot turns the camera by dragging with the right mouse button and zooms with the mouse wheel, and only during that check. In tests it returned to within 1–6 px of the saved view, even after the camera had been turned all the way around.

- **To change the view it keeps:** set the camera how you like, choose **Setup → Save the camera view**, press F6 in Roblox, and don't touch the mouse for about 10 seconds.
- **To turn it off:** untick **Settings → General → Keep the camera on the saved view**.
- If the log keeps saying the camera can't match the saved view (for example after a big lighting change, or if you moved to another spot), save the view again.

## Preview: check detection without fishing

Choose **Setup → Preview detection** and fish **by hand**. Two windows show live what the bot sees. **No input is sent.** Press **S** to save a snapshot to `debug/`, and **Q** to quit.

The fishing-bar window has four panels:
- **frame:** magenta = bar, yellow = target zone, green = white box, cyan line = where the controller would aim. The text at the bottom says whether it would HOLD or release.
- **edges:** the bar's left side should be a red line and its right side a blue line, from top to bottom.
- **yellow:** pixels counted as the target zone. It should be one solid block.
- **white:** pixels counted as the white box. It should include a solid square.

## Debug images

Tick **Settings → General → Save debug images**. The bot then saves annotated images like the preview into the `debug/` folder while it fishes. It saves minigame frames, periodic snapshots while waiting for a bite, and images of the prompt when it's found or missed. Old images are deleted automatically after 600. Open the folder with **Setup → Open the debug image folder**.

---

## Tuning the minigame controller

These settings are on the **Settings → Minigame** tab. Positions are measured as a fraction of the bar's height, where 0 is the bottom and 1 is the top, so `0.01` means 1% of the bar.

How it works: the controller predicts where the box and the zone will be a moment from now, based on how fast they're moving. It then decides what share of the time to hold the button. 1.0 means hold constantly, 0 means release, and 0.5 means tap to hover. It feathers the click at that rate.

| Setting | Default | What it does |
|---|---|---|
| Gain | 25 | How strongly it reacts to distance from the target. Higher is snappier but twitchier. |
| Look-ahead | 0.30 s | How far ahead it predicts using the box's speed, to cover reaction time. |
| Braking | 0.2 | How much room the box needs to stop, per speed². Twice the speed needs four times the room. |
| Learn braking while playing | on | Each time it lets go of a fast-moving box, it measures how far the box actually travels before stopping. The learned value shows as `brake` in debug images. |
| Dead zone | 0.0 | Errors smaller than this are ignored, so it just hovers. |
| Hover duty | 0.5 | Share of the time to hold click to stay still. |
| Feathering period | 0.05 s | Length of one hold/release cycle while feathering. |
| Speed smoothing | 0.5 | Smooths the speed estimate. 0 = raw, 0.9 = very smooth but slow to react. |
| Target offset | 0.0 | Aim above (+) or below (−) the zone centre. |

**If the box keeps slipping out of the zone,** watch it with Preview or debug images, then change **one value at a time**:

| Symptom | Try |
|---|---|
| Overshoots on **big** moves even after a few fish (braking is learned during the first catches) | Raise Braking (0.2 → 0.3). If it keeps un-learning it, untick *Learn braking while playing*. |
| Overshoots all the time, even on small moves | Raise Look-ahead (0.30 → 0.40), or lower Gain |
| Too slow: lags behind a zone that moves | Raise Gain (25 → 40), lower Speed smoothing (0.5 → 0.3) |
| Hovers steadily but a bit **below** the centre | Raise Hover duty (0.5 → 0.6), or set Target offset to 0.02 |
| Hovers steadily but a bit **above** the centre | Lower Hover duty (0.5 → 0.4) |
| Shakes up and down around the centre | Raise Dead zone (0.01 → 0.02), or raise Feathering period |
| Falls out while fast feathering doesn't register | Raise Feathering period (0.05 → 0.08) |
| fps in the app window is below 30 | Close other heavy programs, and use a smaller bar box when calibrating |

The defaults were tuned for how the box moves in Slayers 2, as measured from recordings of the real game: top speed about 0.65 bar-heights per second and acceleration about 2 bar/s², the same going up or down. They were tested live, where the box stayed in the zone 86–100% of the time. You can try settings safely in the simulator (below) before using them in the game.

---

## Simulator: watch the bot without the game

Choose **Setup → Simulator**. A window opens where the real bot plays a simulated copy of the fishing minigame, drawn to look like Slayers 2. **Nothing is sent to Windows or Roblox.**

The window shows:
- the simulated game
- what the bot sees, with the same panels as preview mode
- the bot's state and stats, and whether it is holding the mouse or the T key
- the catch progress
- the collect prompt with its hold ring
- an event log

Keys (click the window first):
- **1–5** switch the box physics. **1** is measured from the real game (the default); 2–5 are Momentum, Floaty, Heavy and Instant.
- **− / +** make the zone slower or faster
- **P** pauses or resumes the bot
- **Q** quits

The simulator uses your Minigame settings, so you can try changes there first. From the source code you can also save a video: `python main.py --simulate --record sim.mp4 --seconds 60`.

---

## Tuning detection

These are on the **Settings → Detection** tab. Colours are in HSV: hue 0–180, saturation 0–255, brightness 0–255.

- **Bar not detected** (stuck on "Waiting" while the bar is on screen): in Preview, check the edges panel. If the lines are broken, lower *Edge brightness step* (8 → 5) or raise *Edge brightness ratio* (0.85 → 0.9). If the bar is found in Preview but only sometimes, lower *Bar edge score* (0.5 → 0.35). Recalibrating with a slightly bigger box also helps.
- **Zone not detected / patchy:** under *Target zone*, lower *Saturation min* or *Brightness min*, or widen *Hue min*–*Hue max*.
- **White box not detected**, especially while inside the zone: under *White box*, lower *Brightness min* (165 → 140) or raise *Saturation max* (90 → 120).
- **The item drifts and the bot lets go of T too early:** raise *Follow a drifting prompt within* (200 → 350). This is how far around the prompt's last spot the bot looks first, before searching the whole area.
- **Camera zoom:** the Collect prompt gets bigger or smaller as you zoom in or out, and the bot handles this automatically (0.6× to 2× the calibrated size). If you zoom very far, widen *Smallest / Largest prompt size*.
- **Box or zone found in the wrong place** (e.g. on bright fog or a lily pad behind the bar): they must be about the right size, within *Box/zone size tolerance*. Loosen it (0.4 → 0.5) if real ones get rejected.
- **Collect prompt not found:** redo **Setup → Redo the collect prompt** with tighter boxes around the T circle and the word "Collect", or lower *"Collect" match score needed* (0.65 → 0.6).
- **Collect prompt "found" when it isn't there:** raise *"Collect" match score needed*. Never untick *Only press T after finding the word "Collect"* while you're near the rod shop or any other T prompt.

### Optional: OCR fallback for the word "Collect" (source code only)
1. Install Tesseract from <https://github.com/UB-Mannheim/tesseract/wiki>.
2. Run `.venv\Scripts\python.exe -m pip install pytesseract`.
3. If Tesseract isn't on your PATH, pick `tesseract.exe` under **Settings → Detection → Tesseract program**.

---

## Fishing and timing settings

The **Settings → Fishing** tab covers casting, the minigame's time limits, collecting and the random pauses. The ones you're most likely to change:

| Setting | Default | Meaning |
|---|---|---|
| Recast if no bite after | 20 s | Recast if the bar hasn't appeared by then |
| Wait for a Collect prompt | 5 s | Some caught items drift a while before their prompt appears |
| Never hold T longer than | 5 s | Safety limit on holding T |
| Pause between steps, min / max | 0.3 / 0.8 s | Random pause between steps |
| Reel in before recasting | off | Turn on if, after a timeout, the first click reels the line in instead of casting |
| Control rate | 60 fps | Minigame control loop rate |

All settings are saved in `config.json` next to the app. You never need to edit it, but you can; anything missing from it falls back to the default.

---

## Troubleshooting

- **Nothing happens after F6:** the app window says why. "Roblox is not the focused window" means you need to click into Roblox.
- **It keeps recasting with no bites:** the cast is probably landing on the dock or on a UI element. Check the log for the "Cast at" position, and recalibrate the cast spot on open water.
- **Clicks or T don't register in Roblox:** don't run Roblox as administrator. If you must, run this app as administrator too, because Windows blocks input from a normal program to an admin one.
- **The calibration window is hidden behind Roblox:** alt-tab to it, or switch Roblox to windowed mode.
- **Hotkeys don't work:** another program may be using F6–F8. Pick other keys under Settings → General.
- **"The screen the bot was calibrated on isn't here any more":** the screen resolution or display scaling changed, or this is another PC. Click Calibrate.
- **Your antivirus complains about the .exe:** apps that read the screen and listen for hotkeys sometimes get flagged by mistake. The full source code is here, so you can check it and run it with Option B instead.
- **Something went wrong:** check the log (**Setup → Open the log folder**).

## Files

| File | Purpose |
|---|---|
| `main.py` | Entry point and command-line options |
| `ui.py` | The app window: status, Start/Pause, Setup menu |
| `settings_ui.py` | The Settings window (one line per setting) |
| `notifier.py` | Discord webhook notifications and alerts |
| `quest.py` | Quest mode (Angler Runo's crate quest) |
| `ocr.py` | Windows' built-in text recognition |
| `bot.py` | The fishing loop (state machine) |
| `detection.py` | Finds the bar, zone, white box and collect prompt |
| `controller.py` | Minigame hold/release controller |
| `camera.py` | Camera keeping |
| `capture.py` | Fast screen capture (mss) |
| `win_input.py` | Mouse and keyboard input via Windows SendInput (scan codes); T is the only key |
| `window.py` | Roblox focus check, DPI awareness, cursor position |
| `calibration.py` | Interactive calibration |
| `hotkeys.py` | Global start/pause/quit hotkeys |
| `debugging.py` | Debug images and preview mode |
| `simulator.py` | The simulated minigame |
| `config.py` | Settings and defaults (`config.json` is created on first run) |
| `setup.bat`, `make_shortcut.py` | Run-from-source setup and the windowless shortcut |
| `run.bat` | Starts the app with a console showing the log |
| `build.bat`, `build_exe.py` | Build the `.exe` and the release zip |
