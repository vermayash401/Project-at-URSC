#ifndef TELEMETRY_COMPRESSOR_H
#define TELEMETRY_COMPRESSOR_H

#include <stdint.h>

/* Max possible compressed size (safe upper bound) */
#define MAX_COMPRESSED_SIZE 65535
#define TELEMETRY_BATCH_FRAMES 128

/*
 * Adds new telemetry frames to the in-progress batch and, once the batch is
 * full, applies the compression pipeline.
 *
 * INPUT:
 *   frames_to_generate -> number of fresh frames to add to the current batch
 *   out_buf             -> buffer to store compressed output when ready
 *   out_capacity        -> size of out_buf in bytes
 *   out_size            -> size of compressed data when a batch is ready
 *
 * RETURN:
 *   1  -> batch became full and was compressed into out_buf
 *   0  -> batch is not full yet
 *  -1  -> failure
 */
int telemetry_generate_and_compress(uint16_t frames_to_generate,
                                    uint8_t *out_buf,
                                    uint16_t out_capacity,
                                    uint16_t *out_size);

#endif
