// fold3-dpms <connector> on|off
// Power one Wayland output on or off through KWin's org_kde_kwin_dpms protocol.
// kscreen-doctor --dpms only does every output at once, and disabling an output
// rearranges the desktop; this leaves layout and windows alone.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wayland-client.h>
#include "dpms-client-protocol.h"

#define MAXO 8
static struct { struct wl_output *o; char name[64]; } outs[MAXO];
static int nouts;
static struct org_kde_kwin_dpms_manager *mgr;

static void o_geometry(void *d, struct wl_output *o, int32_t x, int32_t y, int32_t pw, int32_t ph, int32_t sp, const char *mk, const char *md, int32_t t) {}
static void o_mode(void *d, struct wl_output *o, uint32_t f, int32_t w, int32_t h, int32_t r) {}
static void o_done(void *d, struct wl_output *o) {}
static void o_scale(void *d, struct wl_output *o, int32_t s) {}
static void o_name(void *d, struct wl_output *o, const char *name) { snprintf(outs[(long)d].name, 64, "%s", name); }
static void o_desc(void *d, struct wl_output *o, const char *desc) {}
static const struct wl_output_listener olis = { o_geometry, o_mode, o_done, o_scale, o_name, o_desc };

static void reg_global(void *d, struct wl_registry *r, uint32_t id, const char *iface, uint32_t ver)
{
	if (!strcmp(iface, "wl_output") && ver >= 4 && nouts < MAXO) {
		outs[nouts].o = wl_registry_bind(r, id, &wl_output_interface, 4);
		wl_output_add_listener(outs[nouts].o, &olis, (void *)(long)nouts);
		nouts++;
	} else if (!strcmp(iface, "org_kde_kwin_dpms_manager")) {
		mgr = wl_registry_bind(r, id, &org_kde_kwin_dpms_manager_interface, 1);
	}
}
static void reg_remove(void *d, struct wl_registry *r, uint32_t id) {}
static const struct wl_registry_listener rlis = { reg_global, reg_remove };

int main(int argc, char **argv)
{
	if (argc != 3 || (strcmp(argv[2], "on") && strcmp(argv[2], "off"))) {
		fprintf(stderr, "usage: %s <connector> on|off\n", argv[0]);
		return 2;
	}
	struct wl_display *dpy = wl_display_connect(NULL);
	if (!dpy) { fprintf(stderr, "no wayland display\n"); return 1; }
	struct wl_registry *reg = wl_display_get_registry(dpy);
	wl_registry_add_listener(reg, &rlis, NULL);
	wl_display_roundtrip(dpy);	/* globals */
	wl_display_roundtrip(dpy);	/* output names */
	if (!mgr) { fprintf(stderr, "compositor has no org_kde_kwin_dpms_manager\n"); return 1; }
	for (int i = 0; i < nouts; i++) {
		if (strcmp(outs[i].name, argv[1]))
			continue;
		struct org_kde_kwin_dpms *d = org_kde_kwin_dpms_manager_get(mgr, outs[i].o);
		org_kde_kwin_dpms_set(d, !strcmp(argv[2], "on") ? ORG_KDE_KWIN_DPMS_MODE_ON : ORG_KDE_KWIN_DPMS_MODE_OFF);
		wl_display_roundtrip(dpy);
		wl_display_roundtrip(dpy);
		return 0;
	}
	fprintf(stderr, "no output named %s (have:", argv[1]);
	for (int i = 0; i < nouts; i++) fprintf(stderr, " %s", outs[i].name);
	fprintf(stderr, ")\n");
	return 1;
}
