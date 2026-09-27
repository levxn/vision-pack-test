cmake_minimum_required(VERSION 3.21)
# roccv::roccv forces HIP device flags (M23), so the probe is compiled with amdclang++ (set by the caller).
project(roccv_launch_probe LANGUAGES CXX)
find_package(roccv CONFIG REQUIRED)
add_executable(launch_probe launch_probe.cpp)
set_target_properties(launch_probe PROPERTIES CXX_STANDARD 20 CXX_STANDARD_REQUIRED ON)
target_link_libraries(launch_probe PRIVATE roccv::roccv)
