cmake_minimum_required(VERSION 3.20)
project(horncad_mfem_acoustics LANGUAGES CXX)

find_package(MFEM CONFIG REQUIRED)
add_executable(horncad_mfem_interior interior_acoustics.cpp)
target_compile_features(horncad_mfem_interior PRIVATE cxx_std_17)
target_link_libraries(horncad_mfem_interior PRIVATE mfem)

