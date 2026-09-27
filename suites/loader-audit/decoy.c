#include <unistd.h>

/* Planted in the working directory under the names of common dependencies
 * (libstdc++.so.6, libm.so.6, libgcc_s.so.1). If the loader ever maps it, the
 * constructor leaves a marker on stderr. */
__attribute__((constructor)) static void vp_decoy_ctor(void) {
    static const char msg[] = "*** CWD-HIJACK: decoy library constructor executed ***\n";
    (void)!write(2, msg, sizeof msg - 1);
}
