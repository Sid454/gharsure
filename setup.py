from pybind11.setup_helpers import Pybind11Extension, build_ext
from setuptools import setup

ext_modules = [
    Pybind11Extension(
        "rentshield_core",
        ["cpp/rentshield_core.cpp"],
        cxx_std=20,
        extra_compile_args=["-O3"],
    ),
]

setup(
    name="rentshield_core",
    version="0.1.0",
    ext_modules=ext_modules,
    cmdclass={"build_ext": build_ext},
)
