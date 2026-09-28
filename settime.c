/* Set CLOCK_REALTIME from "SECONDS.NANOSECONDS"; busybox date -s drops the fraction. */
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

int main(int argc, char **argv)
{
    if (argc != 2) {
        fprintf(stderr, "usage: settime SECONDS.NANOSECONDS\n");
        return 2;
    }
    char *end;
    errno = 0;
    struct timespec now = {.tv_sec = strtoll(argv[1], &end, 10)};
    if (errno == 0 && *end == '.') {
        char *fraction = end + 1;
        now.tv_nsec = strtol(fraction, &end, 10);
        if (end - fraction != 9) {
            end = fraction;
        }
    }
    if (errno != 0 || *end != '\0' || now.tv_sec <= 0 || now.tv_nsec < 0) {
        fprintf(stderr, "settime: invalid time %s\n", argv[1]);
        return 2;
    }
    if (clock_settime(CLOCK_REALTIME, &now) != 0) {
        perror("settime");
        return 1;
    }
    return 0;
}
