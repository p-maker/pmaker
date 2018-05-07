#!/usr/bin/python2

from setuptools import setup, find_packages
from codecs import open
import os, os.path

with open(os.path.join(os.path.abspath(os.path.dirname(__file__)), 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

setup(
    name = "pmaker",
    description = "Toolkit for creating problems for programming competitions",
    long_description = long_description,
    long_description_content_type='text/markdown',
    url = "https://github.com/p-maker/pmaker",
    author = "Dmitry Sayutin",
    
    setup_requires = ['setuptools_scm', 'jinja2', 'python_version>="3.5"'],
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
