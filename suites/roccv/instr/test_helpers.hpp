// Per-case instrumentation for the shipped rocCV C++ tests.
//
// run.sh compiles the installed test sources unchanged with "-iquote <this dir>", so their
// #include "test_helpers.hpp" resolves here first; #include_next pulls in the shipped header.
// TEST_CASE keeps the shipped behaviour (catch std::exception, print the "Test Failed:" block,
// mark the suite failed) and additionally prints one marker line per executed case:
//   @@VPCASE<TAB>PASS|FAIL<TAB>milliseconds<TAB>__LINE__<TAB>#call<TAB>reason
#pragma once

#include_next "test_helpers.hpp"

#include <chrono>
#include <iostream>
#include <string>

namespace roccv::tests::vp {
inline void emit_case(bool ok, double ms, int line, std::string call, std::string reason) {
    for (auto& c : call)
        if (c == '\n' || c == '\t' || c == '\r') c = ' ';
    for (auto& c : reason)
        if (c == '\n' || c == '\t' || c == '\r') c = ' ';
    std::cerr << "@@VPCASE\t" << (ok ? "PASS" : "FAIL") << "\t" << ms << "\t" << line << "\t" << call << "\t" << reason
              << std::endl;
}
}  // namespace roccv::tests::vp

#undef TEST_CASE
#define TEST_CASE(call)                                                                                             \
    {                                                                                                               \
        auto _vp_t0 = std::chrono::steady_clock::now();                                                             \
        bool _vp_ok = true;                                                                                         \
        std::string _vp_reason;                                                                                     \
        try {                                                                                                       \
            call;                                                                                                   \
        } catch (const std::exception& e) {                                                                         \
            std::cerr << "Test Failed: " << #call << "\n    Line: " << ERROR_PREFIX << "\n    Reason: " << e.what() \
                      << "\n\n";                                                                                    \
            _testSuiteStatus = 1;                                                                                   \
            _vp_ok = false;                                                                                         \
            _vp_reason = e.what();                                                                                  \
        }                                                                                                           \
        ::roccv::tests::vp::emit_case(                                                                              \
            _vp_ok, std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - _vp_t0).count(),   \
            __LINE__, #call, _vp_reason);                                                                           \
    }
