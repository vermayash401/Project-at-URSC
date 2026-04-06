#include "telemetry_compressor.h"

#include <stdlib.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

/* ================= CONFIG ================= */

#define FRAME_SIZE_BYTES 256
#define HEADER_BYTES 5
#define PAYLOAD_BYTES (FRAME_SIZE_BYTES - 6)

#define FRAMES_PER_MASTER_FRAME 32
#define MASTER_FRAMES_PER_BATCH 4
#define TOTAL_FRAMES (FRAMES_PER_MASTER_FRAME * MASTER_FRAMES_PER_BATCH)
#define WINDOW_SIZE FRAMES_PER_MASTER_FRAME

#define MAX_CHANGES 32

#define BYPASS 0
#define SEQUENTIAL 1
#define MASTER 2

#define BATCH_RAW_DELTA 0
#define BATCH_RAW_ZRLE 1
#define BATCH_ARITHMETIC 2

#define TAG_ZERO 0x00
#define TAG_LITERAL 0x01
#define MAX_ZEROS 0xFFFFu
#define MAX_LITERALS 0xFFFFu

#define TOP 0xFFFFFFFFu
#define HALF 0x80000000u
#define FIRST_QTR 0x40000000u
#define THIRD_QTR 0xC0000000u

/* ================= STATIC BUFFERS ================= */

static uint8_t frames[TOTAL_FRAMES][FRAME_SIZE_BYTES];
static uint8_t delta_out[TOTAL_FRAMES * (FRAME_SIZE_BYTES + 1)];
static uint8_t zrle_out[MAX_COMPRESSED_SIZE];
static uint8_t arithmetic_out[MAX_COMPRESSED_SIZE];
static uint8_t final_out[MAX_COMPRESSED_SIZE];

/* ================= RNG / GENERATOR ================= */

static uint32_t state = 1;
static uint8_t payload[PAYLOAD_BYTES];
static uint8_t master_ref_payloads[FRAMES_PER_MASTER_FRAME][PAYLOAD_BYTES];
static uint8_t header_bytes[HEADER_BYTES];
static int telemetry_mode = SEQUENTIAL;
static uint16_t frames_in_batch = 0;
static uint16_t batch_counter = 0;
static int initialized = 0;

static uint32_t rng_next(void)
{
    state = state * 1664525u + 1013904223u;
    return state;
}

static uint8_t rng_byte(void)
{
    return (uint8_t)(rng_next() >> 24);
}

static void random_payload(uint8_t *p)
{
    int i;

    for (i = 0; i < PAYLOAD_BYTES; i++)
        p[i] = rng_byte();
}

static void init_generator(void)
{
    int i;

    random_payload(payload);

    for (i = 0; i < FRAMES_PER_MASTER_FRAME; i++)
        random_payload(master_ref_payloads[i]);

    initialized = 1;
}

static void mutate_payload(uint8_t *p)
{
    int changes = (rng_byte() % MAX_CHANGES) + 1;
    int i;

    for (i = 0; i < changes; i++)
    {
        int pos = rng_byte() % PAYLOAD_BYTES;
        p[pos] = rng_byte();
    }
}

static void write_batch_first_frame(const uint8_t *frame)
{
    char filename[64];
    FILE *fp;
    int i;

  
    snprintf(filename, sizeof(filename), "/tmp/comp_batch_%u.raw.txt", batch_counter);
    fp = fopen(filename, "w");
    if (fp == NULL)
        return;

    for (i = 0; i < FRAME_SIZE_BYTES; i++)
    {
        fprintf(fp, "%02X", frame[i]);
        if (i + 1 < FRAME_SIZE_BYTES)
            fputc(' ', fp);
    }
    fputc('\n', fp);
    fclose(fp);
}

static void generate_frame(uint16_t frame_index)
{
    int slot = frame_index % FRAMES_PER_MASTER_FRAME;
    uint8_t *frame = frames[frame_index];
    int i;

    if (slot == 0)
    {
        for (i = 0; i < HEADER_BYTES; i++)
            header_bytes[i] = rng_byte();

        telemetry_mode = (rng_next() & 1u) ? MASTER : SEQUENTIAL;
    }

    memcpy(frame, header_bytes, HEADER_BYTES);
    frame[5] = (uint8_t)slot;

    if (telemetry_mode == SEQUENTIAL)
    {
        mutate_payload(payload);
        memcpy(&frame[6], payload, PAYLOAD_BYTES);
    }
    else
    {
        if (slot == 0)
        {
            for (i = 0; i < FRAMES_PER_MASTER_FRAME; i++)
                mutate_payload(master_ref_payloads[i]);
        }

        memcpy(&frame[6], master_ref_payloads[slot], PAYLOAD_BYTES);
    }

    if (frame_index == 0)
        write_batch_first_frame(frame);
}

static void generate_frames(uint16_t frame_count)
{
    if (!initialized)
        init_generator();

    while (frame_count > 0 && frames_in_batch < TOTAL_FRAMES)
    {
        generate_frame(frames_in_batch);
        frames_in_batch++;
        frame_count--;
    }
}

/* ================= DELTA (V7 STYLE) ================= */

static void compute_window_features(const uint8_t *current_window,
                                    const uint8_t *prev_window,
                                    double *f1,
                                    double *f2)
{
    uint32_t seq_zero_count = 0;
    uint32_t seq_total = 0;
    uint32_t master_zero_count = 0;
    uint32_t master_total = 0;
    int k;
    int i;

    for (k = 1; k < WINDOW_SIZE; ++k)
    {
        const uint8_t *prev_frame = current_window + (k - 1) * FRAME_SIZE_BYTES;
        const uint8_t *current_frame = current_window + k * FRAME_SIZE_BYTES;

        for (i = 0; i < FRAME_SIZE_BYTES; ++i)
        {
            uint8_t delta = (uint8_t)((current_frame[i] - prev_frame[i]) & 0xFFu);
            if (delta == 0)
                ++seq_zero_count;
            ++seq_total;
        }
    }

    *f1 = seq_total ? (double)seq_zero_count / (double)seq_total : 0.0;

    if (prev_window == NULL)
    {
        *f2 = 0.0;
        return;
    }

    for (k = 0; k < WINDOW_SIZE; ++k)
    {
        const uint8_t *current_frame = current_window + k * FRAME_SIZE_BYTES;
        const uint8_t *prev_frame = prev_window + k * FRAME_SIZE_BYTES;

        for (i = 0; i < FRAME_SIZE_BYTES; ++i)
        {
            uint8_t delta = (uint8_t)((current_frame[i] - prev_frame[i]) & 0xFFu);
            if (delta == 0)
                ++master_zero_count;
            ++master_total;
        }
    }

    *f2 = master_total ? (double)master_zero_count / (double)master_total : 0.0;
}

static int behaviour_selector(double f1, double f2)
{
    if ((f2 <= 0.42) && (f1 <= 0.43))
        return BYPASS;
    if (f1 > 0.43)
        return SEQUENTIAL;
    return MASTER;
}

static void compute_delta(const uint8_t *current_frame,
                          const uint8_t *reference_frame,
                          uint8_t *out_frame)
{
    int i;

    for (i = 0; i < FRAME_SIZE_BYTES; ++i)
        out_frame[i] = (uint8_t)((current_frame[i] - reference_frame[i]) & 0xFFu);
}

static uint16_t delta_encode_v7(void)
{
    uint8_t master_refs[FRAMES_PER_MASTER_FRAME][FRAME_SIZE_BYTES];
    uint8_t prev_window[WINDOW_SIZE][FRAME_SIZE_BYTES];
    uint8_t window[WINDOW_SIZE][FRAME_SIZE_BYTES];
    int have_master_ref[FRAMES_PER_MASTER_FRAME] = {0};
    int have_prev_window = 0;
    const uint8_t *prev_frame = NULL;
    size_t frame_index = 0;
    size_t window_len = 0;
    int current_mode = SEQUENTIAL;
    uint16_t out_idx = 0;
    int i;

    for (i = 0; i < TOTAL_FRAMES; ++i)
    {
        const uint8_t *current_frame = frames[i];
        size_t slot = frame_index % FRAMES_PER_MASTER_FRAME;
        uint8_t out_frame[FRAME_SIZE_BYTES];

        memcpy(window[window_len], current_frame, FRAME_SIZE_BYTES);
        ++window_len;

        if (window_len == WINDOW_SIZE)
        {
            double f1;
            double f2;

            compute_window_features(&window[0][0],
                                    have_prev_window ? &prev_window[0][0] : NULL,
                                    &f1,
                                    &f2);
            current_mode = behaviour_selector(f1, f2);
            memcpy(prev_window, window, sizeof(window));
            have_prev_window = 1;
            window_len = 0;
        }

        if (prev_frame == NULL)
        {
            delta_out[out_idx++] = BYPASS;
            memcpy(&delta_out[out_idx], current_frame, FRAME_SIZE_BYTES);
            out_idx += FRAME_SIZE_BYTES;

            memcpy(master_refs[slot], current_frame, FRAME_SIZE_BYTES);
            have_master_ref[slot] = 1;
            prev_frame = current_frame;
            ++frame_index;
            continue;
        }

        if (current_mode == BYPASS)
        {
            memcpy(out_frame, current_frame, FRAME_SIZE_BYTES);
        }
        else if (current_mode == SEQUENTIAL)
        {
            compute_delta(current_frame, prev_frame, out_frame);
        }
        else
        {
            const uint8_t *ref = have_master_ref[slot] ? master_refs[slot] : prev_frame;
            compute_delta(current_frame, ref, out_frame);
        }

        delta_out[out_idx++] = (uint8_t)current_mode;
        memcpy(&delta_out[out_idx], out_frame, FRAME_SIZE_BYTES);
        out_idx += FRAME_SIZE_BYTES;

        memcpy(master_refs[slot], current_frame, FRAME_SIZE_BYTES);
        have_master_ref[slot] = 1;
        prev_frame = current_frame;
        ++frame_index;
    }

    return out_idx;
}

/* ================= ZRLE (V7 STYLE) ================= */

static void write_u16_le(uint8_t *buf, uint16_t *idx, uint16_t value)
{
    buf[(*idx)++] = (uint8_t)(value & 0xFFu);
    buf[(*idx)++] = (uint8_t)((value >> 8) & 0xFFu);
}

static uint16_t zrle_encode_v7(const uint8_t *in, uint16_t size)
{
    uint16_t in_idx = 0;
    uint16_t out_idx = 0;
    uint16_t zero_run = 0;
    static uint8_t literal_buf[MAX_LITERALS];
    uint16_t literal_len = 0;

    write_u16_le(zrle_out, &out_idx, size);

    while (in_idx < size)
    {
        uint8_t b = in[in_idx++];

        if (b == 0)
        {
            if (literal_len > 0)
            {
                zrle_out[out_idx++] = TAG_LITERAL;
                write_u16_le(zrle_out, &out_idx, literal_len);
                memcpy(&zrle_out[out_idx], literal_buf, literal_len);
                out_idx += literal_len;
                literal_len = 0;
            }

            ++zero_run;
            if (zero_run == MAX_ZEROS)
            {
                zrle_out[out_idx++] = TAG_ZERO;
                write_u16_le(zrle_out, &out_idx, zero_run);
                zero_run = 0;
            }
        }
        else
        {
            if (zero_run > 0)
            {
                zrle_out[out_idx++] = TAG_ZERO;
                write_u16_le(zrle_out, &out_idx, zero_run);
                zero_run = 0;
            }

            literal_buf[literal_len++] = b;
            if (literal_len == MAX_LITERALS)
            {
                zrle_out[out_idx++] = TAG_LITERAL;
                write_u16_le(zrle_out, &out_idx, literal_len);
                memcpy(&zrle_out[out_idx], literal_buf, literal_len);
                out_idx += literal_len;
                literal_len = 0;
            }
        }
    }

    if (zero_run > 0)
    {
        zrle_out[out_idx++] = TAG_ZERO;
        write_u16_le(zrle_out, &out_idx, zero_run);
    }

    if (literal_len > 0)
    {
        zrle_out[out_idx++] = TAG_LITERAL;
        write_u16_le(zrle_out, &out_idx, literal_len);
        memcpy(&zrle_out[out_idx], literal_buf, literal_len);
        out_idx += literal_len;
    }

    return out_idx;
}

/* ================= ARITHMETIC (V7 STYLE) ================= */

typedef struct
{
    uint8_t *data;
    uint32_t capacity;
    uint32_t index;
    uint8_t buffer;
    int nbits;
    int overflow;
} BitWriter;

static void bitwriter_init(BitWriter *bw, uint8_t *data, uint32_t capacity, uint32_t start_index)
{
    bw->data = data;
    bw->capacity = capacity;
    bw->index = start_index;
    bw->buffer = 0;
    bw->nbits = 0;
    bw->overflow = 0;
}

static void bitwriter_write_byte(BitWriter *bw, uint8_t value)
{
    if (bw->index >= bw->capacity)
    {
        bw->overflow = 1;
        return;
    }

    bw->data[bw->index++] = value;
}

static void bitwriter_write_bit(BitWriter *bw, int bit)
{
    bw->buffer = (uint8_t)((bw->buffer << 1) | (bit & 1));
    ++bw->nbits;

    if (bw->nbits == 8)
    {
        bitwriter_write_byte(bw, bw->buffer);
        bw->buffer = 0;
        bw->nbits = 0;
    }
}

static void bitwriter_flush(BitWriter *bw)
{
    if (bw->nbits > 0)
    {
        bw->buffer <<= (8 - bw->nbits);
        bitwriter_write_byte(bw, bw->buffer);
        bw->buffer = 0;
        bw->nbits = 0;
    }
}

static void build_cumulative(const uint16_t freq[256], uint32_t cum[257])
{
    int i;
    uint32_t running = 0;

    cum[0] = 0;
    for (i = 0; i < 256; ++i)
    {
        running += freq[i];
        cum[i + 1] = running;
    }
}

static int arithmetic_encode_v7(const uint8_t *in,
                                uint16_t size,
                                int zrle_done,
                                uint16_t *out_size)
{
    uint16_t freq[256] = {0};
    uint32_t cum[257];
    uint32_t total;
    BitWriter bw;
    uint32_t low = 0;
    uint32_t high = TOP;
    uint32_t pending_bits = 0;
    uint16_t idx = 0;
    uint16_t i;

    if (size == 0)
        return -1;

    for (i = 0; i < size; ++i)
    {
        if (freq[in[i]] == 0xFFFFu)
            return -1;
        ++freq[in[i]];
    }

    build_cumulative(freq, cum);
    total = cum[256];

    arithmetic_out[idx++] = zrle_done ? 1u : 0u;
    write_u16_le(arithmetic_out, &idx, size);

    for (i = 0; i < 256; ++i)
        write_u16_le(arithmetic_out, &idx, freq[i]);

    bitwriter_init(&bw, arithmetic_out, MAX_COMPRESSED_SIZE, idx);

    for (i = 0; i < size; ++i)
    {
        uint8_t sym = in[i];
        uint64_t range = (uint64_t)high - low + 1u;
        uint64_t sym_low = cum[sym];
        uint64_t sym_high = cum[sym + 1];

        high = low + (uint32_t)((range * sym_high) / total) - 1u;
        low = low + (uint32_t)((range * sym_low) / total);

        for (;;)
        {
            if (high < HALF)
            {
                bitwriter_write_bit(&bw, 0);
                while (pending_bits > 0)
                {
                    bitwriter_write_bit(&bw, 1);
                    --pending_bits;
                }
            }
            else if (low >= HALF)
            {
                bitwriter_write_bit(&bw, 1);
                while (pending_bits > 0)
                {
                    bitwriter_write_bit(&bw, 0);
                    --pending_bits;
                }
                low -= HALF;
                high -= HALF;
            }
            else if (low >= FIRST_QTR && high < THIRD_QTR)
            {
                ++pending_bits;
                low -= FIRST_QTR;
                high -= FIRST_QTR;
            }
            else
            {
                break;
            }

            low = (low << 1) & TOP;
            high = ((high << 1) & TOP) | 1u;
        }
    }

    ++pending_bits;
    if (low < FIRST_QTR)
    {
        bitwriter_write_bit(&bw, 0);
        while (pending_bits > 0)
        {
            bitwriter_write_bit(&bw, 1);
            --pending_bits;
        }
    }
    else
    {
        bitwriter_write_bit(&bw, 1);
        while (pending_bits > 0)
        {
            bitwriter_write_bit(&bw, 0);
            --pending_bits;
        }
    }

    bitwriter_flush(&bw);

    if (bw.overflow)
        return -1;

    *out_size = (uint16_t)bw.index;
    return 0;
}

/* ================= MAIN ================= */

int telemetry_generate_and_compress(uint16_t frames_to_generate,
                                    uint8_t *out_buf,
                                    uint16_t out_capacity,
                                    uint16_t *out_size)
{
    uint16_t delta_size;
    uint16_t zrle_size;
    uint16_t arithmetic_size = 0;
    const uint8_t *entropy_input;
    uint16_t entropy_size;
    int zrle_done;
    uint8_t batch_type;
    const uint8_t *payload_ptr;
    uint16_t payload_size;
    uint32_t total_size;

    if (!out_buf || !out_size)
        return -1;

    *out_size = 0;

    if (frames_to_generate > 0)
        generate_frames(frames_to_generate);

    if (frames_in_batch < TOTAL_FRAMES)
        return 0;

    delta_size = delta_encode_v7();
    zrle_size = zrle_encode_v7(delta_out, delta_size);

    if (zrle_size > delta_size)
    {
        entropy_input = delta_out;
        entropy_size = delta_size;
        zrle_done = 0;
        batch_type = BATCH_RAW_DELTA;
    }
    else
    {
        entropy_input = zrle_out;
        entropy_size = zrle_size;
        zrle_done = 1;
        batch_type = BATCH_RAW_ZRLE;
    }

    if (arithmetic_encode_v7(entropy_input, entropy_size, zrle_done, &arithmetic_size) == 0 &&
        arithmetic_size < entropy_size)
    {
        payload_ptr = arithmetic_out;
        payload_size = arithmetic_size;
        batch_type = BATCH_ARITHMETIC;
    }
    else
    {
        payload_ptr = entropy_input;
        payload_size = entropy_size;
    }

    total_size = (uint32_t)payload_size + 3u;
    if (total_size > MAX_COMPRESSED_SIZE || total_size > out_capacity)
        return -1;

    final_out[0] = batch_type;
    final_out[1] = (uint8_t)(payload_size & 0xFFu);
    final_out[2] = (uint8_t)((payload_size >> 8) & 0xFFu);
    memcpy(&final_out[3], payload_ptr, payload_size);
    memcpy(out_buf, final_out, total_size);

    *out_size = (uint16_t)total_size;
    frames_in_batch = 0;
    batch_counter++;

    return 1;
}
