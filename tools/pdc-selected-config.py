#!/usr/bin/env python3
"""Read the modem's SELECTED persistent-device-config IDs (PDC) over QMI/qrtr.

qmicli only reports Active/Inactive status per stored config; the QMI
GetSelectedConfig message additionally reports the *active* and *pending*
config IDs per configuration type. Pending matters: a config can be selected
for the next modem boot without being active yet, which is invisible to
`qmicli --pdc-list-configs`.

STRICTLY READ-ONLY: GetSelectedConfig only. Nothing here activates,
deactivates, loads or deletes a config.

Run on the phone as root.
"""
import sys
import gi
gi.require_version("Qmi", "1.0")
gi.require_version("Qrtr", "1.0")
from gi.repository import Qmi, Qrtr, GLib  # noqa: E402

NODE_ID = 0
loop = GLib.MainLoop()
st = {"dev": None, "client": None, "queue": [], "token": 0}


def done(code=0):
    cl, dev = st.get("client"), st.get("dev")
    if cl is not None and dev is not None:
        try:
            dev.release_client(cl, Qmi.DeviceReleaseClientFlags.RELEASE_CID, 5, None, None, None)
        except Exception:
            pass
    st["code"] = code
    GLib.idle_add(loop.quit)


def fail(what, err):
    print(f"ERROR: {what}: {err}")
    done(1)


def hexid(blob):
    if blob is None:
        return "(none)"
    b = bytes(blob)
    return ":".join("%02X" % x for x in b) if b else "(empty)"


def on_indication(client, output):
    try:
        ok = output.get_indication_result()
    except Exception:
        ok = None
    label = st["inflight"]
    print(f"\n### selected config: {label}")
    if ok not in (None, 0):
        print(f"    indication result: {ok}")
    for name, getter in (("active ", "get_active_id"), ("pending", "get_pending_id")):
        try:
            got = getattr(output, getter)()
            val = got[1] if isinstance(got, tuple) else got
            print(f"    {name} id: {hexid(val)}")
        except Exception as e:
            print(f"    {name} id: unavailable ({type(e).__name__})")
    next_query()


def on_sent(client, res, _):
    try:
        client.get_selected_config_finish(res)
    except Exception as e:
        fail("get-selected-config request", e)


def next_query():
    if not st["queue"]:
        done(0)
        return
    label, ctype = st["queue"].pop(0)
    st["inflight"] = label
    st["token"] += 1
    inp = Qmi.MessagePdcGetSelectedConfigInput()
    inp.set_config_type(ctype)
    inp.set_token(st["token"])
    st["client"].get_selected_config(inp, 10, None, on_sent, None)


def on_client(dev, res, _):
    try:
        st["client"] = dev.allocate_client_finish(res)
    except Exception as e:
        return fail("allocate PDC client", e)
    connected = False
    for signal in ("get-selected-config", "pdc-get-selected-config"):
        try:
            st["client"].connect(signal, on_indication)
            connected = True
            print(f"# indication signal: {signal}")
            break
        except TypeError:
            continue
    if not connected:
        return fail("connect indication", "no known signal name on QmiClientPdc")
    st["queue"] = [("software (carrier config)", Qmi.PdcConfigurationType.SOFTWARE),
                   ("platform", Qmi.PdcConfigurationType.PLATFORM)]
    next_query()


def on_open(dev, res, _):
    try:
        dev.open_finish(res)
    except Exception as e:
        return fail("open device", e)
    dev.allocate_client(Qmi.Service.PDC, Qmi.CID_NONE, 10, None, on_client, None)


def on_dev(_src, res, _):
    try:
        st["dev"] = Qmi.Device.new_from_node_finish(res)
    except Exception as e:
        return fail("create QMI device", e)
    st["dev"].open(Qmi.DeviceOpenFlags.NONE, 15, None, on_open, None)


def on_bus(_src, res, _):
    try:
        bus = Qrtr.Bus.new_finish(res)
    except Exception as e:
        return fail("open qrtr bus", e)
    node = bus.peek_node(NODE_ID) if hasattr(bus, "peek_node") else bus.get_node(NODE_ID)
    if node is None:
        return fail("qrtr node", f"node {NODE_ID} not present")
    Qmi.Device.new_from_node(node, None, on_dev, None)


print("# PDC selected-config query (read-only)")
Qrtr.Bus.new(3000, None, on_bus, None)
GLib.timeout_add_seconds(30, lambda: (print("ERROR: timed out"), done(1))[0])
loop.run()
sys.exit(st.get("code", 0))
