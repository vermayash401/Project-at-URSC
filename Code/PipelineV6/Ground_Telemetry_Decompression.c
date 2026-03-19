#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <errno.h>

#ifdef _WIN32
#include <direct.h>
#define MKDIR(path) _mkdir(path)
#else
#include <unistd.h>
#define MKDIR(path) mkdir(path, 0777)
#endif

/*
    This code decompressess the output produced by Spacecraft_Telemetry_Compression.c

    Input is the compressed telemetry (.bin) file produced by said code.

    Output is an exact reconstructed telemetry txt file, without any loss.
*/

/////////////////////////// Delta Encoding //////////////////////////////////

#define BYPASS 0
#define SEQUENTIAL 1
#define MASTER 2
#define TAG_ZERO 0x00
#define TAG_LITERAL 0x01
#define TOP 0xFFFFFFFFu
#define HALF 0x80000000u
#define FIRST_QTR 0x40000000u
#define THIRD_QTR 0xC0000000u

typedef struct {
    FILE *f;
    uint8_t buffer;
    int nbits;
} BitReader;

static void die(const char *message) {
    fprintf(stderr, "%s\n", message);
    exit(1);
}

static void die_errno(const char *message) {
    fprintf(stderr, "%s: %s\n", message, strerror(errno));
    exit(1);
}

static uint32_t read_u32_le(FILE *f) {
    uint8_t buf[4];

    if (fread(buf, 1, 4, f) != 4) {
        die("Truncated uint32 field");
    }

    return (uint32_t) buf[0] |
           ((uint32_t) buf[1] << 8) |
           ((uint32_t) buf[2] << 16) |
           ((uint32_t) buf[3] << 24);
}

static uint64_t read_u64_le(FILE *f) {
    uint8_t buf[8];
    uint64_t value = 0;
    int i;

    if (fread(buf, 1, 8, f) != 8) {
        die("Truncated uint64 field");
    }

    for (i = 0; i < 8; ++i) {
        value |= ((uint64_t) buf[i]) << (8 * i);
    }

    return value;
}

static void ensure_parent_dir(const char *path) {
    char *copy = strdup(path);
    char *last1;
    char *last2;
    size_t i;

    if (!copy) {
        die("Out of memory");
    }

    last1 = strrchr(copy, '/');
    last2 = strrchr(copy, '\\');
    if (last2 && (!last1 || last2 > last1)) {
        last1 = last2;
    }
    if (!last1) {
        free(copy);
        return;
    }

    *last1 = '\0';
    if (copy[0] == '\0') {
        free(copy);
        return;
    }

    for (i = 1; copy[i] != '\0'; ++i) {
        if (copy[i] == '/' || copy[i] == '\\') {
            char saved = copy[i];
            copy[i] = '\0';
            if (strlen(copy) > 0) {
                if (MKDIR(copy) != 0 && errno != EEXIST) {
                    free(copy);
                    die_errno("Failed creating parent directory");
                }
            }
            copy[i] = saved;
        }
    }

    if (MKDIR(copy) != 0 && errno != EEXIST) {
        free(copy);
        die_errno("Failed creating parent directory");
    }

    free(copy);
}

static char *path_dirname(const char *path) {
    char *copy = strdup(path);
    char *last1;
    char *last2;

    if (!copy) {
        die("Out of memory");
    }

    last1 = strrchr(copy, '/');
    last2 = strrchr(copy, '\\');
    if (last2 && (!last1 || last2 > last1)) {
        last1 = last2;
    }
    if (!last1) {
        free(copy);
        copy = strdup(".");
        if (!copy) {
            die("Out of memory");
        }
    } else {
        *last1 = '\0';
    }

    return copy;
}

static char *path_stem(const char *path) {
    const char *start = path;
    const char *slash1 = strrchr(path, '/');
    const char *slash2 = strrchr(path, '\\');
    const char *dot;
    char *stem;
    size_t len;

    if (slash1 || slash2) {
        start = (slash1 && slash2) ? ((slash1 > slash2) ? slash1 + 1 : slash2 + 1)
                                   : ((slash1 ? slash1 : slash2) + 1);
    }

    dot = strrchr(start, '.');
    len = dot ? (size_t) (dot - start) : strlen(start);
    stem = (char *) malloc(len + 1);
    if (!stem) {
        die("Out of memory");
    }
    memcpy(stem, start, len);
    stem[len] = '\0';

    return stem;
}

static char *join_path(const char *a, const char *b) {
    size_t len_a = strlen(a);
    size_t len_b = strlen(b);
    int need_sep = len_a > 0 && a[len_a - 1] != '/' && a[len_a - 1] != '\\';
    char *out = (char *) malloc(len_a + len_b + (need_sep ? 2 : 1));

    if (!out) {
        die("Out of memory");
    }

    strcpy(out, a);
    if (need_sep) {
        strcat(out, "/");
    }
    strcat(out, b);

    return out;
}

static void remove_dir_recursive(const char *path) {
    char command[4096];
#ifdef _WIN32
    snprintf(command, sizeof(command), "rmdir /s /q \"%s\" >nul 2>nul", path);
#else
    snprintf(command, sizeof(command), "rm -rf \"%s\" >/dev/null 2>&1", path);
#endif
    system(command);
}

///////////////// Entropy Coding Method- Arithmetic Coding ///////////////////

static void bitreader_init(BitReader *br, FILE *f) {
    br->f = f;
    br->buffer = 0;
    br->nbits = 0;
}

static int bitreader_read_bit(BitReader *br) {
    if (br->nbits == 0) {
        int c = fgetc(br->f);
        if (c == EOF) {
            return 0;
        }
        br->buffer = (uint8_t) c;
        br->nbits = 8;
    }

    {
        int bit = (br->buffer >> 7) & 1;
        br->buffer <<= 1;
        --br->nbits;
        return bit;
    }
}

static void build_cumulative(const uint32_t freq[256], uint64_t cum[257]) {
    int i;
    uint64_t running = 0;

    cum[0] = 0;
    for (i = 0; i < 256; ++i) {
        running += freq[i];
        cum[i + 1] = running;
    }
}

static int find_symbol(const uint64_t cum[257], uint64_t value) {
    int lo = 0;
    int hi = 256;

    while (lo + 1 < hi) {
        int mid = (lo + hi) / 2;
        if (cum[mid] <= value) {
            lo = mid;
        } else {
            hi = mid;
        }
    }

    return lo;
}

static int arithmetic_decode(const char *in_file, const char *out_file) {
    FILE *fin = fopen(in_file, "rb");
    FILE *fout = fopen(out_file, "wb");
    uint32_t freq[256];
    uint32_t original_size;
    uint32_t low = 0;
    uint32_t high = TOP;
    uint32_t code = 0;
    uint32_t written = 0;
    uint64_t cum[257];
    uint64_t total;
    int zrle_done;
    int i;
    BitReader br;

    if (!fin || !fout) {
        if (fin) fclose(fin);
        if (fout) fclose(fout);
        die_errno("Unable to open arithmetic decode files");
    }

    {
        int c = fgetc(fin);
        if (c == EOF) {
            fclose(fin);
            fclose(fout);
            die("Truncated outer flags");
        }
        zrle_done = (((uint8_t) c) & 0x01u) ? 1 : 0;
    }

    original_size = read_u32_le(fin);
    for (i = 0; i < 256; ++i) {
        freq[i] = read_u32_le(fin);
    }
    build_cumulative(freq, cum);
    total = cum[256];

    if (original_size == 0) {
        fclose(fin);
        fclose(fout);
        return zrle_done;
    }
    if (total != original_size) {
        fclose(fin);
        fclose(fout);
        die("Invalid arithmetic stream: frequency total != original size");
    }

    bitreader_init(&br, fin);
    for (i = 0; i < 32; ++i) {
        code = ((code << 1) & TOP) | (uint32_t) bitreader_read_bit(&br);
    }

    while (written < original_size) {
        uint64_t range = (uint64_t) high - low + 1u;
        uint64_t value = (((uint64_t) (code - low + 1u) * total) - 1u) / range;
        int sym = find_symbol(cum, value);
        uint64_t sym_low = cum[sym];
        uint64_t sym_high = cum[sym + 1];

        fputc(sym, fout);
        ++written;
        high = low + (uint32_t) ((range * sym_high) / total) - 1u;
        low = low + (uint32_t) ((range * sym_low) / total);

        for (;;) {
            if (high < HALF) {
            } else if (low >= HALF) {
                low -= HALF;
                high -= HALF;
                code -= HALF;
            } else if (low >= FIRST_QTR && high < THIRD_QTR) {
                low -= FIRST_QTR;
                high -= FIRST_QTR;
                code -= FIRST_QTR;
            } else {
                break;
            }

            low = (low << 1) & TOP;
            high = ((high << 1) & TOP) | 1u;
            code = ((code << 1) & TOP) | (uint32_t) bitreader_read_bit(&br);
        }
    }

    fclose(fin);
    fclose(fout);
    return zrle_done;
}

/////////////////////////// Zero Run Length Encoding //////////////////////////

static void zero_rle_decode(const char *in_file, const char *out_file) {
    FILE *fin = fopen(in_file, "rb");
    FILE *fout = fopen(out_file, "wb");
    uint64_t expected_size;
    uint64_t written = 0;

    if (!fin || !fout) {
        if (fin) fclose(fin);
        if (fout) fclose(fout);
        die_errno("Unable to open ZRLE decode files");
    }

    expected_size = read_u64_le(fin);
    while (written < expected_size) {
        int tag = fgetc(fin);
        if (tag == EOF) {
            break;
        }

        if ((uint8_t) tag == TAG_ZERO) {
            uint32_t count = read_u32_le(fin);
            uint8_t zeros[65536] = {0};
            while (count > 0) {
                uint32_t take = count > sizeof(zeros) ? (uint32_t) sizeof(zeros) : count;
                if (fwrite(zeros, 1, take, fout) != take) {
                    fclose(fin);
                    fclose(fout);
                    die_errno("Failed writing zero-run output");
                }
                written += take;
                count -= take;
            }
        } else if ((uint8_t) tag == TAG_LITERAL) {
            int b0 = fgetc(fin);
            int b1 = fgetc(fin);
            uint32_t length;
            uint8_t *payload;

            if (b0 == EOF || b1 == EOF) {
                fclose(fin);
                fclose(fout);
                die("Truncated literal packet length");
            }

            length = (uint32_t) ((uint8_t) b0) | ((uint32_t) ((uint8_t) b1) << 8);
            payload = (uint8_t *) malloc(length);
            if (!payload) {
                fclose(fin);
                fclose(fout);
                die("Out of memory");
            }
            if (fread(payload, 1, length, fin) != length) {
                free(payload);
                fclose(fin);
                fclose(fout);
                die("Truncated literal packet payload");
            }
            if (fwrite(payload, 1, length, fout) != length) {
                free(payload);
                fclose(fin);
                fclose(fout);
                die_errno("Failed writing literal output");
            }
            written += length;
            free(payload);
        } else {
            fclose(fin);
            fclose(fout);
            die("Invalid packet tag in ZRLE stream");
        }
    }

    fclose(fin);
    fclose(fout);
}

static void reverse_delta_ml(const char *in_bin, const char *out_txt) {
    FILE *f_in = fopen(in_bin, "rb");
    FILE *f_out = fopen(out_txt, "w");
    uint8_t *prev_frame = NULL;
    uint8_t *master_refs[32] = {0};
    uint8_t *frame;
    uint8_t *reconstructed;
    size_t frame_index = 0;
    size_t i;
    int lead_space;
    int upper_case;
    uint32_t frame_size;

    if (!f_in || !f_out) {
        if (f_in) fclose(f_in);
        if (f_out) fclose(f_out);
        die_errno("Unable to open reverse-delta files");
    }

    {
        int c = fgetc(f_in);
        if (c == EOF) {
            fclose(f_in);
            fclose(f_out);
            die("Truncated delta header");
        }
        lead_space = ((uint8_t) c) ? 1 : 0;
    }
    {
        int c = fgetc(f_in);
        if (c == EOF) {
            fclose(f_in);
            fclose(f_out);
            die("Truncated delta header");
        }
        upper_case = ((uint8_t) c) ? 1 : 0;
    }

    frame_size = read_u32_le(f_in);
    frame = (uint8_t *) malloc(frame_size);
    reconstructed = (uint8_t *) malloc(frame_size);
    if (!frame || !reconstructed) {
        if (frame) free(frame);
        if (reconstructed) free(reconstructed);
        fclose(f_in);
        fclose(f_out);
        die("Out of memory");
    }

    for (;;) {
        int mode_byte = fgetc(f_in);
        size_t slot;

        if (mode_byte == EOF) {
            break;
        }
        if (fread(frame, 1, frame_size, f_in) != frame_size) {
            break;
        }
        slot = frame_index % 32;

        if (!prev_frame) {
            memcpy(reconstructed, frame, frame_size);
        } else if ((uint8_t) mode_byte == BYPASS) {
            memcpy(reconstructed, frame, frame_size);
        } else if ((uint8_t) mode_byte == SEQUENTIAL) {
            for (i = 0; i < frame_size; ++i) {
                reconstructed[i] = (uint8_t) ((prev_frame[i] + frame[i]) & 0xFFu);
            }
        } else if ((uint8_t) mode_byte == MASTER) {
            uint8_t *ref = master_refs[slot] ? master_refs[slot] : prev_frame;
            for (i = 0; i < frame_size; ++i) {
                reconstructed[i] = (uint8_t) ((ref[i] + frame[i]) & 0xFFu);
            }
        } else {
            free(frame);
            free(reconstructed);
            fclose(f_in);
            fclose(f_out);
            die("Unknown mode byte in delta stream");
        }

        if (lead_space) {
            fputc(' ', f_out);
        }
        for (i = 0; i < frame_size; ++i) {
            if (upper_case) {
                fprintf(f_out, "%02X", reconstructed[i]);
            } else {
                fprintf(f_out, "%02x", reconstructed[i]);
            }
            if (i + 1 < frame_size) {
                fputc(' ', f_out);
            }
        }
        fputc('\n', f_out);

        if (!prev_frame) {
            prev_frame = (uint8_t *) malloc(frame_size);
            if (!prev_frame) {
                free(frame);
                free(reconstructed);
                fclose(f_in);
                fclose(f_out);
                die("Out of memory");
            }
        }
        memcpy(prev_frame, reconstructed, frame_size);

        if (!master_refs[slot]) {
            master_refs[slot] = (uint8_t *) malloc(frame_size);
            if (!master_refs[slot]) {
                free(frame);
                free(reconstructed);
                free(prev_frame);
                fclose(f_in);
                fclose(f_out);
                die("Out of memory");
            }
        }
        memcpy(master_refs[slot], reconstructed, frame_size);
        ++frame_index;
    }

    for (i = 0; i < 32; ++i) {
        free(master_refs[i]);
    }
    free(prev_frame);
    free(frame);
    free(reconstructed);
    fclose(f_in);
    fclose(f_out);
}

////////////////////////////////# Pipeline #//////////////////////////////////

static void run_chain(const char *compressed_bin, const char *output_txt) {
    char *out_dir = path_dirname(output_txt);
    char *base = path_stem(output_txt);
    char temp_name[1024];
    char recovered_name[1024];
    char recovered_delta_name[1024];
    char *temp_dir;
    char *recovered;
    char *recovered_delta;
    int zrle_done;

    ensure_parent_dir(output_txt);
    snprintf(temp_name, sizeof(temp_name), ".%s_tmp", base);
    temp_dir = join_path(out_dir, temp_name);
    remove_dir_recursive(temp_dir);
    if (MKDIR(temp_dir) != 0) {
        free(out_dir);
        free(base);
        free(temp_dir);
        die_errno("Unable to create temp directory");
    }

    snprintf(recovered_name, sizeof(recovered_name), "%s_recovered_rle.bin", base);
    snprintf(recovered_delta_name, sizeof(recovered_delta_name), "%s_recovered_delta.bin", base);
    recovered = join_path(temp_dir, recovered_name);
    recovered_delta = join_path(temp_dir, recovered_delta_name);

    zrle_done = arithmetic_decode(compressed_bin, recovered);
    if (zrle_done) {
        zero_rle_decode(recovered, recovered_delta);
        reverse_delta_ml(recovered_delta, output_txt);
    } else {
        reverse_delta_ml(recovered, output_txt);
    }

    free(out_dir);
    free(base);
    free(recovered);
    free(recovered_delta);
    remove_dir_recursive(temp_dir);
    free(temp_dir);
}

////////////////////////////////# Main #//////////////////////////////////////

int main(void) {
    const char *INPUT_TELEMETRY_COMPRESSED = "d:\\URSC\\Code\\TEST_3_compressed_c.bin";
    const char *OUTPUT_TELEMETRY = "d:\\URSC\\Code\\TEST_3_reconstructed_c.txt";

    run_chain(INPUT_TELEMETRY_COMPRESSED, OUTPUT_TELEMETRY);
    return 0;
}
