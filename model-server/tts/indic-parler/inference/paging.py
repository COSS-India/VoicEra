"""KV cache for the Parler decoder: one fixed tensor, one slot per request.

Three other backends used to live here -- PageTable, VirtualMemoryPaged (a
FlashInfer paged-attention implementation), VirtualMemorySDPA and
VirtualMemoryCompare, together about 490 lines. None of them ran. runner.py has
only ever built both caches with type="dense", so the paged path was a prototype
that was never switched on, while `import flashinfer` at the top of this file
stayed a hard, top-level dependency of a container that never called it -- and
both READMEs, plus the test named after it, described the dead half as if it
were the live one.

What actually serves traffic, and all that is left, is VirtualMemoryDense: a
pre-allocated contiguous K/V tensor with slot allocation, mask maintenance,
compaction and plain SDPA. Removed rather than kept "in case": they are in git
history, and unreachable code that the docs advertise is worse than absent code.
"""
import torch
from inference.config import device

try:
    from torch.nn.attention import SDPBackend, sdpa_kernel

    # Short masked decode: MATH keeps SMs busy. Longer buckets: efficient kernels
    # keep step time well under 7ms.
    _SDPA_SHORT = [SDPBackend.MATH]
    _SDPA_LONG = [
        SDPBackend.EFFICIENT_ATTENTION,
        SDPBackend.FLASH_ATTENTION,
        SDPBackend.MATH,
    ]
    _SDPA_SHORT_LEN = 256
except Exception:  # pragma: no cover
    sdpa_kernel = None
    _SDPA_SHORT = _SDPA_LONG = None
    _SDPA_SHORT_LEN = 256



class VirtualMemoryDense:
    """
    Contiguous KV cache + SDPA. Fixed shapes so the full decode step can be
    captured in a CUDA graph (unlike FlashInfer on this stack).
    """

    def __init__(
        self,
        max_num_pages,
        page_size,
        num_kv_heads,
        head_dim,
        num_layers,
        max_seq_len=1024,
        max_batch_size=32,
    ):
        self.num_kv_heads = num_kv_heads
        self.head_dim = head_dim
        self.num_layers = num_layers
        self.max_seq_len = max_seq_len
        self.max_batch_size = max_batch_size
        self.k_cache = torch.zeros(
            num_layers,
            max_batch_size,
            num_kv_heads,
            max_seq_len,
            head_dim,
            dtype=torch.float16,
            device=device,
        )
        self.v_cache = torch.zeros_like(self.k_cache)
        self.seq_lens = torch.zeros(max_batch_size, dtype=torch.int32, device=device)
        # 0 = attend, -inf = masked
        self.attn_mask = torch.full(
            (max_batch_size, 1, 1, max_seq_len),
            float("-inf"),
            dtype=torch.float16,
            device=device,
        )
        self.pid_to_slot = {}
        self._free_slots = list(range(max_batch_size))
        self._cg_bs = None
        # Persistent buffers closed over by CUDA-graph closures (updated in-place).
        self._write_slots = torch.arange(
            max_batch_size, dtype=torch.int64, device=device
        )
        self._write_positions = torch.zeros(
            max_batch_size, dtype=torch.int64, device=device
        )
        self._active_n = 0
        # Host-side seq lengths — avoid GPU sync (.item) on the hot decode path.
        self._host_seq_lens = [0] * max_batch_size

    def enable_cuda_graph(self, batch_size):
        if batch_size > self.max_batch_size:
            raise RuntimeError(
                f"batch_size {batch_size} > max_batch_size {self.max_batch_size}"
            )
        self._cg_bs = batch_size

    def disable_cuda_graph(self):
        self._cg_bs = None

    def max_host_seq_len(self, n=None):
        if n is None:
            n = len(self.pid_to_slot)
        if n <= 0:
            return 0
        return max(self._host_seq_lens[:n])

    def prefill(self, pid, model_kv_cache):
        assert model_kv_cache[0][0].shape[0] == 1
        if pid in self.pid_to_slot:
            raise RuntimeError(f"pid {pid} already prefilling")
        # Validate BEFORE taking a slot. Raising after the pop leaked the slot --
        # it never returned to _free_slots, and pid_to_slot kept an entry with no
        # cache behind it, so the next batch was built with a shape mismatch
        # rather than one request short.
        n_seq = model_kv_cache[0][0].shape[2]
        if n_seq > self.max_seq_len:
            raise RuntimeError(
                f"prefill len {n_seq} > max_seq_len {self.max_seq_len}"
            )
        if not self._free_slots:
            raise RuntimeError("dense KV: no free slots")
        slot = self._free_slots.pop(0)
        self.pid_to_slot[pid] = slot
        for layer in range(self.num_layers):
            self.k_cache[layer, slot, :, :n_seq].copy_(model_kv_cache[layer][0][0])
            self.v_cache[layer, slot, :, :n_seq].copy_(model_kv_cache[layer][1][0])
        self.seq_lens[slot] = n_seq
        self._host_seq_lens[slot] = n_seq
        self.attn_mask[slot].fill_(float("-inf"))
        self.attn_mask[slot, 0, 0, :n_seq] = 0

    def free(self, pid, compact=True):
        slot = self.pid_to_slot.pop(pid)
        self.seq_lens[slot] = 0
        self._host_seq_lens[slot] = 0
        self.attn_mask[slot].fill_(float("-inf"))
        self._free_slots.append(slot)
        self._free_slots.sort()
        if compact:
            self.compact()

    def compact(self):
        """Repack active sequences into slots 0..n-1 (required for CUDA graphs)."""
        if not self.pid_to_slot:
            self._free_slots = list(range(self.max_batch_size))
            self._host_seq_lens = [0] * self.max_batch_size
            return
        ordered = sorted(self.pid_to_slot.items(), key=lambda kv: kv[1])
        if [s for _, s in ordered] == list(range(len(ordered))):
            return  # already dense
        new_map = {}
        for new_slot, (pid, old_slot) in enumerate(ordered):
            if new_slot == old_slot:
                new_map[pid] = new_slot
                continue
            # Move KV + metadata
            self.k_cache[:, new_slot].copy_(self.k_cache[:, old_slot])
            self.v_cache[:, new_slot].copy_(self.v_cache[:, old_slot])
            self.seq_lens[new_slot] = self.seq_lens[old_slot]
            self._host_seq_lens[new_slot] = self._host_seq_lens[old_slot]
            self.attn_mask[new_slot].copy_(self.attn_mask[old_slot])
            self.seq_lens[old_slot] = 0
            self._host_seq_lens[old_slot] = 0
            self.attn_mask[old_slot].fill_(float("-inf"))
            new_map[pid] = new_slot
        self.pid_to_slot = new_map
        n = len(new_map)
        self._free_slots = list(range(n, self.max_batch_size))

    def get_decode_closures(self, grow=True, attn_len=None):
        sorted_pids = sorted(
            self.pid_to_slot.keys(), key=lambda p: self.pid_to_slot[p]
        )
        n = len(sorted_pids)
        if n == 0:
            raise RuntimeError("no active sequences")
        slots = [self.pid_to_slot[pid] for pid in sorted_pids]
        contiguous = slots == list(range(n))
        if self._cg_bs is not None and not contiguous:
            raise RuntimeError(
                "dense CUDA graph requires contiguous slots 0..bs-1"
            )
        if self._cg_bs is not None and n != self._cg_bs:
            raise RuntimeError(
                f"cuda-graph batch size mismatch: wrapper={self._cg_bs} active={n}"
            )

        # Contiguous 0..n-1: slots buffer is already arange; skip host->device copy.
        if not contiguous:
            self._write_slots[:n].copy_(
                torch.tensor(slots, dtype=torch.int64, device=device)
            )
        slot_tensor = self._write_slots[:n]
        self._active_n = n

        if grow:
            live_before = self.max_host_seq_len(n)
            if live_before >= self.max_seq_len:
                raise RuntimeError(
                    f"sequence exceeded max_seq_len={self.max_seq_len}"
                )
            # Write at current length, then bump host + device counters.
            self._write_positions[:n].copy_(self.seq_lens[slot_tensor].to(torch.int64))
            positions = self._write_positions[:n]
            self.seq_lens[slot_tensor] = self.seq_lens[slot_tensor] + 1
            for s in slots:
                self._host_seq_lens[s] += 1
            self.attn_mask[slot_tensor, 0, 0, positions] = 0

            def _cache_updater(layer_id, append_kv):
                assert append_kv[0].shape[0] == self._active_n
                k = append_kv[0].squeeze(2)
                v = append_kv[1].squeeze(2)
                if k.dtype != torch.float16:
                    k = k.half()
                    v = v.half()
                sl = self._write_slots[: self._active_n]
                pos = self._write_positions[: self._active_n]
                self.k_cache[layer_id, sl, :, pos, :] = k
                self.v_cache[layer_id, sl, :, pos, :] = v

        else:

            def _cache_updater(layer_id, append_kv):
                raise RuntimeError(
                    "cross-attn KV is static; cache updater must not be called"
                )

        k_view = self.k_cache[:, :n]
        v_view = self.v_cache[:, :n]
        mask_view = self.attn_mask[:n]
        use_index = not contiguous
        live_len = self.max_host_seq_len(n)
        # Fixed attn_len for CUDA-graph capture/replay (seq-length bucket).
        cur_len = int(attn_len) if attn_len is not None else live_len
        if cur_len < live_len:
            raise RuntimeError(f"attn_len {cur_len} < live seq {live_len}")
        if cur_len > self.max_seq_len:
            cur_len = self.max_seq_len

        def _attn(layer_id, q):
            if use_index:
                sl = self._write_slots[: self._active_n]
                k = self.k_cache[layer_id].index_select(0, sl)[:, :, :cur_len]
                v = self.v_cache[layer_id].index_select(0, sl)[:, :, :cur_len]
                m = self.attn_mask.index_select(0, sl)[:, :, :, :cur_len]
            else:
                k = k_view[layer_id, :, :, :cur_len]
                v = v_view[layer_id, :, :, :cur_len]
                m = mask_view[:, :, :, :cur_len]
            if sdpa_kernel is None:
                return torch.nn.functional.scaled_dot_product_attention(
                    q, k, v, attn_mask=m
                )
            backends = _SDPA_SHORT if cur_len <= _SDPA_SHORT_LEN else _SDPA_LONG
            with sdpa_kernel(backends):
                return torch.nn.functional.scaled_dot_product_attention(
                    q, k, v, attn_mask=m
                )

        return _cache_updater, _attn


def VirtualMemory(
    max_num_pages, page_size, num_kv_heads, head_dim, num_layers, type="dense", **kwargs
):
    if type == "dense":
        return VirtualMemoryDense(
            max_num_pages,
            page_size,
            num_kv_heads,
            head_dim,
            num_layers,
            **kwargs,
        )
    raise ValueError(
        f"unknown VirtualMemory type: {type!r}; only 'dense' is implemented "
        f"(paged/sdpa/compare were removed -- see the module docstring)"
    )

