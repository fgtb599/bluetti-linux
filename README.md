# bluetti-linux

Tray monitor for a Bluetti **EB3A** over Bluetooth LE. Shows a coloured battery icon (green,
red at 20% or below, bolt while charging) and battery % in the top bar, and a
dashboard window (battery ring, input/output cards, AC/DC on/off switches, runtime estimate)
similar to the Android app. The only thing it ever writes to the device is the AC/DC output
switches; turning AC off asks for confirmation first.

## Install (Ubuntu)

```bash
sudo apt install python3-bleak gir1.2-ayatanaappindicator3-0.1
```

GNOME needs the AppIndicator extension (`ubuntu-appindicators@ubuntu.com`, enabled by default on Ubuntu).

## Run

```bash
python3 bluetti_tray.py              # active device from Devices…, else the first EB3A* found
python3 bluetti_tray.py --address XX:XX:XX:XX:XX:XX --interval 3   # one-off override
python3 bluetti_tray.py --hidden     # tray only
```

Both the tray menu and the dashboard's ☰ menu have:

- **Theme**: System (follows GNOME light/dark), Light or Dark
- **Tray view**: *Battery* (coloured battery + `99%`) or *Battery + in/out*, which adds a green ↓ input
  and an orange ↑ output item with their watts (grey at 0 W)
- **Devices…**: saved units, which one is active, and a scan for nearby EB3As
- **About**: app version and license, plus the connected unit's model, serial, address and firmware

Settings live in `~/.config/bluetti-linux/config.json`.

The EB3A accepts **one BLE connection at a time** — close the phone app (or turn off phone
Bluetooth) or the PC will not find it.

## Autostart

```bash
cp bluetti-tray.desktop ~/.config/autostart/
# then edit the Exec= line: real path to bluetti_tray.py, and optionally --address XX:XX:XX:XX:XX:XX
```

## Tests

```bash
python3 -m unittest discover tests
```

Protocol and register map are based on the community
[bluetti_mqtt](https://github.com/warhammerkid/bluetti_mqtt) project.

## License

MIT — see [LICENSE](LICENSE).
