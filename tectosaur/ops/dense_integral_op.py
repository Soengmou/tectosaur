import numpy as np

from tectosaur.nearfield.nearfield_op import NearfieldIntegralOp, \
    RegularizedNearfieldIntegralOp
from tectosaur.nearfield.pairs_integrator import get_gpu_module
from tectosaur.util.quadrature import gauss4d_tri
from tectosaur.ops.dense_op import DenseOp
import tectosaur.util.gpu as gpu
from tectosaur.util.timer import Timer

def farfield_tris(kernel, params, pts, obs_tris, src_tris, n_q, float_type):
    assembler = FarfieldTriMatrix(kernel, params, n_q, float_type)
    return assembler.assemble(pts, obs_tris, src_tris)

class FarfieldTriMatrix:
    def __init__(self, kernel, params, n_q, float_type):
        self.float_type = float_type
        self.integrator = getattr(get_gpu_module(kernel, float_type), "farfield_tris")
        self.q = gauss4d_tri(n_q, n_q)

        self.gpu_qx = gpu.to_gpu(self.q[0], float_type)
        self.gpu_qw = gpu.to_gpu(self.q[1], float_type)
        self.gpu_params = gpu.to_gpu(np.array(params), float_type)

    def assemble(self, pts, obs_tris, src_tris):
        gpu_pts = gpu.to_gpu(pts, self.float_type)
        gpu_src_tris = gpu.to_gpu(src_tris, np.int32)

        n = obs_tris.shape[0]
        out = np.empty(
            (n, 3, 3, src_tris.shape[0], 3, 3), dtype = self.float_type
        )

        def call_integrator(start_idx, end_idx):
            n_items = end_idx - start_idx
            gpu_result = gpu.empty_gpu((n_items, 3, 3, src_tris.shape[0], 3, 3), self.float_type)
            gpu_obs_tris = gpu.to_gpu(obs_tris[start_idx:end_idx], np.int32)
            self.integrator(
                gpu_result, np.int32(self.q[0].shape[0]),
                self.gpu_qx, self.gpu_qw,
                gpu_pts, np.int32(n_items), gpu_obs_tris,
                np.int32(src_tris.shape[0]), gpu_src_tris,
                self.gpu_params,
                grid = (n_items, src_tris.shape[0], 1),
                block = (1, 1, 1)
            )
            out[start_idx:end_idx] = gpu_result.get()

        call_size = 1024
        for I in gpu.intervals(n, call_size):
            call_integrator(*I)

        return out

class RegularizedDenseIntegralOp(DenseOp):
    def __init__(self, nq_coincident, nq_edge_adj, nq_vert_adjacent, nq_far, nq_near,
            near_threshold, K_near_name, K_far_name, params, pts, tris, float_type,
            obs_subset = None, src_subset = None):

        if obs_subset is None:
            obs_subset = np.arange(tris.shape[0])
        if src_subset is None:
            src_subset = np.arange(tris.shape[0])

        self.float_type = float_type

        nearfield = RegularizedNearfieldIntegralOp(
            pts, tris, obs_subset, src_subset,
            nq_coincident, nq_edge_adj, nq_vert_adjacent, nq_far, nq_near,
            near_threshold, K_near_name, K_far_name, params, float_type
        ).no_correction_to_dense()

        farfield = farfield_tris(
            K_far_name, params, pts, tris[obs_subset], tris[src_subset], nq_far, float_type
        ).reshape(nearfield.shape)

        self.mat = np.where(np.abs(nearfield) > 0, nearfield, farfield)
        #TODO: fix and use a non-hacky way of deciding when to use the nearfield!
        self.mat[np.isnan(self.mat)] = 0.0
        self.shape = self.mat.shape
        self.gpu_mat = None

    def dot(self, v):
        return self.mat.dot(v)
