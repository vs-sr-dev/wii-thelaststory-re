/* lwextract - LastWorld pack extractor (The Last Story, Wii)
 *
 * Usage: lwextract <file.pk> <manifest.txt> <outdir>
 * Manifest: lines of "offset|compSize|uncSize|relative/path"
 *           compSize==0 -> stored uncompressed (uncSize raw bytes)
 *           otherwise Nintendo LZ11 (magic 0x11 + 24-bit LE size)
 *
 * Windows-only as written: it uses <direct.h>, _mkdir and _fseeki64.
 * On POSIX swap those for <sys/stat.h>, mkdir(path, 0755) and fseeko.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <direct.h>
#include <errno.h>

static int mkdirs(const char *path) {
    char tmp[1024];
    strncpy(tmp, path, sizeof tmp - 1);
    tmp[sizeof tmp - 1] = 0;
    for (char *p = tmp + 1; *p; p++) {
        if (*p == '/' || *p == '\\') {
            char c = *p; *p = 0;
            if (_mkdir(tmp) && errno != EEXIST) return -1;
            *p = c;
        }
    }
    return 0;
}

static long lz11_decompress(const uint8_t *in, size_t in_len,
                            uint8_t *out, size_t out_cap) {
    if (in_len < 4 || in[0] != 0x11) return -1;
    size_t size = in[1] | (in[2] << 8) | ((size_t)in[3] << 16);
    size_t pos = 4, olen = 0;
    if (size == 0) {
        if (in_len < 8) return -1;
        size = in[4] | (in[5] << 8) | ((size_t)in[6] << 16) | ((size_t)in[7] << 24);
        pos = 8;
    }
    if (size > out_cap) return -2;
    while (olen < size && pos < in_len) {
        uint8_t flags = in[pos++];
        for (int bit = 0; bit < 8 && olen < size; bit++) {
            if (flags & (0x80 >> bit)) {
                uint8_t b0 = in[pos];
                unsigned ind = b0 >> 4, length, disp;
                if (ind == 0) {
                    length = (((b0 & 0xF) << 4) | (in[pos+1] >> 4)) + 0x11;
                    disp = (((in[pos+1] & 0xF) << 8) | in[pos+2]) + 1;
                    pos += 3;
                } else if (ind == 1) {
                    length = (((b0 & 0xF) << 12) | (in[pos+1] << 4) | (in[pos+2] >> 4)) + 0x111;
                    disp = (((in[pos+2] & 0xF) << 8) | in[pos+3]) + 1;
                    pos += 4;
                } else {
                    length = ind + 1;
                    disp = (((b0 & 0xF) << 8) | in[pos+1]) + 1;
                    pos += 2;
                }
                if (disp > olen || olen + length > out_cap) return -3;
                for (unsigned i = 0; i < length; i++, olen++)
                    out[olen] = out[olen - disp];
            } else {
                out[olen++] = in[pos++];
            }
        }
    }
    return (long)olen;
}

int main(int argc, char **argv) {
    if (argc != 4) {
        fprintf(stderr, "usage: lwextract <file.pk> <manifest.txt> <outdir>\n");
        return 1;
    }
    FILE *pk = fopen(argv[1], "rb");
    if (!pk) { perror(argv[1]); return 1; }
    FILE *mf = fopen(argv[2], "r");
    if (!mf) { perror(argv[2]); return 1; }

    size_t cap_in = 1 << 20, cap_out = 1 << 20;
    uint8_t *bin = malloc(cap_in), *bout = malloc(cap_out);
    char line[1200];
    long n_ok = 0, n_err = 0;

    while (fgets(line, sizeof line, mf)) {
        unsigned long long off; unsigned long comp, unc;
        char rel[1024];
        if (sscanf(line, "%llu|%lu|%lu|%1023[^\r\n]", &off, &comp, &unc, rel) != 4)
            continue;
        size_t stored = comp ? comp : unc;
        if (stored > cap_in) { cap_in = stored * 2; bin = realloc(bin, cap_in); }
        if (unc > cap_out)   { cap_out = unc * 2;  bout = realloc(bout, cap_out); }

        if (_fseeki64(pk, (long long)off, SEEK_SET) ||
            fread(bin, 1, stored, pk) != stored) {
            fprintf(stderr, "ERR read %s\n", rel); n_err++; continue;
        }
        uint8_t *data = bin; size_t dlen = stored;
        if (comp) {
            long r = lz11_decompress(bin, stored, bout, cap_out);
            if (r < 0 || (unsigned long)r != unc) {
                fprintf(stderr, "ERR lz11 %s (r=%ld want=%lu)\n", rel, r, unc);
                n_err++; continue;
            }
            data = bout; dlen = unc;
        }
        char full[1200];
        snprintf(full, sizeof full, "%s/%s", argv[3], rel);
        mkdirs(full);
        FILE *out = fopen(full, "wb");
        if (!out) { fprintf(stderr, "ERR open %s\n", full); n_err++; continue; }
        fwrite(data, 1, dlen, out);
        fclose(out);
        n_ok++;
    }
    printf("extracted %ld files, %ld errors\n", n_ok, n_err);
    fclose(pk); fclose(mf);
    return n_err ? 2 : 0;
}
