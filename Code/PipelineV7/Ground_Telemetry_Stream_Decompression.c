#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>

#ifdef _WIN32
#include <direct.h>
#define MKDIR(path) _mkdir(path)
#else
#include <unistd.h>
#define MKDIR(path) mkdir(path, 0777)
#endif

#define FRAME_SIZE_BYTES 256
#define FRAMES_PER_MASTER_FRAME 32

#define BYPASS 0
#define SEQUENTIAL 1
#define MASTER 2

#define TAG_ZERO 0x00
#define TAG_LITERAL 0x01

#define TOP 0xFFFFFFFFu
#define HALF 0x80000000u
#define FIRST_QTR 0x40000000u
#define THIRD_QTR 0xC0000000u

#define BATCH_RAW_DELTA 0
#define BATCH_RAW_ZRLE 1
#define BATCH_ARITHMETIC 2

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

static char *dup_string(const char *text) {
    size_t len = strlen(text);
    char *out = (char *) malloc(len + 1);
    if (!out) {
        die("Out of memory");
    }
    memcpy(out, text, len + 1);
    return out;
}

static uint16_t read_u16_le(FILE *f) {
    uint8_t buf[2];
    if (fread(buf, 1, 2, f) != 2) {
        die("Truncated uint16 field");
    }
    return (uint16_t) buf[0] | ((uint16_t) buf[1] << 8);
}

static void ensure_parent_dir(const char *path) {
    char *copy = dup_string(path);
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
            if (strlen(copy) > 0 && MKDIR(copy) != 0 && errno != EEXIST) {
                free(copy);
                die_errno("Failed creating parent directory");
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
    char *copy = dup_string(path);
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
        copy = dup_string(".");
        if (!copy) {
            die("Out of memory");
        }
        return copy;
    }
    *last1 = '\0';
    return copy;
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

static void bitreader_init(BitReader *br, FILE *f) {
    br->f = f;
    br->buffer = 0;
    br->nbits = 0;
}

static int bitreader_read_bit(BitReader *br) {
    if (br->nbits == 0) {
        int c = fgetc(br->f);
        if (c == EOF) {
            return -1;
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

static void bitreader_align_to_byte(BitReader *br) {
    br->buffer = 0;
    br->nbits = 0;
}

static void build_cumulative(const uint16_t freq[256], uint32_t cum[257]) {
    int i;
    uint32_t running = 0;
    cum[0] = 0;
    for (i = 0; i < 256; ++i) {
        running += freq[i];
        cum[i + 1] = running;
    }
}

static int find_symbol(const uint32_t cum[257], uint32_t value) {
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

static int arithmetic_decode_stream(const char *in_file, const char *out_file) {
    FILE *fin = fopen(in_file, "rb");
    FILE *fout = fopen(out_file, "wb");
    uint16_t freq[256];
    uint16_t original_size;
    uint32_t cum[257];
    uint32_t total;
    uint32_t low = 0;
    uint32_t high = TOP;
    uint32_t code = 0;
    uint32_t written = 0;
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
            die("Truncated arithmetic flags");
        }
        zrle_done = (((uint8_t) c) & 0x01u) ? 1 : 0;
    }

    original_size = read_u16_le(fin);
    for (i = 0; i < 256; ++i) {
        freq[i] = read_u16_le(fin);
    }
    build_cumulative(freq, cum);
    total = cum[256];
    if (total != original_size) {
        fclose(fin);
        fclose(fout);
        die("Invalid arithmetic stream: frequency total != original size");
    }
    if (original_size == 0) {
        fclose(fin);
        fclose(fout);
        return zrle_done;
    }

    bitreader_init(&br, fin);
    for (i = 0; i < 32; ++i) {
        int bit = bitreader_read_bit(&br);
        if (bit < 0) {
            fclose(fin);
            fclose(fout);
            die("Truncated arithmetic bitstream");
        }
        code = ((code << 1) & TOP) | (uint32_t) bit;
    }

    while (written < original_size) {
        uint64_t range = (uint64_t) high - low + 1u;
        uint32_t value = (uint32_t) ((((uint64_t) (code - low + 1u) * total) - 1u) / range);
        int sym = find_symbol(cum, value);
        uint32_t sym_low = cum[sym];
        uint32_t sym_high = cum[sym + 1];

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
            {
                int bit = bitreader_read_bit(&br);
                if (bit < 0) {
                    bit = 0;
                }
                code = ((code << 1) & TOP) | (uint32_t) bit;
            }
        }
    }

    bitreader_align_to_byte(&br);
    fclose(fin);
    fclose(fout);
    return zrle_done;
}

static void zero_rle_decode(const char *in_file, const char *out_file) {
    FILE *fin = fopen(in_file, "rb");
    FILE *fout = fopen(out_file, "wb");
    uint16_t expected_size;
    uint32_t written = 0;

    if (!fin || !fout) {
        if (fin) fclose(fin);
        if (fout) fclose(fout);
        die_errno("Unable to open ZRLE decode files");
    }

    expected_size = read_u16_le(fin);
    while (written < expected_size) {
        int tag = fgetc(fin);
        if (tag == EOF) {
            break;
        }
        if ((uint8_t) tag == TAG_ZERO) {
            uint16_t count = read_u16_le(fin);
            uint8_t zeros[4096] = {0};
            while (count > 0) {
                uint16_t take = (count > sizeof(zeros)) ? (uint16_t) sizeof(zeros) : count;
                if (fwrite(zeros, 1, take, fout) != take) {
                    fclose(fin);
                    fclose(fout);
                    die_errno("Failed writing zero-run output");
                }
                written += take;
                count -= take;
            }
        } else if ((uint8_t) tag == TAG_LITERAL) {
            uint16_t length = read_u16_le(fin);
            uint8_t *payload = (uint8_t *) malloc(length);
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

    if (written != expected_size) {
        fclose(fin);
        fclose(fout);
        die("Decoded ZRLE size mismatch");
    }

    fclose(fin);
    fclose(fout);
}

static void reverse_delta_ml(const char *in_bin, const char *out_txt, int append) {
    FILE *fin = fopen(in_bin, "rb");
    FILE *fout = fopen(out_txt, append ? "a" : "w");
    uint8_t *prev_frame = NULL;
    uint8_t *master_refs[FRAMES_PER_MASTER_FRAME] = {0};
    uint8_t frame[FRAME_SIZE_BYTES];
    uint8_t reconstructed[FRAME_SIZE_BYTES];
    size_t frame_index = 0;
    size_t i;

    if (!fin || !fout) {
        if (fin) fclose(fin);
        if (fout) fclose(fout);
        die_errno("Unable to open reverse-delta files");
    }

    for (;;) {
        int mode_byte = fgetc(fin);
        size_t slot;
        if (mode_byte == EOF) {
            break;
        }
        if (fread(frame, 1, FRAME_SIZE_BYTES, fin) != FRAME_SIZE_BYTES) {
            fclose(fin);
            fclose(fout);
            die("Truncated delta frame payload");
        }
        slot = frame_index % FRAMES_PER_MASTER_FRAME;

        if (!prev_frame) {
            memcpy(reconstructed, frame, FRAME_SIZE_BYTES);
            prev_frame = (uint8_t *) malloc(FRAME_SIZE_BYTES);
            if (!prev_frame) {
                fclose(fin);
                fclose(fout);
                die("Out of memory");
            }
        } else if ((uint8_t) mode_byte == BYPASS) {
            memcpy(reconstructed, frame, FRAME_SIZE_BYTES);
        } else if ((uint8_t) mode_byte == SEQUENTIAL) {
            for (i = 0; i < FRAME_SIZE_BYTES; ++i) {
                reconstructed[i] = (uint8_t) ((prev_frame[i] + frame[i]) & 0xFFu);
            }
        } else if ((uint8_t) mode_byte == MASTER) {
            uint8_t *ref = master_refs[slot] ? master_refs[slot] : prev_frame;
            for (i = 0; i < FRAME_SIZE_BYTES; ++i) {
                reconstructed[i] = (uint8_t) ((ref[i] + frame[i]) & 0xFFu);
            }
        } else {
            fclose(fin);
            fclose(fout);
            die("Unknown mode byte in delta stream");
        }

        for (i = 0; i < FRAME_SIZE_BYTES; ++i) {
            fprintf(fout, "%02X", reconstructed[i]);
            if (i + 1 < FRAME_SIZE_BYTES) {
                fputc(' ', fout);
            }
        }
        fputc('\n', fout);

        memcpy(prev_frame, reconstructed, FRAME_SIZE_BYTES);
        if (!master_refs[slot]) {
            master_refs[slot] = (uint8_t *) malloc(FRAME_SIZE_BYTES);
            if (!master_refs[slot]) {
                fclose(fin);
                fclose(fout);
                die("Out of memory");
            }
        }
        memcpy(master_refs[slot], reconstructed, FRAME_SIZE_BYTES);
        ++frame_index;
    }

    for (i = 0; i < FRAMES_PER_MASTER_FRAME; ++i) {
        free(master_refs[i]);
    }
    free(prev_frame);
    fclose(fin);
    fclose(fout);
}

static void write_payload_file(FILE *fin, uint16_t payload_len, const char *payload_path) {
    FILE *fout = fopen(payload_path, "wb");
    uint8_t buffer[4096];
    uint16_t remaining = payload_len;
    if (!fout) {
        die_errno("Unable to create payload temp file");
    }
    while (remaining > 0) {
        uint16_t take = (remaining > sizeof(buffer)) ? (uint16_t) sizeof(buffer) : remaining;
        if (fread(buffer, 1, take, fin) != take) {
            fclose(fout);
            die("Truncated batch payload");
        }
        if (fwrite(buffer, 1, take, fout) != take) {
            fclose(fout);
            die_errno("Failed writing payload temp file");
        }
        remaining -= take;
    }
    fclose(fout);
}

static void run_stream_chain(const char *compressed_bin, const char *output_txt) {
    FILE *fin = fopen(compressed_bin, "rb");
    char *out_dir;
    char *temp_dir;
    char payload_name[64];
    char recovered_name[64];
    char delta_name[64];
    size_t batch_index = 0;

    if (!fin) {
        die_errno("Unable to open compressed stream");
    }

    ensure_parent_dir(output_txt);
    out_dir = path_dirname(output_txt);
    temp_dir = join_path(out_dir, ".stream_decode_tmp");
    remove_dir_recursive(temp_dir);
    if (MKDIR(temp_dir) != 0 && errno != EEXIST) {
        fclose(fin);
        free(out_dir);
        free(temp_dir);
        die_errno("Unable to create decode temp directory");
    }

    {
        FILE *fout = fopen(output_txt, "w");
        if (!fout) {
            fclose(fin);
            free(out_dir);
            free(temp_dir);
            die_errno("Unable to clear output txt");
        }
        fclose(fout);
    }

    while (1) {
        int type = fgetc(fin);
        uint16_t payload_len;
        char *payload_path;
        char *recovered_path;
        char *delta_path;

        if (type == EOF) {
            break;
        }

        payload_len = read_u16_le(fin);
        if (payload_len == 0) {
            fclose(fin);
            free(out_dir);
            free(temp_dir);
            die("Invalid empty batch payload");
        }

        ++batch_index;
        snprintf(payload_name, sizeof(payload_name), "batch_%06u_payload.bin", (unsigned) batch_index);
        snprintf(recovered_name, sizeof(recovered_name), "batch_%06u_recovered.bin", (unsigned) batch_index);
        snprintf(delta_name, sizeof(delta_name), "batch_%06u_delta.bin", (unsigned) batch_index);
        payload_path = join_path(temp_dir, payload_name);
        recovered_path = join_path(temp_dir, recovered_name);
        delta_path = join_path(temp_dir, delta_name);

        write_payload_file(fin, payload_len, payload_path);

        if ((uint8_t) type == BATCH_ARITHMETIC) {
            int zrle_done = arithmetic_decode_stream(payload_path, recovered_path);
            if (zrle_done) {
                zero_rle_decode(recovered_path, delta_path);
                reverse_delta_ml(delta_path, output_txt, 1);
            } else {
                reverse_delta_ml(recovered_path, output_txt, 1);
            }
        } else if ((uint8_t) type == BATCH_RAW_ZRLE) {
            zero_rle_decode(payload_path, delta_path);
            reverse_delta_ml(delta_path, output_txt, 1);
        } else if ((uint8_t) type == BATCH_RAW_DELTA) {
            reverse_delta_ml(payload_path, output_txt, 1);
        } else {
            fclose(fin);
            free(payload_path);
            free(recovered_path);
            free(delta_path);
            free(out_dir);
            free(temp_dir);
            die("Unknown batch type in compressed stream");
        }

        free(payload_path);
        free(recovered_path);
        free(delta_path);
    }

    fclose(fin);
    remove_dir_recursive(temp_dir);
    free(out_dir);
    free(temp_dir);
}

int main(void) {
    const char *input_compressed = "d:\\URSC\\Code\\telemetry_stream_compressed_c.bin";
    const char *output_txt = "d:\\URSC\\Code\\telemetry_stream_reconstructed_c.txt";
    run_stream_chain(input_compressed, output_txt);
    return 0;
}
