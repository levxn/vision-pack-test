cmake_minimum_required(VERSION 3.16)
project(mvx_consumer C)

# Customer idiom: add <ROCm>/lib/cmake to CMAKE_MODULE_PATH. VP_PREFIX (explicit)
# wins, otherwise $ENV{ROCM_PATH}; with neither, find_package must fail cleanly.
if(DEFINED VP_PREFIX)
  list(APPEND CMAKE_MODULE_PATH "${VP_PREFIX}/lib/cmake")
elseif(DEFINED ENV{ROCM_PATH})
  list(APPEND CMAKE_MODULE_PATH "$ENV{ROCM_PATH}/lib/cmake")
endif()

find_package(MIVisionX REQUIRED)
message(STATUS "VPTEST MIVisionX_INCLUDE_DIRS=${MIVisionX_INCLUDE_DIRS}")
message(STATUS "VPTEST MIVisionX_LIBRARIES=${MIVisionX_LIBRARIES}")

add_executable(mvx_consumer main.c)
target_link_libraries(mvx_consumer PRIVATE MIVisionX::MIVisionX)
if(VP_WORKAROUND_INC)
  # FindMIVisionX exports <prefix>/include, but <VX/vx.h> lives in <prefix>/include/mivisionx
  target_include_directories(mvx_consumer PRIVATE "${MIVisionX_INCLUDE_DIRS}/mivisionx")
endif()
