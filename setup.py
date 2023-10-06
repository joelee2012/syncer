#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import pathlib

from setuptools import setup

requires = [
    'httpx',
]


here = os.path.abspath(os.path.dirname(__file__))
about = {}
with open(os.path.join(here, 'syncer', '__version__.py')) as f:
    exec(f.read(), about)

readme = pathlib.Path('README.md').read_text()
setup(
    name=about['__title__'],
    version=about['__version__'],
    description=about['__description__'],
    long_description=readme,
    long_description_content_type='text/markdown',
    url=about['__url__'],
    author=about['__author__'],
    author_email=about['__author_email__'],
    packages=['syncer'],
    install_requires=requires,
    license=about['__license__'],
    python_requires='>=3.8, !=3.0.*, !=3.1.*, !=3.2.*,'
                    ' !=3.3.*, !=3.4.*, !=3.5.*',
    entry_points={
        'console_scripts': [
            'syncer = syncer.cmd:main'
        ]
    },
    classifiers=[
        'Intended Audience :: Developers',
        'Intended Audience :: System Administrators',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Topic :: Software Development',
    ],
)
