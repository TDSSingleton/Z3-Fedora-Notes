// Fold 3: a File transfer (MTP) tile in Plasma Mobile's quick settings drawer.
//
// This is the RIGHT place for the toggle. Plasma Mobile has no system tray --
// that much was already known -- but it does have a first-class toggle
// surface, the quick settings drawer, with a plugin API. A notification with
// an action button was a workaround for a problem that does not exist.
//
// Every built-in tile drives a C++/D-Bus plugin rather than running a command.
// We have no such plugin, so this uses plasma5support's `executable` engine,
// which is the supported escape hatch for QML that must run something.
//
// Privilege split: `fold3-mtp state` is deliberately unprivileged (the
// gadget's configfs tree is world-readable), so only the toggle goes through
// sudo, via a single NOPASSWD line for exactly this one binary.
//
// Install to ~/.local/share/plasma/quicksettings/org.kde.plasma.quicksetting.fold3mtp/

import QtQuick

import org.kde.plasma.private.mobileshell.quicksettingsplugin as QS
import org.kde.plasma.plasma5support as P5Support

QS.QuickSetting {
    id: root

    readonly property string bin: "/usr/local/bin/fold3-mtp"
    property string mtpState: "NOGADGET"
    property bool busy: false

    text: i18n("File transfer")
    icon: mtpState === "ON" ? "drive-harddisk" : "drive-removable-media-usb"

    // Hidden entirely on a kernel whose gadget does not exist, rather than
    // showing a tile that can only fail.
    available: mtpState !== "NOGADGET"
    enabled: mtpState === "ON"

    status: busy
        ? i18n("Switching…")
        : (mtpState === "ON"
            ? i18n("On — browse this phone from your computer")
            : i18n("Off — tap to share files over USB"))

    P5Support.DataSource {
        id: exec
        engine: "executable"
        connectedSources: []

        onNewData: function(source, data) {
            // Always disconnect: the executable engine keeps a source alive
            // and will not re-run an identical command string otherwise.
            disconnectSource(source);

            if (source.indexOf("state") !== -1) {
                const out = (data["stdout"] || "").trim();
                if (out.length > 0) {
                    root.mtpState = out;
                }
            } else {
                // A toggle finished, successfully or not; re-read the truth
                // rather than assuming it flipped.
                root.busy = false;
                poll();
            }
        }

        function run(cmd) {
            connectSource(cmd);
        }
    }

    function poll() {
        exec.run(root.bin + " state");
    }

    function toggle() {
        if (busy || mtpState === "NOGADGET") {
            return;
        }
        busy = true;
        // -n: never prompt. If the sudoers drop-in is missing this fails
        // immediately instead of hanging on a password nobody can type.
        exec.run("sudo -n " + root.bin + " toggle");
    }

    Timer {
        interval: 3000
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: root.poll()
    }
}
