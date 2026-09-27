// Customer-style rocAL consumer: JPEG folder -> decode -> resize 224x224 -> copy to host.
//   rocal_consumer <jpeg dir> <cpu|gpu|rocjpeg> <dump prefix>
// Env: VP_BS (batch, default 4), VP_THREADS (cpu_thread_count, default 1), VP_ITERS (default 1).
// Writes <dump prefix>_iter<N>.raw (NHWC U8) and prints "CHECK pipeline PASS|FAIL <detail>".
#include ROCAL_HEADER
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <string>
#include <vector>

static size_t env_or(const char *name, size_t def) {
    const char *v = getenv(name);
    return v ? strtoul(v, nullptr, 10) : def;
}

int main(int argc, char **argv) {
    if (argc < 4) {
        fprintf(stderr, "usage: %s <jpeg dir> <cpu|gpu|rocjpeg> <dump prefix>\n", argv[0]);
        return 2;
    }
    const std::string dir = argv[1], mode = argv[2], dump = argv[3];
    const size_t bs = env_or("VP_BS", 4), nthreads = env_or("VP_THREADS", 1), iters_max = env_or("VP_ITERS", 1);
    const unsigned OW = 224, OH = 224;
    RocalProcessMode pm = mode == "cpu" ? ROCAL_PROCESS_CPU : ROCAL_PROCESS_GPU;
    RocalDecoderType dec = mode == "rocjpeg" ? ROCAL_DECODER_ROCJPEG : ROCAL_DECODER_TJPEG;
    RocalContext h = rocalCreate(bs, pm, 0, nthreads);
    if (!h || rocalGetStatus(h) != ROCAL_OK) {
        printf("CHECK pipeline FAIL rocalCreate: %s\n", h ? rocalGetErrorMessage(h) : "NULL");
        return 1;
    }
    RocalTensor decoded = rocalJpegFileSource(h, dir.c_str(), ROCAL_COLOR_RGB24, 1, false, false, false,
                                              ROCAL_USE_MOST_FREQUENT_SIZE, 0, 0, dec);
    RocalTensor out = rocalResize(h, decoded, OW, OH, true);
    (void)out;
    if (rocalGetStatus(h) != ROCAL_OK || rocalVerify(h) != ROCAL_OK) {
        printf("CHECK pipeline FAIL graph/verify: %s\n", rocalGetErrorMessage(h));
        rocalRelease(h);
        return 1;
    }
    size_t iters = 0, bad = 0;
    std::vector<unsigned char> buf;
    std::string last;
    while (iters < iters_max && rocalGetRemainingImages(h) >= bs) {
        if (rocalRun(h) != ROCAL_OK) {
            last = std::string("rocalRun: ") + rocalGetErrorMessage(h);
            bad++;
            break;
        }
        RocalTensorList tl = rocalGetOutputTensors(h);
        if (!tl || tl->size() < 1) {
            last = "no output tensors";
            bad++;
            break;
        }
        rocalTensor *t = tl->at(0);
        std::vector<size_t> d = t->dims();
        size_t n = t->data_size(), nz = 0;
        buf.assign(n, 0);
        t->copy_data(buf.data());
        for (size_t i = 0; i < n; i++) nz += buf[i] != 0;
        bool shape_ok = d.size() == 4 && d[0] == bs && d[1] == OH && d[2] == OW && d[3] == 3;
        bool content_ok = n == bs * OH * OW * 3 && nz > n / 2;
        if (!shape_ok || !content_ok) {
            last = "iteration " + std::to_string(iters) + ": shape_ok=" + std::to_string(shape_ok) +
                   " content_ok=" + std::to_string(content_ok);
            bad++;
        }
        std::ofstream f(dump + "_iter" + std::to_string(iters) + ".raw", std::ios::binary);
        f.write(reinterpret_cast<const char *>(buf.data()), static_cast<std::streamsize>(n));
        iters++;
    }
    rocalRelease(h);
    if (iters == 0 && !bad) {
        last = "no iteration ran";
        bad++;
    }
    printf("CHECK pipeline %s mode=%s bs=%zu threads=%zu iterations=%zu %s\n", bad ? "FAIL" : "PASS", mode.c_str(), bs,
           nthreads, iters, last.c_str());
    return bad ? 1 : 0;
}
