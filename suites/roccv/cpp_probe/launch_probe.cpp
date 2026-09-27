// Does an operator surface a kernel-launch failure (M21)? On a targeted GPU the launch succeeds, so this is the
// control for the robustness suite's unsupported-GPU run.
// cpp-probe.launch::flip_launch_status: fail when Flip returns normally while hipGetLastError() reports an error.
#include <hip/hip_runtime.h>

#include <core/tensor.hpp>
#include <op_flip.hpp>
#include <string>

#include "check.hpp"

using namespace roccv;

int main() {
    hipDeviceProp_t prop{};
    (void)hipGetDeviceProperties(&prop, 0);
    TensorShape shape(TensorLayout(TENSOR_LAYOUT_NHWC), {1, 8, 8, 1});
    std::string dev = std::string(prop.name) + " (" + prop.gcnArchName + ")";
    try {
        Tensor in(shape, DataType(DATA_TYPE_U8), eDeviceType::GPU);
        Tensor out(shape, DataType(DATA_TYPE_U8), eDeviceType::GPU);
        Flip op;
        op(nullptr, in, out, 1, eDeviceType::GPU);
    } catch (const std::exception& e) {
        vp_check("cpp-probe.launch", "flip_launch_status", "pass", dev + ": Flip reported the error: " + e.what());
        return 0;
    }
    hipError_t last = hipGetLastError();
    hipError_t sync = hipDeviceSynchronize();
    std::string msg = dev + ": Flip returned normally; hipGetLastError=" + hipGetErrorName(last) +
                      " hipDeviceSynchronize=" + hipGetErrorName(sync);
    vp_check("cpp-probe.launch", "flip_launch_status", last == hipSuccess && sync == hipSuccess ? "pass" : "fail",
             msg + (last == hipSuccess ? "" : " (launch failure swallowed)"));
    return 0;
}
