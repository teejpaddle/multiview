# Show Multiview: Beginner Setup Guide

This guide takes you from a Windows PC with nothing installed to a working multiview. You don't need any computer experience. Do the parts in order, and finish each step before starting the next.

**What you are setting up:** one screen on your show computer that shows the Center Screen, the Side Screens, the PTZ camera, a clock, a countdown and audio meters. Each picture has a colored border that tells you if it is working.

**Is it safe for the show?** The multiview only watches copies of your video. If it crashes or you close it, the projectors keep playing.

> **Do the setup on a day with no show.** Allow about two hours, and do not change anything in Resolume while an audience is watching.

## Contents

| Part | What you will do |
|---|---|
| [1](#part-1-learn-three-basic-skills) | Learn three basic skills |
| [2](#part-2-check-your-computer) | Check your computer |
| [3](#part-3-prepare-windows) | Prepare Windows |
| [4](#part-4-install-python-and-vlc) | Install Python and VLC |
| [5](#part-5-set-up-the-camera) | Set up the camera |
| [6](#part-6-set-up-resolume) | Set up Resolume |
| [7](#part-7-download-and-install-the-multiview) | Download and install the multiview |
| [8](#part-8-enter-your-settings) | Enter your settings |
| [9](#part-9-run-the-automatic-check) | Run the automatic check |
| [10](#part-10-start-the-multiview-for-the-first-time) | Start the multiview for the first time |
| [11](#part-11-do-a-full-rehearsal) | Do a full rehearsal |
| [12](#part-12-show-day-routine) | **Show day routine** (use this every show) |
| [13](#part-13-how-to-read-and-use-the-screen) | How to read and use the screen |
| [14](#part-14-if-something-goes-wrong) | If something goes wrong |

## What you need

- The Windows show computer, with your administrator password if it has one
- An internet connection (only needed during setup)
- Resolume, already installed, with your show file
- The PTZOptics camera, powered on and plugged into the network
- A monitor for the multiview
- Paper and a pen

### Your settings sheet

Copy this table onto paper. You will fill it in as you go.

| Item | Write it here | Found in |
|---|---|---|
| Camera address (looks like `192.168.100.88`) | | Part 5 |
| Camera stream link (starts with `rtsp://`) | | Part 5 |
| Center sender name | | Part 8 |
| Side sender name | | Part 8 |
| Sound device name | | Part 8 |
| Multiview monitor x and y | | Part 8 |

---

## Part 1: Learn three basic skills

### Skill 1: Open PowerShell

PowerShell is a window where you type instructions for the computer.

1. Press the **Windows key** on your keyboard. It has the Windows logo on it.
2. Type `powershell`.
3. Press **Enter**.

A window with a dark background and some text opens.

### Skill 2: Run a command

A **command** is a line of text in a gray box in this guide, like this:

```powershell
Get-Date
```

1. Hover over the gray box and click the copy icon in its corner. If there isn't one, drag across the text to select it and press **Ctrl + C**.
2. **Right-click** inside the PowerShell window. This pastes the text.
3. Press **Enter**.
4. Wait until a new line starting with `PS` appears. That means it has finished.

Run one command at a time. **Red text usually means something went wrong.** Stop and look in [Part 14](#part-14-if-something-goes-wrong).

### Skill 3: Open Settings

Press the **Windows key + I** together. The Windows Settings window opens.

---

## Part 2: Check your computer

### Step 1: Check your Resolume edition

1. Open Resolume.
2. Look at the title at the top of the window, or click **Help** then **About**.
3. See whether it says **Arena** or **Avenue**.

- **Arena:** continue to Step 2.
- **Avenue:** stop here. This setup needs a feature that may only be in Arena, and the alternative method has not been built yet.

### Step 2: Count your graphics cards

1. Press **Ctrl + Shift + Esc** to open Task Manager.
2. If you see a small window, click **More details**.
3. Click the **Performance** tab.
4. Count the entries whose names start with **GPU**.

- **One GPU:** continue to Part 3.
- **Two or more GPUs:** continue to Step 3.

### Step 3: Only if you have two or more GPUs

1. Open Settings, then go to **System > Display**.
2. Scroll down and click **Advanced display**.
3. Use the drop-down at the top to look at each display. Write down the GPU listed next to **Connected to** for each one.

- **All projector displays use the same GPU:** write down its name. You will need it in Part 7.
- **Projectors are spread across different GPUs:** stop here. Spout, the method used to copy the video, needs one GPU, and the alternative method has not been built yet.

---

## Part 3: Prepare Windows

These settings stop Windows from interrupting your show. Menu names can differ slightly between Windows 10 and Windows 11.

1. **Stop the computer sleeping.** In Settings, go to **System > Power** (it may be called **Power & battery** or **Power & sleep**). Set the screen and sleep options to **Never**.
2. **Use full power.** On the same page, set **Power mode** to **Best performance** if you see that option.
3. **Turn off the screen saver.** Press the Windows key, type `screen saver`, and press Enter. Set it to **(None)** and click **OK**.
4. **Stop pop-up notifications.** In Settings, go to **System > Notifications** and turn on **Do not disturb**. On Windows 10 this is called **Focus assist**.
5. **Stop surprise updates.** In Settings, open **Windows Update** and click **Pause updates**. Repeat this during every show week.

---

## Part 4: Install Python and VLC

Python runs the multiview. VLC lets you test the camera.

1. Open PowerShell.
2. Run this command to install Python:

   ```powershell
   winget install Python.Python.3.12
   ```

   If it asks you to agree to terms, type `Y` and press **Enter**. If Windows asks for permission, click **Yes**.

3. Run this command to install VLC:

   ```powershell
   winget install VideoLAN.VLC
   ```

4. **Close the PowerShell window**, then open a new one. New programs are only recognized in a new window.
5. Check that Python works:

   ```powershell
   py -3.12 --version
   ```

**You should see:** `Python 3.12` followed by more numbers.

---

## Part 5: Set up the camera

### Step 1: Find the camera's address

The address is four numbers separated by dots. PTZOptics cameras often show it on screen during start-up, and it may also be in your show notes. Write it on your settings sheet.

In the commands below, replace `192.168.100.88` with your camera's address.

### Step 2: Check the computer can reach the camera

```powershell
ping 192.168.100.88
```

**You should see:** four lines starting with `Reply from`.

If you see `Request timed out` or `Destination host unreachable`, check the camera's power and network cable. If that doesn't fix it, ask whoever set up your show network to put this computer on the same network as the camera.

### Step 3: Change the camera's second video stream

The camera can send two video streams. The multiview uses the second one, so your main camera picture is not affected.

1. Open Microsoft Edge.
2. In the address bar at the top, type `http://` followed by the camera's address, such as `http://192.168.100.88`, and press **Enter**.
3. If it asks you to sign in, enter the camera's username and password. On many PTZOptics cameras, both are `admin` unless someone changed them.
4. Open the **Video** settings.
5. **Do not change the first (main) stream.**
6. Find the **second stream**, and set:

   | Setting | Value |
   |---|---|
   | Codec / compression | **H.264** (not H.265) |
   | Resolution | **1280 × 720** |
   | Frame rate | **30** |
   | I-frame interval | **30**, or the lowest number offered |
   | Bitrate | **2048 to 4096** kbps |
   | Audio | **On**, if you want a camera audio meter |

7. Save the settings.

### Step 4: Test the stream in VLC

1. Open **VLC**. Press the Windows key, type `VLC`, and press **Enter**.
2. Click **Media**, then **Open Network Stream**.
3. Type this, using your camera's address:

   ```text
   rtsp://192.168.100.88:554/2
   ```

4. Click **Play**.

**You should see:** the live camera picture within a few seconds.

If it doesn't work, try the same link ending in `/1`. Write the link that works on your settings sheet, then close VLC.

---

## Part 6: Set up Resolume

You will add two small hidden outputs to Resolume. **Your real Center and Side screens must stay exactly as they are.**

Button names may differ slightly depending on your Resolume version.

### Step 1: Save a safe copy of your current setup

1. Open Resolume and load your show.
2. Click **Output**, then **Advanced**.
3. Find the **Preset** menu in the Advanced Output window.
4. Save the current setup as a new preset named `Show only`.

This is your emergency backup. Selecting it puts everything back to how it is now.

### Step 2: Save a second copy to work on

Save another new preset named `Show + Multiview`. Make all of the following changes in this preset.

### Step 3: Add the Center preview

1. Add a new screen, and name it `MV Center`.
2. Set its output **Device** to **Spout**.
3. Set its **Width** to `1152` and **Height** to `536`.
4. Add a slice to this screen. On the **Input Selection** tab, make it cover the same area of your composition as your real Center screen's slice. Copying and pasting that slice is easiest, if your version allows it.
5. On the **Output Transformation** tab, make the slice fill the whole `MV Center` screen.
6. Turn on **Black BG** for the slice.

### Step 4: Add the Side preview

Repeat Step 3 with these changes:

- Name the screen `MV Side`.
- Set **Width** to `960` and **Height** to `540`.
- Copy the input area from your real **Side** screen.

### Step 5: Save and check

1. Save the `Show + Multiview` preset.
2. Check that the projectors look exactly as they did before.

If anything looks wrong on a projector, select the `Show only` preset straight away.

---

## Part 7: Download and install the multiview

### Step 1: Download it

1. Open Edge and go to this address. The download starts by itself:

   ```text
   https://github.com/teejpaddle/multiview/archive/refs/heads/main.zip
   ```

2. Wait for `multiview-main.zip` to finish downloading to your **Downloads** folder.

### Step 2: Put it in the right place

The folder must end up in this exact location: `C:\Show\multiview`

1. Open **File Explorer** by pressing **Windows key + E**.
2. Click **This PC** on the left, then double-click **Local Disk (C:)**.
3. Right-click an empty area, then choose **New > Folder**. Name it `Show`. If Windows asks for permission, click **Continue**.
4. Go to your **Downloads** folder and right-click `multiview-main.zip`.
5. Choose **Extract All**.
6. Replace the location in the box with `C:\Show`, then click **Extract**.
7. Open `C:\Show`. You will see a folder named `multiview-main`.
8. Right-click that folder, choose **Rename**, type `multiview`, and press **Enter**.

**You should see:** folders named `config`, `scripts` and `web` when you open `C:\Show\multiview`. If you only see one more folder inside, the files are one level too deep. Move that inner folder so it is `C:\Show\multiview`.

### Step 3: Install it

1. Open PowerShell.
2. Go to the multiview folder:

   ```powershell
   cd C:\Show\multiview
   ```

3. Run the installer:

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\Install.ps1
   ```

This takes a few minutes, and a lot of text will scroll past.

**You should see:** `Install complete` at the end, and two new desktop icons named **Start Multiview** and **Stop Multiview**.

### Step 4: Only if you have two or more GPUs

1. In PowerShell, run this command. It shows where Python is installed:

   ```powershell
   py -3.12 -c "import sys; print(sys.executable)"
   ```

2. Write down the location it prints.
3. Open Settings and go to **System > Display > Graphics**.
4. Add that `python.exe` file, click **Options**, and choose the GPU that drives your projectors.
5. Do the same for Resolume (`Arena.exe`).

---

## Part 8: Enter your settings

### Step 1: Turn on the Resolume outputs

Open Resolume, load your show, and select the `Show + Multiview` preset.

### Step 2: Find your Spout sender names

In PowerShell, run these two commands, one at a time:

```powershell
cd C:\Show\multiview
```

```powershell
.venv\Scripts\python.exe tools\list_sources.py
```

**You should see:** two lines similar to this:

```text
spout.sender = "MV Center"    # 1152x536
spout.sender = "MV Side"    # 960x540
```

Write the exact names between the quotation marks on your settings sheet.

### Step 3: Find your multiview monitor's position

```powershell
.venv\Scripts\python.exe tools\list_monitors.py
```

**You should see:** one line for each monitor, like this:

```text
Monitor 0: x=0 y=0 w=1920 h=1080  (primary)
Monitor 1: x=1920 y=0 w=1920 h=1080
```

Write down the `x` and `y` numbers for your multiview monitor. If you aren't sure which one it is, pick one. You can change it in Part 10.

### Step 4: Find your sound device name

1. In Resolume, open **Preferences** and then **Audio**. Note the output device it uses.
2. Write down one distinctive word from that name. For `Speakers (Focusrite USB Audio)`, you could write `Focusrite`.

### Step 5: Type your settings into the settings file

1. Open the settings file:

   ```powershell
   notepad config\multiview.toml
   ```

2. Find each line below and change only the value. **Keep the quotation marks exactly where they are.**

   | Find this line | Change it to |
   |---|---|
   | `window_x = 0` | Your monitor's `x` number |
   | `window_y = 0` | Your monitor's `y` number |
   | `device_match = "Speakers"` | Your sound device word |
   | `spout.sender = "MV Center"` | Your Center sender name |
   | `spout.sender = "MV Side"` | Your Side sender name |
   | `rtsp.url = "rtsp://192.168.100.88:554/2"` | The camera link that worked in VLC |

   For example, a finished camera line looks like this:

   ```toml
   rtsp.url = "rtsp://192.168.1.50:554/2"
   ```

3. Press **Ctrl + S** to save, then close Notepad.

---

## Part 9: Run the automatic check

This tests everything at once. Before you run it, make sure:

- Resolume is open with the `Show + Multiview` preset selected
- The camera is on
- The multiview is **not** running

Run this command:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\Preflight.ps1
```

**You should see:** every line starting with `PASS`, and `Preflight PASSED` at the end.

If any line says `FAIL`, find it in [Part 14](#part-14-if-something-goes-wrong), fix it, and run the check again. **Do not continue until every line says PASS.**

---

## Part 10: Start the multiview for the first time

1. Double-click **Start Multiview** on your desktop.
2. Wait up to 20 seconds. The multiview opens full-screen.

**You should see:** three pictures with green borders, each marked `LIVE`, plus a clock with moving seconds.

### If it opened on the wrong monitor

1. Double-click **Stop Multiview**.
2. Run `notepad config\multiview.toml` from the `C:\Show\multiview` folder in PowerShell.
3. Change `window_x` and `window_y` to another monitor's numbers.
4. Save, and double-click **Start Multiview** again.

---

## Part 11: Do a full rehearsal

Do this before you rely on the multiview in a real show. **Never do these tests during a show.**

| # | Do this | It passes if |
|---|---|---|
| 1 | Play different content on Center and Side | Each picture matches its projectors |
| 2 | Unplug the camera's network cable | The PTZ picture turns amber, then red `NO SIGNAL` within about 4 seconds. The other two stay green |
| 3 | Plug the cable back in | The PTZ picture shows `RESTORED` within 10 seconds |
| 4 | Click **Pause Previews** | All three pictures show blue `PAUSED` |
| 5 | Click **Resume Previews** | All three return to green `LIVE` within 3 seconds |
| 6 | Pause a clip in Resolume for 15 seconds | The picture stays green and shows `LIVE · STILL` |
| 7 | Close the multiview, then start it again | The projectors never change |

### The most important test: does it slow down Resolume?

1. Select the `Show only` preset, with the multiview stopped. Play your heaviest content and write down Resolume's frames-per-second (FPS) number.
2. Select `Show + Multiview`, and start the multiview. Play the same content for at least as long as your show.
3. Compare the FPS numbers, and watch the projectors for stutter.

**It passes if** the FPS stays within 1 of your first number and the video looks smooth. If it doesn't, use the `Show only` preset for your show.

The complete professional test list is in Part 3 of `docs\multiview-plan.md`.

---

## Part 12: Show day routine

**Starting up, in this order:**

1. Turn on the projectors and video equipment.
2. Turn on the camera, and wait 60 seconds.
3. Turn on the computer and open Resolume.
4. Load your show, and select the `Show + Multiview` preset.
5. Check that the projectors look correct.
6. Double-click **Start Multiview**.
7. Check for three green `LIVE` pictures and a moving clock.

**Shutting down:** double-click **Stop Multiview**.

> ### In an emergency
>
> If the show looks wrong or stutters:
>
> 1. Click **Pause Previews**.
> 2. If it is still wrong, select the `Show only` preset in Resolume.

---

## Part 13: How to read and use the screen

### What the pictures are telling you

| You see | What it means | What to do |
|---|---|---|
| Gray `CONNECTING…` | Starting up | Wait a few seconds |
| Green `LIVE` | Working normally | Nothing |
| Green `LIVE · STILL` | Working, but the picture isn't moving | Check it should be still |
| Green `LIVE · BLACK` | Working, but the picture is black | Check it should be black |
| Amber `LATE` | No new picture for over 1 second | Watch it closely |
| Red `NO SIGNAL` | No picture for over 3 seconds. It keeps retrying by itself | Check that source |
| Green `RESTORED` | The picture just came back | Nothing |
| Blue `PAUSED` | Previews are paused | Click **Resume Previews** |
| Red bar across the top | The multiview program stopped | Double-click **Start Multiview** |

> **Always look at the real projectors too.** The Center and Side pictures prove what Resolume is sending. They can't prove that the cables and projectors are working.

If the clock's seconds stop moving, the page has frozen. Click it and press **F5**.

### Using the countdown

| To do this | Do this |
|---|---|
| Choose a length | Click **5 min**, **10 min** or **15 min** |
| Choose another length | Type minutes in the **Minutes** box and click **Set** |
| Count down to a time of day | Enter the time in **Count to** and click **Go** |
| Start | Click **Start** |
| Pause | Click **Pause** |
| Clear it | Click **Reset** |

The countdown turns amber for the last 60 seconds. After zero, it turns red and counts up to show how far over you are. To choose a new length while it is running, click **Reset** first.

### Keyboard shortcuts

| Key | Action |
|---|---|
| `Space` | Start or pause the countdown |
| `R` | Reset the countdown |
| `P` | Pause or resume previews |

> **Be careful with shortcuts.** They only work when the multiview was the last window you clicked. If Resolume was the last window you clicked, the key goes to Resolume instead. During a show, using the mouse is safer.

### The audio meters

The **SHOW** and **CAM** bars show sound levels. The multiview never plays sound. Green is normal, amber is loud, and red is very loud. `NO DEVICE` means the sound device name in your settings is wrong. `NO AUDIO TRACK` means the camera isn't sending audio.

### Preview quality drops by itself

If the top bar shows `PREVIEW REDUCED`, the computer is busy, so the multiview has lowered its picture quality to protect the projectors. It recovers on its own when the computer is less busy.

---

## Part 14: If something goes wrong

### During installation

| Problem | Fix |
|---|---|
| `py is not recognized` | Close PowerShell and open a new window. If it still happens, repeat Part 4 |
| `winget is not recognized` | Open the **Microsoft Store**, search for **App Installer**, and install or update it |
| `running scripts is disabled` | Copy the full command from this guide, including `-ExecutionPolicy Bypass` |
| `Cannot find path` | Run `cd C:\Show\multiview`, then try again. Check the folder location from Part 7 |
| No desktop icons appeared | Run `powershell -ExecutionPolicy Bypass -File scripts\Create-Shortcut.ps1` from the multiview folder |

### Automatic check failures

| The line says `FAIL` for | Fix |
|---|---|
| `Python 3.12` | Repeat Part 4, then run the installer in Part 7 again |
| `Config valid` | The message names the setting with the problem. Fix that line in Part 8, and check the quotation marks |
| `Port 8090 free` | The multiview is already running. Double-click **Stop Multiview** and try again |
| `Spout sender` | Select `Show + Multiview` in Resolume, then compare the names in Part 8 letter for letter |
| `Camera` | Turn on the camera, test the link in VLC, and check that it matches your settings file exactly |
| `Audio device` | Try a different word from the device's name |
| `Multiview monitor` | Repeat Part 8, Step 3, and check that the monitor is on |

### While running

| Problem | Fix |
|---|---|
| A message says the configuration has a problem | The message names the setting. Fix that line as in Part 8, and check the quotation marks |
| A message says the bridge did not start | Run the check in Part 9, and look at the newest file in `C:\Show\multiview\logs` |
| A message says Start Multiview stopped unexpectedly | Run the check in Part 9. If every line passes, take a photo of the message for whoever supports your setup |
| Center or Side shows `NO SIGNAL` | In Resolume, select the `Show + Multiview` preset |
| PTZ shows `NO SIGNAL` | Check the camera's power and network cable. It reconnects by itself |
| A picture is upside down | In `config\multiview.toml`, add a new line directly under that feed's `spout.sender` line: `spout.flip_vertical = true`. Then restart the multiview |
| A picture shows only part of the screen | Fix that slice in Resolume (Part 6, Step 3) |
| The projectors stutter | Click **Pause Previews**. If that doesn't help, select `Show only` |

### Restart everything

Most problems clear if you do this:

1. Double-click **Stop Multiview**.
2. Wait 10 seconds.
3. Double-click **Start Multiview**.

This doesn't affect the projectors.
