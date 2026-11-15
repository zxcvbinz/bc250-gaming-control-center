/* SPDX-License-Identifier: GPL-3.0-or-later
 * Copyright (C) 2026 zxcvbinz and contributors */
/* libbc250_gl.so: LD_PRELOAD for OpenGL games (GLX and EGL).
 * Hooks the swap calls, including when the game resolves them through
 * dlsym / glXGetProcAddress / eglGetProcAddress (SDL does this). */
#include "common.h"
#include <dlfcn.h>

#define API __attribute__((visibility("default")))
typedef void (*fn_glx_swap)(void *, unsigned long);
typedef unsigned (*fn_egl_swap)(void *, void *);
typedef unsigned (*fn_egl_swap_dmg)(void *, void *, int *, int);
typedef void *(*fn_getproc)(const char *);

static void *(*real_dlsym)(void *, const char *);
static fn_glx_swap r_glx_swap;
static fn_egl_swap r_egl_swap;
static fn_egl_swap_dmg r_egl_swap_khr, r_egl_swap_ext;
static fn_getproc r_glx_gpa, r_glx_gpa_arb, r_egl_gpa;

static void init_dlsym(void) {
    if (real_dlsym) return;
    real_dlsym = dlvsym(RTLD_NEXT, "dlsym", "GLIBC_2.34");
    if (!real_dlsym) real_dlsym = dlvsym(RTLD_NEXT, "dlsym", "GLIBC_2.2.5");
}

static int is_ours(void *p);

/* Find the real GL/EGL symbol. RTLD_NEXT fails when the game (SDL, .NET) loaded
 * libEGL/libGL with dlopen(RTLD_LOCAL): then ask the already-loaded libraries. */
static void *next_sym(const char *n) {
    init_dlsym();
    if (!real_dlsym) return NULL;
    void *p = real_dlsym(RTLD_NEXT, n);
    if (p && !is_ours(p)) return p;
    static const char *libs[] = { "libEGL.so.1", "libEGL.so", "libGLX.so.0", "libGL.so.1", "libGL.so",
                                  "libEGL_mesa.so.0", "libGLX_mesa.so.0", NULL };
    for (int i = 0; libs[i]; i++) {
        void *h = dlopen(libs[i], RTLD_LAZY | RTLD_NOLOAD);
        if (!h) continue;
        p = real_dlsym(h, n);
        dlclose(h);
        if (p && !is_ours(p)) return p;
    }
    return NULL;
}

API void glXSwapBuffers(void *dpy, unsigned long drawable) {
    if (!r_glx_swap) r_glx_swap = (fn_glx_swap)next_sym("glXSwapBuffers");
    bc_frame_tick(2);
    if (r_glx_swap) r_glx_swap(dpy, drawable);
}

API unsigned eglSwapBuffers(void *dpy, void *surf) {
    if (!r_egl_swap) r_egl_swap = (fn_egl_swap)next_sym("eglSwapBuffers");
    bc_frame_tick(2);
    return r_egl_swap ? r_egl_swap(dpy, surf) : 0;
}

API unsigned eglSwapBuffersWithDamageKHR(void *dpy, void *surf, int *rects, int n) {
    if (!r_egl_swap_khr) r_egl_swap_khr = (fn_egl_swap_dmg)next_sym("eglSwapBuffersWithDamageKHR");
    bc_frame_tick(2);
    return r_egl_swap_khr ? r_egl_swap_khr(dpy, surf, rects, n) : 0;
}

API unsigned eglSwapBuffersWithDamageEXT(void *dpy, void *surf, int *rects, int n) {
    if (!r_egl_swap_ext) r_egl_swap_ext = (fn_egl_swap_dmg)next_sym("eglSwapBuffersWithDamageEXT");
    bc_frame_tick(2);
    return r_egl_swap_ext ? r_egl_swap_ext(dpy, surf, rects, n) : 0;
}

/* true if p points inside this library (one of our own hooks) */
static int is_ours(void *p) {
    static void *self_base;
    Dl_info a;
    if (!self_base) {
        if (dladdr((void *)is_ours, &a)) self_base = a.dli_fbase;
    }
    return p && dladdr(p, &a) && a.dli_fbase == self_base;
}

/* map a GL symbol name to our hook, remembering the real function */
static void *hook_for(const char *n, void *real) {
    if (!n || !real) return real;
    if (is_ours(real)) {          /* lookup in global scope found our export */
        void *r = next_sym(n);
        if (!r) return real;
        real = r;
    }
    if (!strcmp(n, "glXSwapBuffers")) { r_glx_swap = real; return (void *)glXSwapBuffers; }
    if (!strcmp(n, "eglSwapBuffers")) { r_egl_swap = real; return (void *)eglSwapBuffers; }
    if (!strcmp(n, "eglSwapBuffersWithDamageKHR")) { r_egl_swap_khr = real; return (void *)eglSwapBuffersWithDamageKHR; }
    if (!strcmp(n, "eglSwapBuffersWithDamageEXT")) { r_egl_swap_ext = real; return (void *)eglSwapBuffersWithDamageEXT; }
    return real;
}

API void *glXGetProcAddress(const char *n);
API void *glXGetProcAddressARB(const char *n);
API void *eglGetProcAddress(const char *n);

API void *glXGetProcAddress(const char *n) {
    if (!r_glx_gpa) r_glx_gpa = (fn_getproc)next_sym("glXGetProcAddress");
    return r_glx_gpa ? hook_for(n, r_glx_gpa(n)) : NULL;
}

API void *glXGetProcAddressARB(const char *n) {
    if (!r_glx_gpa_arb) r_glx_gpa_arb = (fn_getproc)next_sym("glXGetProcAddressARB");
    return r_glx_gpa_arb ? hook_for(n, r_glx_gpa_arb(n)) : NULL;
}

API void *eglGetProcAddress(const char *n) {
    if (!r_egl_gpa) r_egl_gpa = (fn_getproc)next_sym("eglGetProcAddress");
    return r_egl_gpa ? hook_for(n, r_egl_gpa(n)) : NULL;
}

API void *dlsym(void *h, const char *n) {
    init_dlsym();
    if (!real_dlsym) return NULL;
    void *real = real_dlsym(h, n);
    if (n[0] != 'g' && n[0] != 'e') return real;
    int gpa = !strcmp(n, "glXGetProcAddress") || !strcmp(n, "glXGetProcAddressARB") || !strcmp(n, "eglGetProcAddress");
    if (gpa && is_ours(real)) {   /* global lookup returned our export: find the real one */
        real = next_sym(n);
        if (!real) return NULL;
    }
    if (!strcmp(n, "glXGetProcAddress")) { if (real) r_glx_gpa = real; return real ? (void *)glXGetProcAddress : NULL; }
    if (!strcmp(n, "glXGetProcAddressARB")) { if (real) r_glx_gpa_arb = real; return real ? (void *)glXGetProcAddressARB : NULL; }
    if (!strcmp(n, "eglGetProcAddress")) { if (real) r_egl_gpa = real; return real ? (void *)eglGetProcAddress : NULL; }
    return hook_for(n, real);
}
