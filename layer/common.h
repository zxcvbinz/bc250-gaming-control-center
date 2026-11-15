/* SPDX-License-Identifier: GPL-3.0-or-later
 * Copyright (C) 2026 zxcvbinz and contributors */
/* BC-250 frame engine: shared memory + frame limiter (Vulkan layer and GL preload).
 *
 * Every presenting process creates  <dir>/fps-<pid>-<rand>.bin  (struct bc_frame)
 * and maps <dir>/control.bin (struct bc_control) written by bc250d.
 * <dir> = $BC250_DIR, else /dev/shm/bc250-<uid>.
 */
#pragma once
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#define BC_MAGIC 0x30353242u /* "B250" */
#define BC_VERSION 1
#define BC_RING 256
#define BC_NO_OVERRIDE 0xFFFFFFFFu

struct bc_control {           /* written by bc250d */
    uint32_t magic, version;
    uint32_t fps_limit;       /* 0 = no limit */
    uint32_t limit_enabled;   /* Shift+F1 toggles this */
    uint32_t engine_enabled;  /* 0 = layer stays passive (no counting, no limiting) */
    uint32_t pad[11];
};

struct bc_frame {             /* written by the game process */
    uint32_t magic, version;
    uint32_t pid, api;        /* api: 1 = Vulkan, 2 = OpenGL */
    char name[32];
    char appid[16];
    uint64_t frames;
    uint64_t last_ns;
    uint32_t ring_idx;
    uint32_t limit_override;  /* written by bc250d (game profile); BC_NO_OVERRIDE = global */
    uint32_t limit_active;    /* limit actually applied on the last frame */
    uint32_t pad;
    uint32_t ring[BC_RING];   /* frame times in microseconds */
};

static struct bc_control *bc_ctl;
static struct bc_frame *bc_fr;
static pthread_once_t bc_once = PTHREAD_ONCE_INIT;
static uint64_t bc_prev_ns, bc_next_ns;
static pthread_mutex_t bc_lock = PTHREAD_MUTEX_INITIALIZER;

static uint64_t bc_now(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ull + ts.tv_nsec;
}

static const char *bc_dir(void) {
    static char buf[256];
    const char *e = getenv("BC250_DIR");
    if (e && *e) return e;
    snprintf(buf, sizeof buf, "/dev/shm/bc250-%u", (unsigned)getuid());
    return buf;
}

static void bc_procname(char *out, size_t n) {
    /* argv[0] basename (works for wine: "C:\\...\\Game.exe"), fallback comm */
    char buf[512] = {0};
    int fd = open("/proc/self/cmdline", O_RDONLY | O_CLOEXEC);
    if (fd >= 0) {
        ssize_t r = read(fd, buf, sizeof buf - 1);
        close(fd);
        if (r > 0) {
            buf[r] = 0;
            const char *b = buf;
            for (const char *p = buf; *p; p++)
                if (*p == '/' || *p == '\\') b = p + 1;
            /* wine-preloader / wine64: use next argument */
            if (!strncmp(b, "wine", 4) && strlen(buf) + 1 < (size_t)r) {
                const char *a = buf + strlen(buf) + 1;
                b = a;
                for (const char *p = a; *p; p++)
                    if (*p == '/' || *p == '\\') b = p + 1;
            }
            snprintf(out, n, "%s", b);
            if (*out) return;
        }
    }
    fd = open("/proc/self/comm", O_RDONLY | O_CLOEXEC);
    if (fd >= 0) {
        ssize_t r = read(fd, out, n - 1);
        close(fd);
        if (r > 0) { out[r] = 0; char *nl = strchr(out, '\n'); if (nl) *nl = 0; return; }
    }
    snprintf(out, n, "unknown");
}

static void *bc_map(const char *path, size_t size, int create) {
    int fd = open(path, (create ? O_CREAT : 0) | O_RDWR | O_CLOEXEC, 0600);
    if (fd < 0) return NULL;
    if (create && ftruncate(fd, size) != 0) { close(fd); return NULL; }
    struct stat st;
    if (fstat(fd, &st) != 0 || (size_t)st.st_size < size) { close(fd); return NULL; }
    void *m = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    close(fd);
    return m == MAP_FAILED ? NULL : m;
}

static int bc_api;

static void bc_init(void) {
    const char *d = bc_dir();
    mkdir(d, 0700);
    char path[400];
    snprintf(path, sizeof path, "%s/control.bin", d);
    bc_ctl = bc_map(path, sizeof(struct bc_control), 0);
    if (bc_ctl && bc_ctl->magic != BC_MAGIC) { munmap(bc_ctl, sizeof *bc_ctl); bc_ctl = NULL; }
    if (bc_ctl && !bc_ctl->engine_enabled) return;
    unsigned r = (unsigned)(bc_now() ^ ((uint64_t)getpid() << 16));
    snprintf(path, sizeof path, "%s/fps-%d-%08x.bin", d, (int)getpid(), r);
    struct bc_frame *f = bc_map(path, sizeof(struct bc_frame), 1);
    if (!f) return;
    memset(f, 0, sizeof *f);
    f->version = BC_VERSION;
    f->pid = getpid();
    f->api = bc_api;
    f->limit_override = BC_NO_OVERRIDE;
    bc_procname(f->name, sizeof f->name);
    const char *a = getenv("SteamAppId");
    if (!a || !*a || !strcmp(a, "0")) a = getenv("SteamGameId");
    if (a) snprintf(f->appid, sizeof f->appid, "%s", a);
    __atomic_store_n(&f->magic, BC_MAGIC, __ATOMIC_RELEASE);
    bc_fr = f;
}

static void bc_sleep_until(uint64_t t) {
    uint64_t now = bc_now();
    if (t <= now) return;
    if (t - now > 300000) { /* sleep, then spin the last 0.3 ms for precision */
        uint64_t s = t - 300000;
        struct timespec ts = { s / 1000000000ull, s % 1000000000ull };
        while (clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &ts, NULL) == EINTR) {}
    }
    while (bc_now() < t) {}
}

/* call right before handing the frame to the driver */
static void bc_frame_tick(int api) {
    if (!bc_api) bc_api = api;
    pthread_once(&bc_once, bc_init);
    if (bc_ctl && !bc_ctl->engine_enabled) return;
    pthread_mutex_lock(&bc_lock);
    static unsigned retry;
    if (!bc_ctl && (++retry % 240) == 0) { /* bc250d started after the game */
        char path[400];
        snprintf(path, sizeof path, "%s/control.bin", bc_dir());
        struct bc_control *c = bc_map(path, sizeof(struct bc_control), 0);
        if (c && c->magic == BC_MAGIC) bc_ctl = c;
        else if (c) munmap(c, sizeof *c);
    }
    uint32_t limit = 0;
    if (bc_ctl && bc_ctl->limit_enabled) limit = bc_ctl->fps_limit;
    if (bc_fr && bc_fr->limit_override != BC_NO_OVERRIDE) limit = bc_fr->limit_override;
    if (limit >= 10 && limit <= 1000) {
        uint64_t interval = 1000000000ull / limit;
        uint64_t now = bc_now();
        if (bc_next_ns == 0 || now > bc_next_ns + interval) bc_next_ns = now;
        bc_sleep_until(bc_next_ns);
        bc_next_ns += interval;
    } else {
        bc_next_ns = 0;
    }
    uint64_t now = bc_now();
    if (bc_fr) {
        if (bc_prev_ns) {
            uint64_t us = (now - bc_prev_ns) / 1000;
            uint32_t i = bc_fr->ring_idx;
            bc_fr->ring[i % BC_RING] = us > 0xFFFFFFFFu ? 0xFFFFFFFFu : (uint32_t)us;
            __atomic_store_n(&bc_fr->ring_idx, i + 1, __ATOMIC_RELEASE);
        }
        bc_fr->limit_active = limit;
        bc_fr->last_ns = now;
        __atomic_add_fetch(&bc_fr->frames, 1, __ATOMIC_RELEASE);
    }
    bc_prev_ns = now;
    pthread_mutex_unlock(&bc_lock);
}
