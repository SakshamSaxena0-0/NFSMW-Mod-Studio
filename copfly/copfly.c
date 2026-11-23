#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "hooks.h"

typedef struct { float x, y, z; } vec3;
#define TC __attribute__((thiscall))
typedef void  (TC *OnImpact_t)(void *self, void *arm, void *normal, float a, float b, void *surface, void *other);
typedef void *(TC *QI_t)(void *list, void *iid);
typedef int   (TC *GetType_t)(void *self);
typedef vec3 *(TC *GetVec_t)(void *self);
typedef void  (TC *SetVec_t)(void *self, const vec3 *v);
typedef char  (TC *IsDestroyed_t)(void *self);
typedef void  (TC *Destroy_t)(void *self);
typedef char  (TC *OnTask_t)(void *self, void *task, float dt);
typedef void  (TC *Simulate_t)(void *self, float dt);

#define COP_IMPACT   ((OnImpact_t)COP_IMPACT_ADDR)
#define DV_IMPACT    ((OnImpact_t)DV_IMPACT_ADDR)
#define QI           ((QI_t)0x005D59F0)
#define IID_RB       ((void *)0x004039C0)
#define IID_DAMAGE   ((void *)0x00405000)
#define VT_COP_DMG   ((void *)0x008AD40C)
#define TASK_SLOT    ((void **)0x008AD434)
#define COP_TASK     ((OnTask_t)0x006B6730)
#define RBCOP_SIM    ((Simulate_t)RBCOP_SIM_ADDR)

static float g_margin = 0.1f, g_up = 14.0f, g_push = 0.5f, g_kick = 5.0f, g_spin = 3.0f, g_minspeed = 4.0f, g_plspeed = 5.0f;
static int g_wreck = 0, g_log = 1, g_upaxis = 1, g_nlaunch = 0, g_ncop = 0, g_nplayer = 0;
static int g_launch = 1, g_nkeep = 0, g_nwall = 0;
static int g_keep_cops = 0, g_keep_traffic = 0, g_keep_walls = 0, g_keep = 0;
static char g_logpath[MAX_PATH];

static void **vt(void *obj) { return *(void ***)obj; }
static void logmsg(const char *fmt, ...) {
    if (!g_log) return;
    FILE *f = fopen(g_logpath, "a"); if (!f) return;
    va_list a; va_start(a, fmt); vfprintf(f, fmt, a); va_end(a); fclose(f);
}
static int vtype(void *o) { return o ? ((GetType_t)vt(o)[1])(o) : -1; }

static int known_simable(void *o) { void **v = o ? vt(o) : 0; return v && v[1] == (void *)0x00686A30 && v[9] == (void *)0x00686A10; }
static int is_player(void *o) { return known_simable(o) && ((IsDestroyed_t)vt(o)[9])(o) != 0; }
static void *com(void *o) { return o ? *(void **)((char *)o + 4) : 0; }

typedef struct { void *iid, *ptr; } iface_t;
static int ifaces(void *c, iface_t **beg, iface_t **end) {
    if (!c) return 0; *beg = *(iface_t **)((char *)c + 4); *end = *(iface_t **)((char *)c + 8);
    return *beg && *end >= *beg && (*end - *beg) < 256;
}
static int is_cop_vt(void *v) {
    return v == (void *)0x008AD438 || v == (void *)0x008AD430 || v == (void *)0x008AD40C ||
           v == (void *)0x008AD408 || v == (void *)0x008AD3FC || v == (void *)0x008AD3F4;
}
static void *cop_damage(void *simable) {
    iface_t *b, *e; if (!ifaces(com(simable), &b, &e)) return 0;
    for (iface_t *p = b; p < e; p++)
        if (p->ptr && is_cop_vt((void *)vt(p->ptr))) {
            void *d = QI(com(simable), IID_DAMAGE);
            if (d && (void *)vt(d) == VT_COP_DMG) return d;
            void *v = (void *)vt(p->ptr);
            char *base = (char *)p->ptr - (v == (void *)0x008AD430 ? 0x08 : v == (void *)0x008AD40C ? 0x4c :
                         v == (void *)0x008AD408 ? 0x54 : v == (void *)0x008AD3FC ? 0x58 : v == (void *)0x008AD3F4 ? 0x60 : 0);
            return base + 0x4c;
        }
    return 0;
}
static void dump(const char *tag, void *simable) {
    iface_t *b, *e; FILE *f = g_log ? fopen(g_logpath, "a") : 0; if (!f) return;
    fprintf(f, "%s simable %p vt %p com %p:", tag, simable, simable ? (void *)vt(simable) : 0, com(simable));
    if (ifaces(com(simable), &b, &e)) for (iface_t *p = b; p < e; p++) fprintf(f, " %p=%p", p->iid, p->ptr ? (void *)vt(p->ptr) : 0);
    else fprintf(f, " (no interface list)");
    fprintf(f, "\n"); fclose(f);
}
static void *g_seen[16]; static int g_nseen = 0;
static int first_time(void *o) {
    for (int i = 0; i < g_nseen; i++) if (g_seen[i] == o) return 0;
    if (g_nseen < 16) g_seen[g_nseen++] = o; return 1;
}

static void *g_player_rb = 0;
static int rb_ok(void *rb) {
    if (!rb || IsBadReadPtr(rb, 0x30)) return 0;
    void **v = vt(rb);
    if (IsBadReadPtr(v, 0x90) || v[28] != (void *)0x00671010 || v[35] != (void *)0x00671060) return 0;
    void **pp = *(void ***)((char *)rb + 0x28);
    return pp && !IsBadReadPtr(pp, 4) && *pp && !IsBadReadPtr(*pp, 0x40);
}

static float *rb_state(void *rb) { return *(float **)*(void **)((char *)rb + 0x28); }
static vec3 *rb_vec(void *rb, int off) { return (vec3 *)((char *)rb_state(rb) + off); }
static vec3 rb_pos(void *rb) { return *rb_vec(rb, 0x10); }

static vec3 rb_dim(void *rb) {
    vec3 d = *(vec3 *)((char *)rb + 0x90);
    if (!(d.x > 0.2f && d.x < 5.0f && d.y > 0.2f && d.y < 5.0f && d.z > 0.5f && d.z < 8.0f)) d = (vec3){ 1.0f, 0.7f, 2.4f };
    if (d.x > 1.4f) { d.x *= 0.5f; d.y *= 0.5f; d.z *= 0.5f; }
    return d;
}
static void rb_axes(void *rb, float r[2], float f[2]) {
    vec3 a = *rb_vec(rb, 0x70), b = *rb_vec(rb, 0x90);
    float la = sqrtf(a.x * a.x + a.z * a.z), lb = sqrtf(b.x * b.x + b.z * b.z);
    if (la < 0.1f) la = 1; if (lb < 0.1f) lb = 1;
    r[0] = a.x / la; r[1] = a.z / la; f[0] = b.x / lb; f[1] = b.z / lb;
}

static float box_gap(void *cop, void *pl, float nrm[2]) {
    vec3 ca = rb_pos(cop), pa = rb_pos(pl), cd = rb_dim(cop), pd = rb_dim(pl);
    float cr[2], cf[2], pr[2], pf[2]; rb_axes(cop, cr, cf); rb_axes(pl, pr, pf);
    float dx = ca.x - pa.x, dz = ca.z - pa.z, dl = sqrtf(dx * dx + dz * dz);
    nrm[0] = dl > 0.01f ? dx / dl : 0; nrm[1] = dl > 0.01f ? dz / dl : 0;
    float *ax[4] = { cr, cf, pr, pf }, gap = -1e9f;
    for (int i = 0; i < 4; i++) {
        float *u = ax[i];
        float rc = cd.x * fabsf(cr[0] * u[0] + cr[1] * u[1]) + cd.z * fabsf(cf[0] * u[0] + cf[1] * u[1]);
        float rp = pd.x * fabsf(pr[0] * u[0] + pr[1] * u[1]) + pd.z * fabsf(pf[0] * u[0] + pf[1] * u[1]);
        float g = fabsf(dx * u[0] + dz * u[1]) - rc - rp;
        if (g > gap) gap = g;
    }
    float gy = fabsf(ca.y - pa.y) - cd.y - pd.y;
    return gy > gap ? gy : gap;
}

static void *g_recent[8]; static DWORD g_recent_t[8];
static int recently(void *rb) {
    DWORD now = GetTickCount();
    for (int i = 0; i < 8; i++) if (g_recent[i] == rb && now - g_recent_t[i] < 3000) return 1;
    int o = 0; for (int i = 1; i < 8; i++) if (g_recent_t[i] < g_recent_t[o]) o = i;
    g_recent[o] = rb; g_recent_t[o] = now; return 0;
}


static void launch(void *copdmg, void *coprb, void *playerrb, float speed, const float nrm[2], const char *via) {
    if (!g_launch || !copdmg || !coprb) return;
    if (((IsDestroyed_t)vt(copdmg)[6])(copdmg)) return;
    vec3 cv = *rb_vec(coprb, 0x20);
    vec3 pv = playerrb ? *rb_vec(playerrb, 0x20) : (vec3){0, 0, 0};
    if (speed < g_minspeed) return;
    if (sqrtf(pv.x * pv.x + pv.z * pv.z) < g_plspeed) return;
    if (recently(coprb)) return;
    float f = speed / 30.0f; if (f < 0.35f) f = 0.35f; if (f > 1.0f) f = 1.0f;
    if (g_wreck) ((Destroy_t)vt(copdmg)[7])(copdmg);
    float h[3] = { pv.x, pv.y, pv.z }; h[g_upaxis] = 0;
    float n[3] = { nrm[0], 0, nrm[1] };
    float out[3] = { cv.x, cv.y, cv.z };
    for (int i = 0; i < 3; i++) out[i] += h[i] * g_push + n[i] * g_kick * f;
    out[g_upaxis] = (out[g_upaxis] > 0 ? out[g_upaxis] : 0) + g_up * f;
    vec3 nv = { out[0], out[1], out[2] }, spin = { g_spin * f * 0.6f, g_spin * f, g_spin * f * 0.4f };
    *rb_vec(coprb, 0x20) = nv;
    *rb_vec(coprb, 0x30) = spin;
    if (g_nlaunch++ < 30)
        logmsg("LAUNCH (%s, closing speed %.1f m/s): player vel (%.1f %.1f %.1f)  cop vel (%.1f %.1f %.1f) -> (%.1f %.1f %.1f)\n",
               via, speed, pv.x, pv.y, pv.z, cv.x, cv.y, cv.z, nv.x, nv.y, nv.z);
}


typedef struct { void *rb; DWORD t; float v; } closing_t;
static closing_t g_close[16];
static float closing(void *coprb, void *plrb, const float nrm[2]) {
    vec3 cv = *rb_vec(coprb, 0x20), pv = *rb_vec(plrb, 0x20);
    float v = (pv.x - cv.x) * nrm[0] + (pv.z - cv.z) * nrm[1];
    DWORD now = GetTickCount(); closing_t *e = 0, *old = &g_close[0];
    for (int i = 0; i < 16; i++) { if (g_close[i].rb == coprb) e = &g_close[i]; if (g_close[i].t < old->t) old = &g_close[i]; }
    if (!e) { e = old; e->rb = coprb; e->v = 0; e->t = 0; }
    if (v >= e->v || now - e->t > 400) { e->v = v; e->t = now; }
    return e->v;
}
static void contact(void *copdmg, void *coprb, void *plrb, const char *via) {
    if (!rb_ok(coprb) || !rb_ok(plrb)) return;
    float nrm[2]; box_gap(coprb, plrb, nrm);
    launch(copdmg, coprb, plrb, closing(coprb, plrb, nrm), nrm, via);
}

static void TC CopHook(void *self, void *arm, void *normal, float a, float b, void *surface, void *other) {
    COP_IMPACT(self, arm, normal, a, b, surface, other);
    if (vtype(other) != 2) return;
    int pl = is_player(other);
    if (g_ncop++ < 2) { dump("cop self", *(void **)((char *)self + 0x34)); dump("cop hit", other); }
    if (pl) contact((char *)self + 0x4c, *(void **)((char *)self + 0x8c), QI(com(other), IID_RB), "cop side");
}


#define HIST 24
typedef struct { DWORD t; vec3 v, w; } sample_t;
static sample_t g_hist[HIST]; static int g_hpos = 0;
static DWORD g_guard_until = 0; static vec3 g_guard_v, g_guard_w; static int g_guard_wall = 0;
static float hspeed(vec3 v) { return sqrtf(v.x * v.x + v.z * v.z); }
static DWORD g_t0;
static int upright(void *rb) { return rb_vec(rb, 0x80)->y > 0.85f; }

static void keep_record(void *rb) {
    sample_t *s = &g_hist[g_hpos++ % HIST];
    s->t = GetTickCount(); s->v = *rb_vec(rb, 0x20); s->w = *rb_vec(rb, 0x30);
}
static void keep_start(void *rb, int wall) {
    DWORD now = GetTickCount(); sample_t *best = 0;
    for (int i = 0; i < HIST; i++) {
        sample_t *s = &g_hist[i];
        if (s->t && now - s->t <= 150 && (!best || hspeed(s->v) > hspeed(best->v))) best = s;
    }
    if (!best || hspeed(best->v) < g_plspeed || !upright(rb)) return;
    if (now >= g_guard_until || hspeed(best->v) > hspeed(g_guard_v)) { g_guard_v = best->v; g_guard_w = best->w; }
    if (now >= g_guard_until) g_guard_wall = wall; else g_guard_wall |= wall;
    g_guard_until = now + 400;
    if (g_nkeep++ < 30) logmsg("KEEP SPEED (%s) at %lu ms: hit at %.1f m/s, now %.1f m/s\n", wall ? "wall" : "car",
                               now - g_t0, hspeed(g_guard_v), hspeed(*rb_vec(rb, 0x20)));
}
static void keep_apply(void *rb) {
    if (!g_keep || GetTickCount() >= g_guard_until || !rb_ok(rb)) return;
    if (!upright(rb)) {
        if (g_nkeep++ < 30) logmsg("KEEP SPEED stopped at %lu ms: car tilted (up %.2f)\n", GetTickCount() - g_t0, rb_vec(rb, 0x80)->y);
        g_guard_until = 0; return;
    }
    vec3 *v = rb_vec(rb, 0x20), *w = rb_vec(rb, 0x30);
    float cur = hspeed(*v), want = hspeed(g_guard_v);
    if (cur < 0.97f * want) {
        if (!g_guard_wall) { v->x = g_guard_v.x; v->z = g_guard_v.z; }
        else if (cur > 0.5f && (v->x * g_guard_v.x + v->z * g_guard_v.z) / (cur * want) > 0.25f) {
            v->x *= want / cur; v->z *= want / cur;
        }
    }
    float dw = fabsf(w->x - g_guard_w.x) + fabsf(w->y - g_guard_w.y) + fabsf(w->z - g_guard_w.z);
    if (dw > 0.5f) *w = g_guard_w;
}

static void TC CarHook(void *self, void *arm, void *normal, float a, float b, void *surface, void *other) {
    DV_IMPACT(self, arm, normal, a, b, surface, other);
    void *owner = *(void **)((char *)self + 0x34);
    if (is_player(owner)) {
        void *prb = *(void **)((char *)self + 0x8c);
        if (prb != g_player_rb && rb_ok(prb)) { g_player_rb = prb; logmsg("player car found (rigid body %p)\n", prb); }
    }
    if (vtype(other) != 2) {
        if (g_keep_walls && !other && is_player(owner)) {
            vec3 n = (normal && !IsBadReadPtr(normal, 12)) ? *(vec3 *)normal : (vec3){0, 0, 0};
            float nl = sqrtf(n.x * n.x + n.y * n.y + n.z * n.z);
            int level = nl > 0.5f && fabsf(n.y) < 0.6f * nl;
            if (g_nwall++ < 12) logmsg("player hit world: normal (%.2f %.2f %.2f) %s, a %.2f b %.2f\n", n.x, n.y, n.z, level ? "wall" : "ground/other", a, b);
            void *prb = *(void **)((char *)self + 0x8c);
            if (level && rb_ok(prb)) { keep_start(prb, 1); keep_apply(prb); }
        } else if (other && is_player(owner) && g_nwall < 12) {
            g_nwall++; logmsg("player hit non-vehicle %p type %d\n", other, vtype(other));
        }
        return;
    }
    if (!is_player(owner)) {
        if (g_nplayer < 20 && !known_simable(owner)) { g_nplayer++; logmsg("car hit vehicle: owner vt %p not recognised\n", owner ? (void *)vt(owner) : 0); }
        return;
    }
    void *dmg = cop_damage(other);
    int cop = dmg != 0;
    if (cop ? g_keep_cops : g_keep_traffic) {
        void *prb = *(void **)((char *)self + 0x8c);
        if (rb_ok(prb)) { keep_start(prb, 0); keep_apply(prb); }
    }
    if (first_time(other) && g_nplayer++ < 12) {
        logmsg("PLAYER hit vehicle, cop %s\n", cop ? "YES" : "no"); dump("  other", other);
        if (g_nplayer == 1) dump("  player", owner);
    }
    if (cop) contact(dmg, QI(com(other), IID_RB), *(void **)((char *)self + 0x8c), "player side");
}

static void report(void);
static void TC VehSimHook(void *self, float dt) {
    RBCOP_SIM(self, dt);
    void *owner = *(void **)((char *)self + 0x34), *rb = (char *)self + 0x50;
    if (rb != g_player_rb && is_player(owner) && rb_ok(rb)) { g_player_rb = rb; logmsg("player car found by physics step (rigid body %p)\n", rb); }
    if (rb == g_player_rb) {
        report();
        if (g_keep && rb_ok(rb)) { keep_apply(rb); keep_record(rb); }
    }
}

static int g_nsim = 0, g_ndim = 0;
static unsigned g_simcalls = 0, g_simok = 0; static DWORD g_lastrep = 0; static float g_mind = 1e9f;
static vec3 g_lastcop, g_lastpl;
static void report(void) {
    DWORD now = GetTickCount();
    if (now - g_lastrep < 2000 || g_nsim > 40) return;
    g_lastrep = now; g_nsim++;
    logmsg("cop physics calls %u (valid %u), nearest cop %.1f m, cop pos (%.1f %.1f %.1f) player pos (%.1f %.1f %.1f)\n",
           g_simcalls, g_simok, g_mind, g_lastcop.x, g_lastcop.y, g_lastcop.z, g_lastpl.x, g_lastpl.y, g_lastpl.z);
    g_mind = 1e9f;
}
static void TC SimHook(void *self, float dt) {
    RBCOP_SIM(self, dt);
    g_simcalls++;
    void *rb = (char *)self + 0x50, *prb = g_player_rb;
    if (rb_ok(rb) && rb_ok(prb)) {
        g_simok++;
        vec3 a = rb_pos(rb), b = rb_pos(prb);
        float dx = a.x - b.x, dy = a.y - b.y, dz = a.z - b.z, d = sqrtf(dx * dx + dy * dy + dz * dz);
        if (d < g_mind) { g_mind = d; g_lastcop = a; g_lastpl = b; }
        if (d < 15.0f) {
            float nrm[2], gap = box_gap(rb, prb, nrm), v = closing(rb, prb, nrm);
            if (gap <= g_margin) {
                void *owner = *(void **)((char *)self + 0x34);
                void *dmg = owner ? QI(com(owner), IID_DAMAGE) : 0;
                if (g_ndim < 6) { g_ndim++; vec3 cd = rb_dim(rb), pd = rb_dim(prb);
                    logmsg("contact: gap %.2f m, centres %.1f m apart, closing %.1f m/s, cop box %.2f %.2f %.2f, player box %.2f %.2f %.2f\n",
                           gap, d, v, cd.x, cd.y, cd.z, pd.x, pd.y, pd.z); }
                if (dmg && (void *)vt(dmg) == VT_COP_DMG) launch(dmg, rb, prb, v, nrm, "touch");
            }
        }
    }
    report();
}

typedef void (TC *Noise_t)(void *cam, void *m, float time, float k);
typedef void (*LookAt_t)(void *out, vec3 *from, vec3 *to, vec3 *up);
#define CAM_NOISE    ((Noise_t)CAM_NOISE_ADDR)
#define CAM_LOOKAT   ((LookAt_t)CAM_LOOKAT_ADDR)
#define DEG_UNITS    (65536.0f / 360.0f)

static int g_cam_fov = 0, g_cam_smooth = 0, g_cam_log = 0, g_ncamlog = 0;
static float g_fov_max = 12.0f, g_fov_start = 15.0f, g_fov_full = 70.0f, g_fov_resp = 0.35f;
static float g_smooth = 0.5f, g_shake = 0.0f;
static unsigned g_nfov = 0, g_nlook = 0, g_nnoise = 0;
static DWORD g_camrep = 0;
static void * __attribute__((used)) g_cam_mover = 0;
static char * __attribute__((used)) g_cam_ebp = 0;

static void camlog(int important, const char *fmt, ...) {
    if (!g_cam_log && !(important && g_log)) return;
    FILE *f = fopen(g_logpath, "a"); if (!f) return;
    va_list a; va_start(a, fmt); vfprintf(f, fmt, a); va_end(a); fclose(f);
}

typedef struct { void *mover; DWORD seen, tf, tl; float fov, extra; vec3 d, up, to; int valid, mode, back; } camstate_t;
static camstate_t g_cams[4];

static camstate_t *cam_state(void *m) {
    DWORD now = GetTickCount();
    camstate_t *o = &g_cams[0];
    for (int i = 0; i < 4; i++) {
        if (g_cams[i].mover == m) { g_cams[i].seen = now; return &g_cams[i]; }
        if (now - g_cams[i].seen > now - o->seen) o = &g_cams[i];
    }
    memset(o, 0, sizeof *o); o->mover = m; o->seen = now;
    return o;
}
static int mover_ok(void *m) {
    if (!m || IsBadReadPtr(m, 0xe4)) return 0;
    void **v = vt(m);
    return v && !IsBadReadPtr(v, 12) && v[2] == (void *)CAM_UPDATE_ADDR;
}
static int cam_mode(void *m) { return *(int *)((char *)m + 0x9c); }
static int cam_back(void *m) { return *((unsigned char *)m + 0xa1) != 0; }
static float cam_speed(void *m) {
    void *a = *(void **)((char *)m + 0x80);
    if (!a || IsBadReadPtr(a, 0x14)) return 0;
    float v = *(float *)((char *)a + 0x10);
    return isfinite(v) && v > 0 && v < 300 ? v : 0;
}
static float cam_dt(DWORD last, DWORD now) {
    char *bp = g_cam_ebp;
    if (bp && !IsBadReadPtr(bp + 8, 4)) {
        float d = *(float *)(bp + 8);
        if (isfinite(d) && d >= 0 && d < 0.25f) return d;
    }
    float d = (now - last) / 1000.0f;
    return d < 0 ? 0 : d > 0.1f ? 0.1f : d;
}
static float ease(float dt, float tau) { return tau > 0.001f ? 1.0f - expf(-dt / tau) : 1.0f; }
static vec3 v_add(vec3 a, vec3 b) { return (vec3){ a.x + b.x, a.y + b.y, a.z + b.z }; }
static vec3 v_sub(vec3 a, vec3 b) { return (vec3){ a.x - b.x, a.y - b.y, a.z - b.z }; }
static vec3 v_mul(vec3 a, float k) { return (vec3){ a.x * k, a.y * k, a.z * k }; }
static float v_dot(vec3 a, vec3 b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
static float v_len(vec3 a) { return sqrtf(v_dot(a, a)); }
static int v_ok(vec3 a) { return isfinite(a.x) && isfinite(a.y) && isfinite(a.z); }

static void cam_report(void *m, camstate_t *s) {
    DWORD now = GetTickCount();
    if (!g_cam_log || now - g_camrep < 2000 || g_ncamlog >= 60) return;
    g_camrep = now; g_ncamlog++;
    camlog(0, "camera: mode %d%s speed %.1f m/s, extra FOV %.1f deg, calls FOV %u smooth %u shake %u\n",
           cam_mode(m), cam_back(m) ? " (looking back)" : "", cam_speed(m), s->extra, g_nfov, g_nlook, g_nnoise);
}

static float __attribute__((used)) cam_fov(float base) {
    void *m = g_cam_mover;
    g_nfov++;
    if (!g_cam_fov || !isfinite(base) || base <= 0 || !mover_ok(m)) return base;
    camstate_t *s = cam_state(m);
    DWORD now = GetTickCount();
    float dt = cam_dt(s->tf, now), want = 0;
    int mode = cam_mode(m);
    if (mode >= 0 && mode <= 6) {
        float t = (cam_speed(m) - g_fov_start) / (g_fov_full - g_fov_start);
        t = t < 0 ? 0 : t > 1 ? 1 : t;
        want = g_fov_max * t * t * (3 - 2 * t);
    }
    if (!s->tf || now - s->tf > 1000) s->fov = want;
    else s->fov += (want - s->fov) * ease(dt, g_fov_resp);
    s->tf = now;
    float out = base + s->fov * DEG_UNITS, cap = 160.0f * DEG_UNITS;
    if (out > cap) out = base > cap ? base : cap;
    s->extra = (out - base) / DEG_UNITS;
    cam_report(m, s);
    return out;
}

static void cam_follow(camstate_t *s, void *m, vec3 *from, const vec3 *to, vec3 *up) {
    DWORD now = GetTickCount();
    float dt = cam_dt(s->tl, now);
    int mode = cam_mode(m), back = cam_back(m);
    vec3 d = v_sub(*from, *to);
    float len = v_len(d);
    int fresh = !s->valid || now - s->tl > 250 || mode != s->mode || back != s->back || v_len(v_sub(*to, s->to)) > 20.0f;
    s->tl = now; s->mode = mode; s->back = back; s->to = *to;
    if (mode < 2 || mode > 6 || back || !v_ok(d) || !v_ok(*up) || !(len > 0.5f && len < 60.0f)) { s->valid = 0; return; }
    if (fresh) { s->d = d; s->up = *up; s->valid = 1; return; }
    float a = ease(dt, g_smooth * 0.3f);
    s->d = v_add(s->d, v_mul(v_sub(d, s->d), a));
    vec3 dev = v_sub(s->d, d);
    float dl = v_len(dev), maxd = len * 0.15f * g_smooth;
    if (dl > maxd) s->d = v_add(d, v_mul(dev, maxd / dl));
    float sl = v_len(s->d);
    if (!(sl > 0.01f) || !v_ok(s->d)) { s->valid = 0; return; }
    s->d = v_mul(s->d, len / sl);
    *from = v_add(*to, s->d);
    float ul = v_len(*up);
    if (ul > 0.5f) {
        vec3 u = v_mul(*up, 1.0f / ul);
        s->up = v_add(s->up, v_mul(v_sub(u, s->up), a));
        float l = v_len(s->up);
        s->up = l > 0.01f ? v_mul(s->up, 1.0f / l) : u;
        if (v_dot(s->up, u) < 0.985f) s->up = u;
        *up = v_mul(s->up, ul);
    }
}

static void __attribute__((used)) cam_lookat(void *out, vec3 *from, vec3 *to, vec3 *up) {
    void *m = g_cam_mover;
    g_nlook++;
    if (g_cam_smooth && g_smooth > 0 && mover_ok(m) && from && to && up &&
        !IsBadWritePtr(from, 12) && !IsBadReadPtr(to, 12) && !IsBadWritePtr(up, 12)) {
        camstate_t *s = cam_state(m);
        cam_follow(s, m, from, to, up);
        cam_report(m, s);
    }
    CAM_LOOKAT(out, from, to, up);
}

static void TC NoiseHook(void *cam, void *m, float time, float k) {
    g_nnoise++;
    CAM_NOISE(cam, m, time, k * g_shake);
}

void FovStub(void);
void LookAtStub(void);
#define STR2(x) #x
#define STR(x) STR2(x)
__asm__(
    ".text\n"
    ".p2align 4\n"
    "_FovStub:\n"
    "    movl %esi, _g_cam_mover\n"
    "    movl %ebp, _g_cam_ebp\n"
    "    subl $4, %esp\n"
    "    fstps (%esp)\n"
    "    call _cam_fov\n"
    "    addl $4, %esp\n"
    "    movl $" STR(CAM_FTOL_ADDR) ", %eax\n"
    "    jmp *%eax\n"
    ".p2align 4\n"
    "_LookAtStub:\n"
    "    movl %esi, _g_cam_mover\n"
    "    movl %ebp, _g_cam_ebp\n"
    "    jmp _cam_lookat\n"
);

static float inic(const char *ini, const char *key, float def, float lo, float hi) {
    char buf[32], d[32], *end; snprintf(d, sizeof d, "%g", def);
    GetPrivateProfileStringA("Camera", key, d, buf, sizeof buf, ini);
    float v = strtof(buf, &end);
    if (end == buf || !isfinite(v)) return def;
    return v < lo ? lo : v > hi ? hi : v;
}
static int call_ok(unsigned char *site, unsigned target, const char *name) {
    if (IsBadReadPtr(site, 5) || site[0] != 0xE8) {
        camlog(1, "camera: %s at %p is not a call - camera not hooked\n", name, site); return 0;
    }
    unsigned got = (unsigned)(site + 5 + *(int *)(site + 1));
    if (got != target) {
        camlog(1, "camera: %s at %p calls %08x, expected %08x - camera not hooked\n", name, site, got, target); return 0;
    }
    return 1;
}
static void hook_call(unsigned char *site, void *fn, const char *name) {
    DWORD old;
    if (!VirtualProtect(site, 5, PAGE_EXECUTE_READWRITE, &old)) { camlog(1, "camera: could not unprotect %s\n", name); return; }
    *(int *)(site + 1) = (int)((char *)fn - (char *)(site + 5));
    VirtualProtect(site, 5, old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, 5);
    camlog(0, "camera: hooked %s at %p\n", name, site);
}
static void cam_setup(const char *ini) {
    g_cam_fov = GetPrivateProfileIntA("Camera", "FovSpeed", 0, ini) != 0;
    g_cam_smooth = GetPrivateProfileIntA("Camera", "SmoothCam", 0, ini) != 0;
    g_cam_log = GetPrivateProfileIntA("Camera", "Log", 0, ini) != 0;
    if (!g_cam_fov && !g_cam_smooth) return;
    g_fov_max = inic(ini, "FovMaxExtra", g_fov_max, 0, 30);
    g_fov_start = inic(ini, "FovStartSpeed", g_fov_start, 0, 100);
    g_fov_full = inic(ini, "FovFullSpeed", g_fov_full, 1, 150);
    if (g_fov_full < g_fov_start + 1) g_fov_full = g_fov_start + 1;
    g_fov_resp = inic(ini, "FovResponse", g_fov_resp, 0.02f, 5);
    g_smooth = inic(ini, "SmoothAmount", g_smooth, 0, 1);
    g_shake = inic(ini, "ShakeScale", g_shake, 0, 1);
    camlog(0, "camera settings: FovSpeed %d FovMaxExtra %.1f FovStartSpeed %.1f FovFullSpeed %.1f FovResponse %.2f SmoothCam %d SmoothAmount %.2f ShakeScale %.2f\n",
           g_cam_fov, g_fov_max, g_fov_start, g_fov_full, g_fov_resp, g_cam_smooth, g_smooth, g_shake);
    int ok = !IsBadReadPtr(CAM_UPDATE_SLOT, 4) && *CAM_UPDATE_SLOT == (void *)CAM_UPDATE_ADDR;
    if (!ok) camlog(1, "camera: chase camera update not found at %p - camera not hooked\n", CAM_UPDATE_SLOT);
    ok = call_ok(CAM_FOV_CALL, CAM_FTOL_ADDR, "FOV") & ok;
    ok = call_ok(CAM_LOOKAT_CALL, CAM_LOOKAT_ADDR, "look-at") & ok;
    ok = call_ok(CAM_SHAKE_CALL, CAM_NOISE_ADDR, "speed shake") & ok;
    ok = call_ok(CAM_NEAR_SHAKE_CALL, CAM_NOISE_ADDR, "nearby shake") & ok;
    ok = call_ok(CAM_EVENT_SHAKE_CALL, CAM_NOISE_ADDR, "event shake") & ok;
    if (!ok) { g_cam_fov = g_cam_smooth = 0; return; }
    if (g_cam_fov) hook_call(CAM_FOV_CALL, (void *)FovStub, "FOV");
    if (g_cam_smooth && g_smooth > 0) hook_call(CAM_LOOKAT_CALL, (void *)LookAtStub, "smoothing");
    if (g_cam_smooth && g_shake < 1) {
        hook_call(CAM_SHAKE_CALL, (void *)NoiseHook, "speed shake");
        hook_call(CAM_NEAR_SHAKE_CALL, (void *)NoiseHook, "nearby shake");
        hook_call(CAM_EVENT_SHAKE_CALL, (void *)NoiseHook, "event shake");
    }
}

static float inif(const char *ini, const char *key, float def) {
    char buf[32], d[32]; snprintf(d, sizeof d, "%g", def);
    GetPrivateProfileStringA("CopFly", key, d, buf, sizeof buf, ini); return (float)atof(buf);
}
static void patch(void **slot, void *expect, void *fn, const char *name) {
    if (*slot != expect) { logmsg("%s slot holds %p, expected %p - not hooked\n", name, *slot, expect); return; }
    DWORD old; VirtualProtect(slot, 4, PAGE_READWRITE, &old); *slot = fn; VirtualProtect(slot, 4, old, &old);
    logmsg("hooked %s\n", name);
}

BOOL WINAPI DllMain(HINSTANCE h, DWORD reason, LPVOID r) {
    if (reason != DLL_PROCESS_ATTACH) return TRUE;
    char ini[MAX_PATH]; GetModuleFileNameA(h, ini, MAX_PATH);
    char *dot = strrchr(ini, '.'); if (dot) strcpy(dot, ".ini");
    strcpy(g_logpath, ini); dot = strrchr(g_logpath, '.'); if (dot) strcpy(dot, ".log");
    DeleteFileA(g_logpath);
    g_t0 = GetTickCount();
    if (!GetPrivateProfileIntA("CopFly", "Enabled", 1, ini)) return TRUE;
    g_margin = inif(ini, "ContactMargin", g_margin);
    g_minspeed = inif(ini, "MinImpactSpeed", g_minspeed);
    g_plspeed = inif(ini, "MinPlayerSpeed", g_plspeed);
    g_up = inif(ini, "UpSpeed", g_up);  g_push = inif(ini, "PushFactor", g_push);
    g_kick = inif(ini, "ForwardKick", g_kick); g_spin = inif(ini, "Spin", g_spin);
    g_wreck = GetPrivateProfileIntA("CopFly", "Wreck", 0, ini);
    g_log = GetPrivateProfileIntA("CopFly", "Log", 1, ini);
    g_upaxis = GetPrivateProfileIntA("CopFly", "UpAxis", 1, ini) % 3;
    g_launch = GetPrivateProfileIntA("CopFly", "Launch", 1, ini);
    int old = GetPrivateProfileIntA("CopFly", "KeepSpeed", 0, ini);
    g_keep_cops = GetPrivateProfileIntA("CopFly", "KeepSpeedCops", old, ini);
    g_keep_traffic = GetPrivateProfileIntA("CopFly", "KeepSpeedTraffic", old, ini);
    g_keep_walls = GetPrivateProfileIntA("CopFly", "KeepSpeedWalls", 0, ini);
    g_keep = g_keep_cops || g_keep_traffic || g_keep_walls;
    logmsg("CopFly v12 loaded: Launch %d KeepSpeed cops %d traffic %d walls %d MinImpactSpeed %.1f MinPlayerSpeed %.1f ContactMargin %.2f UpSpeed %.1f PushFactor %.2f ForwardKick %.1f Spin %.1f Wreck %d UpAxis %d\n",
           g_launch, g_keep_cops, g_keep_traffic, g_keep_walls, g_minspeed, g_plspeed, g_margin, g_up, g_push, g_kick, g_spin, g_wreck, g_upaxis);
    patch(COP_SLOT, (void *)COP_IMPACT, (void *)CopHook, "DamageCopCar");
    patch(DV_SLOT, (void *)DV_IMPACT, (void *)CarHook, "DamageVehicle");
    patch(RACER_SLOT, (void *)DV_IMPACT, (void *)CarHook, "DamageRacer");
    patch(RBCOP_SLOT, (void *)RBCOP_SIM, (void *)SimHook, "RBCop simulate");
    patch(RBVEH_SLOT, (void *)RBCOP_SIM, (void *)VehSimHook, "RBVehicle simulate");
    cam_setup(ini);
    return TRUE;
}
