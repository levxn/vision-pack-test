// Customer-style rocCV consumer: Flip (codes 1, 0, -1) on GPU and CPU tensors
// against a hand-computed expectation. Prints "CHECK <name> PASS|FAIL <detail>".
//   roccv_consumer [gpu,cpu]
// GPU.launch-errors: after every GPU operator call hipGetLastError() must be
// hipSuccess and the output correct; rocCV never reports a failed kernel launch
// itself (M21), so a pending launch error with wrong output would fail here.
#include <hip/hip_runtime.h>

#include <core/exception.hpp>
#include <core/image_format.hpp>
#include <core/tensor.hpp>
#include <op_flip.hpp>

#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>

using namespace roccv;

static int g_launch_errors = 0;

static void check(const std::string &name, bool ok, const std::string &detail) {
    printf("CHECK %s %s %s\n", name.c_str(), ok ? "PASS" : "FAIL", detail.c_str());
    fflush(stdout);
}

static void test_flip(eDeviceType dev, int code) {
    const int W = 7, H = 5, N = 2;
    const bool gpu = dev == eDeviceType::GPU;
    const std::string name = std::string(gpu ? "GPU" : "CPU") + ".flip" + std::to_string(code);
    try {
        Tensor in(N, Size2D{W, H}, FMT_U8, dev);
        Tensor out(N, Size2D{W, H}, FMT_U8, dev);
        std::vector<uint8_t> src(N * W * H), dst(N * W * H, 0xAA), exp(N * W * H);
        for (int b = 0; b < N; b++)
            for (int y = 0; y < H; y++)
                for (int x = 0; x < W; x++) src[(b * H + y) * W + x] = static_cast<uint8_t>(b * 100 + y * 10 + x);
        for (int b = 0; b < N; b++)
            for (int y = 0; y < H; y++)
                for (int x = 0; x < W; x++) {
                    int sx = code != 0 ? W - 1 - x : x;
                    int sy = code <= 0 ? H - 1 - y : y;
                    exp[(b * H + y) * W + x] = src[(b * H + sy) * W + sx];
                }
        hipStream_t s = nullptr;
        if (hipStreamCreate(&s) != hipSuccess) {
            check(name, false, "hipStreamCreate failed");
            return;
        }
        in.copyFromHostAsync(src.data(), s);
        Flip op;
        op(s, in, out, code, dev);
        hipError_t le = hipGetLastError();
        out.copyToHostAsync(dst.data(), s);
        hipError_t se = hipStreamSynchronize(s);
        (void)hipStreamDestroy(s);
        int bad = 0;
        for (size_t i = 0; i < dst.size(); i++) bad += dst[i] != exp[i];
        char detail[200];
        snprintf(detail, sizeof detail, "mismatches=%d/%zu sync=%s last_error=%s", bad, dst.size(), hipGetErrorName(se),
                 hipGetErrorName(le));
        check(name, bad == 0 && se == hipSuccess, detail);
        if (gpu && (le != hipSuccess || bad)) g_launch_errors++;
    } catch (const std::exception &ex) {
        check(name, false, std::string("exception: ") + ex.what());
        if (gpu) g_launch_errors++;
    }
}

int main(int argc, char **argv) {
    std::string which = argc > 1 ? argv[1] : "gpu,cpu";
    int dc = -1;
    hipError_t e = hipGetDeviceCount(&dc);
    if (e == hipSuccess && dc > 0) {
        hipDeviceProp_t p;
        if (hipGetDeviceProperties(&p, 0) == hipSuccess) printf("device0: %s %s\n", p.name, p.gcnArchName);
    }
    for (int code : {1, 0, -1}) {
        if (which.find("gpu") != std::string::npos) test_flip(eDeviceType::GPU, code);
        if (which.find("cpu") != std::string::npos) test_flip(eDeviceType::CPU, code);
    }
    if (which.find("gpu") != std::string::npos)
        check("GPU.launch-errors", g_launch_errors == 0,
              g_launch_errors ? std::to_string(g_launch_errors) + " GPU call(s) left a launch error or wrong output"
                              : "no pending launch error after any GPU operator");
    return 0;
}
