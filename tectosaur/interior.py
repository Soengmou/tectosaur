import attr
import numpy as np
from tectosaur.util.quadrature import gauss2d_tri, gaussxw, map_to
import tectosaur.util.gpu as gpu
import scipy.sparse

import tectosaur.fmm.fmm as fmm
from tectosaur.farfield import farfield_pts_direct
import tectosaur.mesh.find_near_adj as find_near_adj
from tectosaur.kernels import kernels
from tectosaur.nearfield.pairs_integrator import get_gpu_module, block_size
from tectosaur.nearfield.triangle_rules import vertex_interior_quad

def make_pairs_mat(pairs, entries, shape):
    rows = np.tile(np.array([
        pairs[:,0] * 3 + i for i in range(3)
    ]).T[:,:, np.newaxis, np.newaxis], (1, 1, 9))

    cols = np.tile(np.array([
        pairs[:,1] * 9 + i for i in range(9)
    ]).T[:, np.newaxis, :], (1, 3, 1))

    return scipy.sparse.csr_matrix(
        (entries.flatten(), (rows.flatten(), cols.flatten())),
        shape = shape
    )


class InteriorOp:
    def __init__(self, obs_pts, obs_ns, src_mesh, K_name, threshold, nq_vertex, nq_far,
            nq_near, params, float_type):
        self.K_name = K_name
        self.float_type = float_type
        self.threshold = 4.0
        pairs = find_near_adj.fast_find_nearfield.get_nearfield(
            obs_pts, np.zeros(obs_pts.shape[0]),
            *find_near_adj.get_tri_centroids_rs(*src_mesh),
            self.threshold, 50
        )

        split = find_near_adj.split_vertex_nearfield(
            pairs, obs_pts, src_mesh[0], src_mesh[1]
        )
        self.vertex_pairs, self.near_pairs = split
        self.all_near_pairs = np.vstack((self.near_pairs, self.vertex_pairs))
        self.all_near_pairs[:,2] = 0

        # for i in range(self.vertex_pairs.shape[0]):
        #     np.testing.assert_almost_equal(
        #         obs_pts[self.vertex_pairs[i,0]],
        #         src_mesh[0][src_mesh[1][self.vertex_pairs[i,1], self.vertex_pairs[i,2]]]
        #     )

        self.farfield = TriToPtDirectFarfieldOp(
            obs_pts, obs_ns, src_mesh, K_name, nq_far,
            params, float_type
        )

        self.gpu_near_quad = self.quad_to_gpu(gauss2d_tri(nq_near))
        self.gpu_far_quad = self.quad_to_gpu(gauss2d_tri(nq_far))
        self.near_mat = self.pairs_mat(self.near_pairs, self.gpu_near_quad)
        self.near_mat_correction = self.pairs_mat(self.all_near_pairs, self.gpu_far_quad)

        self.vertex_mat = self.build_vertex_mat(
            self.vertex_pairs, self.quad_to_gpu(
                map_to(gaussxw(nq_vertex), [0.0, np.pi/2])
            )
        )

    def build_vertex_mat(self, pairs, quad):
        block_size = 128
        gpu_cfg = dict(
            block_size = block_size,
            float_type = gpu.np_to_c_type(self.float_type)
        )
        module = gpu.load_gpu('interior_corners.cl', tmpl_args = gpu_cfg, no_caching = True)

        n_pairs = pairs.shape[0]
        gpu_result = gpu.zeros_gpu((n_pairs, 3, 3, 3), self.float_type)
        gpu_pairs = gpu.to_gpu(pairs.copy(), np.int32)
        n_threads = int(np.ceil(n_pairs / block_size))

        if n_pairs != 0:
            module.interior_corners(
                gpu_result,
                np.int32(quad[0].shape[0]), quad[0], quad[1],
                self.farfield.gpu_obs_pts, self.farfield.gpu_obs_ns,
                self.farfield.gpu_src_pts, self.farfield.gpu_src_tris,
                gpu_pairs, np.int32(0), np.int32(n_pairs),
                self.farfield.gpu_params,
                grid = (n_threads, 1, 1), block = (block_size, 1, 1)
            )
        return make_pairs_mat(pairs, gpu_result.get(), self.farfield.shape)

    def pairs_mat(self, pairs, quad, finite_part = False):
        entries = interior_pairs_quad(self.K_name, pairs,
            quad, self.farfield.gpu_obs_pts, self.farfield.gpu_obs_ns,
            self.farfield.gpu_src_pts, self.farfield.gpu_src_tris,
            self.farfield.gpu_params, self.float_type,
            finite_part
        )
        return make_pairs_mat(pairs, entries, self.farfield.shape)

    #TODO: duplicated with pairs_integrator.py
    def quad_to_gpu(self, q):
        return [gpu.to_gpu(arr.copy(), self.float_type) for arr in q]

    def dot(self, v):
        return (
            self.farfield.dot(v)
            + self.near_mat.dot(v)
            - self.near_mat_correction.dot(v)
            + self.vertex_mat.dot(v)
        )

def interior_pairs_quad(K_name, pairs_list, gpu_quad,
        gpu_obs_pts, gpu_obs_ns, gpu_src_pts, gpu_src_tris,
        gpu_params, float_type, finite_part):

    n_pairs = pairs_list.shape[0]
    gpu_result = gpu.zeros_gpu((n_pairs, 3, 3, 3), float_type)
    gpu_pairs_list = gpu.to_gpu(pairs_list.copy(), np.int32)
    module = get_gpu_module(K_name, float_type)
    n_threads = int(np.ceil(n_pairs / block_size))

    if n_pairs != 0:
        module.interior_pairs(
            gpu_result,
            np.int32(gpu_quad[0].shape[0]), gpu_quad[0], gpu_quad[1],
            gpu_obs_pts, gpu_obs_ns,
            gpu_src_pts, gpu_src_tris,
            gpu_pairs_list, np.int32(0), np.int32(n_pairs),
            gpu_params, np.int32(1 if finite_part else 0),
            grid = (n_threads, 1, 1), block = (block_size, 1, 1)
        )
    return gpu_result.get()

#TODO: A lot of duplication with TriToTriDirectFarfieldOp
class TriToPtDirectFarfieldOp:
    def __init__(self, obs_pts, obs_ns, src_mesh, K_name, nq,
            params, float_type):

        self.shape = (obs_pts.shape[0] * 3, src_mesh[1].shape[0] * 9)
        self.dim = obs_pts.shape[1]
        self.tensor_dim = kernels[K_name].tensor_dim
        self.n_obs = obs_pts.shape[0]
        self.n_src = src_mesh[1].shape[0]

        in_size = self.n_src * self.dim * self.tensor_dim
        out_size = self.n_obs * self.tensor_dim
        self.gpu_in = gpu.empty_gpu(in_size, float_type)
        self.gpu_out = gpu.empty_gpu(out_size, float_type)

        self.q = gauss2d_tri(nq)

        self.gpu_obs_pts = gpu.to_gpu(obs_pts, float_type)
        self.gpu_obs_ns = gpu.to_gpu(obs_ns, float_type)
        self.gpu_src_pts = gpu.to_gpu(src_mesh[0], float_type)
        self.gpu_src_tris = gpu.to_gpu(src_mesh[1], np.int32)
        self.gpu_params = gpu.to_gpu(np.array(params), float_type)
        self.block_size = 128
        self.n_blocks = int(np.ceil(self.n_obs / self.block_size))

        self.module = gpu.load_gpu(
            'matrix_free.cl',
            tmpl_args = dict(
                block_size = self.block_size,
                float_type = gpu.np_to_c_type(float_type),
                quad_pts = self.q[0],
                quad_wts = self.q[1]
            )
        )
        self.fnc = getattr(self.module, "farfield_tris_to_pts" + K_name)

    def dot(self, v):
        self.gpu_in[:] = v[:].astype(self.gpu_in.dtype)
        self.fnc(
            self.gpu_out, self.gpu_in,
            self.gpu_obs_pts, self.gpu_obs_ns,
            self.gpu_src_pts, self.gpu_src_tris,
            self.gpu_params,
            np.int32(self.n_obs), np.int32(self.n_src),
            grid = (self.n_blocks, 1, 1), block = (self.block_size, 1, 1)
        )
        return self.gpu_out.get()
