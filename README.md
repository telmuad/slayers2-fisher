# Slayers 2 Auto-Fisher

A Windows desktop app that fishes for you in the Roblox game **Slayers 2**. It watches your screen, plays the fishing minigame, and collects the catch:

1. **Cast:** clicks the water spot you picked.
2. **Wait:** watches for the fishing bar to appear. If no bite comes within 20 s, it casts again.
3. **Minigame:** holds and releases left-click to keep the white box inside the yellow zone.
4. **Collect:** if the "T / Collect" prompt appears, holds **T** until it goes away. Many fish go straight into your inventory with no prompt. That's normal, and the bot just casts again.

> **Safety:** the rod shop next to the fishing spot shows an identical "T" prompt that says **Purchase**. The bot only presses T after it has found the word **Collect**, so it never buys the rod.
5. Waits a random 0.3–0.8 s and starts again.

> **Use at your own risk.** This is a fan-made tool, not affiliated with Roblox or the Slayers 2 developers. Automating gameplay may be against Roblox's or a game's rules, so check that you're allowed to before using it.

It only sends input while Roblox is the focused window. The only key it ever presses is **T**. It never presses movement keys (W/A/S/D, the arrow keys or space), so it doesn't walk your character; everything else it does uses the mouse.

---

## 1. Setup (one time)

### Install Python
1. Download **Python 3.11 or newer** from <https://www.python.org/downloads/>.
2. Run the installer. **Tick "Add python.exe to PATH"** at the bottom of the first screen, then click *Install Now*.
3. Open a new Command Prompt and check it worked:
   ```
   python --version
   ```
   If this opens the Microsoft Store instead, Python isn't on PATH. Reinstall and tick the box.

### Run setup
Double-click **`setup.bat`**. It:
- creates a private Python environment in the `.venv` folder
- installs the requirements into it, so nothing else on your PC changes
- creates the **Slayers 2 Fisher** shortcut in this folder and on your Desktop

Run it again any time, for example after moving this folder. If you'd rather do it by hand, run `python -m pip install -r requirements.txt`, then `python make_shortcut.py`.

### Settings that depend on your PC
Nothing in the bot is tied to one computer. Everything that is lives in `config.json` and `templates/`, which are created on your PC:
- **Calibration** (section 3): where the fishing bar, cast spot and collect prompt are on your screen. It's in screen pixels, so it only fits the screen it was made on. If you start the bot on a different screen size, display scaling or PC, it notices and asks you to calibrate again.
- **Hotkeys:** F6 / F7 / F8 by default. To change them, edit the `"hotkeys"` section of `config.json`, for example `"start": "f9"`. You can use f1–f24, insert, delete, home, end, page_up, page_down, pause, scroll_lock, num_lock or print_screen.
- **Roblox window:** `"window"` lists the Roblox program names the bot looks for. The defaults cover the normal Roblox player and the Microsoft Store version.

If you share the bot, leave out `config.json` and `templates/`, because they only fit your screen. The included `.gitignore` already skips them.

---

## 2. Roblox settings (important!)

The bot finds things by their **position on screen**, so keep these the same between calibrating and fishing:

- **Windowed or borderless fullscreen.** Avoid exclusive fullscreen, where the bot's windows can't appear on top.
- **Don't move or resize the Roblox window** after calibrating.
- **Keep the same in-game UI scale and screen resolution.** Windows display scaling (100% / 125% / 150%) must stay the same too.
- **Stand in the same fishing spot.** When you press F6, the bot puts the camera back where you saved it (see *Camera keeping* below). A click only casts if it lands on water; if the cast spot ever ends up on the dock, the bot moves the click to the nearest water by itself.
- **Shift-lock off**, so the mouse cursor is free.
- **Equip your fishing rod** before starting.
- Keep the little status window, and any other window that floats on top, such as a chat overlay, away from the fishing bar and the collect prompt.

If you change any of these, calibrate again.

---

## 3. Calibrate

Double-click **`calibrate.bat`**, or run `python main.py --calibrate`. Calibration also runs automatically the first time you start the bot. Follow the prompts in the console.

**Step 1: the fishing bar**
1. In Roblox, cast your rod and wait for a bite so the fishing bar is on screen.
2. Press **F6**. A snapshot of your screen opens in a calibration window. Click on it if it's behind Roblox.
3. **Drag a box around the whole fishing bar.** Include a little water on the left and right. Press **Enter**.
4. The next screen shows what the bot detected. The bar is outlined in magenta, the target zone in yellow and the white box in green. Press **Enter** to accept or **R** to select again.
5. **Click the spot on the water where you want to cast**, then press **Enter**.

**Step 2: the collect prompt**
1. Go back to Roblox and catch a fish by hand. When the **T / Collect** prompt shows, don't press T yet. Press **F6** instead.
2. **Drag a generous box** around where the prompt can appear. The caught item can drift around and its prompt moves with it, so be generous. Press **Enter**, or press **Esc** to use the default, which is most of the screen.
3. The area is shown zoomed in. **Drag a tight box around only the white circle with the "T"** and press **Enter**. This is saved as `templates/collect_t.png`.
4. **Drag a tight box around only the word "Collect"** (the small gray word under the item name) and press **Enter**. This is saved as `templates/collect_word.png`. The bot won't press T without it, so it can never trigger a different prompt like the rod shop's "Purchase".
5. Check it says "Collect prompt FOUND" and press **Enter**.

**Step 3: the camera view**
Set the camera the way you want the bot to keep it, with open water in front of you where the cast spot is. Then press **F6** and **don't touch the mouse for about 10 seconds.** The bot zooms fully out, looks straight down, turns a little, then comes back to your view, measuring each move as it goes.

You can press **F7** to skip step 2, but then the bot won't press T at all (unless the optional OCR below is set up). Everything else still works, and catches that need collecting will be left uncollected. To do or redo only step 2 later, run `python main.py --calibrate-collect`.

Everything is saved in `config.json`, so you only calibrate once.

---

## 4. Fish

1. Double-click the **Slayers 2 Fisher** shortcut, which `setup.bat` put on your Desktop and in this folder. It starts the bot with just the small status window and no terminal. Everything is still logged to `logs/fishing_bot.log`, and any problem pops up as a message box. If you'd rather watch the log live, use **`run.bat`** instead, which also opens a terminal.
2. Click into Roblox and make sure the rod is equipped.
3. Press **F6** to start.

| Key | Action |
|---|---|
| **F6** | Start / resume |
| **F7** | Pause (releases everything) |
| **F8** | Quit immediately (releases everything) |
| **Mouse to top-left corner** | Emergency stop (same as F8) |

These are the defaults. You can change the keys in the `"hotkeys"` section of `config.json` (see *Settings that depend on your PC*), and the status window always shows the keys in use. The rest of this README says F6 / F7 / F8.

The status window (always on top) shows:
- the current state: Casting / Waiting / Minigame / Collecting / Paused
- **Minigames**: fish hooked and played
- **Collected**: catches that showed a Collect prompt and were collected with T
- **No prompt**: minigames with no Collect prompt afterwards. Usually the fish went straight into your inventory; sometimes it escaped.
- **Recasts**: casts with no bite within 20 s
- the detection fps

After each minigame the log says how much of the time the box was in the zone, e.g. "box in the zone 97% of the time". It's the easiest way to see how well it's playing.

If you alt-tab away, the bot pauses by itself and resumes when Roblox is focused again. Clicking the status window also takes focus away from Roblox, so avoid that while fishing.

---

## Camera keeping

Each time you press **F6** (to start, or to resume after F7), the bot checks the camera once, before its first cast. It doesn't touch the camera between catches after that. The check compares the screen with the camera view you saved (in about 0.1 s). If the view has moved, the bot resets it, which takes about 4 s:
1. Zoom fully out, and tilt to look straight down. These are the camera's limits, so they are always the same.
2. Turn until the ground below matches the saved top-down snapshot. From straight above, turning just rotates the picture, which is easy to measure.
3. Tilt back up and zoom back in by the amounts measured when you saved the view.

The bot turns the camera by dragging with the right mouse button and zooms with the mouse wheel, and only during that check. In tests it returned to within 1–6 px of the saved view, even after the camera had been turned all the way around.

- **To change the view it keeps:** set the camera how you like, double-click **`save-camera.bat`** (or run `python main.py --save-camera`), press F6 in Roblox, and don't touch the mouse for about 10 seconds.
- **To turn it off:** set `"camera": {"enabled": false}` in `config.json`.
- If the log keeps saying the camera can't match the saved view (for example after a big lighting change, or if you moved to another spot), save the view again.

## 5. Check detection without fishing: preview mode

Double-click **`preview.bat`** (`python main.py --preview`) and fish **by hand**. Two windows show live what the bot sees. **No input is sent.** Press **S** to save a snapshot to `debug/`, and **Q** to quit.

The fishing-bar window has four panels:
- **frame:** magenta = bar, yellow = target zone, green = white box, cyan line = where the controller would aim. The text at the bottom says whether it would HOLD or release.
- **edges:** the bar's left side should be a red line and its right side a blue line, from top to bottom.
- **yellow:** pixels counted as the target zone. It should be one solid block.
- **white:** pixels counted as the white box. It should include a solid square.

## 6. Debug mode

Run `python main.py --debug`, or set `"debug": {"enabled": true}` in `config.json`. The bot then saves annotated images like the preview into the `debug/` folder while it fishes. It saves minigame frames, periodic snapshots while waiting for a bite, and images of the prompt when it's found or missed. Old images are deleted automatically after 600.

Everything that happens is also logged to `logs/fishing_bot.log`.

---

## 7. Tuning the minigame controller

These settings live in the `"controller"` section of `config.json`. Positions are measured as a fraction of the bar's height, where 0 is the bottom and 1 is the top, so `0.01` means 1% of the bar.

How it works: the controller predicts where the box and the zone will be a moment from now, based on how fast they're moving. It then decides what share of the time to hold the button. 1.0 means hold constantly, 0 means release, and 0.5 means tap to hover. It feathers the click at that rate.

| Setting | Default | What it does |
|---|---|---|
| `gain` | 25 | How strongly it reacts to distance from the target. Higher is snappier but twitchier. |
| `prediction_s` | 0.30 | How far ahead (in seconds) it predicts using the box's speed, to cover reaction time. |
| `braking` | 0.2 | How much room the box needs to stop, per speed². Twice the speed needs four times the room. |
| `auto_braking` | true | Learns `braking` while playing. Each time it lets go of a fast-moving box, it measures how far the box actually travels before stopping. The learned value shows as `brake` in debug images. |
| `dead_zone` | 0.0 | Errors smaller than this are ignored, so it just hovers. |
| `hover_duty` | 0.5 | Share of the time to hold click to stay still. |
| `pwm_period_s` | 0.05 | Length of one hold/release cycle while feathering. |
| `velocity_smoothing` | 0.5 | Smooths the speed estimate. 0 = raw, 0.9 = very smooth but slow to react. |
| `target_offset` | 0.0 | Aim above (+) or below (−) the zone centre. |

**If the box keeps slipping out of the zone,** run `--preview` or `--debug`, look at what it does, then change **one value at a time**:

| Symptom | Try |
|---|---|
| Overshoots on **big** moves even after a few fish (braking is learned during the first catches) | Raise `braking` (0.2 → 0.3). If it keeps un-learning it, set `auto_braking` to false. |
| Overshoots all the time, even on small moves | Raise `prediction_s` (0.30 → 0.40), or lower `gain` |
| Too slow: lags behind a zone that moves | Raise `gain` (25 → 40), lower `velocity_smoothing` (0.5 → 0.3) |
| Hovers steadily but a bit **below** the centre | Raise `hover_duty` (0.5 → 0.6), or set `target_offset` to 0.02 |
| Hovers steadily but a bit **above** the centre | Lower `hover_duty` (0.5 → 0.4) |
| Shakes up and down around the centre | Raise `dead_zone` (0.01 → 0.02), or raise `pwm_period_s` |
| Falls out while fast feathering doesn't register | Raise `pwm_period_s` (0.05 → 0.08) |
| fps in the status window is below 30 | Close other heavy programs, and use a smaller bar box when calibrating |

Save `config.json` and restart the bot after each change.

The defaults were tuned for how the box moves in Slayers 2, as measured from recordings of the real game: top speed about 0.65 bar-heights per second and acceleration about 2 bar/s², the same going up or down. They were tested live, where the box stayed in the zone 86–100% of the time. You can try settings safely in the simulator (below) before using them in the game.

---

## Simulator: watch the bot without the game

Double-click **`simulate.bat`**, or run `python main.py --simulate`. A window opens where the real bot plays a simulated copy of the fishing minigame, drawn to look like Slayers 2. **Nothing is sent to Windows or Roblox.**

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

The simulator uses the controller settings from your `config.json`, so you can try tuning changes there first. To save a video instead of opening a window, run `python main.py --simulate --record sim.mp4 --seconds 60`.

---

## 8. Tuning detection

The colour settings are in the `"detection"` section of `config.json`. Colours are in OpenCV HSV: hue 0–180, saturation 0–255, brightness 0–255.

- **Bar not detected** (stuck on "Waiting" while the bar is on screen): in preview, check the edges panel. If the lines are broken, lower `edge_min_step` (8 → 5) or raise `edge_max_ratio` (0.85 → 0.9). If the bar is found in preview but only sometimes, lower `bar_min_edge_score` (0.5 → 0.35). Recalibrating with a slightly bigger box also helps.
- **Zone not detected / patchy:** lower `zone_s_min` or `zone_v_min`, or widen `zone_h_min`–`zone_h_max`.
- **White box not detected**, especially while inside the zone: lower `box_v_min` (165 → 140) or raise `box_s_max` (90 → 120).
- **The item drifts and the bot lets go of T too early:** raise `prompt_follow_px` (200 → 350). This is how far around the prompt's last spot the bot looks first, before searching the whole area.
- **Camera zoom:** the Collect prompt gets bigger or smaller as you zoom in or out, and the bot handles this automatically (0.6× to 2× the calibrated size). If you zoom very far, widen `prompt_scale_min` / `prompt_scale_max`.
- **Box or zone found in the wrong place** (e.g. on bright fog or a lily pad behind the bar): they must be about the right size, `box_size_frac` of the bar's width and `zone_height_frac` of its height, within `size_tolerance`. Loosen `size_tolerance` (0.4 → 0.5) if real ones get rejected.
- **Collect prompt not found:** redo `--calibrate-collect` with tighter boxes around the T circle and the word "Collect", or lower `word_threshold` (0.65 → 0.6).
- **Collect prompt "found" when it isn't there:** raise `word_threshold`. Never set `require_collect_word` to false while you're near the rod shop or any other T prompt.

### Optional: OCR fallback for the word "Collect"
1. Install Tesseract from <https://github.com/UB-Mannheim/tesseract/wiki>.
2. Run `python -m pip install pytesseract`.
3. If Tesseract isn't on your PATH, set `"tesseract_cmd": "C:/Program Files/Tesseract-OCR/tesseract.exe"` in `config.json`.

---

## 9. Other settings (`"timing"` in config.json)

| Setting | Default | Meaning |
|---|---|---|
| `bite_timeout_s` | 20 | Recast if the bar hasn't appeared by then |
| `minigame_end_grace_s` | 0.5 | The bar must be gone this long to count as over |
| `collect_appear_timeout_s` | 5 | How long to wait for a Collect prompt after a catch (some items drift a while before theirs appears) |
| `collect_max_hold_s` | 5 | Never hold T longer than this |
| `delay_min_s` / `delay_max_s` | 0.3 / 0.8 | Random pause between steps |
| `reel_in_before_recast` | false | Set to true if, after a timeout, the first click reels the line in instead of casting |
| `control_fps` | 60 | Minigame control loop rate |

---

## 10. Troubleshooting

- **Nothing happens after F6:** the status window says why. "Roblox is not the focused window" means you need to click into Roblox.
- **It keeps recasting with no bites:** the cast is probably landing on the dock or on a UI element. Check the log for the "Cast at" position, and recalibrate the cast spot on open water.
- **Clicks or T don't register in Roblox:** don't run Roblox as administrator. If you must, run this bot as administrator too, because Windows blocks input from a normal program to an admin one.
- **The calibration window is hidden behind Roblox:** alt-tab to it, or switch Roblox to windowed mode.
- **Hotkeys don't work:** another program may be using F6–F8. Pick other keys in the `"hotkeys"` section of `config.json`. Also check that the console shows no errors.
- **"The screen the bot was calibrated on isn't here any more":** the screen resolution or display scaling changed, or this is another PC. Double-click `calibrate.bat`.
- **Something went wrong:** check `logs/fishing_bot.log`.

## Files

| File | Purpose |
|---|---|
| `main.py` | Entry point and command-line options |
| `bot.py` | The fishing loop (state machine) |
| `detection.py` | Finds the bar, zone, white box and collect prompt |
| `controller.py` | Minigame hold/release controller |
| `capture.py` | Fast screen capture (mss) |
| `win_input.py` | Mouse and keyboard input via Windows SendInput (scan codes) |
| `window.py` | Roblox focus check, DPI awareness, cursor position |
| `calibration.py` | Interactive calibration |
| `ui.py` | Status window |
| `hotkeys.py` | Global start/pause/quit hotkeys (set in `config.json`) |
| `setup.bat` | One-time setup: `.venv`, requirements, shortcuts |
| `make_shortcut.py` | Creates the windowless shortcut for this PC |
| `debugging.py` | Debug images and preview mode |
| `config.py` | Settings and defaults (`config.json` is created on first run) |
