#include <windows.h>
#include <stdio.h>
#include <math.h>

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

#define COP_SLOT     ((void **)0x008AD460)
#define DV_SLOT      ((void **)0x008AD2F4)
#define RACER_SLOT   ((void **)0x008AD378)
#define COP_IMPACT   ((OnImpact_t)0x0069CA30)
#define DV_IMPACT    ((OnImpact_t)0x0069C030)
#define QI           ((QI_t)0x005D59F0)
#define IID_RB       ((void *)0x004039C0)
#define IID_DAMAGE   ((void *)0x00405000)
#define VT_COP_DMG   ((void *)0x008AD40C)
#define TASK_SLOT    ((void **)0x008AD434)
#define COP_TASK     ((OnTask_t)0x006B6730)
#define RBCOP_SLOT   ((void **)0x008AD020)
#define RBCOP_SIM    ((Simulate_t)0x0068BC80)
#define RBVEH_SLOT   ((void **)0x008AC950)

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
    logmsg("CopFly v11 loaded: Launch %d KeepSpeed cops %d traffic %d walls %d MinImpactSpeed %.1f MinPlayerSpeed %.1f ContactMargin %.2f UpSpeed %.1f PushFactor %.2f ForwardKick %.1f Spin %.1f Wreck %d UpAxis %d\n",
           g_launch, g_keep_cops, g_keep_traffic, g_keep_walls, g_minspeed, g_plspeed, g_margin, g_up, g_push, g_kick, g_spin, g_wreck, g_upaxis);
    patch(COP_SLOT, (void *)COP_IMPACT, (void *)CopHook, "DamageCopCar");
    patch(DV_SLOT, (void *)DV_IMPACT, (void *)CarHook, "DamageVehicle");
    patch(RACER_SLOT, (void *)DV_IMPACT, (void *)CarHook, "DamageRacer");
    patch(RBCOP_SLOT, (void *)RBCOP_SIM, (void *)SimHook, "RBCop simulate");
    patch(RBVEH_SLOT, (void *)RBCOP_SIM, (void *)VehSimHook, "RBVehicle simulate");
    return TRUE;
}
