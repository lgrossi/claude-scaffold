# Platform Limitations

## GNOME Wayland: Terminal focus-raise is impossible

`notify.sh` works cross-platform for desktop notifications (Linux + macOS).

On GNOME Wayland, raising/focusing a terminal window on notification click is **not possible** due to focus-stealing prevention. All approaches were debugged and confirmed blocked:
- `gdbus` activation via `org.gnome.Terminal`
- `xdg-activation` protocol
- `GApplication.Activate` D-Bus method

The only path to focus-raise on Wayland is a GNOME Shell extension (C/GJS) — a different project entirely. Accept this as a known limitation; do not re-investigate.
