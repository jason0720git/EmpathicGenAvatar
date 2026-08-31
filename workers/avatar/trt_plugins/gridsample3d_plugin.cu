// TensorRT 10 implementation of the custom ONNX GridSample3D operator used
// by Ditto's warp network.  It supports the exact online graph contract:
// input [N,C,D,H,W], grid [N,Do,Ho,Wo,3], output [N,C,Do,Ho,Wo], float32.
// The ONNX export uses bilinear (= trilinear in 3D), zero padding, and
// align_corners=0.  Other settings are deliberately rejected at build time.

#include <NvInfer.h>
#include <NvInferRuntimePlugin.h>
#include <cuda_runtime.h>

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

namespace {
constexpr char kPluginName[] = "GridSample3D";
constexpr char kPluginVersion[] = "1";

struct Params {
    int32_t alignCorners{0};
    int32_t mode{0};        // bilinear
    int32_t paddingMode{0}; // zeros
};

__device__ inline float coordinate(float x, int size, int alignCorners) {
    return alignCorners ? ((x + 1.f) * (size - 1) * .5f) : (((x + 1.f) * size - 1.f) * .5f);
}

__global__ void gridSample3dKernel(const float* input, const float* grid, float* output,
                                   int n, int c, int d, int h, int w,
                                   int od, int oh, int ow, int alignCorners) {
    const int64_t total = static_cast<int64_t>(n) * c * od * oh * ow;
    for (int64_t linear = static_cast<int64_t>(blockIdx.x) * blockDim.x + threadIdx.x;
         linear < total; linear += static_cast<int64_t>(blockDim.x) * gridDim.x) {
        int64_t v = linear;
        const int xOut = v % ow; v /= ow;
        const int yOut = v % oh; v /= oh;
        const int zOut = v % od; v /= od;
        const int channel = v % c; v /= c;
        const int batch = v;
        const int64_t gridBase = (((static_cast<int64_t>(batch) * od + zOut) * oh + yOut) * ow + xOut) * 3;
        const float x = coordinate(grid[gridBase], w, alignCorners);
        const float y = coordinate(grid[gridBase + 1], h, alignCorners);
        const float z = coordinate(grid[gridBase + 2], d, alignCorners);
        const int x0 = static_cast<int>(floorf(x)), y0 = static_cast<int>(floorf(y)), z0 = static_cast<int>(floorf(z));
        const int x1 = x0 + 1, y1 = y0 + 1, z1 = z0 + 1;
        const float wx1 = x - x0, wy1 = y - y0, wz1 = z - z0;
        const float wx0 = 1.f - wx1, wy0 = 1.f - wy1, wz0 = 1.f - wz1;
        float value = 0.f;
        const int xs[2] = {x0, x1}; const int ys[2] = {y0, y1}; const int zs[2] = {z0, z1};
        const float wx[2] = {wx0, wx1}; const float wy[2] = {wy0, wy1}; const float wz[2] = {wz0, wz1};
        for (int zi = 0; zi != 2; ++zi) for (int yi = 0; yi != 2; ++yi) for (int xi = 0; xi != 2; ++xi) {
            if (xs[xi] >= 0 && xs[xi] < w && ys[yi] >= 0 && ys[yi] < h && zs[zi] >= 0 && zs[zi] < d) {
                const int64_t offset = ((((static_cast<int64_t>(batch) * c + channel) * d + zs[zi]) * h + ys[yi]) * w + xs[xi]);
                value += input[offset] * wx[xi] * wy[yi] * wz[zi];
            }
        }
        output[linear] = value;
    }
}

class GridSample3DPlugin final : public nvinfer1::IPluginV2DynamicExt {
public:
    GridSample3DPlugin() = default;
    explicit GridSample3DPlugin(const Params& params) : params_(params) {}
    GridSample3DPlugin(const void* data, size_t length) {
        if (length == sizeof(params_)) std::memcpy(&params_, data, sizeof(params_));
    }
    const char* getPluginType() const noexcept override { return kPluginName; }
    const char* getPluginVersion() const noexcept override { return kPluginVersion; }
    int getNbOutputs() const noexcept override { return 1; }
    int initialize() noexcept override { return 0; }
    void terminate() noexcept override {}
    size_t getSerializationSize() const noexcept override { return sizeof(params_); }
    void serialize(void* buffer) const noexcept override { std::memcpy(buffer, &params_, sizeof(params_)); }
    void destroy() noexcept override { delete this; }
    nvinfer1::IPluginV2DynamicExt* clone() const noexcept override {
        auto* plugin = new GridSample3DPlugin(params_); plugin->namespace_ = namespace_; return plugin;
    }
    void setPluginNamespace(const char* pluginNamespace) noexcept override { namespace_ = pluginNamespace ? pluginNamespace : ""; }
    const char* getPluginNamespace() const noexcept override { return namespace_.c_str(); }
    nvinfer1::DimsExprs getOutputDimensions(int, const nvinfer1::DimsExprs* inputs, int, nvinfer1::IExprBuilder&) noexcept override {
        nvinfer1::DimsExprs out{}; out.nbDims = 5;
        out.d[0] = inputs[0].d[0]; out.d[1] = inputs[0].d[1];
        out.d[2] = inputs[1].d[1]; out.d[3] = inputs[1].d[2]; out.d[4] = inputs[1].d[3];
        return out;
    }
    bool supportsFormatCombination(int pos, const nvinfer1::PluginTensorDesc* io, int, int) noexcept override {
        return io[pos].format == nvinfer1::TensorFormat::kLINEAR && io[pos].type == nvinfer1::DataType::kFLOAT;
    }
    void configurePlugin(const nvinfer1::DynamicPluginTensorDesc*, int, const nvinfer1::DynamicPluginTensorDesc*, int) noexcept override {}
    size_t getWorkspaceSize(const nvinfer1::PluginTensorDesc*, int, const nvinfer1::PluginTensorDesc*, int) const noexcept override { return 0; }
    int enqueue(const nvinfer1::PluginTensorDesc* inputDesc, const nvinfer1::PluginTensorDesc*, const void* const* inputs,
                void* const* outputs, void*, cudaStream_t stream) noexcept override {
        if (params_.mode != 0 || params_.paddingMode != 0) return 1;
        const auto a = inputDesc[0].dims, g = inputDesc[1].dims;
        if (a.nbDims != 5 || g.nbDims != 5 || g.d[4] != 3) return 1;
        const int64_t count = static_cast<int64_t>(a.d[0]) * a.d[1] * g.d[1] * g.d[2] * g.d[3];
        const int blocks = static_cast<int>(std::min<int64_t>((count + 255) / 256, 65535));
        gridSample3dKernel<<<blocks, 256, 0, stream>>>(static_cast<const float*>(inputs[0]), static_cast<const float*>(inputs[1]),
            static_cast<float*>(outputs[0]), a.d[0], a.d[1], a.d[2], a.d[3], a.d[4], g.d[1], g.d[2], g.d[3], params_.alignCorners);
        return cudaGetLastError() == cudaSuccess ? 0 : 1;
    }
    nvinfer1::DataType getOutputDataType(int, const nvinfer1::DataType* inputTypes, int) const noexcept override { return inputTypes[0]; }
    void attachToContext(cudnnContext*, cublasContext*, nvinfer1::IGpuAllocator*) noexcept override {}
    void detachFromContext() noexcept override {}
private:
    Params params_{};
    std::string namespace_;
};

class GridSample3DCreator final : public nvinfer1::IPluginCreator {
public:
    GridSample3DCreator() { fields_.nbFields = 0; fields_.fields = nullptr; }
    const char* getPluginName() const noexcept override { return kPluginName; }
    const char* getPluginVersion() const noexcept override { return kPluginVersion; }
    const nvinfer1::PluginFieldCollection* getFieldNames() noexcept override { return &fields_; }
    nvinfer1::IPluginV2* createPlugin(const char*, const nvinfer1::PluginFieldCollection* fc) noexcept override {
        Params p{};
        // ONNX parser passes attributes as plugin fields when present. Ditto's
        // export is bilinear/zeros/align_corners=0; reject incompatible values
        // rather than accidentally producing plausible but wrong video.
        for (int i = 0; fc && i < fc->nbFields; ++i) {
            const auto& f = fc->fields[i];
            if (!f.data || f.length < 1) continue;
            const int value = *static_cast<const int*>(f.data);
            if (std::strcmp(f.name, "align_corners") == 0) p.alignCorners = value;
            else if (std::strcmp(f.name, "mode") == 0) p.mode = value;
            else if (std::strcmp(f.name, "padding_mode") == 0) p.paddingMode = value;
        }
        auto* plugin = new GridSample3DPlugin(p); plugin->setPluginNamespace(namespace_.c_str()); return plugin;
    }
    nvinfer1::IPluginV2* deserializePlugin(const char*, const void* data, size_t length) noexcept override {
        auto* plugin = new GridSample3DPlugin(data, length); plugin->setPluginNamespace(namespace_.c_str()); return plugin;
    }
    void setPluginNamespace(const char* ns) noexcept override { namespace_ = ns ? ns : ""; }
    const char* getPluginNamespace() const noexcept override { return namespace_.c_str(); }
private:
    nvinfer1::PluginFieldCollection fields_{};
    std::string namespace_;
};
} // namespace

REGISTER_TENSORRT_PLUGIN(GridSample3DCreator);
