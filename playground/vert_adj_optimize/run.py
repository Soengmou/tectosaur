import numpy as np

from tectosaur.util.timer import Timer
import tectosaur.util.gpu as gpu
from tectosaur.nearfield_op import cached_vert_adj_quad, pairs_quad, get_gpu_config, float_type

def vertex_adj_pairs_quad(K, sm, pr, pts, obs_tris, src_tris, nq):
    cfg = get_gpu_config()
    cfg['nq'] = nq
    integrator = getattr(gpu.load_gpu('fast_vert_adj.cl', tmpl_args = cfg), 'vert_adj_pairs' + K)

    n = obs_tris.shape[0]
    out = np.empty((n, 3, 3, 3, 3), dtype = float_type)
    if n == 0:
        return out

    gpu_pts = gpu.to_gpu(pts, float_type)

    def call_integrator(start_idx, end_idx):
        n_items = end_idx - start_idx
        gpu_result = gpu.empty_gpu((n_items, 3, 3, 3, 3), float_type)
        gpu_obs_tris = gpu.to_gpu(obs_tris[start_idx:end_idx], np.int32)
        gpu_src_tris = gpu.to_gpu(src_tris[start_idx:end_idx], np.int32)
        integrator(
            gpu.gpu_queue, (n_items,), None,
            gpu_result.data,
            gpu_pts.data, gpu_obs_tris.data, gpu_src_tris.data,
            np.float32(sm), np.float32(pr),
        )
        out[start_idx:end_idx] = gpu_result.get()

    t = Timer()
    call_size = 2 ** 14
    for I in gpu.intervals(n, call_size):
        call_integrator(*I)
        t.report("call")
    return out

nq = 11
kernel = 'H'
sm = 1.0
pr = 0.25

filebase = 'quicker_vert_adj'
# filebase = 'large_vert_adj'
correct_filename = 'correct_' + filebase + '.npy'

pts, obs_tris, src_tris = np.load(filebase + '.npy')
# q = cached_vert_adj_quad(nq)
# t = Timer()
# correct = pairs_quad(kernel, sm, pr, pts, obs_tris, src_tris, q, False)
# t.report('integrate')
# np.save(correct_filename, correct)
correct = np.load(correct_filename)

# t = Timer()
# out = vertex_adj_pairs_quad(kernel, sm, pr, pts, obs_tris, src_tris, nq)
# t.report('integrate')
q = cached_vert_adj_quad(nq)
t = Timer()
print(obs_tris.shape[0])
print(q[0].shape[0])
out = pairs_quad(kernel, sm, pr, pts, obs_tris, src_tris, q, False)
t.report('integrate')
np.testing.assert_almost_equal(out, correct)

