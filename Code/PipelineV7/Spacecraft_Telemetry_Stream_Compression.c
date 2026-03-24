#include <errno.h>
#include <math.h>
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
#define HEADER_BYTES 5
#define PAYLOAD_BYTES (FRAME_SIZE_BYTES - 6)
#define FRAMES_PER_MASTER_FRAME 32
#define MASTER_FRAMES_PER_BATCH 4
#define FRAMES_PER_MINUTE 120

#define WINDOW_SIZE FRAMES_PER_MASTER_FRAME
#define BYPASS 0
#define SEQUENTIAL 1
#define MASTER 2

#define TAG_ZERO 0x00
#define TAG_LITERAL 0x01
#define MAX_ZEROS 0xFFFFu
#define MAX_LITERALS 0xFFFFu

#define TOP 0xFFFFFFFFu
#define HALF 0x80000000u
#define FIRST_QTR 0x40000000u
#define THIRD_QTR 0xC0000000u

#define BATCH_RAW_DELTA 0
#define BATCH_RAW_ZRLE 1
#define BATCH_ARITHMETIC 2

typedef struct {
    uint8_t *data;
    size_t count;
} FrameBatch;

typedef struct {
    FILE *f;
    uint8_t buffer;
    int nbits;
} BitWriter;

typedef struct {
    uint32_t state;
    size_t total_frames;
    size_t generated_frames;
    uint8_t sequential_payload[PAYLOAD_BYTES];
    uint8_t master_payloads[FRAMES_PER_MASTER_FRAME][PAYLOAD_BYTES];
    uint8_t header[HEADER_BYTES];
    int telemetry_mode;
    int initialized;
} GeneratorState;

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

static uint16_t get_file_size16(const char *path) {
    FILE *f = fopen(path, "rb");
    long size;
    if (!f) {
        die_errno("Unable to open file for size");
    }
    if (fseek(f, 0, SEEK_END) != 0) {
        fclose(f);
        die_errno("Unable to seek file");
    }
    size = ftell(f);
    fclose(f);
    if (size < 0 || size > 0xFFFFL) {
        die("File size exceeds 2-byte V7 limit");
    }
    return (uint16_t) size;
}

static void write_u16_le(FILE *f, uint16_t value) {
    uint8_t buf[2];
    buf[0] = (uint8_t) (value & 0xFFu);
    buf[1] = (uint8_t) ((value >> 8) & 0xFFu);
    if (fwrite(buf, 1, 2, f) != 2) {
        die_errno("Failed writing uint16");
    }
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

static void remove_dir_recursive(const char *path) {
    char command[4096];
#ifdef _WIN32
    snprintf(command, sizeof(command), "rmdir /s /q \"%s\" >nul 2>nul", path);
#else
    snprintf(command, sizeof(command), "rm -rf \"%s\" >/dev/null 2>&1", path);
#endif
    system(command);
}

static uint32_t rng_next(GeneratorState *state) {
    state->state = state->state * 1664525u + 1013904223u;
    return state->state;
}

static uint8_t rng_byte(GeneratorState *state) {
    return (uint8_t) ((rng_next(state) >> 24) & 0xFFu);
}

static int rng_randint(GeneratorState *state, int low, int high) {
    uint32_t span = (uint32_t) (high - low + 1);
    return low + (int) (rng_next(state) % span);
}

static size_t total_frames_for_days(double days) {
    double total = days * 24.0 * 60.0 * (double) FRAMES_PER_MINUTE;
    if (total < 0.0) {
        return 0;
    }
    return (size_t) total;
}

static void random_payload(GeneratorState *state, uint8_t *payload) {
    size_t i;
    for (i = 0; i < PAYLOAD_BYTES; ++i) {
        payload[i] = rng_byte(state);
    }
}

static void mutate_payload(GeneratorState *state, uint8_t *payload, int max_changes) {
    int changes;
    int i;
    if (max_changes <= 0) {
        return;
    }
    changes = rng_randint(state, 1, max_changes);
    for (i = 0; i < changes; ++i) {
        size_t pos = (size_t) (rng_next(state) % PAYLOAD_BYTES);
        payload[pos] = rng_byte(state);
    }
}

static void generator_init(GeneratorState *state, double days, int max_changes, uint32_t seed) {
    int slot;
    state->state = seed ? seed : 1u;
    state->total_frames = total_frames_for_days(days);
    state->generated_frames = 0;
    state->telemetry_mode = SEQUENTIAL;
    state->initialized = max_changes;
    random_payload(state, state->sequential_payload);
    for (slot = 0; slot < FRAMES_PER_MASTER_FRAME; ++slot) {
        random_payload(state, state->master_payloads[slot]);
    }
}

static void build_frame_bytes(const uint8_t header[HEADER_BYTES], uint8_t frame_id, const uint8_t payload[PAYLOAD_BYTES], uint8_t *out) {
    memcpy(out, header, HEADER_BYTES);
    out[5] = frame_id;
    memcpy(out + 6, payload, PAYLOAD_BYTES);
}

static FrameBatch generate_next_batch(GeneratorState *state, int master_frames_per_batch) {
    size_t batch_size_frames = (size_t) (FRAMES_PER_MASTER_FRAME * master_frames_per_batch);
    size_t remaining = state->total_frames - state->generated_frames;
    size_t count = remaining < batch_size_frames ? remaining : batch_size_frames;
    FrameBatch batch = {0};
    size_t index;
    int max_changes = state->initialized;

    if (count == 0) {
        return batch;
    }

    batch.data = (uint8_t *) malloc(count * FRAME_SIZE_BYTES);
    if (!batch.data) {
        die("Out of memory");
    }
    batch.count = count;

    for (index = 0; index < count; ++index) {
        size_t global_frame = state->generated_frames + index;
        uint8_t frame_id = (uint8_t) (global_frame % FRAMES_PER_MASTER_FRAME);
        uint8_t *frame = batch.data + index * FRAME_SIZE_BYTES;

        if (frame_id == 0) {
            size_t j;
            for (j = 0; j < HEADER_BYTES; ++j) {
                state->header[j] = rng_byte(state);
            }
            state->telemetry_mode = (rng_next(state) & 1u) ? MASTER : SEQUENTIAL;
        }

        if (state->telemetry_mode == SEQUENTIAL) {
            mutate_payload(state, state->sequential_payload, max_changes);
            build_frame_bytes(state->header, frame_id, state->sequential_payload, frame);
        } else {
            if (frame_id == 0) {
                int slot;
                for (slot = 0; slot < FRAMES_PER_MASTER_FRAME; ++slot) {
                    mutate_payload(state, state->master_payloads[slot], max_changes);
                }
            }
            build_frame_bytes(state->header, frame_id, state->master_payloads[frame_id], frame);
        }
    }

    state->generated_frames += count;
    return batch;
}

static void free_batch(FrameBatch *batch) {
    free(batch->data);
    batch->data = NULL;
    batch->count = 0;
}

static void append_frames_to_txt(const FrameBatch *batch, const char *txt_path) {
    FILE *f = fopen(txt_path, "a");
    size_t i, j;
    if (!f) {
        die_errno("Unable to open telemetry txt output");
    }
    for (i = 0; i < batch->count; ++i) {
        const uint8_t *frame = batch->data + i * FRAME_SIZE_BYTES;
        for (j = 0; j < FRAME_SIZE_BYTES; ++j) {
            fprintf(f, "%02X", frame[j]);
            if (j + 1 < FRAME_SIZE_BYTES) {
                fputc(' ', f);
            }
        }
        fputc('\n', f);
    }
    fclose(f);
}

static void compute_window_features(const uint8_t *current_window, const uint8_t *prev_window, double *f1, double *f2) {
    uint64_t seq_zero_count = 0;
    uint64_t seq_total = 0;
    uint64_t master_zero_count = 0;
    uint64_t master_total = 0;
    size_t k, i;

    for (k = 1; k < WINDOW_SIZE; ++k) {
        const uint8_t *prev_frame = current_window + (k - 1) * FRAME_SIZE_BYTES;
        const uint8_t *current_frame = current_window + k * FRAME_SIZE_BYTES;
        for (i = 0; i < FRAME_SIZE_BYTES; ++i) {
            uint8_t delta = (uint8_t) ((current_frame[i] - prev_frame[i]) & 0xFFu);
            if (delta == 0) {
                ++seq_zero_count;
            }
            ++seq_total;
        }
    }
    *f1 = seq_total ? (double) seq_zero_count / (double) seq_total : 0.0;

    if (!prev_window) {
        *f2 = 0.0;
        return;
    }

    for (k = 0; k < WINDOW_SIZE; ++k) {
        const uint8_t *current_frame = current_window + k * FRAME_SIZE_BYTES;
        const uint8_t *prev_frame = prev_window + k * FRAME_SIZE_BYTES;
        for (i = 0; i < FRAME_SIZE_BYTES; ++i) {
            uint8_t delta = (uint8_t) ((current_frame[i] - prev_frame[i]) & 0xFFu);
            if (delta == 0) {
                ++master_zero_count;
            }
            ++master_total;
        }
    }
    *f2 = master_total ? (double) master_zero_count / (double) master_total : 0.0;
}

static int behaviour_selector(double f1, double f2) {
    if ((f2 <= 0.42) && (f1 <= 0.43)) {
        return BYPASS;
    }
    if (f1 > 0.43) {
        return SEQUENTIAL;
    }
    return MASTER;
}

static void compute_delta(const uint8_t *current_frame, const uint8_t *reference_frame, uint8_t *out_frame) {
    size_t i;
    for (i = 0; i < FRAME_SIZE_BYTES; ++i) {
        out_frame[i] = (uint8_t) ((current_frame[i] - reference_frame[i]) & 0xFFu);
    }
}

static void frames_to_delta_ml(const FrameBatch *batch, const char *out_bin) {
    FILE *f = fopen(out_bin, "wb");
    uint8_t master_refs[FRAMES_PER_MASTER_FRAME][FRAME_SIZE_BYTES];
    uint8_t prev_window[WINDOW_SIZE][FRAME_SIZE_BYTES];
    int have_master_ref[FRAMES_PER_MASTER_FRAME] = {0};
    int have_prev_window = 0;
    const uint8_t *prev_frame = NULL;
    size_t frame_index = 0;
    size_t window_len = 0;
    uint8_t window[WINDOW_SIZE][FRAME_SIZE_BYTES];
    int current_mode = SEQUENTIAL;
    size_t i;

    if (!f) {
        die_errno("Unable to open delta output");
    }

    for (i = 0; i < batch->count; ++i) {
        const uint8_t *current_frame = batch->data + i * FRAME_SIZE_BYTES;
        size_t slot = frame_index % FRAMES_PER_MASTER_FRAME;
        uint8_t out_frame[FRAME_SIZE_BYTES];

        memcpy(window[window_len], current_frame, FRAME_SIZE_BYTES);
        ++window_len;

        if (window_len == WINDOW_SIZE) {
            double f1, f2;
            compute_window_features(&window[0][0], have_prev_window ? &prev_window[0][0] : NULL, &f1, &f2);
            current_mode = behaviour_selector(f1, f2);
            memcpy(prev_window, window, sizeof(window));
            have_prev_window = 1;
            window_len = 0;
        }

        if (!prev_frame) {
            fputc(BYPASS, f);
            if (fwrite(current_frame, 1, FRAME_SIZE_BYTES, f) != FRAME_SIZE_BYTES) {
                fclose(f);
                die_errno("Failed writing first delta frame");
            }
            memcpy(master_refs[slot], current_frame, FRAME_SIZE_BYTES);
            have_master_ref[slot] = 1;
            prev_frame = current_frame;
            ++frame_index;
            continue;
        }

        if (current_mode == BYPASS) {
            memcpy(out_frame, current_frame, FRAME_SIZE_BYTES);
        } else if (current_mode == SEQUENTIAL) {
            compute_delta(current_frame, prev_frame, out_frame);
        } else {
            const uint8_t *ref = have_master_ref[slot] ? master_refs[slot] : prev_frame;
            compute_delta(current_frame, ref, out_frame);
        }

        fputc(current_mode, f);
        if (fwrite(out_frame, 1, FRAME_SIZE_BYTES, f) != FRAME_SIZE_BYTES) {
            fclose(f);
            die_errno("Failed writing delta frame");
        }

        memcpy(master_refs[slot], current_frame, FRAME_SIZE_BYTES);
        have_master_ref[slot] = 1;
        prev_frame = current_frame;
        ++frame_index;
    }

    fclose(f);
}

static void zero_rle_encode(const char *in_file, const char *out_file) {
    FILE *fin = fopen(in_file, "rb");
    FILE *fout = fopen(out_file, "wb");
    uint16_t original_size = get_file_size16(in_file);
    uint16_t zero_run = 0;
    uint8_t *literal_buf = (uint8_t *) malloc(MAX_LITERALS);
    uint16_t literal_len = 0;
    int c;

    if (!fin || !fout) {
        if (fin) fclose(fin);
        if (fout) fclose(fout);
        die_errno("Unable to open ZRLE files");
    }
    if (!literal_buf) {
        fclose(fin);
        fclose(fout);
        die("Out of memory");
    }

    write_u16_le(fout, original_size);

    while ((c = fgetc(fin)) != EOF) {
        uint8_t b = (uint8_t) c;
        if (b == 0) {
            if (literal_len > 0) {
                fputc(TAG_LITERAL, fout);
                write_u16_le(fout, literal_len);
                if (fwrite(literal_buf, 1, literal_len, fout) != literal_len) {
                    free(literal_buf);
                    fclose(fin);
                    fclose(fout);
                    die_errno("Failed writing literal packet");
                }
                literal_len = 0;
            }
            ++zero_run;
            if (zero_run == MAX_ZEROS) {
                fputc(TAG_ZERO, fout);
                write_u16_le(fout, zero_run);
                zero_run = 0;
            }
        } else {
            if (zero_run > 0) {
                fputc(TAG_ZERO, fout);
                write_u16_le(fout, zero_run);
                zero_run = 0;
            }
            literal_buf[literal_len++] = b;
            if (literal_len == MAX_LITERALS) {
                fputc(TAG_LITERAL, fout);
                write_u16_le(fout, literal_len);
                if (fwrite(literal_buf, 1, literal_len, fout) != literal_len) {
                    free(literal_buf);
                    fclose(fin);
                    fclose(fout);
                    die_errno("Failed writing literal packet");
                }
                literal_len = 0;
            }
        }
    }

    if (zero_run > 0) {
        fputc(TAG_ZERO, fout);
        write_u16_le(fout, zero_run);
    }
    if (literal_len > 0) {
        fputc(TAG_LITERAL, fout);
        write_u16_le(fout, literal_len);
        if (fwrite(literal_buf, 1, literal_len, fout) != literal_len) {
            free(literal_buf);
            fclose(fin);
            fclose(fout);
            die_errno("Failed writing literal packet");
        }
    }

    free(literal_buf);
    fclose(fin);
    fclose(fout);
}

static void bitwriter_init(BitWriter *bw, FILE *f) {
    bw->f = f;
    bw->buffer = 0;
    bw->nbits = 0;
}

static void bitwriter_write_bit(BitWriter *bw, int bit) {
    bw->buffer = (uint8_t) ((bw->buffer << 1) | (bit & 1));
    ++bw->nbits;
    if (bw->nbits == 8) {
        fputc(bw->buffer, bw->f);
        bw->buffer = 0;
        bw->nbits = 0;
    }
}

static void bitwriter_flush(BitWriter *bw) {
    if (bw->nbits > 0) {
        bw->buffer <<= (8 - bw->nbits);
        fputc(bw->buffer, bw->f);
        bw->buffer = 0;
        bw->nbits = 0;
    }
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

static void arithmetic_encode(const char *in_file, const char *out_file, int zrle_done) {
    FILE *fin;
    FILE *fout;
    uint16_t freq[256] = {0};
    uint32_t cum[257];
    uint32_t total;
    uint16_t original_size = get_file_size16(in_file);
    BitWriter bw;
    uint32_t low = 0;
    uint32_t high = TOP;
    uint32_t pending_bits = 0;
    int c;
    int i;

    fin = fopen(in_file, "rb");
    if (!fin) {
        die_errno("Unable to open input for arithmetic encode");
    }
    while ((c = fgetc(fin)) != EOF) {
        if (freq[(uint8_t) c] == 0xFFFFu) {
            fclose(fin);
            die("Frequency exceeds 2-byte V7 arithmetic limit");
        }
        ++freq[(uint8_t) c];
    }
    fclose(fin);

    build_cumulative(freq, cum);
    total = cum[256];
    if (total != original_size) {
        die("Frequency model error: total count mismatch");
    }

    fin = fopen(in_file, "rb");
    fout = fopen(out_file, "wb");
    if (!fin || !fout) {
        if (fin) fclose(fin);
        if (fout) fclose(fout);
        die_errno("Unable to open arithmetic files");
    }

    fputc(zrle_done ? 1 : 0, fout);
    write_u16_le(fout, original_size);
    for (i = 0; i < 256; ++i) {
        write_u16_le(fout, freq[i]);
    }

    bitwriter_init(&bw, fout);

    while ((c = fgetc(fin)) != EOF) {
        uint8_t sym = (uint8_t) c;
        uint64_t range = (uint64_t) high - low + 1u;
        uint64_t sym_low = cum[sym];
        uint64_t sym_high = cum[sym + 1];

        high = low + (uint32_t) ((range * sym_high) / total) - 1u;
        low = low + (uint32_t) ((range * sym_low) / total);

        for (;;) {
            if (high < HALF) {
                bitwriter_write_bit(&bw, 0);
                while (pending_bits > 0) {
                    bitwriter_write_bit(&bw, 1);
                    --pending_bits;
                }
            } else if (low >= HALF) {
                bitwriter_write_bit(&bw, 1);
                while (pending_bits > 0) {
                    bitwriter_write_bit(&bw, 0);
                    --pending_bits;
                }
                low -= HALF;
                high -= HALF;
            } else if (low >= FIRST_QTR && high < THIRD_QTR) {
                ++pending_bits;
                low -= FIRST_QTR;
                high -= FIRST_QTR;
            } else {
                break;
            }

            low = (low << 1) & TOP;
            high = ((high << 1) & TOP) | 1u;
        }
    }

    ++pending_bits;
    if (low < FIRST_QTR) {
        bitwriter_write_bit(&bw, 0);
        while (pending_bits > 0) {
            bitwriter_write_bit(&bw, 1);
            --pending_bits;
        }
    } else {
        bitwriter_write_bit(&bw, 1);
        while (pending_bits > 0) {
            bitwriter_write_bit(&bw, 0);
            --pending_bits;
        }
    }
    bitwriter_flush(&bw);

    fclose(fin);
    fclose(fout);
}

static void copy_file_bytes(FILE *dst, const char *src_path) {
    FILE *src = fopen(src_path, "rb");
    uint8_t buffer[4096];
    size_t nread;
    if (!src) {
        die_errno("Unable to open source file for copy");
    }
    while ((nread = fread(buffer, 1, sizeof(buffer), src)) > 0) {
        if (fwrite(buffer, 1, nread, dst) != nread) {
            fclose(src);
            die_errno("Failed writing stream payload");
        }
    }
    fclose(src);
}

static uint8_t compress_frames_batch(const FrameBatch *batch, const char *temp_dir, size_t batch_index, uint16_t *payload_len, char **payload_path_out) {
    char delta_name[64];
    char rle_name[64];
    char arithmetic_name[64];
    char *delta_path;
    char *rle_path;
    char *arithmetic_path;
    const char *entropy_input;
    uint16_t delta_size;
    uint16_t zrle_size;
    uint16_t arithmetic_size;
    int zrle_done;
    uint8_t raw_type;

    snprintf(delta_name, sizeof(delta_name), "batch_%06u_delta.bin", (unsigned) batch_index);
    snprintf(rle_name, sizeof(rle_name), "batch_%06u_zrle.bin", (unsigned) batch_index);
    snprintf(arithmetic_name, sizeof(arithmetic_name), "batch_%06u_arithmetic.bin", (unsigned) batch_index);
    delta_path = join_path(temp_dir, delta_name);
    rle_path = join_path(temp_dir, rle_name);
    arithmetic_path = join_path(temp_dir, arithmetic_name);

    frames_to_delta_ml(batch, delta_path);
    delta_size = get_file_size16(delta_path);
    zero_rle_encode(delta_path, rle_path);
    zrle_size = get_file_size16(rle_path);

    if (zrle_size > delta_size) {
        entropy_input = delta_path;
        zrle_done = 0;
        raw_type = BATCH_RAW_DELTA;
    } else {
        entropy_input = rle_path;
        zrle_done = 1;
        raw_type = BATCH_RAW_ZRLE;
    }

    arithmetic_encode(entropy_input, arithmetic_path, zrle_done);
    arithmetic_size = get_file_size16(arithmetic_path);

    if (arithmetic_size < get_file_size16(entropy_input)) {
        *payload_len = arithmetic_size;
        *payload_path_out = arithmetic_path;
        free(delta_path);
        free(rle_path);
        return BATCH_ARITHMETIC;
    }

    *payload_len = get_file_size16(entropy_input);
    *payload_path_out = (char *) entropy_input;
    if (entropy_input == delta_path) {
        free(rle_path);
        free(arithmetic_path);
    } else {
        free(delta_path);
        free(arithmetic_path);
    }
    return raw_type;
}

static void run_streaming_chain(double days, const char *output_bin, const char *txt_output, int max_changes, int master_frames_per_batch, uint32_t seed) {
    GeneratorState generator;
    FILE *compressed;
    char *output_dir;
    char *temp_dir;
    size_t batch_index = 0;
    size_t processed_frames = 0;
    size_t total_frames = total_frames_for_days(days);
    char temp_name[256];

    ensure_parent_dir(output_bin);
    ensure_parent_dir(txt_output);

    output_dir = path_dirname(output_bin);
    snprintf(temp_name, sizeof(temp_name), ".stream_tmp");
    temp_dir = join_path(output_dir, temp_name);
    remove_dir_recursive(temp_dir);
    if (MKDIR(temp_dir) != 0 && errno != EEXIST) {
        free(output_dir);
        free(temp_dir);
        die_errno("Unable to create temp directory");
    }

    compressed = fopen(output_bin, "wb");
    if (!compressed) {
        free(output_dir);
        free(temp_dir);
        die_errno("Unable to open compressed output");
    }

    {
        FILE *txt = fopen(txt_output, "w");
        if (!txt) {
            fclose(compressed);
            free(output_dir);
            free(temp_dir);
            die_errno("Unable to clear telemetry txt output");
        }
        fclose(txt);
    }

    generator_init(&generator, days, max_changes, seed);

    while (processed_frames < total_frames) {
        FrameBatch batch = generate_next_batch(&generator, master_frames_per_batch);
        uint16_t payload_len = 0;
        char *payload_path = NULL;
        uint8_t batch_type;
        double raw_size;
        double stored_size;
        const char *stored_as;

        if (batch.count == 0) {
            break;
        }

        ++batch_index;
        append_frames_to_txt(&batch, txt_output);
        batch_type = compress_frames_batch(&batch, temp_dir, batch_index, &payload_len, &payload_path);

        fputc(batch_type, compressed);
        write_u16_le(compressed, payload_len);
        copy_file_bytes(compressed, payload_path);

        processed_frames += batch.count;
        raw_size = (double) batch.count * FRAME_SIZE_BYTES;
        stored_size = (double) payload_len + 3.0;
        stored_as = (batch_type == BATCH_RAW_DELTA) ? "delta" :
                    (batch_type == BATCH_RAW_ZRLE) ? "zrle" : "arithmetic";
        printf("Batch %u: stored_as=%s, raw=%.0f bytes, compressed=%.0f bytes, CR=%.3f, total=%u/%u frames\n",
               (unsigned) batch_index,
               stored_as,
               raw_size,
               stored_size,
               raw_size / stored_size,
               (unsigned) processed_frames,
               (unsigned) total_frames);

        free(payload_path);
        free_batch(&batch);
    }

    fclose(compressed);
    remove_dir_recursive(temp_dir);
    free(output_dir);
    free(temp_dir);
}

int main(void) {
    const char *output_bin = "d:\\URSC\\Code\\telemetry_stream_compressed_c.bin";
    const char *output_txt = "d:\\URSC\\Code\\telemetry_stream_generated_c.txt";
    double days = 0.02;
    int master_frames_per_batch = MASTER_FRAMES_PER_BATCH;
    int max_changes = 1;
    uint32_t seed = 1u;

    run_streaming_chain(days, output_bin, output_txt, max_changes, master_frames_per_batch, seed);
    return 0;
}
