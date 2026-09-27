cmake_minimum_required(VERSION 3.21)
project(roccv_consumer CXX)

# Customer idiom: CMAKE_PREFIX_PATH, or roccv found through PATH (<prefix>/bin).
find_package(roccv CONFIG REQUIRED)
message(STATUS "VPTEST CMAKE_CXX_COMPILER=${CMAKE_CXX_COMPILER} (${CMAKE_CXX_COMPILER_ID})")
message(STATUS "VPTEST roccv_DIR=${roccv_DIR}")

add_executable(roccv_consumer main.cpp)
set_target_properties(roccv_consumer PROPERTIES CXX_STANDARD 20 CXX_STANDARD_REQUIRED ON)
target_link_libraries(roccv_consumer PRIVATE roccv::roccv)
