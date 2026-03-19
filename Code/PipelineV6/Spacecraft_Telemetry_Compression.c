#include <ctype.h>
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

/*
    This code assumes the telemetry file is a .txt file
    with frames of 2 digit hexadecimal (bytes) values
    which are space separated.

    Frame Length: Does not matter, code handles all frame
    lengths as long as all frames are of same length.

    2 digit hexadecimal bytes: Code supports upper and lowercase

    Code assumes no byte is missing in a frame.
    Each frame in a new line.

    Code can handle a SPACE character before first byte of frame
    (as seen in actual telemetry file)

    Example:
    85 2b 1a 68 50 00 a7.... (or uppercase-both work)
    8f a3 39 a9 70 34 25.....

    Output: .bin file with a compressed size. Testing says compressed size
            is about 1/10th size compared to input txt file. (sometimes more, rarely less)
            90% size reduction. Lossless.

            This output can only be decoded/decompressed by Ground_Telemetry_Decompression.c
*/


#define WINDOW_SIZE 32
#define BYPASS 0
#define SEQUENTIAL 1
#define MASTER 2

#define TAG_ZERO 0x00
#define TAG_LITERAL 0x01
#define MAX_LITERALS 0xFFFFu

#define TOP 0xFFFFFFFFu
#define HALF 0x80000000u
#define FIRST_QTR 0x40000000u
#define THIRD_QTR 0xC0000000u

typedef struct {
    uint8_t **data;
    size_t count;
    size_t frame_size;
} Frames;

typedef struct {
    FILE *f;
    uint8_t buffer;
    int nbits;
} BitWriter;

static void die(const char *message) {
    fprintf(stderr, "%s\n", message);
    exit(1);
}

static void die_errno(const char *message) {
    fprintf(stderr, "%s: %s\n", message, strerror(errno));
    exit(1);
}

static uint32_t get_file_size32(const char *path) {
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
    if (size < 0) {
        die("Unable to determine file size");
    }
    return (uint32_t) size;
}

static uint64_t get_file_size64(const char *path) {
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
    if (size < 0) {
        die("Unable to determine file size");
    }
    return (uint64_t) size;
}

static void write_u32_le(FILE *f, uint32_t value) {
    uint8_t buf[4];
    buf[0] = (uint8_t) (value & 0xFFu);
    buf[1] = (uint8_t) ((value >> 8) & 0xFFu);
    buf[2] = (uint8_t) ((value >> 16) & 0xFFu);
    buf[3] = (uint8_t) ((value >> 24) & 0xFFu);
    if (fwrite(buf, 1, 4, f) != 4) {
        die_errno("Failed writing uint32");
    }
}

static void write_u64_le(FILE *f, uint64_t value) {
    uint8_t buf[8];
    int i;
    for (i = 0; i < 8; ++i) {
        buf[i] = (uint8_t) ((value >> (8 * i)) & 0xFFu);
    }
    if (fwrite(buf, 1, 8, f) != 8) {
        die_errno("Failed writing uint64");
    }
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
        return copy;
    }
    *last1 = '\0';
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

static void free_frames(Frames *frames) {
    size_t i;
    if (!frames) {
        return;
    }
    for (i = 0; i < frames->count; ++i) {
        free(frames->data[i]);
    }
    free(frames->data);
    frames->data = NULL;
    frames->count = 0;
    frames->frame_size = 0;
}

////////////////////////////////# Load Telemetry #////////////////////////////

static Frames load_frames_from_txt(const char *txt_file, int *lead_space, int *upper_case) {
    FILE *f = fopen(txt_file, "r");
    Frames frames = {0};
    char line[65536];
    size_t capacity = 0;
    int found_case = 0;

    if (!f) {
        die_errno("Unable to open telemetry txt");
    }

    while (fgets(line, sizeof(line), f)) {
        char *token;
        uint8_t *frame = NULL;
        size_t count = 0;
        size_t token_capacity = 0;
        size_t i;

        *lead_space = (line[0] == ' ');
        for (i = 0; line[i] != '\0'; ++i) {
            if (isalpha((unsigned char) line[i])) {
                *upper_case = isupper((unsigned char) line[i]) ? 1 : 0;
                found_case = 1;
                break;
            }
        }

        token = strtok(line, " \t\r\n");
        while (token) {
            unsigned int value;
            uint8_t *grown;
            if (sscanf(token, "%x", &value) != 1 || value > 0xFFu) {
                fclose(f);
                free(frame);
                free_frames(&frames);
                die("Invalid hex byte in telemetry txt");
            }
            if (count == token_capacity) {
                token_capacity = token_capacity ? token_capacity * 2 : 64;
                grown = (uint8_t *) realloc(frame, token_capacity);
                if (!grown) {
                    fclose(f);
                    free(frame);
                    free_frames(&frames);
                    die("Out of memory");
                }
                frame = grown;
            }
            frame[count++] = (uint8_t) value;
            token = strtok(NULL, " \t\r\n");
        }

        if (count == 0) {
            free(frame);
            continue;
        }

        if (frames.count == 0) {
            frames.frame_size = count;
        } else if (count != frames.frame_size) {
            fclose(f);
            free(frame);
            free_frames(&frames);
            die("Telemetry txt contains frames of different lengths");
        }

        if (frames.count == capacity) {
            uint8_t **grown_rows;
            capacity = capacity ? capacity * 2 : 64;
            grown_rows = (uint8_t **) realloc(frames.data, capacity * sizeof(uint8_t *));
            if (!grown_rows) {
                fclose(f);
                free(frame);
                free_frames(&frames);
                die("Out of memory");
            }
            frames.data = grown_rows;
        }
        frames.data[frames.count++] = frame;
    }
    fclose(f);

    if (frames.count == 0) {
        die("Input telemetry txt has no frames");
    }
    if (!found_case) {
        *upper_case = 1;
    }
    return frames;
}

/////////////////////////// Feature Extraction //////////////////////////////

static void compute_window_features(uint8_t **current_window, uint8_t **prev_window, size_t frame_size, size_t window_len,
                                    double *f1, double *f2) {
    uint64_t seq_zero_count = 0;
    uint64_t seq_total = 0;
    uint64_t master_zero_count = 0;
    uint64_t master_total = 0;
    size_t k;
    size_t i;

    for (k = 1; k < window_len; ++k) {
        uint8_t *prev_frame = current_window[k - 1];
        uint8_t *current_frame = current_window[k];
        for (i = 0; i < frame_size; ++i) {
            uint8_t delta = (uint8_t) ((current_frame[i] - prev_frame[i]) & 0xFFu);
            if (delta == 0) {
                ++seq_zero_count;
            }
            ++seq_total;
        }
    }
    *f1 = seq_total ? ((double) seq_zero_count / (double) seq_total) : 0.0;

    if (!prev_window) {
        *f2 = 0.0;
        return;
    }

    for (k = 0; k < window_len; ++k) {
        for (i = 0; i < frame_size; ++i) {
            uint8_t delta = (uint8_t) ((current_window[k][i] - prev_window[k][i]) & 0xFFu);
            if (delta == 0) {
                ++master_zero_count;
            }
            ++master_total;
        }
    }
    *f2 = master_total ? ((double) master_zero_count / (double) master_total) : 0.0;
}

/////////////////////////// Delta Encoding //////////////////////////////////

static int behaviour_selector(double f1, double f2) {
    if ((f2 <= 0.42) && (f1 <= 0.43)) {
        return BYPASS;
    }
    if (f1 > 0.43) {
        return SEQUENTIAL;
    }
    return MASTER;
}

static void compute_delta(const uint8_t *current_frame, const uint8_t *reference_frame, uint8_t *out_frame, size_t frame_size) {
    size_t i;
    for (i = 0; i < frame_size; ++i) {
        out_frame[i] = (uint8_t) ((current_frame[i] - reference_frame[i]) & 0xFFu);
    }
}

static void frames_to_delta_ml(const Frames *frames, int lead_space, int upper_case, uint32_t frame_size, const char *out_bin) {
    FILE *f = fopen(out_bin, "wb");
    uint8_t *master_refs[32] = {0};
    uint8_t *prev_frame = NULL;
    uint8_t *window[WINDOW_SIZE];
    uint8_t *prev_window[WINDOW_SIZE];
    size_t frame_index = 0;
    size_t window_len = 0;
    size_t prev_window_len = 0;
    int current_mode = SEQUENTIAL;
    size_t i;

    if (!f) {
        die_errno("Unable to open delta output");
    }

    for (i = 0; i < frames->count; ++i) {
        uint8_t *current_frame = frames->data[i];
        size_t slot = frame_index % 32;
        uint8_t *out_frame;

        window[window_len++] = current_frame;
        if (window_len == WINDOW_SIZE) {
            double f1, f2;
            compute_window_features(window, prev_window_len ? prev_window : NULL, frame_size, WINDOW_SIZE, &f1, &f2);
            current_mode = behaviour_selector(f1, f2);
            memcpy(prev_window, window, sizeof(window));
            prev_window_len = WINDOW_SIZE;
            window_len = 0;
        }

        if (!prev_frame) {
            fputc(lead_space ? 1 : 0, f);
            fputc(upper_case ? 1 : 0, f);
            write_u32_le(f, frame_size);
            fputc(BYPASS, f);
            if (fwrite(current_frame, 1, frame_size, f) != frame_size) {
                fclose(f);
                die_errno("Failed writing first delta frame");
            }
            prev_frame = current_frame;
            master_refs[slot] = current_frame;
            ++frame_index;
            continue;
        }

        out_frame = (uint8_t *) malloc(frame_size);
        if (!out_frame) {
            fclose(f);
            die("Out of memory");
        }

        if (current_mode == BYPASS) {
            memcpy(out_frame, current_frame, frame_size);
        } else if (current_mode == SEQUENTIAL) {
            compute_delta(current_frame, prev_frame, out_frame, frame_size);
        } else {
            uint8_t *ref = master_refs[slot] ? master_refs[slot] : prev_frame;
            compute_delta(current_frame, ref, out_frame, frame_size);
        }

        fputc(current_mode, f);
        if (fwrite(out_frame, 1, frame_size, f) != frame_size) {
            free(out_frame);
            fclose(f);
            die_errno("Failed writing delta frame");
        }
        free(out_frame);
        prev_frame = current_frame;
        master_refs[slot] = current_frame;
        ++frame_index;
    }

    fclose(f);
}

/////////////////////////// Zero Run Length Encoding //////////////////////////

static void zero_rle_encode(const char *in_file, const char *out_file) {
    FILE *fin = fopen(in_file, "rb");
    FILE *fout = fopen(out_file, "wb");
    uint64_t original_size;
    uint32_t zero_run = 0;
    uint8_t *literal_buf = (uint8_t *) malloc(MAX_LITERALS);
    uint32_t literal_len = 0;
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

    original_size = get_file_size64(in_file);
    write_u64_le(fout, original_size);

    while ((c = fgetc(fin)) != EOF) {
        uint8_t b = (uint8_t) c;
        if (b == 0) {
            if (literal_len > 0) {
                fputc(TAG_LITERAL, fout);
                fputc((literal_len & 0xFFu), fout);
                fputc(((literal_len >> 8) & 0xFFu), fout);
                if (fwrite(literal_buf, 1, literal_len, fout) != literal_len) {
                    free(literal_buf);
                    fclose(fin);
                    fclose(fout);
                    die_errno("Failed writing literal packet");
                }
                literal_len = 0;
            }
            ++zero_run;
            if (zero_run == 0xFFFFFFFFu) {
                fputc(TAG_ZERO, fout);
                write_u32_le(fout, zero_run);
                zero_run = 0;
            }
        } else {
            if (zero_run > 0) {
                fputc(TAG_ZERO, fout);
                write_u32_le(fout, zero_run);
                zero_run = 0;
            }
            literal_buf[literal_len++] = b;
            if (literal_len == MAX_LITERALS) {
                fputc(TAG_LITERAL, fout);
                fputc((literal_len & 0xFFu), fout);
                fputc(((literal_len >> 8) & 0xFFu), fout);
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
        write_u32_le(fout, zero_run);
    }
    if (literal_len > 0) {
        fputc(TAG_LITERAL, fout);
        fputc((literal_len & 0xFFu), fout);
        fputc(((literal_len >> 8) & 0xFFu), fout);
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

///////////////// Entropy Coding Method- Arithmetic Coding ///////////////////

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

static void build_cumulative(const uint32_t freq[256], uint64_t cum[257]) {
    int i;
    uint64_t running = 0;
    cum[0] = 0;
    for (i = 0; i < 256; ++i) {
        running += freq[i];
        cum[i + 1] = running;
    }
}

static void arithmetic_encode(const char *in_file, const char *out_file, int zrle_done) {
    FILE *fin;
    FILE *fout;
    uint32_t freq[256] = {0};
    uint64_t cum[257];
    uint64_t total;
    uint32_t original_size = get_file_size32(in_file);
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
    write_u32_le(fout, original_size);
    for (i = 0; i < 256; ++i) {
        write_u32_le(fout, freq[i]);
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

////////////////////////////////# Pipeline #//////////////////////////////////

static void run_chain(const char *input_txt, const char *output_bin) {
    Frames frames;
    int lead_space = 0;
    int upper_case = 1;
    char *out_dir = path_dirname(output_bin);
    char *base = path_stem(output_bin);
    char temp_name[1024];
    char delta_name[1024];
    char rle_name[1024];
    char *temp_dir;
    char *delta_bin;
    char *rle_bin;
    uint32_t delta_size;
    uint32_t zrle_size;
    const char *entropy_input;
    int zrle_done;

    ensure_parent_dir(output_bin);
    snprintf(temp_name, sizeof(temp_name), ".%s_tmp", base);
    temp_dir = join_path(out_dir, temp_name);
    remove_dir_recursive(temp_dir);
    if (MKDIR(temp_dir) != 0) {
        free(out_dir);
        free(base);
        free(temp_dir);
        die_errno("Unable to create temp directory");
    }

    snprintf(delta_name, sizeof(delta_name), "%s_delta.bin", base);
    snprintf(rle_name, sizeof(rle_name), "%s_delta_rle.bin", base);
    delta_bin = join_path(temp_dir, delta_name);
    rle_bin = join_path(temp_dir, rle_name);

    frames = load_frames_from_txt(input_txt, &lead_space, &upper_case);
    frames_to_delta_ml(&frames, lead_space, upper_case, (uint32_t) frames.frame_size, delta_bin);
    delta_size = get_file_size32(delta_bin);
    zero_rle_encode(delta_bin, rle_bin);
    zrle_size = get_file_size32(rle_bin);

    if (zrle_size > delta_size) {
        entropy_input = delta_bin;
        zrle_done = 0;
    } else {
        entropy_input = rle_bin;
        zrle_done = 1;
    }

    arithmetic_encode(entropy_input, output_bin, zrle_done);

    free_frames(&frames);
    free(out_dir);
    free(base);
    free(delta_bin);
    free(rle_bin);
    remove_dir_recursive(temp_dir);
    free(temp_dir);
}

////////////////////////////////# Main #//////////////////////////////////////

int main(void) {
    const char *INPUT_TELEMETRY = "d:\\URSC\\Code\\TEST_3.txt";
    const char *OUTPUT_TELEMETRY_COMPRESSED = "d:\\URSC\\Code\\TEST_3_compressed_c.bin";
    run_chain(INPUT_TELEMETRY, OUTPUT_TELEMETRY_COMPRESSED);
    return 0;
}