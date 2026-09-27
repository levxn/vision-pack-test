#include <stdio.h>

/* Linked with --no-as-needed -l<lib>: the loader must fully relocate the
 * library before main() runs, exactly like any C/C++ consumer of it. */
int main(void) {
    puts("LINKED_START_OK");
    return 0;
}
