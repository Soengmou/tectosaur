import scipy.spatial
import numpy as np

import tectosaur.mesh.refine as refine

# Corners are ordered: lower left, lower right, upper right, upper left
def rect_points(corners, xhat_vals, yhat_vals):
    nx = xhat_vals.shape[0]
    ny = yhat_vals.shape[0]
    corners = np.array(corners)

    rect_basis = [
        lambda x, y: x * y,
        lambda x, y: (1 - x) * y,
        lambda x, y: (1 - x) * (1 - y),
        lambda x, y: x * (1 - y)
    ]

    X, Y = np.meshgrid(xhat_vals, yhat_vals)
    vertices = np.vstack((X.reshape(nx * ny), Y.reshape(nx * ny))).T

    pts = np.sum([
        np.outer(rect_basis[i](vertices[:,0], vertices[:,1]), corners[i, :])
        for i in range(4)
    ], axis = 0)
    return pts

def rect_topology(nx, ny):
    def v_idx(i, j):
        return j * nx + i

    tris = []
    for i in range(nx - 1):
        for j in range(ny - 1):
            top_left = v_idx(i, j)
            top_right = v_idx(i + 1, j)
            bottom_left = v_idx(i, j + 1)
            bottom_right = v_idx(i + 1, j + 1)
            tris.append([top_left, bottom_left, top_right])
            tris.append([bottom_left, bottom_right, top_right])
    return np.array(tris, dtype = np.int)

#TODO: Technically, this is make quadrilateral!
def make_rect(nx, ny, corners):
    x = np.linspace(0, 1, nx)
    y = np.linspace(0, 1, ny)
    return rect_points(corners, x, y), rect_topology(nx, ny)

def spherify(pts):
    D = scipy.spatial.distance.cdist(pts, np.zeros((1,3)))
    return (1.0 / D) * pts

def make_ellipse(center, rx, ry, rz):
    pts = np.array([[0,-ry,0],[rx,0,0],[0,0,rz],[-rx,0,0],[0,0,-rz],[0,ry,0]])
    tris = np.array([[1,0,2],[2,0,3],[3,0,4],[4,0,1],[5,1,2],[5,2,3],[5,3,4],[5,4,1]])
    pts += center
    return pts, tris

def make_sphere(center, r, refinements):
    pts = np.array([[0,-1.0,0],[1.0,0,0],[0,0,1.0],[-1.0,0,0],[0,0,-1.0],[0,1.0,0]])
    tris = np.array([[1,0,2],[2,0,3],[3,0,4],[4,0,1],[5,1,2],[5,2,3],[5,3,4],[5,4,1]])
    m = pts, tris
    for i in range(refinements):
        m = refine.refine(m)
        m = (spherify(m[0]), m[1])
    m = (np.array(center) + r * m[0], m[1])
    return m

def plot_mesh3d(pts, tris):
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d import Axes3D
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    fig = plt.figure()
    ax = Axes3D(fig)
    verts = pts[tris]
    coll = Poly3DCollection(verts)
    coll.set_facecolor((0.0, 0.0, 0.0, 0.0))
    coll.set_edgecolor((0.0, 0.0, 0.0, 1.0))
    ax.add_collection3d(coll)
    plt.show()
