"""Mimi decoded as a streaming codec: per-stream state, fixed cost per chunk, exact.

Why: `MimiModel.decode` in `transformers` keeps no state between calls, so the
first streaming build decoded each chunk together with a window of the frames
before it. Measured on ace-h200 with real speech through this checkpoint's
Mimi, against one whole-clip decode, that window was never good enough:

    context  8 frames: 48.8% peak error   16: 34.4%   32: 6.7%

because Mimi's decoder transformer attends 250 steps back, so any shorter
window changes every chunk's audio. Widening it to the whole utterance is exact
but makes each chunk cost more the longer a stream talks -- not acceptable for
live streaming, where the budget per chunk must not depend on how far into an
utterance a stream is.

So the decoder runs the way Mimi was designed to run, as a streaming codec.
Its three stages each need only bounded state, and each is carried per stream:

    quantizer.decode   per-frame embedding lookup             no state
    upsample           transposed conv, kernel 4, stride 2:   the previous frame
                       output 2t, 2t+1 depend on frames t-1, t
    transformer        8 layers, RoPE, causal attention over   a KV ring buffer
                       a 250-step sliding window               of 250 steps
    SEANet decoder     local causal convolutions up to 24 kHz  the last 8 steps
                                                               of transformer output

Every chunk therefore costs the same: its own frames through the upsample, a
transformer step for its new positions attending at most 250 cached keys, and
SEANet over 8 + new steps. The 8 is measured, not assumed: streamed against a
whole decode it was 38% off at 6 steps of history and exact (float noise) from
8 on, including utterances longer than the attention window, where the ring
buffer wraps.

The transformer step is re-implemented over the checkpoint's own modules
(projections, norms, layer scales, MLP, rotary embedding), because
`transformers` caches one batch together and cannot batch streams that are at
different positions. Here every row carries its own positions and its own
mask, so all concurrent streams step in ONE batched call. tests/ check it
against `MimiModel.decode` on a model whose decoder transformer is strong
enough to matter, streams of different lengths batched together, slots reused.

Not thread-safe by design: only the decoder worker thread calls `step`.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

#: Transformer-output steps of history SEANet needs to match a whole decode.
#: Measured (see module docstring); below it the output is wrong, not degraded.
SEANET_CONTEXT_STEPS = 8


@dataclass(frozen=True)
class Chunk:
    """One stream's next frames. `start` resets the slot for a new utterance."""

    slot: int
    frames: Sequence[Sequence[int]]
    start: bool = False


class MimiStreamer:
    """Batched, stateful Mimi decode for up to `slots` concurrent streams."""

    def __init__(self, mimi, *, slots: int, seanet_context: int = SEANET_CONTEXT_STEPS) -> None:
        import torch

        cfg = mimi.config
        self.mimi = mimi
        self.slots = slots
        self.window = int(cfg.sliding_window)
        self.layers = list(mimi.decoder_transformer.layers)
        self.heads = int(cfg.num_attention_heads)
        self.kv_heads = int(cfg.num_key_value_heads)
        self.head_dim = int(cfg.head_dim)
        self.hidden = int(cfg.hidden_size)
        self.context = seanet_context
        if self.kv_heads != self.heads:
            raise ValueError("this streamer assumes no grouped-query attention in Mimi")
        param = next(mimi.parameters())
        device, dtype = param.device, param.dtype
        n_layers = len(self.layers)
        # KV ring buffers, one row per slot: ~4 MB per slot in bf16.
        self.k = torch.zeros(n_layers, slots, self.heads, self.window, self.head_dim,
                             device=device, dtype=dtype)
        self.v = torch.zeros_like(self.k)
        self.kpos = torch.full((slots, self.window), -1, dtype=torch.long, device=device)
        self.pos = torch.zeros(slots, dtype=torch.long, device=device)
        self.prev = torch.zeros(slots, self.hidden, 1, device=device, dtype=dtype)
        self.hist = torch.zeros(slots, self.hidden, max(1, seanet_context),
                                device=device, dtype=dtype)
        # Host-side bookkeeping, so grouping needs no device sync.
        self.has_prev = [False] * slots
        self.hist_len = [0] * slots
        self.samples_per_step: int | None = None

    def reset(self, slot: int) -> None:
        self.kpos[slot] = -1
        self.pos[slot] = 0
        self.has_prev[slot] = False
        self.hist_len[slot] = 0

    # ------------------------------------------------------------------ api
    def step(self, chunks: Sequence[Chunk]) -> list[bytes]:
        """Decode every chunk; s16le PCM per chunk, in order.

        Chunks with the same frame count step together; within that, the
        stages whose history differs at the very start of a stream (upsample,
        SEANet) split into sub-batches by how much history the row has.
        """
        if len({c.slot for c in chunks}) != len(chunks):
            raise ValueError("a slot may appear once per step")
        for c in chunks:
            if c.start:
                self.reset(c.slot)
        out: list[bytes] = [b""] * len(chunks)
        by_n: dict[int, list[int]] = {}
        for i, c in enumerate(chunks):
            if c.frames:
                by_n.setdefault(len(c.frames), []).append(i)
        for indexes in by_n.values():
            for i, pcm in zip(indexes, self._step([chunks[i] for i in indexes]), strict=True):
                out[i] = pcm
        return out

    # ------------------------------------------------------------ internals
    def _step(self, chunks: Sequence[Chunk]) -> list[bytes]:
        import torch
        import torch.nn.functional as F
        from transformers.models.mimi.modeling_mimi import apply_rotary_pos_emb

        m = self.mimi
        device = self.k.device
        slots = [c.slot for c in chunks]
        sl = torch.tensor(slots, device=device)
        rows_n = len(chunks)
        n = len(chunks[0].frames)

        with torch.inference_mode():
            codes = torch.tensor([[list(f) for f in c.frames] for c in chunks],
                                 dtype=torch.long).permute(0, 2, 1).to(device)   # [R, Q, n]
            x = m.quantizer.decode(codes)                                         # [R, D, n]

            # ---- upsample: needs the previous frame
            up = torch.empty(rows_n, self.hidden, 2 * n, device=device, dtype=x.dtype)
            for flag in (True, False):
                rows = [i for i, s in enumerate(slots) if self.has_prev[s] is flag]
                if not rows:
                    continue
                xi = x[rows]
                if flag:
                    xi = torch.cat([self.prev[sl[rows]], xi], dim=-1)
                    up[rows] = m.upsample(xi)[..., 2:]       # drop the 2 outputs t-1 owns
                else:
                    up[rows] = m.upsample(xi)
            self.prev[sl] = x[..., -1:]
            for s in slots:
                self.has_prev[s] = True

            # ---- transformer: one step for every row's new positions
            steps = 2 * n
            h = up.transpose(1, 2)                                                # [R, T, D]
            qpos = self.pos[sl][:, None] + torch.arange(steps, device=device)     # [R, T]
            cos, sin = m.decoder_transformer.rotary_emb(h, qpos)
            kpos = torch.cat([self.kpos[sl], qpos], dim=1)                       # [R, W+T]
            mask = ((kpos[:, None, :] >= 0)
                    & (kpos[:, None, :] <= qpos[:, :, None])
                    & (kpos[:, None, :] > qpos[:, :, None] - self.window))[:, None]
            new_k, new_v = [], []
            for li, layer in enumerate(self.layers):
                attn = layer.self_attn
                y = layer.input_layernorm(h)
                q = attn.q_proj(y).view(rows_n, steps, self.heads, self.head_dim).transpose(1, 2)
                k = attn.k_proj(y).view(rows_n, steps, self.heads, self.head_dim).transpose(1, 2)
                v = attn.v_proj(y).view(rows_n, steps, self.heads, self.head_dim).transpose(1, 2)
                q, k = apply_rotary_pos_emb(q, k, cos, sin)
                keys = torch.cat([self.k[li, sl], k], dim=2)
                values = torch.cat([self.v[li, sl], v], dim=2)
                o = F.scaled_dot_product_attention(q, keys, values, attn_mask=mask,
                                                   scale=attn.scaling)
                o = attn.o_proj(o.transpose(1, 2).reshape(rows_n, steps, -1))
                h = h + layer.self_attn_layer_scale(o)
                h = h + layer.mlp_layer_scale(layer.mlp(layer.post_attention_layernorm(h)))
                new_k.append(k)
                new_v.append(v)
            # Written only after every layer has attended: a step longer than one
            # position overwrites ring entries its own earlier queries still need.
            ring = qpos % self.window
            si = sl[:, None].expand(rows_n, steps)
            for li in range(len(self.layers)):
                self.k[li][si, :, ring] = new_k[li].permute(0, 2, 1, 3)
                self.v[li][si, :, ring] = new_v[li].permute(0, 2, 1, 3)
            self.kpos[si, ring] = qpos
            self.pos[sl] += steps

            # ---- SEANet: local convolutions over the last few steps + new ones
            out = h.transpose(1, 2)                                               # [R, D, T]
            pcm: list[bytes] = [b""] * rows_n
            for have in sorted({self.hist_len[s] for s in slots}):
                rows = [i for i, s in enumerate(slots) if self.hist_len[s] == have]
                inp = out[rows]
                if have:
                    inp = torch.cat([self.hist[sl[rows], :, self.context - have:], inp], dim=-1)
                wav = m.decoder(inp)[:, 0]                            # [r, (have+T)*spt]
                spt = wav.shape[-1] // (have + steps)
                self.samples_per_step = spt
                fresh = (wav[:, have * spt:].float().clamp(-1.0, 1.0) * 32767.0)
                host = fresh.to(torch.int16).cpu().numpy()
                for j, i in enumerate(rows):
                    pcm[i] = host[j].astype("<i2").tobytes()
            if self.context:
                self.hist[sl] = torch.cat([self.hist[sl], out], dim=-1)[..., -self.context:]
                for s in slots:
                    self.hist_len[s] = min(self.context, self.hist_len[s] + steps)
        return pcm
