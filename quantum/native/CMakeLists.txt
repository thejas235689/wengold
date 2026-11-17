cmake_minimum_required(VERSION 3.18)
project(wengold_quest_bridge LANGUAGES CXX)

find_package(Python3 REQUIRED COMPONENTS Interpreter Development.Module)
find_package(pybind11 CONFIG REQUIRED)
find_path(QUEST_INCLUDE_DIR NAMES quest.h REQUIRED)
find_library(QUEST_LIBRARY NAMES QuEST quest REQUIRED)

pybind11_add_module(_quest_bridge quest_bridge.cpp)
target_compile_features(_quest_bridge PRIVATE cxx_std_17)
target_include_directories(_quest_bridge PRIVATE ${QUEST_INCLUDE_DIR})
target_link_libraries(_quest_bridge PRIVATE ${QUEST_LIBRARY})
target_compile_options(_quest_bridge PRIVATE -Wall -Wextra -Wpedantic)

# Install directly beside quest_backend.py so the regular Python import finds it.
install(TARGETS _quest_bridge LIBRARY DESTINATION quantum/backends)
