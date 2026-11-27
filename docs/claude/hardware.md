# Target device

Part of the notes for Claude Code sessions. The index is in `CLAUDE.md`.

- Raspberry Pi 3 Model A+ since the evening of 2026-11-22: 512 MB RAM (about
  415 MB usable), 4 cores at up to 1.4 GHz. Until then a Raspberry Pi Zero
  2 W: the same memory, 1.0 GHz. The owner moved the SD card from the one
  board to the other and changed nothing else. What the move showed:
  - The card started on the other board as the same machine: same name, same
    keys, same user, checkout and data as they were, `ssh` without a
    warning. cloud-init ran its stages and set nothing up again (it is the
    same instance, see the card's own move below).
  - It joined the Wi-Fi by itself, at the second start of that evening
    within a minute. The saved networks are tied to `wlan0`, not to a
    radio's own address. The other board has another radio, though, and the
    router gave it another IP address: `ssh pi` timed out on the PC and
    `ssh pi-local` worked at the first try (see "Reaching the Pi").
  - Memory is the same (415 MB, and 414 MB of compressed swap), so the
    memory figures in this file hold, and with them the rule for child runs.
    Times do not: importing the SDK takes 10 s here (15 on the Zero), and
    the test suite 70 s in the checkout (80). What this file dates before
    that evening was measured on the Zero 2 W.
  - The radio has both bands here: `iw list` shows 13 channels from
    2,412 MHz and 19 from 5,180 MHz, and a scan found 10 networks on the one
    band and 6 on the other. The Zero had the first band only. The Pi stayed
    on the network and the band it was on, with power saving off as before.
  - The board has ONE USB port, a full-size one, and it is a host port as
    built (`lsusb -t`: a `dwc_otg` root hub with one port). The webcam and
    the keyboard's receiver cannot both be in it without a hub: that evening
    the receiver was in it at the start and the webcam from 21:19 (`sudo
    dmesg -T | grep usb`).
  - The webcam is `/dev/video0` as before. Its microphone is still the sound
    card NAMED `B100`, but its number went from 1 to 2: this board has a
    headphone socket, which is card 0 (`bcm2835 Headphones`). The skills
    name the card, so they work unchanged: all four commands of
    `take-photo` and `record-sound` were run on this board, and so were two
    runs of the owner's with a photo and a recording.
  - That headphone socket is a way to make sound that the Zero did not
    have. Later that evening the owner put speakers on it (see "Sound").
  - `vcgencmd get_throttled` said `0x80000` from the first look, 37 minutes
    after the start: bit 19, "soft temperature limit has occurred". The
    limit is 60 degrees by default, where the firmware lowers the clock
    (from 1.4 to 1.2 GHz; the documentation's text names the 3 B+, and its
    `temp_soft_limit` entry says "3A+/3B+ only"). That evening it was not
    seen to happen: 44 to 46 degrees idle, 50.5 at the hottest during the
    test suite, the clock at 1,400 MHz. No bit for low voltage was set.
  - It was seen on 2026-11-23, with all four cores loaded (`sha256sum
    /dev/zero` four times): from 41 degrees the Pi was at 60 within 20
    seconds. There bit 3 came on ("soft temperature limit active",
    `0x80008`), `vcgencmd measure_clock arm` went from 1,400 to 1,200 MHz
    and the core's voltage from 1.365 to 1.26 V. For the 20 seconds
    watched it switched on and off about once a second and the temperature
    stayed at 59 to 60; with one core loaded it was back at full speed at
    58. So one busy half minute is enough to set bit 19. Stronger
    throttling, by the documentation, comes between 80 and 85 degrees on
    every model, 85 being the limit: not reached here. The kernel's own
    trip point is 110 degrees (`critical`).
- 64-bit Raspberry Pi OS Lite (Trixie), Python 3.13.5, no tkinter
- Hostname `robot.local`, user `grobliro`, repo checkout at `~/robot`
- Virtual environment: `~/robot/.venv` (created with `--system-site-packages`)
- API keys: `~/robot/.env` (`ANTHROPIC_API_KEY=...`, and since 2026-11-23
  `XAI_API_KEY=...` for hearing and speaking, see "Hearing" and "Speaking"). Never commit it; `.env` is
  in `.gitignore`.
- The program's data: `~/robot-data` (outside the checkout on purpose).
- Passwordless sudo is enabled for `grobliro` (the user set it up on
  2026-11-15 in `/etc/sudoers.d/010_grobliro-nopasswd`).
- `/tmp` is a RAM disk. Importing the Anthropic SDK takes about 10 s (15 s
  on the Zero 2 W) and one process uses about 77 MB.
- Swap is compressed memory, not the SD card: a zram device of 415 MB with
  zstd, set up by the `rpi-swap` package, swappiness 60. What sits idle is
  squeezed to about a quarter of its size once memory gets short (121 MB
  into 30 MB, measured on 2026-11-19). So a program that is open but idle
  costs far less than its size, and the kernel's "available" figure, which
  counts only what can be had without swapping, can rise when one more
  program is started.
- The SD card is a 32 GB card (29.1 GiB) since 2026-11-19, and the system
  partition fills it: 29 GB, of which 2.7 GB is used. Before that it was a
  16 GB card. The owner keeps an image of the 16 GB card on the laptop (the
  state of that morning; it fits any card of 16 GB or more). What the move
  showed, since restoring a backup goes the same way:
  - The image was read with Win32 Disk Imager, with the Pi shut down, and
    written to the new card with Raspberry Pi Imager ("Use custom"). The
    copy started as the same machine: same name, same keys, `ssh pi` without
    a warning.
  - The system had been set up through cloud-init: Raspberry Pi Imager put
    `user-data` and `meta-data` on the boot partition, and `cmdline.txt`
    carries `ds=nocloud;i=<instance>`. A copy has the same instance name, so
    nothing is set up again. Writing a copy WITH the Imager's customisation
    settings would give it a new one, and the first start could then reset
    the name, the password and the keys.
  - The system does not enlarge itself on a larger card, cloud-init or not.
    `sudo growpart /dev/mmcblk0 2` (try `--dry-run` first) and `sudo
    resize2fs /dev/mmcblk0p2` did it while the Pi was running, with no
    restart and with an interface of the owner's open. The partition keeps
    its start and the disk its identifier, which is all that
    `root=PARTUUID=...` in `cmdline.txt` goes by. `raspi-config
    --expand-rootfs` does it with `fdisk` and a step at the next start (read
    in its script, not tried here).
  - A copy onto a card writes and verifies only the image's own length, here
    the first 14.6 GB. The rest of the new card was therefore tested in
    full: 23.8 GB written over the free space, in files whose every 4 KB
    block carries a stamp of its place, and all of it read back right, up to
    the card's last block (16 MB/s writing, 22 MB/s reading, 50 minutes).
    Its size is proven and needs no second test. The script was fed over
    ssh and is not in the repo.
  - `sudo dpkg --verify` checks every installed system file against its
    checksum (two minutes). On this Pi it always reports one file,
    `/usr/lib/modprobe.d/g_ether.conf`, which the tool of its own package
    (`rpi-usb-gadget`) rewrites. That is not damage.
  - A backup of the card as it is now is a 29 GB file and needs a card of
    32 GB or more.
  - The Pi keeps no log across restarts (the journal is in memory), so the
    messages of an earlier start cannot be read afterwards.
- The Pi also has a keyboard and screen attached. The screen is a text
  console (tty1) of 240 columns by 67 rows on 1920 x 1080, in UTF-8, with the
  kernel's own font and no mouse service. The screen is the same on the
  3 A+; the keyboard's receiver shares that board's one USB port with the
  webcam (see above). In everyday use since then the port has the webcam,
  so there is no keyboard at the Pi, and it runs with no screen as well
  (see "Starting by itself").
- Looked at on 2026-11-28: `Raspberry Pi 3 Model A Plus Rev 1.1`, the card
  29 GB with 3.0 GB used, tmux 3.5a, 263 MB available with nothing of the
  robot running, and 182 MB with the owner's interface up and one run
  going.
