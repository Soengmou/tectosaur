import tectosaur.triangle_rules as triangle_rules
import tectosaur.quadrature as quad
from tectosaur.gpu import load_gpu
from laplace import laplace
from slow_test import slow
import pycuda.driver as drv

import numpy as np

tri_ref = [[0,0,0],[1,0,0],[0,1,0]]
tri_down = [[1,0,0],[0,0,0],[0,-1,0]]
tri_up_right = [[0,1,0],[1,0,0],[1,1,0]]
def test_weakly_singular_adjacent():
    # When one of the basis functions is zero along the edge where the triangles
    # touch, the integral is no longer hypersingular, but instead is only weakly
    # singular.
    weakly_singular = [(2, 2), (2, 0), (2, 1), (0, 2), (1, 2)]
    q1 = triangle_rules.adjacent_quad(0, 4, 4, 4, 4, True)
    q2 = triangle_rules.adjacent_quad(0, 5, 5, 5, 5, True)
    for i, j in weakly_singular:
        K = lambda pts: laplace(tri_ref, tri_down, i, j, 0, pts)
        v = quad.quadrature(K, q1)
        v2 = quad.quadrature(K, q2)
        print(i,j,v,v2)
        assert(np.abs((v - v2) / v2) < 0.012)

@slow
def test_adjacent_quad():
    # The complement of the nonsingular and weakly singular sets above.
    # These basis function pairs are both non-zero along the triangle boundary
    hypersingular = [(0, 0), (0, 1), (1, 0), (1, 1)]
    eps = 0.01
    q1 = triangle_rules.adjacent_quad(eps, 8, 8, 8, 8, False)
    q2 = triangle_rules.adjacent_quad(eps, 9, 9, 9, 9, False)
    for i, j in hypersingular:
        K = lambda pts: laplace(tri_ref, tri_down, i, j, eps, pts)
        v = quad.quadrature(K, q1)
        v2 = quad.quadrature(K, q2)
        print(i,j,v,v2)
        np.testing.assert_almost_equal(v, v2, 3)

@slow
def test_cancellation():
    result = []
    for n_eps in range(1,4):
        eps = 8 ** (-np.arange(n_eps).astype(np.float) - 1)
        print(eps)
        qc = quad.richardson_quad(
            eps, lambda e: triangle_rules.coincident_quad(e, 15, 15, 15, 20)
        )
        qa = quad.richardson_quad(
            eps, lambda e: triangle_rules.adjacent_quad(e, 15, 15, 15, 20, False)
        )

        Kco = lambda pts: laplace(tri_ref, tri_ref, 1, 1, pts[:,4], pts)
        Kadj_down = lambda pts: laplace(tri_ref, tri_down, 1, 0, pts[:,4], pts)
        tri_ref_rotated = [tri_ref[1], tri_ref[2], tri_ref[0]]
        Kadj_up_right = lambda pts: laplace(
                tri_ref_rotated, tri_up_right, 0, 1, pts[:,4], pts
        )
        Ic = quad.quadrature(Kco, qc)
        Ia1 = quad.quadrature(Kadj_down, qa)
        Ia2 = quad.quadrature(Kadj_up_right, qa)
        print(Ic,Ia1,Ia2)
        nondivergent = Ic + Ia1 + Ia2
        result.append(nondivergent)
    print(result)
    assert(abs(result[2] - result[1]) < 0.5 * abs(result[1] - result[0]))

@slow
def test_gpu_adjacent():
    eps = [0.02]
    q = quad.richardson_quad(
        eps, lambda e: triangle_rules.adjacent_quad(e, 8, 8, 8, 8, False)
    )
    qx = q[0].astype(np.float32)
    qw = q[1].astype(np.float32)

    pts = np.array([[0,0,0],[1,0,0],[0,1,0],[1,-1,0]]).astype(np.float32)
    N = 32 * 1000
    obs_tris = np.array([[0,1,2]] * N).astype(np.int32)
    src_tris = np.array([[1,0,3]] * N).astype(np.int32)

    adjacent = load_gpu('tectosaur/integrals.cu').get_function('adjacentH')

    result = np.empty((obs_tris.shape[0], 3, 3, 3, 3)).astype(np.float32)

    block = (32, 1, 1)
    grid = (N // block[0],1)
    print(adjacent(
        drv.Out(result),
        np.int32(q[0].shape[0]),
        drv.In(qx),
        drv.In(qw),
        drv.In(pts),
        drv.In(obs_tris),
        drv.In(src_tris),
        np.float32(1.0),
        np.float32(0.25),
        block = block,
        grid = grid,
        time_kernel = True
    ))

