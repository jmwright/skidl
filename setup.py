#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys

import setuptools

__version__ = "1.2.0"
__author__ = "Dave Vandenbout"
__email__ = "devb@xess.com"

if "sdist" in sys.argv[1:]:
    with open("skidl/pckg_info.py", "w") as f:
        for name in ["__version__", "__author__", "__email__"]:
            f.write('{} = "{}"\n'.format(name, locals()[name]))

try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup


with open("README.rst") as readme_file:
    readme = readme_file.read()

with open("HISTORY.rst") as history_file:
    history = history_file.read().replace(".. :changelog:", "")

requirements = [
    "future >= 0.15.0",
    "sexpdata",
    "kinparse >= 0.1.0",
    "kinet2pcb",
    'enum34; python_version < "3.0"',
    #'PySpice; python_version >= "3.0"',
    "graphviz",
]

test_requirements = [
    # TODO: put package test requirements here
]

setup(
    name="skidl",
    version=__version__,
    description="A Python package for textually describing electronic circuit schematics.",
    long_description=readme + "\n\n" + history,
    author=__author__,
    author_email=__email__,
    url="https://github.com/devbisme/skidl",
    project_urls={
        "Documentation": "https://devbisme.github.io/skidl",
        "Source": "https://github.com/devbisme/skidl",
        "Changelog": "https://github.com/devbisme/skidl/blob/master/HISTORY.rst",
        "Tracker": "https://github.com/devbisme/skidl/issues",
    },
    # packages=['skidl',],
    packages=setuptools.find_packages(),
    entry_points={
        "console_scripts": ["netlist_to_skidl = skidl.scripts.netlist_to_skidl_main:main"]
    },
    package_dir={"skidl": "skidl"},
    include_package_data=False,
    scripts=[],
    install_requires=requirements,
    license="MIT",
    zip_safe=False,
    keywords="skidl kicad electronic circuit schematics",
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Manufacturing",
        "License :: OSI Approved :: MIT License",
        "Natural Language :: English",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 2.7",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: Implementation :: CPython",
        "Topic :: Scientific/Engineering :: Electronic Design Automation (EDA)",
    ],
    test_suite="tests",
    tests_require=test_requirements,
)
