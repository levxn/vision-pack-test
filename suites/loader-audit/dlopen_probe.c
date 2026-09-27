#include <dlfcn.h>
#include <stdio.h>
#include <string.h>

/* usage: dlopen_probe <lib> [lazy|now] */
int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "usage: %s <lib> [lazy|now]\n", argv[0]);
        return 2;
    }
    const char *mode = argc > 2 ? argv[2] : "now";
    int flags = strcmp(mode, "lazy") == 0 ? RTLD_LAZY : RTLD_NOW;
    void *h = dlopen(argv[1], flags | RTLD_LOCAL);
    if (!h) {
        printf("DLOPEN_FAIL[%s] %s\n", mode, dlerror());
        return 1;
    }
    printf("DLOPEN_OK[%s] %s\n", mode, argv[1]);
    return 0;
}
