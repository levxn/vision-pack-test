// Result lines for suites/roccv/harness/emit_checks.py:
//   @@VPCHECK<TAB>group<TAB>name<TAB>pass|fail|error<TAB>message
#pragma once

#include <cstdio>
#include <string>

inline void vp_check(const char* group, const std::string& name, const char* status, const std::string& msg) {
    std::string m = msg;
    for (auto& c : m)
        if (c == '\n' || c == '\t') c = ' ';
    std::printf("@@VPCHECK\t%s\t%s\t%s\t%s\n", group, name.c_str(), status, m.c_str());
    std::fflush(stdout);
}
