#include <math.h>

/* Control library: NEEDs libm, built with different RUNPATHs by cwd_hijack.py. */
double vp_ctrl_uses_libm(double x) { return cos(x); }
