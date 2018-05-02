#!/usr/bin/python3

from setuptools import setup, find_packages

setup(
    name = "pmaker",
    setup_requires = ['setuptools_scm', 'jinja2'],
    use_scm_version = {"local_scheme": "dirty-tag"},

    packages = find_packages('src'),
    package_dir = {'': 'src'},
    
    entry_points = {
        'console_scripts': [
            'pmaker = pmaker.enter:main'
        ]
    },
    package_data = {
        '': ['*.css', '*.html']
    }
)
