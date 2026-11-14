#!/usr/bin/env python3
"""
Prove the GPU is really rendering. Runs ON THE DEVICE.

    python3 gl-probe.py

No packages needed: the Fedora Mobile image has no mesa-demos, no glmark2 and
no vulkan-tools, and there is no network on this phone to install them. So
this drives libEGL/libGLESv2 directly through ctypes on a surfaceless display,
which needs nothing but a render node.

What it checks, in order of how much it proves:
  1. a render node exists and EGL can open it
  2. GL_RENDERER -- "FD660" means freedreno on the Adreno 660. "llvmpipe" or
     "softpipe" means EGL fell back to software and the GPU is NOT in use,
     which is the failure this script exists to catch
  3. a real draw: render into an FBO and read the pixels back. Context
     creation alone can succeed without the GPU ever executing anything
  4. a crude throughput number, so "the GPU is up" can be distinguished from
     "the GPU is up and faster than the CPU was"
"""
import ctypes as C
import os
import sys
import time

os.environ.setdefault("EGL_PLATFORM", "surfaceless")

EGL_NO_SURFACE = C.c_void_p(0)
EGL_NO_CONTEXT = C.c_void_p(0)
EGL_DEFAULT_DISPLAY = C.c_void_p(0)
EGL_NO_DISPLAY = None

EGL_OPENGL_ES_API = 0x30A0
EGL_OPENGL_ES2_BIT = 0x0004
EGL_RENDERABLE_TYPE = 0x3040
EGL_SURFACE_TYPE = 0x3033
EGL_PBUFFER_BIT = 0x0001
EGL_RED_SIZE = 0x3024
EGL_NONE = 0x3038
EGL_CONTEXT_CLIENT_VERSION = 0x3098
EGL_VENDOR = 0x3053
EGL_VERSION = 0x3054

GL_VENDOR = 0x1F00
GL_RENDERER = 0x1F01
GL_VERSION = 0x1F02
GL_COLOR_BUFFER_BIT = 0x4000
GL_FRAMEBUFFER = 0x8D40
GL_RENDERBUFFER = 0x8D41
GL_COLOR_ATTACHMENT0 = 0x8CE0
GL_RGBA8 = 0x8058
GL_RGBA = 0x1908
GL_UNSIGNED_BYTE = 0x1401
GL_FRAMEBUFFER_COMPLETE = 0x8CD5
GL_TRIANGLES = 0x0004
GL_FLOAT = 0x1406
GL_VERTEX_SHADER = 0x8B31
GL_FRAGMENT_SHADER = 0x8B30
GL_COMPILE_STATUS = 0x8B81
GL_LINK_STATUS = 0x8B82


def die(msg):
    print("FAIL: " + msg)
    sys.exit(1)


egl = C.CDLL("libEGL.so.1")
gl = C.CDLL("libGLESv2.so.2")

egl.eglGetDisplay.restype = C.c_void_p
egl.eglGetDisplay.argtypes = [C.c_void_p]
egl.eglQueryString.restype = C.c_char_p
egl.eglQueryString.argtypes = [C.c_void_p, C.c_int]
egl.eglCreateContext.restype = C.c_void_p
egl.eglCreateContext.argtypes = [C.c_void_p, C.c_void_p, C.c_void_p,
                                 C.POINTER(C.c_int)]
egl.eglMakeCurrent.argtypes = [C.c_void_p, C.c_void_p, C.c_void_p, C.c_void_p]
gl.glGetString.restype = C.c_char_p
gl.glGetString.argtypes = [C.c_int]
gl.glShaderSource.argtypes = [C.c_uint, C.c_int, C.POINTER(C.c_char_p),
                              C.c_void_p]

print("render nodes:", sorted(f for f in os.listdir("/dev/dri")
                              if f.startswith("render")) or "NONE")

dpy = egl.eglGetDisplay(EGL_DEFAULT_DISPLAY)
if not dpy:
    die("eglGetDisplay returned EGL_NO_DISPLAY")
major, minor = C.c_int(), C.c_int()
if not egl.eglInitialize(C.c_void_p(dpy), C.byref(major), C.byref(minor)):
    die("eglInitialize failed -- no usable driver")
print(f"EGL {major.value}.{minor.value}  vendor "
      f"{egl.eglQueryString(C.c_void_p(dpy), EGL_VENDOR).decode()}")

egl.eglBindAPI(EGL_OPENGL_ES_API)
attrs = (C.c_int * 9)(EGL_SURFACE_TYPE, EGL_PBUFFER_BIT,
                      EGL_RENDERABLE_TYPE, EGL_OPENGL_ES2_BIT,
                      EGL_RED_SIZE, 8,
                      EGL_NONE, 0, 0)
cfg = C.c_void_p()
n = C.c_int()
if not egl.eglChooseConfig(C.c_void_p(dpy), attrs, C.byref(cfg), 1,
                           C.byref(n)) or n.value == 0:
    die("eglChooseConfig found no config")

ctx_attrs = (C.c_int * 3)(EGL_CONTEXT_CLIENT_VERSION, 2, EGL_NONE)
ctx = egl.eglCreateContext(C.c_void_p(dpy), cfg, EGL_NO_CONTEXT, ctx_attrs)
if not ctx:
    die("eglCreateContext failed")
if not egl.eglMakeCurrent(C.c_void_p(dpy), EGL_NO_SURFACE, EGL_NO_SURFACE,
                          C.c_void_p(ctx)):
    die("eglMakeCurrent failed (no EGL_KHR_surfaceless_context?)")

vendor = gl.glGetString(GL_VENDOR).decode()
renderer = gl.glGetString(GL_RENDERER).decode()
version = gl.glGetString(GL_VERSION).decode()
print(f"GL_VENDOR   {vendor}")
print(f"GL_RENDERER {renderer}")
print(f"GL_VERSION  {version}")

soft = any(s in renderer.lower() for s in ("llvmpipe", "softpipe", "swrast"))

# --- a real draw into an FBO, then read it back -------------------------
W = H = 256
fbo, rb = C.c_uint(), C.c_uint()
gl.glGenFramebuffers(1, C.byref(fbo))
gl.glGenRenderbuffers(1, C.byref(rb))
gl.glBindRenderbuffer(GL_RENDERBUFFER, rb)
gl.glRenderbufferStorage(GL_RENDERBUFFER, GL_RGBA8, W, H)
gl.glBindFramebuffer(GL_FRAMEBUFFER, fbo)
gl.glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                             GL_RENDERBUFFER, rb)
if gl.glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE:
    die("FBO incomplete")

VS = b"attribute vec2 p; void main(){ gl_Position = vec4(p,0.0,1.0); }"
FS = b"precision mediump float; void main(){ gl_FragColor = vec4(0.0,1.0,0.0,1.0); }"


def shader(kind, src):
    s = gl.glCreateShader(kind)
    buf = C.c_char_p(src)
    gl.glShaderSource(s, 1, C.byref(buf), None)
    gl.glCompileShader(s)
    ok = C.c_int()
    gl.glGetShaderiv(s, GL_COMPILE_STATUS, C.byref(ok))
    if not ok.value:
        log = C.create_string_buffer(2048)
        gl.glGetShaderInfoLog(s, 2048, None, log)
        die("shader compile failed: " + log.value.decode())
    return s


prog = gl.glCreateProgram()
gl.glAttachShader(prog, shader(GL_VERTEX_SHADER, VS))
gl.glAttachShader(prog, shader(GL_FRAGMENT_SHADER, FS))
gl.glLinkProgram(prog)
ok = C.c_int()
gl.glGetProgramiv(prog, GL_LINK_STATUS, C.byref(ok))
if not ok.value:
    die("program link failed")
gl.glUseProgram(prog)

verts = (C.c_float * 6)(-1.0, -1.0, 3.0, -1.0, -1.0, 3.0)   # covers the FBO
loc = gl.glGetAttribLocation(prog, b"p")
gl.glEnableVertexAttribArray(loc)
gl.glVertexAttribPointer(loc, 2, GL_FLOAT, 0, 0, verts)

gl.glViewport(0, 0, W, H)
gl.glClearColor(C.c_float(0.0), C.c_float(0.0), C.c_float(1.0), C.c_float(1.0))
gl.glClear(GL_COLOR_BUFFER_BIT)
gl.glDrawArrays(GL_TRIANGLES, 0, 3)
gl.glFinish()

px = C.create_string_buffer(W * H * 4)
gl.glReadPixels(0, 0, W, H, GL_RGBA, GL_UNSIGNED_BYTE, px)
mid = px.raw[(H // 2 * W + W // 2) * 4:(H // 2 * W + W // 2) * 4 + 4]
print("centre pixel", tuple(mid), "(expect (0, 255, 0, 255) green)")
drew = mid[1] > 200 and mid[0] < 50

# --- crude throughput: redraw the full-FBO triangle many times ----------
N = 2000
gl.glFinish()
t0 = time.time()
for _ in range(N):
    gl.glDrawArrays(GL_TRIANGLES, 0, 3)
gl.glFinish()
el = time.time() - t0
print(f"{N} full-{W}x{H} draws in {el:.2f}s "
      f"({N*W*H/el/1e6:.1f} Mpix/s fill)")

print()
if not drew:
    die("the draw did not land -- context is up but nothing rendered")
if soft:
    print("RESULT: rendering works but it is SOFTWARE "
          f"({renderer}). The GPU is not being used.")
    sys.exit(2)
print(f"RESULT: hardware rendering on {renderer}")
