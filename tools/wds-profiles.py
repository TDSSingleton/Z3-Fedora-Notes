#!/usr/bin/env python3
"""List modem data profiles in ALL families, including EPC.

Why: `qmicli --wds-get-profile-list` accepts only 3gpp|3gpp2, but libqmi
itself models QmiWdsProfileType.EPC -- the unified LTE/EPS profile family
where the *attach* profile lives. In the Fold 3's known-good state, 3GPP
profile 1 is EMPTY yet the modem still reports an LTE attach APN, so the
attach configuration is not in the family qmicli can show. This reaches it.

STRICTLY READ-ONLY: GetProfileList + GetProfileSettings only.

Run on the phone as root.
"""
import sys
import gi
gi.require_version("Qmi", "1.0")
gi.require_version("Qrtr", "1.0")
from gi.repository import Qmi, Qrtr, GLib  # noqa: E402

loop = GLib.MainLoop()
st = {"dev": None, "client": None, "queue": [], "profiles": []}

# enum members are literally named "3GPP"/"3GPP2", not valid Python identifiers
FAMILIES = [("3gpp", getattr(Qmi.WdsProfileType, "3GPP")),
            ("3gpp2", getattr(Qmi.WdsProfileType, "3GPP2")),
            ("epc", Qmi.WdsProfileType.EPC)]

INTERESTING = ["apn_name", "username", "password", "authentication", "pdp_type",
               "profile_name", "apn_type_mask", "pdp_context_number",
               "roaming_disallowed_flag", "apn_disabled_flag", "ipv4_dns_address"]


def done(code=0):
    st["code"] = code
    GLib.idle_add(loop.quit)


def fail(what, err):
    print(f"ERROR: {what}: {err}")
    done(1)


def show_settings(client, res, ctx):
    fam, idx, name = ctx
    try:
        out = client.get_profile_settings_finish(res)
        out.get_result()
    except Exception as e:
        print(f"      settings unavailable: {e}")
        return next_item()
    for attr in INTERESTING:
        g = getattr(out, "get_" + attr, None)
        if g is None:
            continue
        try:
            v = g()
            v = v[1] if isinstance(v, tuple) else v
            print(f"      {attr}: {v!r}")
        except Exception:
            pass
    next_item()


def next_item():
    if not st["queue"]:
        done(0)
        return
    kind, payload = st["queue"].pop(0)
    if kind == "list":
        fam_name, fam = payload
        print(f"\n### family: {fam_name}")
        inp = Qmi.MessageWdsGetProfileListInput()
        inp.set_profile_type(fam)
        st["client"].get_profile_list(inp, 10, None, got_list, fam_name)
    else:
        fam_name, idx, name = payload
        print(f"    [{idx}] {name!r}")
        inp = Qmi.MessageWdsGetProfileSettingsInput()
        try:
            inp.set_profile_id(dict(FAMILIES)[fam_name], idx)
        except Exception as e:
            print(f"      cannot address profile: {e}")
            return next_item()
        st["client"].get_profile_settings(inp, 10, None, show_settings, payload)


def got_list(client, res, fam_name):
    try:
        out = client.get_profile_list_finish(res)
        out.get_result()
        lst = out.get_profile_list()
    except Exception as e:
        print(f"    (no list: {e})")
        return next_item()
    if not lst:
        print("    (empty)")
    items = []
    for el in lst or []:
        idx = getattr(el, "profile_index", None)
        nm = getattr(el, "profile_name", None)
        items.append(("settings", (fam_name, idx, nm)))
        print(f"    index={idx} name={nm!r}")
    st["queue"] = items + st["queue"]
    next_item()


def on_client(dev, res, _):
    try:
        st["client"] = dev.allocate_client_finish(res)
    except Exception as e:
        return fail("allocate WDS client", e)
    st["queue"] = [("list", f) for f in FAMILIES]
    next_item()


def on_open(dev, res, _):
    try:
        dev.open_finish(res)
    except Exception as e:
        return fail("open device", e)
    dev.allocate_client(Qmi.Service.WDS, Qmi.CID_NONE, 10, None, on_client, None)


def on_dev(_s, res, _):
    try:
        st["dev"] = Qmi.Device.new_from_node_finish(res)
    except Exception as e:
        return fail("create device", e)
    st["dev"].open(Qmi.DeviceOpenFlags.NONE, 15, None, on_open, None)


def on_bus(_s, res, _):
    try:
        bus = Qrtr.Bus.new_finish(res)
    except Exception as e:
        return fail("qrtr bus", e)
    node = bus.peek_node(0)
    if node is None:
        return fail("qrtr node", "node 0 absent")
    Qmi.Device.new_from_node(node, None, on_dev, None)


print("# WDS data profiles, all families (read-only)")
Qrtr.Bus.new(3000, None, on_bus, None)
GLib.timeout_add_seconds(45, lambda: (print("ERROR: timed out"), done(1))[0])
loop.run()
sys.exit(st.get("code", 0))
