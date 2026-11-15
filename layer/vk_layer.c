/* VK_LAYER_BC250_frame: implicit Vulkan layer, hooks vkQueuePresentKHR only.
 * Minimal self-contained definitions (no Vulkan headers needed). */
#include "common.h"

#define VKAPI __attribute__((visibility("default")))
typedef int32_t VkResult;
typedef void *VkInstance, *VkPhysicalDevice, *VkDevice, *VkQueue;
typedef void (*PFN_vkVoidFunction)(void);
typedef PFN_vkVoidFunction (*PFN_vkGetInstanceProcAddr)(VkInstance, const char *);
typedef PFN_vkVoidFunction (*PFN_vkGetDeviceProcAddr)(VkDevice, const char *);
typedef VkResult (*PFN_vkCreateInstance)(const void *, const void *, VkInstance *);
typedef void (*PFN_vkDestroyInstance)(VkInstance, const void *);
typedef VkResult (*PFN_vkCreateDevice)(VkPhysicalDevice, const void *, const void *, VkDevice *);
typedef void (*PFN_vkDestroyDevice)(VkDevice, const void *);
typedef VkResult (*PFN_vkQueuePresentKHR)(VkQueue, const void *);

#define VK_SUCCESS 0
#define VK_ERROR_INITIALIZATION_FAILED (-3)
#define STYPE_LOADER_INSTANCE_CREATE_INFO 47
#define STYPE_LOADER_DEVICE_CREATE_INFO 48
#define VK_LAYER_LINK_INFO 0

struct base { int32_t sType; const struct base *pNext; };
struct inst_link { struct inst_link *pNext; PFN_vkGetInstanceProcAddr gipa; void *gpdpa; };
struct dev_link { struct dev_link *pNext; PFN_vkGetInstanceProcAddr gipa; PFN_vkGetDeviceProcAddr gdpa; };
struct layer_ci { int32_t sType; const void *pNext; int32_t function; union { void *link; } u; };

/* dispatch key = first pointer of a dispatchable handle */
#define KEY(h) (*(void **)(h))
#define MAXN 64
struct inst { void *key; PFN_vkGetInstanceProcAddr gipa; PFN_vkDestroyInstance destroy; };
struct dev { void *key; PFN_vkGetDeviceProcAddr gdpa; PFN_vkDestroyDevice destroy; PFN_vkQueuePresentKHR present; };
static struct inst insts[MAXN];
static struct dev devs[MAXN];
static pthread_mutex_t tbl = PTHREAD_MUTEX_INITIALIZER;

static struct inst *find_inst(void *key) {
    for (int i = 0; i < MAXN; i++) if (insts[i].key == key) return &insts[i];
    return NULL;
}
static struct dev *find_dev(void *key) {
    for (int i = 0; i < MAXN; i++) if (devs[i].key == key) return &devs[i];
    return NULL;
}

static VkResult bc_CreateInstance(const void *ci, const void *alloc, VkInstance *out) {
    struct layer_ci *l = (struct layer_ci *)((const struct base *)ci)->pNext;
    while (l && !(l->sType == STYPE_LOADER_INSTANCE_CREATE_INFO && l->function == VK_LAYER_LINK_INFO))
        l = (struct layer_ci *)l->pNext;
    if (!l) return VK_ERROR_INITIALIZATION_FAILED;
    struct inst_link *link = l->u.link;
    PFN_vkGetInstanceProcAddr gipa = link->gipa;
    l->u.link = link->pNext;
    PFN_vkCreateInstance create = (PFN_vkCreateInstance)gipa(NULL, "vkCreateInstance");
    if (!create) return VK_ERROR_INITIALIZATION_FAILED;
    VkResult r = create(ci, alloc, out);
    if (r != VK_SUCCESS) return r;
    pthread_mutex_lock(&tbl);
    struct inst *s = find_inst(NULL);
    if (s) {
        s->key = KEY(*out);
        s->gipa = gipa;
        s->destroy = (PFN_vkDestroyInstance)gipa(*out, "vkDestroyInstance");
    }
    pthread_mutex_unlock(&tbl);
    return r;
}

static void bc_DestroyInstance(VkInstance i, const void *alloc) {
    pthread_mutex_lock(&tbl);
    struct inst *s = find_inst(KEY(i));
    PFN_vkDestroyInstance d = s ? s->destroy : NULL;
    if (s) memset(s, 0, sizeof *s);
    pthread_mutex_unlock(&tbl);
    if (d) d(i, alloc);
}

static VkResult bc_CreateDevice(VkPhysicalDevice pd, const void *ci, const void *alloc, VkDevice *out) {
    struct layer_ci *l = (struct layer_ci *)((const struct base *)ci)->pNext;
    while (l && !(l->sType == STYPE_LOADER_DEVICE_CREATE_INFO && l->function == VK_LAYER_LINK_INFO))
        l = (struct layer_ci *)l->pNext;
    if (!l) return VK_ERROR_INITIALIZATION_FAILED;
    struct dev_link *link = l->u.link;
    PFN_vkGetInstanceProcAddr gipa = link->gipa;
    PFN_vkGetDeviceProcAddr gdpa = link->gdpa;
    l->u.link = link->pNext;
    PFN_vkCreateDevice create = (PFN_vkCreateDevice)gipa(NULL, "vkCreateDevice");
    if (!create) return VK_ERROR_INITIALIZATION_FAILED;
    VkResult r = create(pd, ci, alloc, out);
    if (r != VK_SUCCESS) return r;
    pthread_mutex_lock(&tbl);
    struct dev *s = find_dev(NULL);
    if (s) {
        s->key = KEY(*out);
        s->gdpa = gdpa;
        s->destroy = (PFN_vkDestroyDevice)gdpa(*out, "vkDestroyDevice");
        s->present = (PFN_vkQueuePresentKHR)gdpa(*out, "vkQueuePresentKHR");
    }
    pthread_mutex_unlock(&tbl);
    return r;
}

static void bc_DestroyDevice(VkDevice d, const void *alloc) {
    pthread_mutex_lock(&tbl);
    struct dev *s = find_dev(KEY(d));
    PFN_vkDestroyDevice fn = s ? s->destroy : NULL;
    if (s) memset(s, 0, sizeof *s);
    pthread_mutex_unlock(&tbl);
    if (fn) fn(d, alloc);
}

static VkResult bc_QueuePresentKHR(VkQueue q, const void *info) {
    pthread_mutex_lock(&tbl);
    struct dev *s = find_dev(KEY(q));
    PFN_vkQueuePresentKHR p = s ? s->present : NULL;
    pthread_mutex_unlock(&tbl);
    if (!p) return VK_ERROR_INITIALIZATION_FAILED;
    bc_frame_tick(1);
    return p(q, info);
}

VKAPI PFN_vkVoidFunction bc250_GetDeviceProcAddr(VkDevice d, const char *n);

static PFN_vkVoidFunction own(const char *n) {
    if (!strcmp(n, "vkCreateInstance")) return (PFN_vkVoidFunction)bc_CreateInstance;
    if (!strcmp(n, "vkDestroyInstance")) return (PFN_vkVoidFunction)bc_DestroyInstance;
    if (!strcmp(n, "vkCreateDevice")) return (PFN_vkVoidFunction)bc_CreateDevice;
    if (!strcmp(n, "vkDestroyDevice")) return (PFN_vkVoidFunction)bc_DestroyDevice;
    if (!strcmp(n, "vkQueuePresentKHR")) return (PFN_vkVoidFunction)bc_QueuePresentKHR;
    if (!strcmp(n, "vkGetDeviceProcAddr")) return (PFN_vkVoidFunction)bc250_GetDeviceProcAddr;
    return NULL;
}

VKAPI PFN_vkVoidFunction bc250_GetDeviceProcAddr(VkDevice d, const char *n) {
    if (!strcmp(n, "vkDestroyDevice") || !strcmp(n, "vkQueuePresentKHR") ||
        !strcmp(n, "vkGetDeviceProcAddr"))
        return own(n);
    pthread_mutex_lock(&tbl);
    struct dev *s = d ? find_dev(KEY(d)) : NULL;
    PFN_vkGetDeviceProcAddr g = s ? s->gdpa : NULL;
    pthread_mutex_unlock(&tbl);
    return g ? g(d, n) : NULL;
}

VKAPI PFN_vkVoidFunction bc250_GetInstanceProcAddr(VkInstance i, const char *n) {
    PFN_vkVoidFunction f = own(n);
    if (f) return f;
    if (!i) return NULL;
    pthread_mutex_lock(&tbl);
    struct inst *s = find_inst(KEY(i));
    PFN_vkGetInstanceProcAddr g = s ? s->gipa : NULL;
    pthread_mutex_unlock(&tbl);
    return g ? g(i, n) : NULL;
}
