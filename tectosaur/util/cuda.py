import numpy as np
import pycuda
import pycuda.gpuarray
import pycuda.compiler

def ensure_initialized():
    import pycuda.autoinit

def ptr(arr):
    if type(arr) is pycuda.gpuarray.GPUArray:
        return arr.gpudata
    return arr

def to_gpu(arr, float_type = np.float32):
    ensure_initialized()
    ensure_initialized()
    if type(arr) is pycuda.gpuarray.GPUArray:
        return arr
    to_type = arr.astype(float_type)
    # tct_log.get_caller_logger().debug('sending n_bytes: ' + str(to_type.nbytes))
    return pycuda.gpuarray.to_gpu(to_type)

def empty_gpu(shape, float_type = np.float32):
    ensure_initialized()
    return pycuda.gpuarray.empty(shape, float_type)

def zeros_gpu(shape, float_type = np.float32):
    ensure_initialized()
    return pycuda.gpuarray.zeros(shape, float_type)

class ModuleWrapper:
    def __init__(self, module):
        self.module = module

    def __getattr__(self, name):
        return self.module.get_function(name)

def compile(code):
    ensure_initialized()
    compiler_args = ['--use_fast_math', '--restrict']
    return ModuleWrapper(pycuda.compiler.SourceModule(
        code, options = compiler_args
    ))

cluda_preamble = """
#define CUDA
// taken from pycuda._cluda
#define LOCAL_BARRIER __syncthreads()
#define WITHIN_KERNEL __device__
#define KERNEL extern "C" __global__
#define GLOBAL_MEM /* empty */
#define LOCAL_MEM __shared__
#define LOCAL_MEM_DYNAMIC extern __shared__
#define LOCAL_MEM_ARG /* empty */
#define CONSTANT __constant__
#define INLINE __forceinline__
#define SIZE_T unsigned int
#define VSIZE_T unsigned int
// used to align fields in structures
#define ALIGN(bytes) __align__(bytes)

WITHIN_KERNEL SIZE_T get_local_id(unsigned int dim)
{
    if(dim == 0) return threadIdx.x;
    if(dim == 1) return threadIdx.y;
    if(dim == 2) return threadIdx.z;
    return 0;
}
WITHIN_KERNEL SIZE_T get_group_id(unsigned int dim)
{
    if(dim == 0) return blockIdx.x;
    if(dim == 1) return blockIdx.y;
    if(dim == 2) return blockIdx.z;
    return 0;
}
WITHIN_KERNEL SIZE_T get_local_size(unsigned int dim)
{
    if(dim == 0) return blockDim.x;
    if(dim == 1) return blockDim.y;
    if(dim == 2) return blockDim.z;
    return 1;
}
WITHIN_KERNEL SIZE_T get_num_groups(unsigned int dim)
{
    if(dim == 0) return gridDim.x;
    if(dim == 1) return gridDim.y;
    if(dim == 2) return gridDim.z;
    return 1;
}
WITHIN_KERNEL SIZE_T get_global_size(unsigned int dim)
{
    return get_num_groups(dim) * get_local_size(dim);
}
WITHIN_KERNEL SIZE_T get_global_id(unsigned int dim)
{
    return get_local_id(dim) + get_group_id(dim) * get_local_size(dim);
}
"""