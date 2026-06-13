/* Minimal Mach-O launcher for .app bundles (Finder / Spotlight / Dock). */
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char *argv[]) {
  char exe[PATH_MAX];
  char script[PATH_MAX];
  char name[PATH_MAX];
  char *base;
  char *macos;

  (void)argc;
  if (realpath(argv[0], exe) == NULL) {
    return 127;
  }

  base = strrchr(exe, '/');
  if (base == NULL) {
    return 127;
  }

  snprintf(name, sizeof(name), "%s", base + 1);
  *base = '\0';

  macos = strstr(exe, "/MacOS");
  if (macos != NULL) {
    snprintf(
      script,
      sizeof(script),
      "%.*s/Resources/%s.sh",
      (int)(macos - exe),
      exe,
      name
    );
  } else {
    snprintf(script, sizeof(script), "%s/Resources/%s.sh", exe, name);
  }

  execl("/bin/bash", "bash", script, (char *)NULL);
  perror(name);
  return 127;
}
