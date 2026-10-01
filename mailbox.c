// Mirrors the activity mailbox directory with the host over vsock.
// Frame: u16 name length, u64 data length (little endian), name, data.
// Files are sent in inotify order, so a marker written after its data arrives after it.
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/inotify.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
#include <linux/vm_sockets.h>

#define TMP_SUFFIX ".mbtmp"

static const char *dir;
static int sock;
static char **received;
static size_t received_len, received_cap;

static void die(const char *what) {
  perror(what);
  exit(1);
}

static int ends_with(const char *name, const char *suffix) {
  size_t n = strlen(name), s = strlen(suffix);
  return n >= s && strcmp(name + n - s, suffix) == 0;
}

static int was_received(const char *name) {
  for (size_t i = 0; i < received_len; i++)
    if (strcmp(received[i], name) == 0) return 1;
  return 0;
}

static void remember(const char *name) {
  if (was_received(name)) return;
  if (received_len == received_cap) {
    received_cap = received_cap ? received_cap * 2 : 64;
    received = realloc(received, received_cap * sizeof *received);
    if (!received) die("realloc");
  }
  received[received_len++] = strdup(name);
}

static void read_exact(void *buf, size_t len) {
  char *p = buf;
  while (len) {
    ssize_t r = read(sock, p, len);
    if (r == 0) exit(0);
    if (r < 0) {
      if (errno == EINTR) continue;
      die("vsock read");
    }
    p += r;
    len -= r;
  }
}

static void write_exact(const void *buf, size_t len) {
  const char *p = buf;
  while (len) {
    ssize_t w = write(sock, p, len);
    if (w < 0) {
      if (errno == EINTR) continue;
      die("vsock write");
    }
    p += w;
    len -= w;
  }
}

static void receive_file(void) {
  unsigned char header[10];
  read_exact(header, sizeof header);
  uint16_t name_len = header[0] | header[1] << 8;
  uint64_t data_len = 0;
  for (int i = 7; i >= 0; i--) data_len = data_len << 8 | header[2 + i];
  char name[NAME_MAX + 1];
  if (name_len == 0 || name_len > NAME_MAX) {
    fprintf(stderr, "mailbox: bad name length %u\n", name_len);
    exit(1);
  }
  read_exact(name, name_len);
  name[name_len] = 0;
  if (strchr(name, '/')) {
    fprintf(stderr, "mailbox: bad name %s\n", name);
    exit(1);
  }
  char tmp[PATH_MAX], path[PATH_MAX];
  snprintf(tmp, sizeof tmp, "%s/%s" TMP_SUFFIX, dir, name);
  snprintf(path, sizeof path, "%s/%s", dir, name);
  int fd = open(tmp, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0644);
  if (fd < 0) die(tmp);
  char buf[65536];
  while (data_len) {
    size_t chunk = data_len < sizeof buf ? data_len : sizeof buf;
    read_exact(buf, chunk);
    for (size_t off = 0; off < chunk;) {
      ssize_t w = write(fd, buf + off, chunk - off);
      if (w < 0) die(tmp);
      off += w;
    }
    data_len -= chunk;
  }
  close(fd);
  // Scripts arrive over the mailbox and are run by path.
  if (ends_with(name, ".sh")) chmod(tmp, 0755);
  remember(name);
  if (rename(tmp, path) < 0) die(path);
}

static void send_file(const char *name) {
  char path[PATH_MAX];
  snprintf(path, sizeof path, "%s/%s", dir, name);
  int fd = open(path, O_RDONLY | O_CLOEXEC);
  if (fd < 0) return;
  struct stat st;
  if (fstat(fd, &st) < 0 || !S_ISREG(st.st_mode)) {
    close(fd);
    return;
  }
  size_t len = st.st_size;
  char *data = malloc(len ? len : 1);
  if (!data) die("malloc");
  size_t got = 0;
  while (got < len) {
    ssize_t r = read(fd, data + got, len - got);
    if (r <= 0) break;
    got += r;
  }
  close(fd);
  size_t name_len = strlen(name);
  unsigned char header[10] = {name_len & 0xff, name_len >> 8};
  for (int i = 0; i < 8; i++) header[2 + i] = (uint64_t)got >> (8 * i);
  write_exact(header, sizeof header);
  write_exact(name, name_len);
  write_exact(data, got);
  free(data);
}

int main(int argc, char **argv) {
  if (argc != 3) {
    fprintf(stderr, "usage: mailbox DIR PORT\n");
    return 2;
  }
  dir = argv[1];
  int inotify = inotify_init1(IN_CLOEXEC | IN_NONBLOCK);
  if (inotify < 0) die("inotify_init1");
  if (inotify_add_watch(inotify, dir, IN_CLOSE_WRITE | IN_MOVED_TO) < 0) die("inotify_add_watch");
  struct sockaddr_vm addr = {
      .svm_family = AF_VSOCK, .svm_cid = VMADDR_CID_HOST, .svm_port = atoi(argv[2])};
  for (int attempt = 0;; attempt++) {
    sock = socket(AF_VSOCK, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (sock < 0) die("socket");
    if (connect(sock, (struct sockaddr *)&addr, sizeof addr) == 0) break;
    if (attempt == 10000) die("vsock connect");
    close(sock);
    struct timespec pause = {0, 1000000};
    nanosleep(&pause, NULL);
  }
  struct pollfd fds[2] = {{sock, POLLIN, 0}, {inotify, POLLIN, 0}};
  char events[16384] __attribute__((aligned(__alignof__(struct inotify_event))));
  for (;;) {
    if (poll(fds, 2, -1) < 0) {
      if (errno == EINTR) continue;
      die("poll");
    }
    if (fds[1].revents & POLLIN) {
      ssize_t len;
      while ((len = read(inotify, events, sizeof events)) > 0) {
        for (char *p = events; p < events + len;) {
          struct inotify_event *event = (struct inotify_event *)p;
          if (event->len && !ends_with(event->name, ".tmp") &&
              !ends_with(event->name, TMP_SUFFIX) && !was_received(event->name))
            send_file(event->name);
          p += sizeof *event + event->len;
        }
      }
    }
    if (fds[0].revents & (POLLIN | POLLHUP)) receive_file();
  }
}
