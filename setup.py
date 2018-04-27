#!/usr/bin/python3

from setuptools import setup, find_packages

setup(
    name = "pmaker",
    use_scm_version = {"local_scheme": "dirty-tag"},
    setup_requires = ['setuptools_scm'],
    packages = find_packages('src'),
    package_dir = {'': 'src'},
    entry_points = {
        'console_scripts': [
            'pmaker = pmaker.enter:main'
        ]
    }
)
