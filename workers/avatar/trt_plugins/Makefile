CUDA_HOME ?= /usr/local/cuda
TRT_INCLUDE ?= /usr/include/x86_64-linux-gnu
TRT_LIB ?= /usr/lib/x86_64-linux-gnu

TARGET := libditto_gridsample3d_trt10.so

NVCCFLAGS := -std=c++17 -O3 -Xcompiler -fPIC -I$(TRT_INCLUDE) -I$(CUDA_HOME)/include
LDFLAGS := -shared -L$(TRT_LIB) -L$(CUDA_HOME)/lib64 -lnvinfer -lnvinfer_plugin -lcudart

all: $(TARGET)

$(TARGET): gridsample3d_plugin.cu
	$(CUDA_HOME)/bin/nvcc $(NVCCFLAGS) $< -o $@ $(LDFLAGS)

clean:
	rm -f $(TARGET)
