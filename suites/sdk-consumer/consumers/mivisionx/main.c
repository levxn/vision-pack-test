/* Customer-style OpenVX consumer. On the target chosen by AGO_DEFAULT_TARGET it
 * runs vxNot and vxBox3x3 on a 64x64 U8 pattern with UNDEFINED, REPLICATE and
 * CONSTANT borders and checks every pixel against a C reference. Prints one
 * "CHECK <name> PASS|FAIL <detail>" line per check. */
#include <VX/vx.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define W 64
#define H 64
#define CONST_VAL 17

static vx_uint8 pattern(int x, int y) { return (vx_uint8)((x * 7 + y * 13 + (x * y) % 5) & 0xFF); }

static void check(const char *name, int ok, const char *detail) {
    printf("CHECK %s %s %s\n", name, ok ? "PASS" : "FAIL", detail);
    fflush(stdout);
}

static vx_status copy_image(vx_image img, vx_uint8 *buf, vx_enum usage) {
    vx_rectangle_t rect = {0, 0, W, H};
    vx_imagepatch_addressing_t addr = {0};
    addr.dim_x = W;
    addr.dim_y = H;
    addr.stride_x = 1;
    addr.stride_y = W;
    return vxCopyImagePatch(img, &rect, 0, &addr, buf, usage, VX_MEMORY_TYPE_HOST);
}

static int box_ref(int x, int y, vx_enum mode) {
    int sum = 0;
    for (int dy = -1; dy <= 1; dy++)
        for (int dx = -1; dx <= 1; dx++) {
            int xx = x + dx, yy = y + dy;
            if (xx < 0 || yy < 0 || xx >= W || yy >= H) {
                if (mode == VX_BORDER_CONSTANT) {
                    sum += CONST_VAL;
                    continue;
                }
                xx = xx < 0 ? 0 : (xx >= W ? W - 1 : xx);
                yy = yy < 0 ? 0 : (yy >= H ? H - 1 : yy);
            }
            sum += pattern(xx, yy);
        }
    return sum / 9;
}

/* Runs Not + Box3x3 with the given border mode. Returns 0 when the graph ran,
 * 1 when the implementation rejected the border mode with NOT_SUPPORTED,
 * -1 on any other error. */
static int run_graph(vx_context ctx, vx_enum mode, vx_uint8 *in_buf, vx_uint8 *not_buf, vx_uint8 *box_buf,
                     char *err, size_t errlen) {
    vx_image in = vxCreateImage(ctx, W, H, VX_DF_IMAGE_U8);
    vx_image out_not = vxCreateImage(ctx, W, H, VX_DF_IMAGE_U8);
    vx_image out_box = vxCreateImage(ctx, W, H, VX_DF_IMAGE_U8);
    vx_graph graph = vxCreateGraph(ctx);
    int rc = -1;
    vx_status s = copy_image(in, in_buf, VX_WRITE_ONLY);
    vx_node n1 = vxNotNode(graph, in, out_not);
    vx_node n2 = vxBox3x3Node(graph, in, out_box);
    vx_border_t border;
    memset(&border, 0, sizeof(border));
    border.mode = mode;
    border.constant_value.U8 = CONST_VAL;
    if (s != VX_SUCCESS || vxGetStatus((vx_reference)n1) != VX_SUCCESS || vxGetStatus((vx_reference)n2) != VX_SUCCESS) {
        snprintf(err, errlen, "graph setup failed (status %d)", s);
        goto done;
    }
    s = vxSetNodeAttribute(n2, VX_NODE_BORDER, &border, sizeof(border));
    if (s == VX_ERROR_NOT_SUPPORTED) { rc = 1; goto done; }
    if (s != VX_SUCCESS) { snprintf(err, errlen, "vxSetNodeAttribute status %d", s); goto done; }
    s = vxVerifyGraph(graph);
    if (s == VX_ERROR_NOT_SUPPORTED) { rc = 1; goto done; }
    if (s != VX_SUCCESS) { snprintf(err, errlen, "vxVerifyGraph status %d", s); goto done; }
    if ((s = vxProcessGraph(graph)) != VX_SUCCESS || (s = vxProcessGraph(graph)) != VX_SUCCESS) {
        snprintf(err, errlen, "vxProcessGraph status %d", s);
        goto done;
    }
    if (copy_image(out_not, not_buf, VX_READ_ONLY) != VX_SUCCESS || copy_image(out_box, box_buf, VX_READ_ONLY) != VX_SUCCESS) {
        snprintf(err, errlen, "reading outputs failed");
        goto done;
    }
    rc = 0;
done:
    vxReleaseNode(&n1);
    vxReleaseNode(&n2);
    vxReleaseGraph(&graph);
    vxReleaseImage(&in);
    vxReleaseImage(&out_not);
    vxReleaseImage(&out_box);
    return rc;
}

int main(void) {
    static vx_uint8 in_buf[W * H], not_buf[W * H], box_buf[W * H];
    char detail[256], err[160];
    const char *tgt = getenv("AGO_DEFAULT_TARGET");
    printf("AGO_DEFAULT_TARGET=%s\n", tgt ? tgt : "(unset)");
    vx_context ctx = vxCreateContext();
    if (vxGetStatus((vx_reference)ctx) != VX_SUCCESS) {
        check("context", 0, "vxCreateContext failed");
        return 1;
    }
    check("context", 1, "vxCreateContext OK");
    for (int y = 0; y < H; y++)
        for (int x = 0; x < W; x++) in_buf[y * W + x] = pattern(x, y);

    const struct { const char *name; vx_enum mode; } modes[] = {
        {"box3x3", VX_BORDER_UNDEFINED}, {"border-replicate", VX_BORDER_REPLICATE}, {"border-constant", VX_BORDER_CONSTANT}};
    for (int m = 0; m < 3; m++) {
        err[0] = 0;
        int rc = run_graph(ctx, modes[m].mode, in_buf, not_buf, box_buf, err, sizeof err);
        if (rc < 0) {
            check(modes[m].name, 0, err);
            if (m == 0) check("not", 0, err);
            continue;
        }
        if (rc == 1) {
            if (m == 0) {
                check("box3x3", 0, "UNDEFINED border rejected");
                check("not", 0, "graph not run");
            } else {
                check(modes[m].name, 1, "rejected with VX_ERROR_NOT_SUPPORTED (allowed by the spec)");
            }
            continue;
        }
        int bad_interior = 0, bad_border = 0, maxdiff = 0, maxdiff_interior = 0, bad_not = 0;
        for (int y = 0; y < H; y++)
            for (int x = 0; x < W; x++) {
                if (not_buf[y * W + x] != (vx_uint8)(255 - pattern(x, y))) bad_not++;
                int d = abs((int)box_buf[y * W + x] - box_ref(x, y, modes[m].mode));
                if (!d) continue;
                if (x == 0 || y == 0 || x == W - 1 || y == H - 1) {
                    bad_border++;
                } else {
                    bad_interior++;
                    if (d > maxdiff_interior) maxdiff_interior = d;
                }
                if (d > maxdiff) maxdiff = d;
            }
        if (m == 0) {
            snprintf(detail, sizeof detail, "%d/%d pixels wrong", bad_not, W * H);
            check("not", bad_not == 0, detail);
            snprintf(detail, sizeof detail, "interior mismatches=%d/%d maxdiff=%d (border pixels undefined)",
                     bad_interior, (W - 2) * (H - 2), maxdiff_interior);
            check("box3x3", bad_interior == 0, detail);
        } else {
            snprintf(detail, sizeof detail,
                     "accepted; border mismatches=%d/%d (interior %d) maxdiff=%d%s", bad_border, 2 * (W + H) - 4,
                     bad_interior, maxdiff, bad_border ? ": mode ignored instead of NOT_SUPPORTED" : "");
            check(modes[m].name, bad_border == 0, detail);
        }
    }

    vx_uint32 before = 0, after = 0;
    vxQueryContext(ctx, VX_CONTEXT_UNIQUE_KERNELS, &before, sizeof(before));
    vx_status ls = vxLoadKernels(ctx, "vx_rpp");
    vxQueryContext(ctx, VX_CONTEXT_UNIQUE_KERNELS, &after, sizeof(after));
    vx_kernel k = vxGetKernelByName(ctx, "org.rpp.Brightness");
    vx_status ks = vxGetStatus((vx_reference)k);
    snprintf(detail, sizeof detail, "vxLoadKernels status=%d kernels %u->%u org.rpp.Brightness status=%d", ls, before,
             after, ks);
    check("vx_rpp-load", ls == VX_SUCCESS && ks == VX_SUCCESS && after > before, detail);
    if (ks == VX_SUCCESS) vxReleaseKernel(&k);
    vxReleaseContext(&ctx);
    return 0;
}
