cmake_minimum_required(VERSION 3.16)
project(rocal_consumer CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(DEFINED VP_PREFIX)
  list(APPEND CMAKE_MODULE_PATH "${VP_PREFIX}/lib/cmake")
elseif(DEFINED ENV{ROCM_PATH})
  list(APPEND CMAKE_MODULE_PATH "$ENV{ROCM_PATH}/lib/cmake")
endif()

find_package(rocal REQUIRED)
message(STATUS "VPTEST rocal_INCLUDE_DIRS=${rocal_INCLUDE_DIRS}")
message(STATUS "VPTEST rocal_LIBRARIES=${rocal_LIBRARIES}")

# Upstream rocAL docs/samples spell #include "rocal_api.h"; VP_ROCAL_PREFIXED
# switches to <rocal/rocal_api.h>, which is what Findrocal's include dir supports.
if(VP_ROCAL_PREFIXED)
  set(_hdr "<rocal/rocal_api.h>")
else()
  set(_hdr "\"rocal_api.h\"")
endif()

add_executable(rocal_consumer main.cpp)
target_compile_definitions(rocal_consumer PRIVATE "ROCAL_HEADER=${_hdr}")
target_link_libraries(rocal_consumer PRIVATE rocal::rocal)
if(VP_ROCAL_LINK_PY)
  # librocal references CPython symbols without a DT_NEEDED on libpython (H1)
  find_package(Python3 REQUIRED COMPONENTS Development.Embed)
  target_link_libraries(rocal_consumer PRIVATE Python3::Python)
endif()
